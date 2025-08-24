# LeaFAI — Discord Bot × Railway × OpenAI（画像入力対応・Railway専用）

Discord のテキストチャンネルで動く雑談ボット。  
OpenAI Chat Completions を使用し、**画像添付にも対応**します。デプロイ先は **Railway** 前提です。

- ペルソナは `base_persona.py` に三重引用でベタ書き
- 画像が来たら自動でビジョン対応モデルに切替
- Discord の「入力中…」インジケータ表示
- 応答切れ時のフォールバック内蔵
- 追加の Web サーバは不要（サービスは Unexposed 推奨）

---

## 事前準備（Discord／OpenAI）

### Discord
1. [Discord Developer Portal](https://discord.com/developers/applications) でアプリ作成
2. **Bot** を追加し、**MESSAGE CONTENT INTENT** を有効化
3. **Token** を取得（後で Railway の Variables に設定）
4. **OAuth2 > URL Generator**
   - Scopes: `bot`（必要なら `applications.commands` も）
   - Bot Permissions: `View Channels` / `Read Message History` / `Send Messages`
   - 生成された URL で対象サーバに Bot を招待

### OpenAI
- OpenAI API Key を取得（後で Railway の Variables に設定）

---

## Railway デプロイ手順（GitHub リポジトリ前提）

1. このリポジトリを GitHub で公開（あるいは自分の Org にプッシュ）
2. Railway で **New Project → Deploy from GitHub**
3. プロジェクトが作成されたら **Variables** に下記を追加

| 変数名 | 必須 | 説明 | 既定値 |
|---|:---:|---|---|
| `DISCORD_TOKEN` | ✅ | Discord Bot Token | なし |
| `OPENAI_API_KEY` | ✅ | OpenAI API Key | なし |
| `MODEL_FAST` |  | テキスト専用の軽量モデル | `gpt-5-nano` |
| `MODEL_VISION` |  | 画像入力対応モデル | `gpt-4o-mini` |

4. Service 設定
   - **Start Command**: `python bot.py`
   - **Networking**: **Unexposed**（公開ポート不要のため）
   - リージョンは任意
5. **Deploy** を実行。`Logs` で `Logged in as ...` が出れば稼働中

---

## 使い方（Discord 上）

- テキストを送るだけで応答します
- **画像を添付**すると自動で画像解析プロンプトとして扱います（最大 4 枚）
- 返答が長い場合は分割送信します（Discord の 2000 文字制限対策）

---

## リポジトリ構成

```
.
├── bot.py                # Discord <-> OpenAI 本体。画像入力対応済み
├── base_persona.py       # """あなたのプロンプト""" を貼るだけ（下記参照）
├── requirements.txt      # 依存パッケージ
└── README.md
```

`base_persona.py` は次のように差し替えてください（中身は自由）:
```python
# base_persona.py
BASE_PERSONA = """あなたのプロンプト"""
```

> ペルソナは長いほど安定します。内容を固定運用するほどプロンプトキャッシュが効きやすく、コスト削減にもつながります。

---

## 画像入力の仕様

- 添付の `content_type` が `image/*`（または拡張子が `.png/.jpg/.jpeg/.webp/.gif`）のものを送信
- 受け取った画像 URL を Chat Completions の `content` 配列に `type: "image_url"` で渡します
- 画像が含まれるときは `MODEL_VISION` を使用（既定 `gpt-4o-mini`）
- 最大 4 枚まで解析（枚数は `bot.py` の `_pick_image_urls` で変更可）

---

## よくある詰まりポイント（Railway 前提）

- **Bot が反応しない**
  - Railway Variables の `DISCORD_TOKEN` / `OPENAI_API_KEY` を再確認
  - Discord の **MESSAGE CONTENT INTENT** が有効か確認
  - サービスが **Unexposed** でも問題ありません（Bot は外向けポート不要）

- **ログに `PyNaCl is not installed, voice will NOT be supported`**
  - 無視して構いません。この Bot はテキスト/画像専用です

- **OpenAI 400: `Unsupported parameter: 'stop'`**
  - nano 系モデルは `stop` 非対応があります。本リポジトリの `bot.py` は送信していません
  - 古いコードや外部スニペットを混ぜていないか確認

- **応答が途中で切れる**
  - `bot.py` の `max_completion_tokens` を調整
  - ペルソナが極端に長すぎる場合は短縮も検討

- **画像に反応しない**
  - Discord で**実ファイル添付**になっているか（URL 貼り付けだけではメタ情報が取れないことがあります）
  - 拡張子・`content_type` 判定に引っかかっているか（`_pick_image_urls` を調整）

---

## セキュリティ

- トークンや API キーは **Railway の Variables** のみに保存し、リポジトリにコミットしない
- Discord の Bot 権限は最小限に絞る
- 不要な環境変数は削除して管理対象を減らす

---

## ライセンス

任意の OSS ライセンスを追加してください（例: MIT）。未指定だと再利用しづらくなります。
