# AWS Daily Digest — Strands Agent × Bedrock AgentCore

AWSの最新情報を毎日自動収集・日本語に翻訳・AI要約してSlackへ通知するシステムです。

## アーキテクチャ

```
EventBridge (朝9時 JST / 毎日)   ─> Lambda {"mode": "morning"}
  └─> Bedrock AgentCore (Strands Agent)
        ├─> What's New のみ取得・翻訳・要約
        └─> Lambda が Slack へ通知（新機能速報）

EventBridge (昼12時 JST / 毎日)  ─> Lambda {"mode": "noon"}
  └─> Bedrock AgentCore (Strands Agent)
        ├─> 技術ブログ全カテゴリ取得・翻訳・要約
        └─> Lambda が Slack へ通知（技術記事まとめ）

EventBridge (朝10時 JST / 月曜)  ─> Lambda (週次レポート)
  ├─> CloudWatch Metrics / Logs Insights でデータ収集
  ├─> Bedrock InvokeModel (Claude) でレポートを生成
  └─> Slack へ週次レポートを投稿
```

### コンポーネント

| コンポーネント | 役割 |
|---|---|
| **Strands Agent** | RSSフィード取得 → 日本語翻訳・要約 → 結果を返す |
| **Bedrock AgentCore Runtime** | Strands Agentをサーバーレスでホスト・スケール・Observability |
| **Lambda (handler)** | AgentCore を呼び出し、結果を受け取りSlackへ投稿 |
| **Lambda (weekly_report)** | CloudWatchからデータ収集 → Claudeでレポート生成 → Slack投稿 |
| **EventBridge** | 朝9時・昼12時（毎日）+ 月曜10時（週次）の3スケジュール |
| **CDK** | 全インフラをコード管理 |

---

## ディレクトリ構成

```
rss-tool/
├── README.md
├── agent/                        # Strands Agent (AgentCore にデプロイ)
│   ├── agent.py                  # RSS取得・日本語翻訳・要約 → 結果を返す
│   ├── rss_feeds.py              # RSSフィードURL一覧（設定）
│   ├── requirements.txt          # strands-agents[otel], aws-opentelemetry-distro 含む
│   ├── Dockerfile                # ARM64 / ADOT 計装済み
│   └── test_local.py             # ローカルテスト
├── lambda/                       # AgentCore 呼び出し + Slack 通知
│   ├── handler.py                # 朝・昼の通知 Lambda
│   ├── weekly_report.py          # 週次レポート Lambda
│   └── requirements.txt          # slack-sdk
└── cdk/                          # CDK インフラ定義
    ├── app.py
    ├── stacks/
    │   ├── aws_digest_stack.py   # 全リソースを管理するメインスタック
    │   └── infra_utils/
    │       ├── agentcore_role.py
    │       └── build_trigger_lambda.py
    └── requirements.txt
```

---

## スケジュール

| Lambda | 実行時刻 (JST) | UTC | 内容 |
|--------|--------------|-----|------|
| handler (morning) | 毎日 09:00 | 00:00 | What's New 速報 |
| handler (noon)    | 毎日 12:00 | 03:00 | 技術ブログまとめ |
| weekly_report     | 毎週月曜 10:00 | 01:00 | 週次レポート |

---

## RSSソース

### 朝（morning）

| カテゴリ | RSS URL |
|---|---|
| What's New（新機能） | `https://aws.amazon.com/about-aws/whats-new/recent/feed/` |
| Amazon Linux Security | `https://alas.aws.amazon.com/alas.rss` |

### 昼（noon）— 技術ブログ全カテゴリ

| カテゴリ | RSS URL |
|---|---|
| AWS News Blog | `https://aws.amazon.com/blogs/aws/feed` |
| Security | `https://aws.amazon.com/blogs/security/feed` |
| Machine Learning | `https://aws.amazon.com/blogs/machine-learning/feed` |
| Architecture | `https://aws.amazon.com/blogs/architecture/feed` |
| Compute | `https://aws.amazon.com/blogs/compute/feed` |
| Database | `https://aws.amazon.com/blogs/database/feed` |
| Containers | `https://aws.amazon.com/blogs/containers/feed` |
| Big Data | `https://aws.amazon.com/blogs/big-data/feed` |
| Developer | `https://aws.amazon.com/blogs/developer/feed` |
| DevOps | `https://aws.amazon.com/blogs/devops/feed` |
| Networking | `https://aws.amazon.com/blogs/networking-and-content-delivery/feed` |
| IoT | `https://aws.amazon.com/blogs/iot/feed` |
| Open Source | `https://aws.amazon.com/blogs/opensource/feed` |
| Management Tools | `https://aws.amazon.com/blogs/mt/feed` |
| Startups | `https://aws.amazon.com/blogs/startups/feed` |
| AWS Japan Blog | `https://aws.amazon.com/jp/blogs/news/feed` |

---

## セットアップ手順

### 前提条件

- Python 3.10+
- AWS CLI（設定済み）
- Node.js 18+（CDK CLI）
- Slack App（`chat:write` スコープ付きBot Token）

### 1. ローカルテスト（任意）

```bash
cd agent
uv venv && uv pip install -r requirements.txt

# RSS 取得のみ確認（AWS 不要）
uv run python test_local.py --hours 200

# Agent 全体確認（AWS 認証必要）
uv run python test_local.py --hours 200 --full
uv run python test_local.py --hours 200 --full --mode noon
```

### 2. CloudWatch Transaction Search を有効化（初回のみ）

