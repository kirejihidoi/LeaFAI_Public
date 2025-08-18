import os
import discord
from openai import OpenAI

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = discord.Client(intents=intents)

# 履歴を保持するための辞書と履歴の最大数を定義
# ユーザーやチャンネルごとの会話履歴を保持し、指定した数を超える場合は古いメッセージから削除する
# ここでは 6 件のメッセージ（ユーザー／アシスタントの計 3 往復）を保持する
MAX_HISTORY_MESSAGES = 6
chat_history = {}

# 🧙‍♀️ 基本人格プロンプト（ここを書き換えればキャラを変えられる）
BASE_PERSONA = """

"""

@bot.event
async def on_ready():
    print(f"ログイン成功: {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    try:
        # ユーザー ID を基に履歴を取得・初期化
        user_id = message.author.id
        if user_id not in chat_history:
            chat_history[user_id] = []

        # 現在のユーザー発言を履歴に追加
        chat_history[user_id].append({"role": "user", "content": message.content})
        # 履歴が指定数を超えたら古い要素を削除
        if len(chat_history[user_id]) > MAX_HISTORY_MESSAGES * 2:
            chat_history[user_id] = chat_history[user_id][-MAX_HISTORY_MESSAGES * 2:]

        # システムメッセージと履歴を合わせて API に送信
        messages_to_send = [{"role": "system", "content": BASE_PERSONA}] + chat_history[user_id]
        response = client.chat.completions.create(
            model="gpt-5",
            messages=messages_to_send,
            max_completion_tokens=1500,  # 2〜3文にちょうど良い
        )

        reply = response.choices[0].message.content.strip()
        if not reply:
            reply = "……返す言葉が見つからなかったわ。"

        # アシスタントの返答も履歴に追加し、指定数を超えたら削除
        chat_history[user_id].append({"role": "assistant", "content": reply})
        if len(chat_history[user_id]) > MAX_HISTORY_MESSAGES * 2:
            chat_history[user_id] = chat_history[user_id][-MAX_HISTORY_MESSAGES * 2:]

        await message.channel.send(reply)
    except discord.errors.HTTPException:
        # Discord の送信制限等により応答できなかった場合
        await message.channel.send("……返す言葉が見つからなかったわ。")
    except Exception as e:
        # その他の例外はログに出力し、エラーメッセージを送信
        print(f"Error: {e}")
        await message.channel.send("魔力が乱れて返答できなかったみたいね。")

bot.run(DISCORD_TOKEN)
