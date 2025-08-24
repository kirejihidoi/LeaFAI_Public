# LeaFAI — Discord Bot × Railway × OpenAI
画像入力対応・軽量メモリ（会話履歴）・Railway専用デプロイ

Discord のテキストチャンネルで動くボットです。OpenAI Chat Completions を使い、**画像添付**にも対応。
ローカル実行は対象外で、**Railway へのデプロイのみ**を想定しています。

---

## 主な特徴

- **ペルソナは `base_persona.py` に三重引用でベタ書き**（長文OK。プロンプトキャッシュ想定）
- **画像入力対応**（画像メッセージが来たら自動でビジョン対応モデルへ切替）
- **会話履歴（軽量メモリ）**：チャンネル単位で直近 N 往復を保持（プロセス内、永続化なし）
- Discord の**「入力中…」インジケータ**表示
- 長文は**分割送信**（Discord の 2000 文字上限対策。既定 1900）
- 追加の Web サーバ不要（Service は **Unexposed** 推奨）

---

## リポジトリ構成

```
.
├── bot.py                # 本体（画像/テキスト、Typing表示、分割送信、メモリ差し込み）
├── history.py            # 会話履歴（プロセス内の簡易ストア、直近 N 往復）
├── base_persona.py       # """あなたのプロンプト""" を貼るだけ
├── requirements.txt      # 依存パッケージ
└── README.md
```

`base_persona.py` は中身をあなたのペルソナに差し替えてください。

```python
# base_persona.py
BASE_PERSONA = """あなたのプロンプト"""
```

> ペルソナを固定するとプロンプトキャッシュが効きやすく、コスト削減が期待できます。

---

## Discord 側の準備

1. Discord Developer Portal でアプリを作成し **Bot** を追加  
2. **MESSAGE CONTENT INTENT** を有効化  
3. 招待 URL（OAuth2）を生成  
   - Scopes: `bot`  
   - Permissions: `View Channels`, `Read Message History`, `Send Messages`

---

## Railway へのデプロイ（ローカル不要）

1. このリポジトリを GitHub にプッシュ（Public/Private どちらでも可）  
2. Railway → **New Project → Deploy from GitHub**  
3. Service 設定  
   - **Start Command**: `python bot.py`  
   - **Networking**: **Unexposed**（ポート公開不要）  
   - リージョンは任意  
4. **Variables（環境変数）** を設定（下表）

### 環境変数（このレポのコードと一致）

| 変数名 | 必須 | 説明 | 既定値 |
|---|:---:|---|---|
| `DISCORD_TOKEN` | ✅ | Discord Bot トークン | なし |
| `OPENAI_API_KEY` | ✅ | OpenAI API Key | なし |
| `MODEL_FAST` |  | テキスト向け軽量モデル | `gpt-5-nano` |
| `MODEL_VISION` |  | 画像入力対応モデル | `gpt-5-mini` |
| `MODEL_VISION_FALLBACK` |  | ビジョン呼び出し失敗時のフォールバック | `gpt-4o-mini` |
| `DISCORD_CHUNK` |  | 分割送信のチャンクサイズ | `1900` |
| `HISTORY_TURNS` |  | 直近で差し込む**往復数**（ユーザ発話基準） | `6` |

> **会話履歴はプロセス内のみ**で、Railway の再デプロイや再起動でリセットされます。永続化は実装していません。

---

## 使い方（Discord）

- Bot をサーバに招待し、テキストチャンネルでメッセージを送るだけ  
- **画像を添付**すると自動で画像解析モード（最大 4 枚まで）  
- 応答が長いときは**分割送信**されます（既定 1900 文字ごと）  
- 返信中はチャンネルに**入力中インジケータ**が表示されます

---

## 仕組みの要点

### 画像入力
- `bot.py` の `_pick_image_urls` が、`content_type=image/*` または拡張子（`.png .jpg .jpeg .webp .gif`）を抽出
- Chat Completions の `messages[].content` に `{"type":"image_url","image_url":{"url":...}}` を付与
- 画像が含まれる場合は `MODEL_VISION`、テキストのみなら `MODEL_FAST` を使用（失敗時は `MODEL_VISION_FALLBACK` を参照）

### 会話履歴（軽量）
- `history.py` の `HistoryStore` が**チャンネルID単位**で直近 `HISTORY_TURNS` 往復を保持  
- **TTL や永続化はなし**（そのぶん軽量で安価）  
- 取得した履歴は system の直後に `role=user/assistant` メッセージとして差し込み

### OpenAI 呼び出し
- `openai` の **Chat Completions** を利用  
- 一部モデルの制限に合わせ、`stop` パラメータは送信していません  
- 応答が空や途切れ（`finish_reason=length`）の場合に備え、簡易フォールバック応答を実装

### Discord 実装
- `async with channel.typing():` で **入力中…** を表示  
- `DISCORD_CHUNK=1900` で**分割送信**  
- Bot 自身の発言には反応しないようガード済み

---

## トラブルシューティング

- **Bot が反応しない**  
  - `DISCORD_TOKEN` / `OPENAI_API_KEY` が正しいか
  - Discord 側で **MESSAGE CONTENT INTENT** を有効化しているか
  - Railway Service は **Unexposed** で問題ありません

- **OpenAI 400: `Unsupported parameter: 'stop'`**  
  - 本実装は `stop` を送信しないため、通常は発生しません。`MODEL_*` の綴りやリージョンの一時障害をご確認ください。

- **finish_reason=length で切れる**  
  - `bot.py` の `max_completion_tokens` を調整  
  - `BASE_PERSONA` が極端に長い場合は短縮も検討

- **画像が認識されない**  
  - 実ファイルを**添付**しているか（外部 URL 貼付けのみだとメタが取れない場合あり）  
  - 拡張子/`content_type` が `_pick_image_urls` の判定に合致しているか

---

## コストとモデル
- 既定は `MODEL_FAST=gpt-5-nano`（テキスト） と `MODEL_VISION=gpt-5-mini`（画像）  
- ペルソナ固定で**プロンプトキャッシュ**が効きやすくなります  
- 応答が長文化する場合は `max_completion_tokens` の見直しを推奨

---

## ライセンス
必要に応じて OSS ライセンスを追加してください（例: MIT）。