AgentCore Observability のトレースデータを CloudWatch に保存するために必要です。

```bash
# X-Ray トレースを CloudWatch Logs に送信する設定
aws xray update-trace-segment-destination --destination CloudWatchLogs

# X-Ray が CloudWatch Logs へ書き込む権限を付与
aws logs put-resource-policy \
  --policy-name AgentCoreXRayPolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "xray.amazonaws.com"},
      "Action": "logs:PutLogEvents",
      "Resource": [
        "arn:aws:logs:*:*:log-group:/aws/spans:*",
        "arn:aws:logs:*:*:log-group:/aws/application-signals/data:*"
      ]
    }]
  }'
```

### 3. CDK でインフラ一括デプロイ

```bash
cd cdk
pip install -r requirements.txt

# CDK ブートストラップ（初回のみ）
cdk bootstrap

# デプロイ（Slack 認証情報をパラメータで渡す）
cdk deploy \
  --parameters SlackBotToken=xoxb-xxxxxxxxxxxx \
  --parameters SlackChannelId=C0XXXXXXXXX
  # --parameters ReportModelId=us.anthropic.claude-3-5-sonnet-20241022-v2:0  # 変更する場合
```

デプロイ後、CDK の Outputs から以下が出力されます：

| Output | 内容 |
|--------|------|
| `AgentRuntimeArn` | AgentCore Runtime ARN |
| `HandlerFunctionName` | 通知 Lambda 名 |
| `WeeklyReportFunctionName` | 週次レポート Lambda 名 |
| `OnlineEvalSetupCommand` | Online Evaluation 設定コマンド（次ステップ参照） |

### 4. Online Evaluation を設定（任意・推奨）

週次レポートの品質スコア欄を有効化するため、Outputs に表示されたコマンドを実行します。

```bash
# bedrock-agentcore-starter-toolkit のインストール
pip install bedrock-agentcore-starter-toolkit

# Online Evaluation を作成
agentcore eval online create \
  --name aws_digest_eval \
  --sampling-rate 100 \
  --evaluator Builtin.GoalSuccessRate \
  --evaluator Builtin.Helpfulness \
  --evaluator Builtin.Correctness
```

出力された `Config ID` を週次レポート Lambda の環境変数に設定します：

```bash
aws lambda update-function-configuration \
  --function-name aws-digest-weekly-report \
  --environment "Variables={
    SLACK_BOT_TOKEN=xoxb-...,
    SLACK_CHANNEL_ID=C0...,
    HANDLER_FUNCTION_NAME=aws-digest-handler,
    EVAL_LOG_GROUP=/aws/bedrock-agentcore/evaluations/results/<Config ID>,
    REPORT_MODEL_ID=us.anthropic.claude-3-5-sonnet-20241022-v2:0
  }"
```

### 5. 動作確認

```bash
# 朝モードのテスト
aws lambda invoke \
  --function-name aws-digest-handler \
  --payload '{"mode": "morning"}' \
  response.json && cat response.json

# 昼モードのテスト
aws lambda invoke \
  --function-name aws-digest-handler \
  --payload '{"mode": "noon"}' \
  response.json && cat response.json

# 週次レポートのテスト
aws lambda invoke \
  --function-name aws-digest-weekly-report \
  response.json && cat response.json
```

---

## 週次レポートの内容

毎週月曜 10:00 JST に Slack へ投稿されます。Claude が以下のデータを読み取って自然な文章でフォーマットします。

| データソース | 収集する情報 |
|------------|------------|
| CloudWatch Metrics (`AWS/Lambda`) | 実行回数・エラー数・実行時間（平均・最大） |
| CloudWatch Logs Insights | 記事取得数（合計・平均・最小・最大）・モード別実行数 |
| Evaluation Results ログ（設定済みの場合） | Helpfulness・Correctness・GoalSuccessRate スコア |

---

## IAM 権限

### AgentCore Runtime ロール（Strands Agent）

```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream"
  ],
  "Resource": "*"
}
```

### Lambda 実行ロール（handler）

```json
{
  "Effect": "Allow",
  "Action": ["bedrock-agentcore:InvokeAgentRuntime"],
  "Resource": "arn:aws:bedrock-agentcore:<region>:<account>:runtime/<runtime-id>"
}
```

### Lambda 実行ロール（weekly_report）

```json
{
  "Effect": "Allow",
  "Action": ["cloudwatch:GetMetricStatistics"],
  "Resource": "*"
},
{
  "Effect": "Allow",
  "Action": ["logs:StartQuery"],
  "Resource": [
    "arn:aws:logs:<region>:<account>:log-group:/aws/lambda/aws-digest-handler",
    "arn:aws:logs:<region>:<account>:log-group:/aws/bedrock-agentcore/evaluations/results/*"
  ]
},
{
  "Effect": "Allow",
  "Action": ["logs:GetQueryResults", "logs:StopQuery"],
  "Resource": "*"
},
{
  "Effect": "Allow",
  "Action": ["bedrock:InvokeModel"],
  "Resource": "arn:aws:bedrock:<region>::foundation-model/*"
}
```

---

## 参考リンク

- [Strands Agents ドキュメント](https://strandsagents.com/latest/)
- [Bedrock AgentCore ドキュメント](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [AgentCore Observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability.html)
- [AgentCore Starter Toolkit](https://aws.github.io/bedrock-agentcore-starter-toolkit/)
- [CloudWatch Logs Insights クエリ構文](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax.html)
