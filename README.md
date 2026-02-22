# AWS Daily Digest — Strands Agent × Bedrock AgentCore

AWSの最新情報を毎日自動収集・日本語に翻訳・AI要約してSlackへ通知するシステムです。

## アーキテクチャ

```
EventBridge (朝9時 JST)  ─> Lambda {"mode": "morning"}
  └─> Bedrock AgentCore (Strands Agent)
        ├─> What's New のみ取得・翻訳・要約
        └─> Lambda が Slack へ通知（新機能速報）

EventBridge (昼12時 JST) ─> Lambda {"mode": "noon"}
  └─> Bedrock AgentCore (Strands Agent)
        ├─> 技術ブログ全カテゴリ取得・翻訳・要約
        └─> Lambda が Slack へ通知（技術記事まとめ）
```

### コンポーネント

| コンポーネント | 役割 |
|---|---|
| **Strands Agent** | RSSフィード取得 → 日本語翻訳・要約 → 結果を返す |
| **Bedrock AgentCore Runtime** | Strands Agentをサーバーレスでホスト・スケール |
| **Lambda** | AgentCore を呼び出し、結果を受け取りSlackへ投稿 |
| **EventBridge** | 朝9時（What's New速報）・昼12時（技術ブログまとめ）の2スケジュール |
| **CDK** | 全インフラ（AgentCore・Lambda・EventBridge等）をコード管理 |
| **Secrets Manager** | Slack Bot Token の安全な管理 |

---

## ディレクトリ構成

```
rss-tool/
├── README.md
├── agent/                        # Strands Agent (AgentCore にデプロイ)
│   ├── agent.py                  # RSS取得・日本語翻訳・要約 → 結果を返す
│   ├── rss_feeds.py              # RSSフィードURL一覧（設定）
│   └── requirements.txt
├── lambda/                       # AgentCore 呼び出し + Slack 通知
│   ├── handler.py
│   └── requirements.txt
├── cdk/                          # CDK インフラ定義
│   ├── app.py
│   ├── stacks/
│   │   └── aws_digest_stack.py   # AgentCore・Lambda・EventBridge・Secrets Manager
│   └── requirements.txt
└── .env.example
```

---

## RSSソース一覧

### AWS 公式ブログ（カテゴリ別）

| カテゴリ | RSS URL |
|---|---|
| AWS News Blog (総合) | `https://aws.amazon.com/blogs/aws/feed` |
| Architecture | `https://aws.amazon.com/blogs/architecture/feed` |
| Security | `https://aws.amazon.com/blogs/security/feed` |
| Machine Learning | `https://aws.amazon.com/blogs/machine-learning/feed` |
| Compute | `https://aws.amazon.com/blogs/compute/feed` |
| Database | `https://aws.amazon.com/blogs/database/feed` |
| Containers | `https://aws.amazon.com/blogs/containers/feed` |
| Big Data | `https://aws.amazon.com/blogs/big-data/feed` |
| Developer | `https://aws.amazon.com/blogs/developer/feed` |
| DevOps | `https://aws.amazon.com/blogs/devops/feed` |
| Networking & Content Delivery | `https://aws.amazon.com/blogs/networking-and-content-delivery/feed` |
| IoT | `https://aws.amazon.com/blogs/iot/feed` |
| Open Source | `https://aws.amazon.com/blogs/opensource/feed` |
| Mobile | `https://aws.amazon.com/blogs/mobile/feed` |
| Management Tools | `https://aws.amazon.com/blogs/mt/feed` |
| Media | `https://aws.amazon.com/blogs/media/feed` |
| Startups | `https://aws.amazon.com/blogs/startups/feed` |
| Partner Network (APN) | `https://aws.amazon.com/blogs/apn/feed` |
| Marketplace | `https://aws.amazon.com/blogs/awsmarketplace/feed` |
| Game Tech | `https://aws.amazon.com/blogs/gametech/feed` |
| Desktop & App Streaming | `https://aws.amazon.com/blogs/desktop-and-application-streaming/feed` |
| Messaging & Targeting | `https://aws.amazon.com/blogs/messaging-and-targeting/feed` |
| Public Sector | `https://aws.amazon.com/blogs/publicsector/feed` |
| SAP | `https://aws.amazon.com/blogs/awsforsap/feed` |
| **AWS Japan Blog** | `https://aws.amazon.com/jp/blogs/news/feed` |

