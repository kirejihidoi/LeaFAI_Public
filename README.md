# LeaFAI — Discord Bot on Railway (No Local Setup)

> 🚀 **Hosted-only**: This repository is designed to run on **Railway** with zero local environment.  
> 🧪 Models: Uses OpenAI Chat Completions API (`gpt-5`, `gpt-5-mini`; optional vision model).  
> 🧵 Replies: Non-stream, “preview then full” UX with safe fallback; `typing()`での擬似ストリーミング。  
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
- 画像メッセージに反応（画像 URL をメッセージに混在させて Vision モデルに切替）。
- `typing()` による軽い「書いてます」表示 → 完成文をまとめて送信。  
- 先出しプレビュー + 本文生成の**二段構え**（どちらかが失敗しても安全にフォールバック）。
- 発話内容に応じて**好感度**を上下し、返答トーンを微調整。好感度は Railway Volume に**永続化**。

---

## アーキテクチャ

```
Discord (Gateway) ──> bot.py
                         ├─ nonstream_reply.py  … 非ストリーム返信（プレビュー→本体）
                         ├─ base_persona.py     … システム/キャラプロンプト
                         └─ /data/affinity.json … 好感度の永続ファイル（Railway Volume）
                  └─ OpenAI (Chat Completions API)
```

- `bot.py` … Discord クライアント、メッセージ処理・履歴・好感度管理。
- `nonstream_reply.py` … `typing()`を使った擬似ストリーミング、プレビュー→本体、画像混在時のモデル切替、堅牢なタイムアウト/フォールバック。
- `base_persona.py` … キャラクタの**長文**プロンプトを分離。
- `/data/affinity.json` … ユーザーごとのスコアを保存（**必ず Volume を /data にマウント**）。

---

## Railway クイックスタート

1) **New Project → GitHub からデプロイ**  
   このリポジトリを Railway に接続してデプロイします。

2) **Environment Variables** を下記の通り作成（後述セクション参照）。

3) **Volumes** で `/data` パスに任意サイズのボリュームをマウント。

4) **Start Command** を `python -u bot.py` に設定。  
   （Procfile/railway.toml がない構成を想定。UI でコマンド指定してください）

5) デプロイ完了後、**Logs** に `ログイン成功: <bot user>` が出ればOK。

---

## 必要な環境変数

| 変数 | 必須 | 例/デフォルト | 説明 |
|---|:--:|---|---|
| `DISCORD_TOKEN` | ✅ | (Discord Bot Token) | Discord Bot のトークン |
| `OPENAI_API_KEY` | ✅ | (OpenAI API Key) | OpenAI API キー |
| `MODEL_FAST` |  | `gpt-5-mini`or nano | 軽量&最軽量モデル |
| `MODEL_HEAVY` |  | `gpt-5` | 重めモデル 場合によってはminiも選択肢|
| `MODEL_VISION` |  | `gpt-5-vision` | 画像混在時の強制切替先（未指定なら内部デフォルトを使用） |
| `AFFINITY_PATH` |  | `/data/affinity.json` | 好感度の保存先（Volume必須） |
| `PREVIEW_TOKENS` |  | `100` | 先出しプレビューの上限 （※うまく返信されないときは徐々に上げる）|
| `FULL_TOKENS_FAST` |  | `400` | mini の本文上限 （※同上）|
| `FULL_TOKENS_HEAVY` |  | `700` | heavy の本文上限 （※同上）|
| `OPENAI_TIMEOUT` |  | `45` | OpenAI 呼び出しの全体タイムアウト（秒）（※こちらも）|

> ℹ️ **サンプリング系 (temperature 等)** は `gpt-5*` では送らず、`gpt-4/4o` のときのみ付与する実装です。

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

- Railway の **Volumes** で `/data` にマウントします。  
- `AFFINITY_PATH=/data/affinity.json` を指定してください。  
- 好感度 JSON はボットが自動作成/更新します。バックアップは必要に応じて。

---

## リポジトリ構成

```
.
├─ bot.py                 # Discord エントリポイント
├─ nonstream_reply.py     # 先出しプレビュー + 本文生成 / typing() 表示 / フォールバック
├─ base_persona.py        # キャラクタ（BASE_PERSONA）
├─ requirements.txt       # Python 依存
└─ README.md              # このドキュメント
```

**requirements.txt 例**（参考）:
```txt
discord.py>=2.3.2,<3
openai>=1.40.0
httpx>=0.27.0
```

> Python 3.11 を推奨。Start Command: `python -u bot.py`。

---

## 動作の流れ

1. Discord メッセージ受信（画像添付があれば URL を抽出）。  
2. 画像が混在 → Vision モデルへ自動切替（`MODEL_VISION`）。  
3. `typing()` を開始し、**プレビュー**用の短文生成と**本体**生成を**並列**で実行。  
4. プレビューが間に合えば先に送信（※上書きはしない実装）。  
5. 本体が完成したら送信。どちらかが失敗/空でも**安全にフォールバック**。  
6. 発話に基づいて好感度を更新・保存。

---

## モデルとコストの運用

- 通常は **`gpt-5-mini`** を既定に、長文/コード/重い会話だけ **`gpt-5`** にスイッチ。  
- 画像混在時は **Vision** に切替。  
- `PREVIEW_TOKENS` / `FULL_TOKENS_*` を小さめにするとコスト圧縮。  
- `gpt-5*` はサンプリング無視（実装で自動制御）。`gpt-4/4o` 使用時のみ `temperature` 等を渡す。

---

## ログ/運用

- Railway の **Logs** を参照。起動時 `ログイン成功: <bot>` が出れば接続OK。  
- Bot の送信メッセージ ID を `my_msgs` に記録。削除検知時は監査ログから削除者推定（権限必要）。

---

## トラブルシューティング

**400 Unsupported parameter: `max_tokens`**  
→ Chat Completions は `max_completion_tokens` を使います（実装済み）。

**400 Unsupported value: `temperature`**  
→ `gpt-5*` には送らないよう実装で制御済み。環境変数で強制している場合は外してください。

**TypeError: event registered must be a coroutine function**  
→ `@bot.event` の関数が `async def` になっているか確認。

**empty_content / 返す言葉が見つからなかった**  
→ モデルが空を返した場合の保険メッセージです。頻発するなら `FULL_TOKENS_*` と締切を緩めてください。

**メッセージがプレースホルダに上書きされる**  
→ 本実装は `typing()` のみで、**メッセージ本文の上書きはしません**。

---

## FAQ

**Q. ローカルで動かせますか？**  
A. 想定していません。Railway 専用です。

**Q. 好感度の上限/下限は？**  
A. `[-5, +5]` でクリップ。JSON に保存されます。

**Q. キャラ文を差し替えたい**  
A. `base_persona.py` の `BASE_PERSONA` を編集してください（長文OK）。

**Q. Vision モデルは必須？**  
A. 画像に反応したい場合のみ。未設定でもテキストは動作します。

---

## ライセンス

MIT License（必要に応じて変更してください）。
