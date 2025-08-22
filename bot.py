import os
import asyncio
import logging
import datetime
import discord
import random
import httpx
import time
from openai import AsyncOpenAI, APIError, APIConnectionError, RateLimitError, APITimeoutError
from pathlib import Path
from nonstream_reply import nonstream_progressive_reply
from base_persona import BASE_PERSONA

import json
import re

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

POSITIVE_WORDS = ("ありがとう", "助かった", "感謝", "うれしい", "好き", "助かる")
NEGATIVE_WORDS = ("つまらん", "バカ", "使えない", "嫌い", "最悪", "ゴミ", "死ね")

def score_text_for_affinity(text: str) -> int:
    t = text.lower()
    sc = 0
    if any(w in text for w in POSITIVE_WORDS): sc += 1
    if any(w in t for w in ("thx", "thanks")): sc += 1
    if "ごめん" in text or "すまん" in text: sc += 1
    if any(w in text for w in NEGATIVE_WORDS): sc -= 1
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

# 同時生成制限とタイムアウト
GEN_SEMAPHORE = asyncio.Semaphore(2)  # 混雑緩和
OPENAI_TIMEOUT = 45  # 秒

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
bot = discord.Client(intents=intents, max_messages=None)

# 会話履歴保持
MAX_HISTORY_MESSAGES = 6
chat_history: dict[int, list[dict]] = {}

# 送信メッセージ追跡（削除検知用）
my_msgs: dict[int, dict] = {}

# メンション暴発で自動削除されないように制限
ALLOWED = discord.AllowedMentions(everyone=False, users=True, roles=False)
ADVICE_PATTERNS = [
    r"(生活の知恵|豆知識|ライフハック)",
    r"(したほうがいい|するといい|しましょう|してください|すべき|べきです)",
    r"(おすすめです|オススメです|注意しましょう|気をつけましょう|心がけましょう)",
    r"(節約|健康|掃除|片付け|睡眠|食生活).{0,12}(コツ|ポイント|方法|テク|手順)",
]
MODEL_FAST = "gpt-5-mini"
MODEL_HEAVY = "gpt-5"

def _choose_model(messages: list[dict]) -> str:
    text = "\n".join(
        m.get("content", "") if isinstance(m.get("content", ""), str) else ""
        for m in messages
    )
    long = len(text) > 3000
    codey = "```" in text or ("# " in text and "def " in text)
    return MODEL_HEAVY if (long or codey) else MODEL_FAST

def _strip_lifehack_tone(text: str) -> str:
    if not text:
        return text
    lowered = text
    hit = any(re.search(p, lowered, re.IGNORECASE) for p in ADVICE_PATTERNS)
    lowered = re.sub(r"(してください|しましょう|したほうがいい|するといい|すべき|べきです)", "かな。", lowered)
    lowered = re.sub(r"(おすすめです|オススメです)", "別に好きにすれば。", lowered)
    lowered = re.sub(r"(?m)^\s*[-・*]\s.*", "", lowered)
    if hit:
        sentences = re.split(r"(?<=[。！!？?])", lowered)
        filtered = [s for s in sentences if not re.search("|".join(ADVICE_PATTERNS), s)]
        lowered = "".join(filtered).strip() or "……別にいいけど。"
    lowered = re.sub(r"\n{3,}", "\n\n", lowered).strip()
    return lowered

async def _call_openai_with_retry(fn, *, retries=3, base_delay=1.0, max_delay=8.0):
    last_err = None
    for attempt in range(retries):
        try:
            async with asyncio.timeout(OPENAI_TIMEOUT):
                return await fn()
        except (APITimeoutError, APIConnectionError) as e:
            last_err = e
        except RateLimitError as e:
            last_err = e
        except APIError as e:
            status = getattr(e, "status_code", None)
            if status and 500 <= status < 600:
                last_err = e
            else:
                raise
        except httpx.ReadTimeout as e:
            last_err = e
        except asyncio.TimeoutError as e:
            last_err = e

        if attempt < retries - 1:
            delay = min(max_delay, base_delay * (2 ** attempt)) + random.random() * 0.5
            await asyncio.sleep(delay)
    raise last_err

def _is_image_attachment(att: discord.Attachment) -> bool:
    ct = (att.content_type or "").lower()
    return ct.startswith("image/") or att.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))