### What's New（新機能・アップデート）

| | URL |
|---|---|
| What's New (英語) | `https://aws.amazon.com/about-aws/whats-new/recent/feed/` |

### セキュリティ

| | URL |
|---|---|
| Amazon Linux Security Center | `https://alas.aws.amazon.com/alas.rss` |

---

## 追加機能（提案）

### 必須機能

- **日本語翻訳**: 英語記事をClaudeが日本語に翻訳してSlackへ投稿
- **重複排除**: 公開日時（`pubDate`）で過去24時間以内の記事のみ処理
- **重要度スコアリング**: Claudeが各記事にスコア付け。高スコアは `@channel` メンション
- **カテゴリタグ付き通知**: Slackメッセージに `[Security]` `[ML]` 等のラベルを付与（Lambdaが整形して投稿）

### 拡張アイデア

| 機能 | 概要 |
|---|---|
| **チャンネル振り分け** | カテゴリごとに別Slackチャンネルへ投稿（例: セキュリティ情報 → `#aws-security`） |
| **週次ダイジェスト** | 週1回、その週のトップ記事をまとめて投稿 |
| **キーワードフィルタリング** | 監視対象サービス（例: EKS, RDS）のみ通知するフィルター |
| **Slack スレッド化** | 1日1投稿のスレッドに記事をぶら下げて見やすく整理 |
| **CloudWatch アラート連携** | セキュリティ系の重大記事はSNSでメール通知も併送 |

---

## セットアップ手順

### 前提条件

- Python 3.10+
- AWS CLI（設定済み）
- Docker / Finch / Podman（ローカルテスト用、任意）
- Slack Bot Token（`chat:write` 権限）

### 1. 環境変数の設定

```bash
cp .env.example .env
# .env を編集して各値を設定
```

```env
AWS_REGION=ap-northeast-1
SLACK_BOT_TOKEN=xoxb-xxxxxxxxxxxx
SLACK_CHANNEL_ID=C0XXXXXXXXX
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20251001-v1:0
```

### 2. Strands Agent のローカルテスト（任意）

```bash
cd agent
pip install -r requirements.txt

python agent.py

# 別ターミナルで動作確認
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "fetch_and_notify"}'
```

### 3. CDK でインフラ一括デプロイ

AgentCore・Lambda・EventBridge・Secrets Manager をまとめてデプロイします。

```bash
cd cdk
pip install -r requirements.txt

# CDK ブートストラップ（初回のみ）
cdk bootstrap

# デプロイ
cdk deploy
```

デプロイ後、CDK の出力から AgentCore Runtime ARN が確認できます。Lambda の環境変数には CDK が自動で設定します。

---

## Slack 通知イメージ

```
📰 AWS Daily Digest — 2026-02-22

━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 [Security] 重要度: HIGH
Amazon EC2 のセキュリティアップデート
> EC2 インスタンスに影響する CVE-XXXX が修正されました。
> 対象: Amazon Linux 2, Amazon Linux 2023
🔗 https://aws.amazon.com/security/...

━━━━━━━━━━━━━━━━━━━━━━━━━
🟡 [Machine Learning] 重要度: MEDIUM
Amazon Bedrock に新モデルが追加
> Claude 4 が Bedrock で利用可能になりました。
🔗 https://aws.amazon.com/blogs/...

━━━━━━━━━━━━━━━━━━━━━━━━━
本日の更新: 12件 | 重要: 2件 | 通常: 10件
```

---

## IAM 権限

### Strands Agent (AgentCore Runtime Role)

```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "secretsmanager:GetSecretValue"
  ],
  "Resource": "*"
}
```

### Lambda 実行ロール

```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock-agentcore:InvokeAgentRuntime"
  ],
  "Resource": "arn:aws:bedrock-agentcore:*:*:runtime/*"
}
```

---

## 参考リンク

- [Strands Agents ドキュメント](https://strandsagents.com/latest/)
- [Bedrock AgentCore Runtime ドキュメント](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [AgentCore Starter Toolkit](https://aws.github.io/bedrock-agentcore-starter-toolkit/)
- [AWS RSSフィード一覧 — DevelopersIO](https://dev.classmethod.jp/articles/aws-rss-feeds/)
