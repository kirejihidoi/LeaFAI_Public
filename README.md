# LeaFAI — Discord Bot on Railway (No Local Setup)

> 🚀 **Hosted-only**: This repository is designed to run on **Railway** with zero local environment.  
> 🧪 Models: Uses OpenAI Chat Completions API (`gpt-5`, `gpt-5-mini`; optional vision model).  
> 🧵 Replies: Non-stream. `typing()`で擬似ストリーミング表示し、完成文を一括送信。  
> 💾 State: Affinity (好感度) is persisted to a Railway **Volume**.

---

## 目次

- [概要](#概要)
- [アーキテクチャ](#アーキテクチャ)
- [Railway クイックスタート](#railway-クイックスタート)
- [必要な環境変数](#必要な環境変数)
- [Discord Bot 側の設定](#discord-bot-側の設定)
- [永続化 (Volume) 設定](#永続化-volume-設定)
- [リポジトリ構成](#リポジトリ構成)
- [動作の流れ](#動作の流れ)
- [モデルとコストの運用](#モデルとコストの運用)
- [ログ/運用](#ログ運用)
- [トラブルシューティング](#トラブルシューティング)
- [FAQ](#faq)
- [ライセンス](#ライセンス)

---

## 概要

LeaFAI は Discord 上で動く雑談寄りボットです。**ローカル実行は想定せず、Railway でのみ**起動できるように作られています。  
メインの特徴：

- OpenAI Chat Completions で応答を生成（`gpt-5` / `gpt-5-mini`）。
- 画像メッセージに反応（添付画像があれば Vision モデルに切替）。
- `typing()` による軽い「書いてます」表示 → 完成文をまとめて送信（メッセージの上書き編集はしません）。
- テキスト会話は軽量モデル既定、長文やコードなどは自動で出力量を拡張。
- 発話内容に応じて**好感度**を上下し、返答トーンを微調整。好感度は Railway Volume に**永続化**。

---

## アーキテクチャ

```
Discord (Gateway) ──> bot.py
                         ├─ nonstream_reply.py  … 画像混在時の堅牢返信（typing 表示 + フォールバック）
                         ├─ base_persona.py     … システム/キャラプロンプト
                         ├─ reply_modes.py      … 出力量の自動調整（Max tokens）
                         ├─ token_budget.py     … プロンプトのトークン予算調整
                         ├─ concurrency.py      … 併発数制御（Semaphore）
                         └─ /data/affinity.json … 好感度永続（Railway Volume）
                  └─ OpenAI (Chat Completions API)
```

- `bot.py` … Discord クライアント、メッセージ処理・履歴・好感度管理。通常テキストはシングルショットで応答。
- `nonstream_reply.py` … 画像混在時に `typing()` を出しながらバックグラウンド生成。短文プレビューも並列起動しますが、**プレビューの送信はせず**最終文のみ送信します（フォールバック用途）。
- `reply_modes.py` … 長文/コード検知時に max tokens を自動拡大（環境変数で調整可）。
- `token_budget.py` … 会話履歴をトークン上限に合うようカット。
- `concurrency.py` … 同時リクエスト数の制御。

---

## Railway クイックスタート

1) **New Project → GitHub からデプロイ**  
   このリポジトリを Railway に接続してデプロイします。

2) **Environment Variables** を下記の通り作成（後述セクション参照）。

3) **Volumes** で `/data` パスに任意サイズのボリュームをマウント。

4) **Start Command** を `python -u bot.py` に設定。  
   （Procfile/railway.toml がない構成を想定。Railway の UI でコマンド指定）

5) デプロイ完了後、**Logs** に `ログイン成功: <bot user>` が出ればOK。

---

## 必要な環境変数

| 変数 | 必須 | 例/デフォルト | 説明 |
|---|:--:|---|---|
| `DISCORD_TOKEN` | ✅ | (Discord Bot Token) | Discord Bot のトークン |
| `OPENAI_API_KEY` | ✅ | (OpenAI API Key) | OpenAI API キー |
| `MODEL_FAST` |  | `gpt-5-mini` | 既定の軽量モデル |
| `MODEL_HEAVY` |  | `gpt-5` | 画像時/重い処理用の候補（内部で使用） |
| `MODEL_VISION` |  | `gpt-5-vision` | 画像混在時の切替先 |
| `MAX_PROMPT_TOKENS` |  | `6144` | プロンプト入力の上限（`token_budget.py`） |
| `MAX_COMPLETION_TOKENS` |  | `384` | 通常時の出力量（`reply_modes.py`） |
| `HEAVY_COMPLETION_TOKENS` |  | `896` | 長文/コード検知時の出力量 |
| `HISTORY_TURNS` |  | `6` | 保存する履歴ペア数（user/assistant で2倍） |
| `GLOBAL_CONCURRENCY` |  | `3` | 同時実行の上限（Semaphore） |
| `SHORTCUTS_ENABLED` |  | `1` | 定型短文ショートカットのON/OFF |
| `AFFINITY_PATH` |  | `/data/affinity.json` | 好感度の保存先（Volume 必須） |
| `TZ` |  | `Asia/Tokyo` | タイムゾーン（Railway Variables に追加推奨） |

> 補足: `nonstream_reply.py` の `preview_tokens` / `full_tokens_*` やタイムアウト値は**関数引数の既定値**で制御しています。必要ならコード側で調整してください。

---

## Discord Bot 側の設定

- **Intents**: *Message Content Intent* を有効化（Discord Developer Portal）。  
- **権限(permissions)**: 少なくとも以下を推奨
  - Send Messages
  - Read Message History
  - Attach Files（画像への反応が必要なため）
- Bot をサーバーに招待後、Bot がメッセージを読めるチャンネルで動作確認。

---

## 永続化 (Volume) 設定

- Railway の **Volumes** で `/data` にマウント。  
- `AFFINITY_PATH=/data/affinity.json` を指定。  
- 好感度 JSON はボットが自動作成/更新します。バックアップは必要に応じて。

---

## リポジトリ構成

```
.
├─ bot.py                 # Discord エントリポイント（テキストはシングルショット応答）
├─ nonstream_reply.py     # 画像混在時の堅牢返信（typing 表示 + フォールバック）
├─ base_persona.py        # キャラクタ（BASE_PERSONA）
├─ reply_modes.py         # 出力量の自動調整（MAX_/HEAVY_COMPLETION_TOKENS）
├─ token_budget.py        # プロンプトのトークン予算調整
├─ concurrency.py         # 併発数制御（GLOBAL_CONCURRENCY）
├─ shortcuts.py           # 定型短文ショートカット（SHORTCUTS_ENABLED）
├─ requirements.txt       # Python 依存
└─ README.md              # このドキュメント
```

**requirements.txt 例**（参考）:
```txt
discord.py>=2.3.2,<3
openai>=1.40.0
httpx>=0.27.0
```

> Python 3.11 推奨。Start Command: `python -u bot.py`。

---

## 動作の流れ

**テキストメッセージ:**
1. メッセージ受信。好感度を微調整。  
2. `base_persona.py` + 好感度 + 会話履歴を結合し、トークン予算内に収める。  
3. `MODEL_FAST` を既定に `chat.completions.create()` を実行。`reply_modes.py` が長文/コード検知時は `MAX_COMPLETION_TOKENS` を自動拡張。  
4. 完成文を送信。履歴に保存。

**画像混在メッセージ:**
1. 添付画像の URL を抽出。  
2. `MODEL_VISION` へ切替し、`nonstream_reply.py` が `typing()` を表示しつつバックグラウンドで生成。短文プレビューも並列で起動しますが**送信はせず**、最終文のみ送信。  
3. 空応答やタイムアウト時はフォールバック（短文強制など）。

---

## モデルとコストの運用

- 通常は **`gpt-5-mini`** を既定に、長文/コード/重い会話は `reply_modes.py` により**出力量を拡張**。  
- 画像混在時は **Vision** に切替。  
- 出力量は `MAX_COMPLETION_TOKENS` / `HEAVY_COMPLETION_TOKENS` を調整。  
- `gpt-5*` はサンプリング無視（実装で自動制御）。`gpt-4/4o` を使う場合のみ `temperature` 等を渡す実装に変更してください。

---

## ログ/運用

- Railway の **Logs** を参照。起動時 `ログイン成功: <bot>` が出れば接続OK。  
- `GLOBAL_CONCURRENCY` で同時実行数を制御。負荷やレート制限に応じて調整。

---

## トラブルシューティング

**400 Unsupported parameter: `max_tokens`**  
→ Chat Completions は `max_completion_tokens` を使います（本実装は対応済み）。

**400 Unsupported value: `temperature`**  
→ `gpt-5*` には送らない設計です。`gpt-4/4o` を使う場合のみ付与。

**TypeError: event registered must be a coroutine function**  
→ `@bot.event` の関数が `async def` になっているか確認。

**empty_content / 返す言葉が見つからなかった**  
→ モデルが空を返した場合の保険メッセージです。頻発するなら出力量やタイムアウトを緩めてください。

**Can't keep up, websocket is Xs behind**  
→ リソース不足かイベント過多。Railway プランや併発数を見直す。

---

## FAQ

**Q. ローカルで動かせますか？**  
A. 想定していません。Railway 専用です。

**Q. 好感度の上限/下限は？**  
A. `[-5, +5]` でクリップ。JSON に保存。

**Q. キャラ文を差し替えたい**  
A. `base_persona.py` の `BASE_PERSONA` を編集してください（長文OK）。

**Q. Vision モデルは必須？**  
A. 画像に反応したい場合のみ。未設定でもテキストは動作します。

---

## ライセンス

MIT License（必要に応じて変更してください）。
