# AWS Daily Digest — プロジェクト概要

AWSの最新情報を毎日Slackに通知するツール。
Strands Agent on Bedrock AgentCore でRSS要約、Lambda + EventBridge で定期実行。

## ディレクトリ構成

```
rss-tool/
├── agent/                  ← Strands Agent（ARM64 Docker コンテナ）
│   ├── agent.py            ← AgentCore エントリーポイント
│   ├── rss_feeds.py        ← MORNING_FEEDS / NOON_FEEDS
│   ├── requirements.txt
│   ├── Dockerfile          ← カスタム ARM64 Dockerfile
│   └── test_local.py       ← ローカルテスト（--hours N で時間範囲指定）
├── lambda/                 ← Handler Lambda（AgentCore 呼び出し + Slack 通知）
│   ├── handler.py
│   └── requirements.txt    ← slack-sdk のみ
├── cdk/                    ← AWS CDK (Python)
│   ├── app.py
│   ├── cdk.json
│   ├── requirements.txt
│   └── stacks/
│       ├── aws_digest_stack.py         ← メインスタック
│       └── infra_utils/
│           ├── agentcore_role.py       ← AgentCore 用 IAM ロール
│           └── build_trigger_lambda.py ← CodeBuild 完了待機
└── README.md
```

## アーキテクチャ

```
EventBridge (朝9時 JST)  → Lambda → AgentCore Runtime → Slack
                                         ↑
EventBridge (昼12時 JST) → Lambda        Strands Agent
                                         - RSS フェッチ
                                         - Claude で日本語翻訳・要約
                                         - JSON 返却
```

## モード

| モード | 時刻 (JST) | UTC | フィード |
|--------|-----------|-----|---------|
| morning | 09:00 | 00:00 | What's New, Amazon Linux Security |
| noon | 12:00 | 03:00 | 技術ブログ全カテゴリ（16種） |

## Slack メッセージ形式

各記事: `重要度emoji タイトル(日本語)` + 概要・変更点・メリット・リンク

重要度: 🔴HIGH（新サービス・脆弱性）/ 🟡MEDIUM（機能追加）/ 🟢LOW（ブログ）

## CDK デプロイ

```bash
cd cdk
cdk deploy \
  --parameters SlackBotToken=xoxb-... \
  --parameters SlackChannelId=C0...
```

## CDK が作成するリソース（順序）

1. ECR リポジトリ (`aws-digest-agent`)
2. S3 に agent/ をアップロード
3. CodeBuild で ARM64 Docker イメージをビルド → ECR push
4. Lambda カスタムリソースが CodeBuild 完了を待機（最大15分）
5. AgentCore Runtime (`aws_digest_agent`) 作成
6. Lambda (`aws-digest-handler`) 作成
7. EventBridge ルール × 2

## AWS 認証

- プロファイル: `<ACCOUNT_ID>_AdministratorAccess`
- リージョン: us-east-1（要確認）

```bash
export AWS_PROFILE=<ACCOUNT_ID>_AdministratorAccess
```

## ローカルテスト

```bash
cd agent
uv run python test_local.py --hours 200           # Step1: RSS取得のみ
uv run python test_local.py --hours 200 --full    # Step2: Agent全体（AWS認証必要）
uv run python test_local.py --hours 200 --full --mode noon  # noonモード
```

## 重要な実装メモ

- `result.message` は `{'role': 'assistant', 'content': [{'text': '...'}]}` という dict
  → テキスト取得: `msg['content'][0]['text']`
- Lambda の boto3 クライアント: `boto3.client('bedrock-agentcore')`
- AgentCore 呼び出し: `client.invoke_agent_runtime(agentRuntimeArn=..., payload=bytes)`
- レスポンス: `response["response"].read().decode("utf-8")`
- `lambda/requirements.txt` には `slack-sdk` のみ（boto3 は Lambda 標準装備）

## テスト手順（段階的）

1. `cd cdk && cdk synth` — CloudFormation テンプレート生成確認
2. `cd agent && uv run python test_local.py --hours 200` — RSS取得確認
3. `cd agent && uv run python test_local.py --hours 200 --full` — Agent動作確認
4. `cdk deploy` — AWS にデプロイ
5. Lambda を手動実行 — `aws lambda invoke --function-name aws-digest-handler --payload '{"mode":"morning"}' out.json`
6. Slack に通知が届くか確認
