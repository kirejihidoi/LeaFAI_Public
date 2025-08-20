# LeaFAI Discord Bot — Setup & Deployment (Railway)

このREADMEは、同梱の `bot.py` を使ってDiscordボットを起動し、Railwayにデプロイして常時稼働させるまでの手順をまとめたものです。

---

## 目次

- [概要](#概要)
- [リポジトリ構成](#リポジトリ構成)
- [必要要件](#必要要件)
- [Discord 側の準備](#discord-側の準備)
- [OpenAI 側の準備](#openai-側の準備)
- [環境変数](#環境変数)
- [設定のカスタマイズ](#設定のカスタマイズ)
- [Railway へデプロイ](#railway-へデプロイ)
- [運用・ログ確認](#運用ログ確認)
- [トラブルシューティング](#トラブルシューティング)

---

## 概要

- Python + `discord.py` で実装されたシンプルなDiscordボットです。
- 返信生成に OpenAI API (`openai>=1.0.0` 系) を使用します。本リポジトリは `openai==1.99.9` を想定しています。
- `bot.py` は会話履歴を一定件数で保持し、超過した古いメッセージを自動で削除します。
- モデルは `gpt-5` を利用し、`max_completion_tokens` を使用する実装にしています（`max_tokens` ではありません）。

---

## リポジトリ構成

```
.
├─ data/affinity.json   # 好感度ファイル
├─ bot.py               # Discordボット本体
├─ conversations.json   # 今後の拡張用（現在は空）
└─ requirements.txt     # 必要パッケージ（discord.py 2.5.2 / openai 1.99.9）
```

---

## 必要要件

- Python 3.10 以上（3.11 推奨）
- Discord アカウント（Bot をサーバに招待する権限）
- OpenAI API キー
- Railway アカウント（デプロイする場合）

---

## Discord 側の準備

1. **Developer Portal** にアクセスし、新規 Application を作成する。
2. 左メニュー **Bot** で **Add Bot**。**Reset Token** で Bot Token を発行して控える。
3. **Privileged Gateway Intents** で **MESSAGE CONTENT INTENT** を **有効化**。
   - 本ボットはメッセージ本文を読む必要があります。
4. 左メニュー **OAuth2 > URL Generator** を開く。
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Read Message History` など最低限に絞る。
   - 生成されたURLでBotを自サーバへ招待。

> 注意: Bot Token は**公開しない**こと。GitHub等に直接コミットしないでください。

---

## OpenAI 側の準備

1. OpenAI アカウント作成・ログイン。
2. API Keys で **Secret Key** を作成・控える。
3. 必要に応じて Billing を有効化。

---

起動後、Bot がサーバに参加している任意のチャンネルでメッセージを送ると応答します。

---

## 環境変数

| 変数名              | 必須 | 用途                |
| ---------------- | -- | ----------------- |
| `DISCORD_TOKEN`  | 必須 | Discord Bot Token |
| `OPENAI_API_KEY` | 必須 | OpenAI の API キー   |
| `AFFINITY_PATH=/data/affinity.json` | 必須 | 好感度ファイルのpath   |
> 代替エンドポイントを使う場合は `openai` の標準設定に従ってコードを拡張してください（本実装は `api_key` のみ）。

---

## 設定のカスタマイズ

`bot.py` 内で主に調整する場所:

- **モデル名**: `model="gpt-5"`
- **トークン数**: `max_completion_tokens=1500`
- **会話履歴の保持数**: `MAX_HISTORY_MESSAGES`（ユーザー/アシスタントで合計 `2 * MAX_HISTORY_MESSAGES` メッセージ分を維持。超過すると古いものから削除）
- **ペルソナ**: `BASE_PERSONA`（長文。口調や制約を変更可）

---

## Railway へデプロイ

ここでは GitHub リポジトリを Railway に接続してデプロイする想定です。

### 1) リポジトリを GitHub に用意

- まだであれば、GitHub に本リポジトリをプッシュしておく。

### 2) Railway プロジェクト作成

1. Railway にログインし **New Project** を選択。
2. **Deploy from GitHub repo** を選び、対象リポジトリを接続。

### 3) Build & Start 設定

Railway は Python プロジェクトを自動検出します。必要に応じて以下を明示:

- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python bot.py`

### 4) 環境変数を設定

Railway の **Variables** で以下を追加:

- `DISCORD_TOKEN` = あなたの Bot Token
- `OPENAI_API_KEY` = あなたの OpenAI API キー
- `AFFINITY_PATH=/data/affinity.json`

### 5) デプロイ
- Volumeを /data/affinity.json にマウントして、好感度はそこに置く。
- 変数を保存すると自動でデプロイが走るか、**Deploy** を実行。
- デプロイ完了後、ログに `Logged in as <BotName>` のような表示が出れば起動成功。

> Free/Trial プランではスリープや時間制限がある場合があります。稼働要件に応じてプランを確認してください。

---

## 運用・ログ確認

- Railway のプロジェクト画面 > **Deployments** または **Logs** からリアルタイムでログを確認できます。
- Discord 側で応答しない時は、Railway ログにエラーが出ていないか確認してください。

---

## トラブルシューティング

**A. OpenAI 側エラー**

- `401 Unauthorized` → `OPENAI_API_KEY` が無効/未設定。
- `429`/レート制限 → リクエスト頻度を下げる。Billing/利用状況を確認。
- `Unsupported parameter: 'max_tokens'` → この実装は `max_completion_tokens` を使用済み。自作改変時は注意。

**B. Discord 側エラー**

- `403 Forbidden` / メッセージ送信不可 → Bot ロール/権限を確認。
- メッセージ本文が読めない → Developer Portal の **MESSAGE CONTENT INTENT** を有効化。
- `Can't keep up, websocket is Xs behind` → 実行環境の負荷やネットワーク遅延。Railway のプランやリソースを確認。

**C. 起動しない / 落ちる**

- Python バージョン違い → 3.10 以上で再実行。
- 依存未インストール → `pip install -r requirements.txt` を再実行。
- 例外ログをRailwayで確認し、該当箇所（`bot.py`）を修正。

---

## ライセンス

- 本リポジトリのライセンス方針に従ってください。未指定の場合は私用の範囲での利用に留め、公開配布時は明記してください。

---

## 参考

- Discord Developer Portal: Bot 作成/権限/Intents 設定
- OpenAI API: Chat Completions (`gpt-5` 系) の利用と課金設定
- Railway Docs: Python サービスのデプロイと環境変数設定
