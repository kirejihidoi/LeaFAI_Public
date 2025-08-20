import os
import asyncio
import logging
import datetime
import discord
from openai import AsyncOpenAI

from pathlib import Path
import json

# ===== 好感度 永続化と制御 =====
AFF_PATH = Path(os.getenv("AFFINITY_PATH", "/data/affinity.json"))
_aff_cache: dict[str, int] = {}
if AFF_PATH.exists():
    try:
        _aff_cache = json.loads(AFF_PATH.read_text(encoding="utf-8"))
    except Exception:
        _aff_cache = {}

def get_affinity(user_id: int) -> int:
    try:
        return int(_aff_cache.get(str(user_id), 0))
    except Exception:
        return 0

def bump_affinity(user_id: int, delta: int) -> None:
    cur = max(-5, min(5, get_affinity(user_id) + int(delta)))
    _aff_cache[str(user_id)] = cur
    try:
        AFF_PATH.write_text(json.dumps(_aff_cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

POSITIVE_WORDS = ("ありがとう","助かった","感謝","うれしい","好き","助かる")
NEGATIVE_WORDS = ("つまらん","バカ","使えない","嫌い","最悪","ゴミ","死ね")

def score_text_for_affinity(text: str) -> int:
    t = text.lower()
    sc = 0
    if any(w in text for w in POSITIVE_WORDS): sc += 1
    if any(w in t for w in ("thx","thanks")): sc += 1
    if "ごめん" in text or "すまん" in text: sc += 1  # 軽い謝意
    if any(w in text for w in NEGATIVE_WORDS): sc -= 1
    # スパム抑制：極端に長い罵倒や連投は-1どまり
    if sc < -1: sc = -1
    if sc > 2: sc = 2
    return sc

def affinity_style_instr(level: int) -> str:
    if level <= -3:
        return "RELATIONSHIP_TONE: cold; brevity: very short; warmth: low; sarcasm: high; avoid emojis."
    if level <= -1:
        return "RELATIONSHIP_TONE: cool; brevity: short; warmth: low; keep dry humor."
    if level <= 1:
        return "RELATIONSHIP_TONE: neutral; brevity: medium; warmth: moderate."
    if level <= 3:
        return "RELATIONSHIP_TONE: friendly; brevity: medium; warmth: a bit higher; slightly more helpful."
    return "RELATIONSHIP_TONE: affectionate; brevity: medium; warmth: high; add a hint of playfulness."
# ===== 好感度 ここまで =====


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# OpenAI 非同期クライアント
oai = AsyncOpenAI(api_key=OPENAI_API_KEY)
GEN_SEMAPHORE = asyncio.Semaphore(3)  # 同時生成制限
OPENAI_TIMEOUT = 30  # 秒

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True  # 監査ログ参照に必要
bot = discord.Client(intents=intents, max_messages=None)  # キャッシュ切れで「消えたように見える」のを防ぐ

# 会話履歴保持
MAX_HISTORY_MESSAGES = 6
chat_history: dict[int, list[dict]] = {}

# 送信メッセージ追跡（削除検知用）
my_msgs: dict[int, dict] = {}

# 🧙‍♀️ 基本人格プロンプト
BASE_PERSONA = """あなたのプロンプト"""

# メンション暴発で自動削除されないように制限
ALLOWED = discord.AllowedMentions(everyone=False, users=True, roles=False)

async def _generate_reply(messages: list[dict]) -> str:
    """OpenAI呼び出し。セマフォとタイムアウト付き。"""
    async with GEN_SEMAPHORE:
        async with asyncio.timeout(OPENAI_TIMEOUT):
            resp = await oai.chat.completions.create(
                model="gpt-5",
                messages=messages,
            )
            return resp.choices[0].message.content.strip()

def _is_image_attachment(att: discord.Attachment) -> bool:
    """画像ファイルかどうかの簡易判定"""
    ct = (att.content_type or "").lower()
    return ct.startswith("image/") or att.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))

current_user_id: int | None = None

async def _generate_vision_reply(user_text: str, image_urls: list[str]) -> str:
    """画像付きメッセージに対して短く回答（画像生成はしない）。"""
    # content に text と image_url を混在
    content: list[dict] = []
    if user_text and user_text.strip():
        content.append({"type": "text", "text": user_text.strip()})
    else:
        # 無言で画像だけ来た場合のデフォルト指示
        content.append({"type": "text", "text": BASE_PERSONA})
    for url in image_urls[:4]:  # 念のため4枚まで
        content.append({"type": "image_url", "image_url": {"url": url}})

    async with GEN_SEMAPHORE:
        async with asyncio.timeout(OPENAI_TIMEOUT):
            resp = await oai.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": BASE_PERSONA},
                    {"role": "system", "content": affinity_style_instr(get_affinity(current_user_id))},
                    {"role": "user", "content": content},
                ],
            )
            return resp.choices[0].message.content.strip()

