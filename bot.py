import os
import asyncio
import logging
import datetime
import discord
from pathlib import Path
from openai import AsyncOpenAI, APIError, APIConnectionError, RateLimitError, APITimeoutError

from nonstream_reply import nonstream_progressive_reply
from base_persona import BASE_PERSONA, BASE_PERSONA_SNARK, pick_persona

# NEW: token saving helpers
from token_budget import fit_to_budget, MAX_PROMPT_TOKENS
from reply_modes import choose_max_out
from shortcuts import shortcut_reply
from concurrency import REQUEST_SEMAPHORE, user_lock

# ====== Discord Setup ======
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
bot = discord.Client(intents=intents, max_messages=None)

ALLOWED = discord.AllowedMentions(everyone=False, users=True, roles=False, replied_user=False)

# ====== OpenAI Setup ======
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set")
oai = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ====== Affinity / Persona ======
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
        AFF_PATH.parent.mkdir(parents=True, exist_ok=True)
        AFF_PATH.write_text(json.dumps(_aff_cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

# ====== History ======
MAX_HISTORY_MESSAGES = int(os.getenv("HISTORY_TURNS", "6"))
chat_history: dict[int, list[dict]] = {}

def _is_image_attachment(att: discord.Attachment) -> bool:
    name = (att.filename or "").lower()
    return any(name.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"))

# ====== Utility ======
def _strip_lifehack_tone(s: str) -> str:
    # Keep it simple; avoid verbose lifehacky tone
    return s

# ====== Event Handlers ======
@bot.event
async def on_ready():
    logging.basicConfig(level=logging.INFO)
    print(f"ログイン成功: {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Cheap replies that don't need the API
    r = shortcut_reply(message.content or "")
    if r:
        await message.channel.send(r, allowed_mentions=ALLOWED)
        return

    async def _work():
        try:
            persona_sys = pick_persona(message.content or "")

            # Image path first
            image_urls = [att.url for att in message.attachments if _is_image_attachment(att)]
            if image_urls:
                user_id = message.author.id
                content = message.content.strip() if (message.content and message.content.strip()) else "画像について説明して。"
                bump_affinity(user_id, 1)

                messages_to_send_vision = [
                    {"role": "system", "content": persona_sys},
                    {"role": "system", "content": f"RELATIONSHIP_AFFINITY={get_affinity(user_id)}"},
                    {"role": "user", "content": content},
                ]
                messages_to_send_vision = fit_to_budget(messages_to_send_vision, MAX_PROMPT_TOKENS)

                async with REQUEST_SEMAPHORE:
                    async with user_lock(user_id):
                        reply = await nonstream_progressive_reply(
                            channel=message.channel,
                            messages=messages_to_send_vision,
                            oai=oai,
                            model_full=os.getenv("MODEL_VISION", "gpt-5-vision"),
                            model_preview=None,
                            allowed_mentions=ALLOWED,
                            my_msgs={},
                            postprocess=_strip_lifehack_tone,
                        )
                # Save history as text only
                chat_history.setdefault(user_id, [])
                chat_history[user_id].append({"role": "user", "content": message.content or "[画像]"})
                chat_history[user_id].append({"role": "assistant", "content": reply or "……返す言葉が見つからなかったわ。"})
                if len(chat_history[user_id]) > MAX_HISTORY_MESSAGES * 2:
                    chat_history[user_id] = chat_history[user_id][-MAX_HISTORY_MESSAGES * 2:]
                return

            # Text path
            user_id = message.author.id
            text = message.content or ""
            bump_affinity(user_id, 1 if len(text) > 4 else 0)

            chat_history.setdefault(user_id, [])
            # 構築: persona + affinity + 履歴 + 最新
            messages_to_send = [
                {"role": "system", "content": persona_sys},
                {"role": "system", "content": f"RELATIONSHIP_AFFINITY={get_affinity(user_id)}"},
            ] + chat_history[user_id] + [{"role": "user", "content": text}]
            messages_to_send = fit_to_budget(messages_to_send, MAX_PROMPT_TOKENS)

            model = os.getenv("MODEL_FAST", "gpt-5-mini")

            async with REQUEST_SEMAPHORE:
                async with user_lock(user_id):
                    r = await oai.chat.completions.create(
                        model=model,
                        messages=messages_to_send,
                        max_completion_tokens=choose_max_out(text),
                    )
            reply = (r.choices[0].message.content or "").strip()

            # Fallback: try once more if empty
            if not reply:
                async with REQUEST_SEMAPHORE:
                    async with user_lock(user_id):
                        r = await oai.chat.completions.create(
                            model=model,
                            messages=messages_to_send,
                            max_completion_tokens=choose_max_out(text),
                        )
                reply = (r.choices[0].message.content or "").strip() or "……返す言葉が見つからなかったわ。"

            chat_history[user_id].append({"role": "user", "content": text})
            chat_history[user_id].append({"role": "assistant", "content": reply})
            if len(chat_history[user_id]) > MAX_HISTORY_MESSAGES * 2:
                chat_history[user_id] = chat_history[user_id][-MAX_HISTORY_MESSAGES * 2:]

            await message.channel.send(reply, allowed_mentions=ALLOWED)

        except RateLimitError:
            await message.channel.send("魔力切れ。少ししてからもう一度。", allowed_mentions=ALLOWED)
        except (APIConnectionError, APITimeoutError):
            await message.channel.send("魔力が乱れて返答できなかったみたいね。", allowed_mentions=ALLOWED)
        except Exception as e:
            logging.exception("LLM生成中に失敗: %s", e)
            await message.channel.send("魔力が乱れて返答できなかったみたいね。", allowed_mentions=ALLOWED)

    asyncio.create_task(_work())

# ====== Run ======
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set")

bot.run(DISCORD_TOKEN)
