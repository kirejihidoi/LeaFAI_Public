# bot.py
import os
import asyncio
import logging
from typing import List

import discord
from discord import Intents
from openai import AsyncOpenAI

from base_persona import BASE_PERSONA

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LeaFDiscordBot")

def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        logger.error(f"環境変数が未設定: {name}")
    return val or ""

DISCORD_TOKEN = _require_env("DISCORD_TOKEN")
OPENAI_API_KEY = _require_env("OPENAI_API_KEY")

# テキスト用と画像入力用モデル
MODEL_FAST = os.getenv("MODEL_FAST", "gpt-5-nano")
MODEL_VISION = os.getenv("MODEL_VISION", "gpt-5-mini")  # 画像対応の既定

DISCORD_CHUNK = 1900

if not DISCORD_TOKEN or not OPENAI_API_KEY:
    import time
    time.sleep(2)
    raise SystemExit(1)

client_oa = AsyncOpenAI(api_key=OPENAI_API_KEY)

intents = Intents.default()
intents.message_content = True
intents.guilds = True

bot = discord.Client(intents=intents)

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

async def _chat_complete(user_text: str, image_urls: List[str]) -> str:
    # image_urls があれば画像入力対応モデルを使用
    model = MODEL_VISION if image_urls else MODEL_FAST

    # Chat Completions 用の content 配列を構築
    user_content = []
    if user_text:
        user_content.append({"type": "text", "text": user_text})

    for url in image_urls:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": url}
        })

    # 画像だけ投げられたときのテキスト
    if not user_content:
        user_content = [{"type": "text", "text": BASE_PERSONA}]

    try:
        resp = await client_oa.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": BASE_PERSONA},
                {"role": "user", "content": user_content},
            ],
            # nano系は stop 未対応のことがあるので付けない
            max_completion_tokens=2896, # ←大きめ。適宜調整
        )
        ch = resp.choices[0]
        msg = (ch.message.content or "").strip()
        u = getattr(resp, "usage", None)
        if u:
            logger.info(f"usage prompt={getattr(u,'prompt_tokens',None)} completion={getattr(u,'completion_tokens',None)}")
        if msg:
            return msg
        if (ch.finish_reason or "") == "length":
            logger.warning("finish_reason=length on main call")
    except Exception as e:
        logger.error(f"OpenAI error: {e}")

    # フォールバック（ローカル）
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
    user_text = message.content.strip() if message.content else ""
    image_urls = _pick_image_urls(message)

    async def work():
        # 入力中… 表示
        async with message.channel.typing():
            reply = await _chat_complete(user_text, image_urls)
        await _chunked_send(message.channel, reply)

    try:
        await asyncio.wait_for(work(), timeout=60)
    except asyncio.TimeoutError:
        await message.channel.send("長い。終わらない。")

def main():
    bot.run(DISCORD_TOKEN, log_handler=None)

if __name__ == "__main__":
    main()