current_user_id: int | None = None

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
            # 画像が付いていたら先に Vision 風プロンプトで処理（画像生成はしない）
            image_urls = [att.url for att in message.attachments if _is_image_attachment(att)]
            if image_urls:
                user_id = message.author.id
                global current_user_id
                current_user_id = user_id
            
                bump_affinity(user_id, score_text_for_affinity(message.content or ""))
            
                # user content（テキスト + 画像）
                content: list[dict] = []
                if message.content and message.content.strip():
                    content.append({"type": "text", "text": message.content.strip()})
                else:
                    # テキストが無いときは軽い指示だけ添える
                    content.append({"type": "text", "text": "この画像について一言で。"})
                for url in image_urls[:4]:
                    content.append({"type": "image_url", "image_url": {"url": url}})
            
                # ← ここが重要：この分岐専用の messages を作る
                messages_to_send_vision = [
                    {"role": "system", "content": BASE_PERSONA},
                    {"role": "system", "content": affinity_style_instr(get_affinity(user_id))},
                    {"role": "user", "content": content},
                ]
            
                # Visionモデルを明示（nonstream_reply 側の自動切替でもOKだが明示のほうが安全）
                reply = await nonstream_progressive_reply(
                    channel=message.channel,
                    messages=messages_to_send_vision,
                    oai=oai,
                    model_full="gpt-5-vision",
                    model_preview="gpt-5-vision",
                    allowed_mentions=ALLOWED,
                    my_msgs=my_msgs,
                    postprocess=_strip_lifehack_tone,  # 任意
                )
            
                # 会話履歴（テキストのみ保持）
                chat_history.setdefault(user_id, [])
                chat_history[user_id].append({"role": "user", "content": message.content or "[画像]"})
                chat_history[user_id].append({"role": "assistant", "content": reply or "……返す言葉が見つからなかったわ。"})
                if len(chat_history[user_id]) > MAX_HISTORY_MESSAGES * 2:
                    chat_history[user_id] = chat_history[user_id][-MAX_HISTORY_MESSAGES * 2:]
                return

            # 通常のテキスト会話
            user_id = message.author.id
            chat_history.setdefault(user_id, [])
            chat_history[user_id].append({"role": "user", "content": message.content})
            bump_affinity(user_id, score_text_for_affinity(message.content or ""))
            if len(chat_history[user_id]) > MAX_HISTORY_MESSAGES * 2:
                chat_history[user_id] = chat_history[user_id][-MAX_HISTORY_MESSAGES * 2:]

            messages_to_send = [
                {"role": "system", "content": BASE_PERSONA},
                {"role": "system", "content": affinity_style_instr(get_affinity(user_id))},
            ] + chat_history[user_id]

            model = _choose_model(messages_to_send)  # "gpt-5" or "gpt-5-mini"
            reply = await nonstream_progressive_reply(
                channel=message.channel,
                messages=messages_to_send,
                oai=oai,
                model_full=model,           # _choose_model の結果
                model_preview="gpt-5-mini",
                allowed_mentions=ALLOWED,
                my_msgs=my_msgs,
                postprocess=_strip_lifehack_tone,
            )

            chat_history[user_id].append({"role": "assistant", "content": reply or "……返す言葉が見つからなかったわ。"})

            if len(chat_history[user_id]) > MAX_HISTORY_MESSAGES * 2:
                chat_history[user_id] = chat_history[user_id][-MAX_HISTORY_MESSAGES * 2:]

        except asyncio.TimeoutError:
            await message.channel.send("魔力切れ。少ししてからもう一度。", allowed_mentions=ALLOWED)
        except discord.errors.HTTPException:
            await message.channel.send("……返す言葉が見つからなかったわ。", allowed_mentions=ALLOWED)
        except Exception as e:
            logging.exception("LLM生成中に失敗: %s", e)
            await message.channel.send("魔力が乱れて返答できなかったみたいね。", allowed_mentions=ALLOWED)

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
                    if (datetime.datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 10:
                        logging.error(
                            "Audit: deleter=%s target=%s reason=%s",
                            entry.user, entry.target, entry.reason
                        )
                        break
    except Exception as e:
        logging.exception("削除検知処理で例外: %s", e)

bot.run(DISCORD_TOKEN)
