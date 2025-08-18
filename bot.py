import os
import asyncio
import logging
import discord
from openai import AsyncOpenAI

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# OpenAI 非同期クライアント
oai = AsyncOpenAI(api_key=OPENAI_API_KEY)
GEN_SEMAPHORE = asyncio.Semaphore(3)  # 同時生成制限
OPENAI_TIMEOUT = 30  # 秒

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = discord.Client(intents=intents)

# 会話履歴保持
MAX_HISTORY_MESSAGES = 6
chat_history = {}

# 🧙‍♀️ 基本人格プロンプト
BASE_PERSONA = """あなたのプロンプト"""

async def _generate_reply(messages):
    """OpenAI呼び出し。セマフォとタイムアウト付き。"""
    async with GEN_SEMAPHORE:
        async with asyncio.timeout(OPENAI_TIMEOUT):
            resp = await oai.chat.completions.create(
                model="gpt-5-mini",
                messages=messages,
            )
            return resp.choices[0].message.content.strip()

def _is_image_attachment(att: discord.Attachment) -> bool:
    """画像ファイルかどうかの簡易判定"""
    ct = (att.content_type or "").lower()
    return ct.startswith("image/") or att.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))

async def _generate_vision_reply(user_text: str, image_urls: list[str]) -> str:
    """画像付きメッセージに対して短く回答（画像生成はしない）。"""
    # content に text と image_url を混在
    content = []
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
                    {"role": "user", "content": content},
                ],
            )
            return resp.choices[0].message.content.strip()

@bot.event
async def on_ready():
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
                async with message.channel.typing():
                    reply = await _generate_vision_reply(message.content or "", image_urls)
                # 会話履歴（テキストのみ保持）
                user_id = message.author.id
                chat_history.setdefault(user_id, [])
                chat_history[user_id].append({"role": "user", "content": message.content or "[画像]"})
                chat_history[user_id].append({"role": "assistant", "content": reply})
                if len(chat_history[user_id]) > MAX_HISTORY_MESSAGES * 2:
                    chat_history[user_id] = chat_history[user_id][-MAX_HISTORY_MESSAGES * 2:]
                # Discordの2000文字制限対策（安全側に1900で分割）
                for i in range(0, len(reply), 1900):
                    await message.channel.send(reply[i:i+1900])
                return

            user_id = message.author.id
            if user_id not in chat_history:
                chat_history[user_id] = []

            # 履歴追加
            chat_history[user_id].append({"role": "user", "content": message.content})
            if len(chat_history[user_id]) > MAX_HISTORY_MESSAGES * 2:
                chat_history[user_id] = chat_history[user_id][-MAX_HISTORY_MESSAGES * 2:]

            messages_to_send = [{"role": "system", "content": BASE_PERSONA}] + chat_history[user_id]

            async with message.channel.typing():
                reply = await _generate_reply(messages_to_send)
                if not reply:
                    reply = "……返す言葉が見つからなかったわ。"

            # 履歴に返答を追加
            chat_history[user_id].append({"role": "assistant", "content": reply})
            if len(chat_history[user_id]) > MAX_HISTORY_MESSAGES * 2:
                chat_history[user_id] = chat_history[user_id][-MAX_HISTORY_MESSAGES * 2:]

            # Discordの2000文字制限対策（安全側に1900で分割）
            for i in range(0, len(reply), 1900):
                await message.channel.send(reply[i:i+1900])

        except asyncio.TimeoutError:
            await message.channel.send("魔力切れ。少ししてからもう一度。")
        except discord.errors.HTTPException:
            await message.channel.send("……返す言葉が見つからなかったわ。")
        except Exception as e:
            logging.exception("LLM生成中に失敗: %s", e)
            await message.channel.send("魔力が乱れて返答できなかったみたいね。")

    # ここでバックグラウンドタスク化 → イベントループが止まらない
    asyncio.create_task(_work())

bot.run(DISCORD_TOKEN)
