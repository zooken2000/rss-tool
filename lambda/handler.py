"""
AWS Daily Digest — Lambda Handler
EventBridge から mode を受け取り、AgentCore Runtime を呼び出して Slack に通知する。
"""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import boto3
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]

agentcore_client = boto3.client("bedrock-agentcore")
slack_client = WebClient(token=SLACK_BOT_TOKEN)

MODE_HEADER = {
    "morning": "☀️ AWS What's New — 朝の速報",
    "noon": "📚 AWS 技術ブログ — お昼まとめ",
}

IMPORTANCE_EMOJI = {
    "HIGH": "🔴",
    "MEDIUM": "🟡",
    "LOW": "🟢",
}


def invoke_agent(mode: str) -> list:
    """AgentCore Runtime を呼び出して記事リストを返す。"""
    payload = json.dumps({"mode": mode}).encode("utf-8")

    response = agentcore_client.invoke_agent_runtime(
        agentRuntimeArn=AGENT_RUNTIME_ARN,
        contentType="application/json",
        accept="application/json",
        payload=payload,
        runtimeSessionId=str(uuid.uuid4()),
    )

    body = response["response"].read().decode("utf-8")
    logger.info("AgentCore レスポンス (先頭200文字): %s", body[:200])

    data = json.loads(body)
    return data.get("articles", [])


def build_slack_blocks(mode: str, articles: list) -> list:
    """Slack Block Kit 形式のメッセージブロックを組み立てる。"""
    jst = timezone(timedelta(hours=9))
    date_str = datetime.now(jst).strftime("%Y年%m月%d日")
    header_text = MODE_HEADER.get(mode, "AWS Daily Digest")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{header_text}  ({date_str})",
                "emoji": True,
            },
        },
        {"type": "divider"},
    ]

    if not articles:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "本日の新着情報はありませんでした。"},
        })
        return blocks

    for article in articles:
        importance = article.get("importance", "LOW")
        emoji = IMPORTANCE_EMOJI.get(importance, "⚪")
        category = article.get("category", "")
        title_ja = article.get("title_ja", "")
        summary_ja = article.get("summary_ja", "")
        change = article.get("change", "")
        benefit = article.get("benefit", "")
        link = article.get("link", "")

        text = "\n".join([
            f"{emoji} *{title_ja}*  `{category}`",
            "",
            f"📌 *概要*: {summary_ja}",
            f"🔄 *変更点*: {change}",
            f"✅ *メリット*: {benefit}",
            f"🔗 <{link}|記事を読む>",
        ])

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": text},
        })
        blocks.append({"type": "divider"})

    return blocks


def handler(event, context):
    """Lambda エントリーポイント。"""
    mode = event.get("mode", "morning")
    logger.info("handler 開始: mode=%s", mode)

    articles = invoke_agent(mode)
    logger.info("取得記事数: %d 件", len(articles))

    blocks = build_slack_blocks(mode, articles)

    try:
        slack_client.chat_postMessage(
            channel=SLACK_CHANNEL_ID,
            blocks=blocks,
            text=f"AWS Daily Digest — {MODE_HEADER.get(mode, 'まとめ')}",
        )
        logger.info("Slack 通知完了")
    except SlackApiError as e:
        logger.error("Slack 通知失敗: %s", e.response["error"])
        raise

    return {"statusCode": 200, "articles_count": len(articles)}
