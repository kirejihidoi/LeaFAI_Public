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
                model="gpt-5",
                messages=messages,
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
