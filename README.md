# LeaFAI - Discord Bot on Railway — README

> これはローカル実行を前提にしていません。Railway にデプロイして動かす構成です。

---

## 概要

- Discord で会話するボット。OpenAI Chat Completions API（非ストリーム）を使って応答します。
- 疑似ストリーミング UX（先に短いプレビューを出して、後から本文に差し替え）を実装。
- ユーザーの反応から「好感度」を学習して簡易的にトーン調整。永続データはボリューム上の JSON。
- 画像メッセージにも対応（画像は投げられても生成はしない）。

---

## 主要機能

- **nonstream_progressive_reply**  
  ストリーム権限不要。ミニモデルでプレビューを先出し→フルモデルで本体生成→メッセージを編集で置き換え。
- **好感度永続化**  
  `AFFINITY_PATH` の JSON に保存。Railway のボリュームに置く想定。
- **Discord 2000 文字制限対応**  
  安全マージン 1900 文字で分割送信。
- **メッセージ削除監視**  
  Bot が送ったメッセージが消されたらログに記録。

---

## 必要要件

- Discord Bot（Message Content Intent 有効）
- OpenAI API Key（Chat Completions 使用）
- Railway アカウント（永続ボリュームを利用）

---

## 環境変数

Railway のプロジェクトで以下を設定します。

| 変数名            | 必須 | 説明 |
|-------------------|------|------|
| `DISCORD_TOKEN`    | はい | Discord Developer Portal で発行した Bot Token |
| `OPENAI_API_KEY`   | はい | OpenAI の API キー |
| `AFFINITY_PATH`    | いいえ | 好感度 JSON のパス。デフォルト `/data/affinity.json`（ボリューム想定） |

---

## Discord 側の準備

1. **アプリ作成**: Discord Developer Portal → New Application → Bot を追加
2. **Intent 設定**:
   - Privileged Gateway Intents → **Message Content Intent** を ON
   - Server Members Intent は不要
3. **権限（Permissions）**:
   - `Send Messages`
   - `Read Message History`
   - `Attach Files`（任意、ログ画像とか貼るなら）
4. **招待リンク**:
   - OAuth2 → URL Generator  
     Scopes: `bot`  
     Bot Permissions: 上記に該当する権限  
   - 生成リンクでサーバーに追加
5. **Bot Token** をコピーして Railway の `DISCORD_TOKEN` に設定

---

## ディレクトリ構成

```
.
├─ bot.py                # 本体
├─ requirements.txt      # 依存関係
└─ (任意) README.md
```

`requirements.txt` 例:
```
discord.py>=2.3.2
openai>=1.40.0
httpx>=0.27.0
```

---

## Railway へのデプロイ手順

1. **新規プロジェクト作成**  
   Railway ダッシュボード → New Project → **Deploy from GitHub**（このリポジトリを選択）

2. **サービス設定**  
   - Build: Railway の Python 自動検出に任せるか、Nixpacks/Buildpack を使用  
   - Start Command: `python bot.py`

3. **環境変数設定**  
   - `DISCORD_TOKEN`  
   - `OPENAI_API_KEY`  
   - `AFFINITY_PATH`（未設定ならデフォルト `/data/affinity.json`）

4. **永続ボリューム**  
   - Project → Add Plugin → **Persistent Volume**（サイズは数 MB 程度で充分）  
   - マウントパスを `/data` に設定（`AFFINITY_PATH=/data/affinity.json` を前提）

5. **デプロイ**  
   - Deploy ボタンで起動  
   - Logs で `ログイン成功: <Bot名>` が出れば接続 OK

---

## ランタイムの挙動

- **疑似ストリーミング**  
  1) 「詠唱中…」のプレースホルダーを即送信  
  2) `gpt-5-mini` で短いプレビューを生成して置き換え  
  3) 並列で `gpt-5` または `gpt-5-mini` の本文を生成し、完成したら編集で差し替え  
  4) 1900 文字を超える場合は追送

- **モデル選択**  
  `_choose_model()` が履歴の長さやコードっぽさで `gpt-5` / `gpt-5-mini` を自動選択

- **画像付きメッセージ**  
  content に text + image_url（最大4件）を混在して API に渡す。返信はテキストのみ。

---

## よくあるハマりどころ

### 1) 「Streaming は組織の検証が必要」の 400 エラー
本実装は **stream=False** なので出ません。以前のコードや他所のサンプルを混ぜて `stream=True` にしていると発生します。  
`nonstream_progressive_reply()` だけ使ってください。

### 2) インデント崩れで SyntaxError
Railway コンソールでたまにタブ/スペース混在が起きます。Git で揃えてから push。  
どうしても不安なら以下をローカルで（実行はしないが静的チェックだけする）:
```bash
python -m tabnanny bot.py
```

### 3) ダブル送信
`nonstream_progressive_reply()` が **送信も編集も全部やる** ので、呼び出し後に `channel.send()` しないこと。  
履歴更新だけにしておくのが正解。

### 4) Message Content Intent が OFF
Bot がメッセージを読めません。Developer Portal で ON にして再起動。

### 5) 永続化が失敗する
- `AFFINITY_PATH` が `/data/affinity.json` 以外になっている  
- ボリューム未マウント  
- JSON 壊れ（とりあえず新規に作り直されます）

---

## 運用・監視

- Railway の Logs を見れば、起動や例外が分かります。
- Bot メッセージ削除は `on_message_delete` でログ出力されます（監査ログ権限があれば削除者も推定）。

---

## セキュリティ注意

- Token や API Key は **Railway の環境変数**にのみ保存。リポジトリに埋め込まない。
- Intent は必要最小限（Message Content のみ）。
- ログには機密を書かない。例外の本文にもユーザーデータを混ぜない。

---

## カスタマイズポイント

- 応答のペルソナは `BASE_PERSONA` を編集。
- 疑似ストリーミングのテンポは `nonstream_progressive_reply()` 内の `max_completion_tokens`（プレビュー量）やアニメーション間隔で調整。
- モデル名は `MODEL_FAST`/`MODEL_HEAVY`、および `_choose_model()` のロジックで切り替え。

---

## ライセンス

プロジェクトポリシーに合わせて設定してください。特に指定がなければ MIT で問題ありません。

---

## デプロイ後チェックリスト

- [ ] Logs に `ログイン成功: ...`  
- [ ] サーバーで Bot がオンライン  
- [ ] 話しかけると「詠唱中…」→短文→本分の順に更新される  
- [ ] 画像添付に反応する  
- [ ] 再デプロイしても好感度が維持される（ボリューム OK）

これだけ。動かなかったら、まずは権限と環境変数、それからログを見ろ。いいね、魔法は大抵ヒューマンエラーで溶ける。
