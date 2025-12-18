# Anti-Gravity: Twilio + OpenAI Realtime オートコールシステム

本システムは、Twilio と OpenAI Realtime API を活用した、AIによる自動架電・対話・集計システムです。
アウトバウンド架電、リアルタイムAI会話、自動分類、管理画面などの機能を備えています。

## 主な機能

- **リアルタイムAI会話**: OpenAI gpt-4o-realtime-preview を使用し、自然な対話を実現。
- **アウトバウンド/インバウンド**: 両方向の通話に対応。
- **シナリオ管理**: 挨拶、質問、終話ガイダンスを自由に設定。
- **会話モード**:
    - **A: 質問順守**: 設定した質問を順番に行う（推奨）。
    - **B: 自由対話**: AIが自由に会話を進行。
    - **C: ハイブリッド**: 基本は質問、適宜脱線に対応。
- **条件付きアクション**: 会話中にAIが判断し、担当者へ転送（ブリッジ）やSMS送信ログの記録が可能。
- **自動分類**: 通話時間やアクションに基づき、通話結果を自動分類。
- **ブラックリスト**: オプトアウト（拒否）番号の管理。
- **管理画面**: シナリオ設定、架電リスト(CSV)アップロード、通話ログ閲覧、音声DLが可能。

## セットアップ (ローカル)

1. **環境変数の設定**:
   `.env.example` を `.env` にコピーし、各値を設定してください。
   ```bash
   cp .env.example .env
   ```
   - `PUBLIC_BASE_URL`: ローカル実行時は ngrok 等のURLを指定してください。

2. **依存関係のインストール**:
   ```bash
   pip install -r requirements.txt
   ```

3. **データベースの初期化**:
   ```bash
   # 実行時に自動的にテーブルが作成されます
   python run.py
   ```

4. **ngrok での公開 (Twilio Webhook用)**:
   ```bash
   ngrok http 8000
   ```
   表示された `https://...` を `.env` の `PUBLIC_BASE_URL` に設定してください。

## Railway へのデプロイ

1. **GitHub へのプッシュ**:
   本リポジトリを自身の GitHub にプッシュします。

2. **Railway で新規プロジェクト作成**:
   - `Deploy from GitHub repo` を選択。
   - `Variables` タブで `.env` の内容をすべて設定します。
   - `DATABASE_URL` は Railway の PostgreSQL を使用する場合、その接続文字列を指定してください。

3. **Twilio の設定**:
   - Twilio 管理画面で、使用する番号の Webhook URL に以下を設定します：
     - `A CALL COMES IN`: `https://your-app.railway.app/twilio/voice`
     - `HTTP POST` を選択。

## 使い方

1. **シナリオ作成**: 管理画面の「シナリオ設定」から新しいシナリオを作成します。
2. **架電リストアップロード**: 「発信リスト・開始」タブでCSVをアップロードします。
   - CSVヘッダー例: `phone_number`, `name`, `note`
3. **架電開始**: 「架電開始」ボタンを押すと、リストの待機中（pending）の番号へ順次発信します。
4. **ログ確認**: 「通話ログ」タブで録音の再生や文字起こしの確認ができます。

## セキュリティ

- 管理画面のデフォルトログイン:
    - ID: `admin`
    - PW: `attendme`
- 録音ZIPのパスワード: `attendme`

## 注意事項

- 本システムは開発・テスト用です。本番運用時は適切な認証（OAuth等）の導入を検討してください。
- OpenAI Realtime API の利用料金にご注意ください。
