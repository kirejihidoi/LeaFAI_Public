# bot.py
import os
import asyncio
import logging
from typing import List

import discord
from discord import Intents
from openai import AsyncOpenAI

from base_persona import BASE_PERSONA
from history import HistoryStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LeaFDiscordBot")

def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        logger.error(f"環境変数が未設定: {name}")
    return val or ""

DISCORD_TOKEN = _require_env("DISCORD_TOKEN")
OPENAI_API_KEY = _require_env("OPENAI_API_KEY")

MODEL_FAST = os.getenv("MODEL_FAST", "gpt-5-nano")
MODEL_VISION = os.getenv("MODEL_VISION", "gpt-5-mini")  # 画像対応の既定
MODEL_VISION_FALLBACK = os.getenv("MODEL_VISION_FALLBACK", "gpt-4o-mini")

# 何往復まで履歴に入れるか（環境変数で調整可能）
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "6"))

DISCORD_CHUNK = 1900

if not DISCORD_TOKEN or not OPENAI_API_KEY:
    import time
    time.sleep(2)
    raise SystemExit(1)

client_oa = AsyncOpenAI(api_key=OPENAI_API_KEY)
history = HistoryStore(max_turns=HISTORY_TURNS)

intents = Intents.default()
intents.message_content = True
intents.guilds = True

bot = discord.Client(intents=intents)

def _conv_id(message: discord.Message) -> str:
    # サーバー内はチャンネル単位、DMはチャンネルIDで分離
    if message.guild:
        return f"g{message.guild.id}:c{message.channel.id}"
    return f"dm:c{message.channel.id}"

async def _chunked_send(channel: discord.abc.Messageable, text: str):
    for i in range(0, len(text), DISCORD_CHUNK):
        await channel.send(text[i : i + DISCORD_CHUNK])

def _pick_image_urls(message: discord.Message, limit: int = 4) -> List[str]:
    urls: List[str] = []
    if not message.attachments:
        return urls
    for a in message.attachments:
        ct = (a.content_type or "").lower()
        name = (a.filename or "").lower()
        if ct.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            urls.append(a.url)
            if len(urls) >= limit:
                break
    return urls

async def _call_openai(model: str, messages, max_tokens: int) -> str:
    resp = await client_oa.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=max_tokens,  # stopは付けない（nano系は未対応のことがある）
    )
    ch = resp.choices[0]
    msg = (ch.message.content or "").strip()
    u = getattr(resp, "usage", None)
    if u:
        logger.info(f"usage model={model} prompt={getattr(u,'prompt_tokens',None)} completion={getattr(u,'completion_tokens',None)}")
    if not msg and (ch.finish_reason or "") == "length":
        logger.warning("finish_reason=length")
    return msg

async def _chat_complete(cid: str, user_text: str, image_urls: List[str]) -> str:
    # 今回のユーザー入力（マルチモーダル）
    user_content = []
    if user_text:
        user_content.append({"type": "text", "text": user_text})
    for url in image_urls:
        user_content.append({"type": "image_url", "image_url": {"url": url}})
    if not user_content:
        user_content = [{"type": "text", "text": "画像を見て一言コメントだけ返して。"}]

    # 履歴込みmessagesを構築
    messages = await history.build_messages(BASE_PERSONA, cid, user_content)

    model = MODEL_VISION if image_urls else MODEL_FAST
    try:
        msg = await _call_openai(model, messages, max_tokens=2896)
        if msg:
            # 成功したら「今回の往復」を履歴に反映
            await history.append_user(cid, user_text, image_urls)
            await history.append_assistant(cid, msg)
            return msg
    except Exception as e:
        logger.error(f"OpenAI error (primary): {e}")

    # モデルが画像非対応だった場合のフォールバック
    if image_urls:
        try:
            logger.info(f"retry with fallback vision model: {MODEL_VISION_FALLBACK}")
            msg = await _call_openai(MODEL_VISION_FALLBACK, messages, max_tokens=2048)
            if msg:
                await history.append_user(cid, user_text, image_urls)
                await history.append_assistant(cid, msg)
                return msg
        except Exception as e:
            logger.error(f"OpenAI error (vision fallback): {e}")

    # テキストのみの軽量フォールバック
    try:
        tiny_sys = "一人称は私。淡々と1〜2文で返す。テキストのみ。"
        tiny_msgs = [
            {"role": "system", "content": tiny_sys},
            # 履歴は詰め替えず、直近のユーザー分だけで妥協
            {"role": "user", "content": user_content},
        ]
        msg = await _call_openai(MODEL_FAST, tiny_msgs, max_tokens=480)
        if msg:
            await history.append_user(cid, user_text, image_urls)
            await history.append_assistant(cid, msg)
            return msg
    except Exception as e:
        logger.error(f"OpenAI error (tiny fallback): {e}")

    return _local_fallback(user_text)

def _local_fallback(user_text: str) -> str:
    ut = (user_text or "").strip()
    if "なにしてる" in ut or "何してる" in ut:
        return "……別に、何もしてないけど。さっき動画見て時間溶かした。"
    if "犬" in ut:
        return "犬は好き。静かに寄ってくるやつは特に。"
    if "猫" in ut:
        return "猫は無理。近づかないでほしい。"
    return "……ふーん、そう。別に大したことじゃないけど。"

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    cid = _conv_id(message)
    # 簡易リセットコマンド（面倒な時用）
    if (message.content or "").strip() == "!reset":
        await history.reset(cid)
        await message.channel.send("履歴、消した。")
        return

    user_text = message.content.strip() if message.content else ""
    image_urls = _pick_image_urls(message)

    async def work():
        async with message.channel.typing():  # 入力中… 表示
            reply = await _chat_complete(cid, user_text, image_urls)
        await _chunked_send(message.channel, reply)

    try:
        await asyncio.wait_for(work(), timeout=60)
    except asyncio.TimeoutError:
        await message.channel.send("長い。終わらない。")

def main():
    bot.run(DISCORD_TOKEN, log_handler=None)

if __name__ == "__main__":
    main()