async def send_chunked(channel: discord.abc.Messageable, text: str) -> list[int]:
    """Discord 2000文字制限対策で分割送信し、各メッセージIDを追跡"""
    sent_ids: list[int] = []
    if not text:
        return sent_ids
    for i in range(0, len(text), 1900):
        chunk = text[i:i+1900]
        sent = await channel.send(chunk, allowed_mentions=ALLOWED)
        sent_ids.append(sent.id)
        my_msgs[sent.id] = {
            "channel_id": sent.channel.id,
            "content": chunk[:200],
            "at": datetime.datetime.utcnow(),
        }
    return sent_ids

@bot.event
async def on_ready():
    logging.basicConfig(level=logging.INFO)
    print(f"ログイン成功: {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    async def _work():
        try:
            # 画像が付いていたら先に Vision で処理（生成はしない）
            image_urls = [att.url for att in message.attachments if _is_image_attachment(att)]
            if image_urls:
                # Vision でも好感度制御を効かせるため、呼び出し前に user_id をセット
                global current_user_id
                current_user_id = message.author.id
                # 好感度更新
                bump_affinity(current_user_id, score_text_for_affinity(message.content or ""))
                async with message.channel.typing():
                    reply = await _generate_vision_reply(message.content or "", image_urls)
                # 会話履歴（テキストのみ保持）
                user_id = message.author.id
                chat_history.setdefault(user_id, [])
                chat_history[user_id].append({"role": "user", "content": message.content or "[画像]"})
                chat_history[user_id].append({"role": "assistant", "content": reply})
                if len(chat_history[user_id]) > MAX_HISTORY_MESSAGES * 2:
                    chat_history[user_id] = chat_history[user_id][-MAX_HISTORY_MESSAGES * 2:]
                await send_chunked(message.channel, reply)
                return

            # 通常のテキスト会話
            user_id = message.author.id
            chat_history.setdefault(user_id, [])
            chat_history[user_id].append({"role": "user", "content": message.content})
            # 好感度の更新
            bump_affinity(user_id, score_text_for_affinity(message.content or ""))
            if len(chat_history[user_id]) > MAX_HISTORY_MESSAGES * 2:
                chat_history[user_id] = chat_history[user_id][-MAX_HISTORY_MESSAGES * 2:]

            # 好感度に応じた追加 system を差し込む
            messages_to_send = [
                {"role": "system", "content": BASE_PERSONA},
                {"role": "system", "content": affinity_style_instr(get_affinity(user_id))},
            ] + chat_history[user_id]

            async with message.channel.typing():
                reply = await _generate_reply(messages_to_send)
                if not reply:
                    reply = "……返す言葉が見つからなかったわ。"

            chat_history[user_id].append({"role": "assistant", "content": reply})
            if len(chat_history[user_id]) > MAX_HISTORY_MESSAGES * 2:
                chat_history[user_id] = chat_history[user_id][-MAX_HISTORY_MESSAGES * 2:]

            await send_chunked(message.channel, reply)

        except asyncio.TimeoutError:
            await message.channel.send("魔力切れ。少ししてからもう一度。", allowed_mentions=ALLOWED)
        except discord.errors.HTTPException:
            await message.channel.send("……返す言葉が見つからなかったわ。", allowed_mentions=ALLOWED)
        except Exception as e:
            logging.exception("LLM生成中に失敗: %s", e)
            await message.channel.send("魔力が乱れて返答できなかったみたいね。", allowed_mentions=ALLOWED)

    # 背景タスク化してイベントループを塞がない
    asyncio.create_task(_work())

@bot.event
async def on_message_delete(msg: discord.Message):
    """Botが送ったメッセージが削除されたらログに残す。監査ログが見られれば削除者も推定。"""
    try:
        if msg.author and bot.user and msg.author.id == bot.user.id:
            info = my_msgs.pop(msg.id, None)
            snippet = (msg.content or (info["content"] if info else ""))[:200]
            logging.error(
                "Bot message deleted: id=%s channel=%s snippet=%r",
                msg.id, getattr(msg.channel, "id", "?"), snippet
            )

            guild = getattr(msg, "guild", None)
            if guild and guild.me and guild.me.guild_permissions.view_audit_log:
                async for entry in guild.audit_logs(action=discord.AuditLogAction.message_delete, limit=5):
                    # 直近10秒以内の削除を候補に
                    if (datetime.datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 10:
                        logging.error(
                            "Audit: deleter=%s target=%s reason=%s",
                            entry.user, entry.target, entry.reason
                        )
                        break
    except Exception as e:
        logging.exception("削除検知処理で例外: %s", e)

bot.run(DISCORD_TOKEN)
