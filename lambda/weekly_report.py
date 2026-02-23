"""
AWS Daily Digest — 週次レポート Lambda

毎週月曜 09:00 JST（UTC 00:00）に実行し:
  1. CloudWatch Metrics からハンドラー Lambda の過去7日分の実行データを収集
  2. CloudWatch Logs Insights からハンドラーログの記事数を集計
  3. CloudWatch Logs Insights から Online Evaluation スコアを集計（EVAL_LOG_GROUP 設定済みの場合）
  4. Bedrock InvokeModel で Slack 用レポートを生成
  5. Slack に投稿
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import boto3
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SLACK_BOT_TOKEN       = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID      = os.environ["SLACK_CHANNEL_ID"]
HANDLER_FUNCTION_NAME = os.environ["HANDLER_FUNCTION_NAME"]
EVAL_LOG_GROUP        = os.environ.get("EVAL_LOG_GROUP", "")   # Online Evaluation 設定後に追加
REPORT_MODEL_ID       = os.environ["REPORT_MODEL_ID"]

cw           = boto3.client("cloudwatch")
logs_client  = boto3.client("logs")
bedrock      = boto3.client("bedrock-runtime")
slack_client = WebClient(token=SLACK_BOT_TOKEN)

REPORT_DAYS           = 7
LOGS_INSIGHTS_TIMEOUT = 60  # seconds


# ─────────────────────────────────────────────────────────
# 1. CloudWatch Metrics（Lambda の標準メトリクス）
# ─────────────────────────────────────────────────────────

def _get_lambda_metric(metric_name: str, stat: str, start: datetime, end: datetime) -> float:
    """AWS/Lambda 名前空間から単一メトリクスを取得する。データなし時は 0.0 を返す。"""
    resp = cw.get_metric_statistics(
        Namespace="AWS/Lambda",
        MetricName=metric_name,
        Dimensions=[{"Name": "FunctionName", "Value": HANDLER_FUNCTION_NAME}],
        StartTime=start,
        EndTime=end,
        Period=int((end - start).total_seconds()),
        Statistics=[stat],
    )
    datapoints = resp.get("Datapoints", [])
    return float(datapoints[0][stat]) if datapoints else 0.0


def collect_lambda_metrics(start: datetime, end: datetime) -> dict:
    """ハンドラー Lambda の実行回数・エラー数・実行時間を収集する。"""
    return {
        "invocations":     int(_get_lambda_metric("Invocations", "Sum",     start, end)),
        "errors":          int(_get_lambda_metric("Errors",      "Sum",     start, end)),
        "duration_avg_ms": round(_get_lambda_metric("Duration",  "Average", start, end)),
        "duration_max_ms": round(_get_lambda_metric("Duration",  "Maximum", start, end)),
        "expected":        REPORT_DAYS * 2,  # morning × 7 + noon × 7
    }


# ─────────────────────────────────────────────────────────
# 2. CloudWatch Logs Insights（ハンドラーログから記事数を集計）
# ─────────────────────────────────────────────────────────

def _run_logs_query(log_group: str, query: str, start: datetime, end: datetime) -> list[dict]:
    """
    Logs Insights クエリを実行してポーリングし、結果を [{field: value}, ...] のリストで返す。
    ログループが存在しない場合・タイムアウト時は空リストを返す。
    """
    try:
        resp = logs_client.start_query(
            logGroupName=log_group,
            startTime=int(start.timestamp()),
            endTime=int(end.timestamp()),
            queryString=query,
        )
    except logs_client.exceptions.ResourceNotFoundException:
        logger.warning("ログループが存在しません: %s", log_group)
        return []

    query_id = resp["queryId"]
    deadline = time.time() + LOGS_INSIGHTS_TIMEOUT

    while time.time() < deadline:
        result = logs_client.get_query_results(queryId=query_id)
        status = result["status"]
        if status == "Complete":
            return [
                {f["field"]: f["value"] for f in row}
                for row in result.get("results", [])
            ]
        if status in ("Failed", "Cancelled"):
            logger.warning("Logs Insights クエリ失敗: status=%s log_group=%s", status, log_group)
            return []
        time.sleep(2)

    logger.warning("Logs Insights タイムアウト: %s", log_group)
    try:
        logs_client.stop_query(queryId=query_id)
    except Exception:
        # タイムアウト判定直後にクエリが完了した場合、stop_query は InvalidParameterException を返す
        pass
    return []


def collect_article_stats(start: datetime, end: datetime) -> dict:
    """ハンドラー Lambda のログから記事数とモード別実行数を集計する。"""
    log_group = f"/aws/lambda/{HANDLER_FUNCTION_NAME}"

    # handler.py の logger.info("取得記事数: %d 件", ...) を集計
    article_query = """
fields @message
| filter @message like /取得記事数/
| parse @message /取得記事数: (?<count>\\d+) 件/
| stats
    sum(count) as total_articles,
    avg(count) as avg_articles,
    min(count) as min_articles,
    max(count) as max_articles,
    count(*)   as runs
""".strip()

    # handler.py の logger.info("handler 開始: mode=%s", ...) からモードを抽出
    mode_query = """
fields @message
| filter @message like /handler 開始/
| parse @message /mode=(?<mode>\\S+)/
| stats count(*) as runs by mode
""".strip()

    article_rows = _run_logs_query(log_group, article_query, start, end)
    mode_rows    = _run_logs_query(log_group, mode_query,    start, end)

    result: dict = {
        "total_articles": 0,
        "avg_articles":   0.0,
        "min_articles":   0,
        "max_articles":   0,
        "runs":           0,
        "by_mode":        {},
    }

    if article_rows:
        row = article_rows[0]
        result.update({
            "total_articles": int(float(row.get("total_articles", 0))),
            "avg_articles":   round(float(row.get("avg_articles",   0)), 1),
            "min_articles":   int(float(row.get("min_articles",   0))),
            "max_articles":   int(float(row.get("max_articles",   0))),
            "runs":           int(float(row.get("runs",           0))),
        })

    for r in mode_rows:
        mode = r.get("mode", "unknown")
        result["by_mode"][mode] = int(float(r.get("runs", 0)))

    return result


# ─────────────────────────────────────────────────────────
# 3. Online Evaluation スコア（EVAL_LOG_GROUP 設定時のみ）
# ─────────────────────────────────────────────────────────

def collect_eval_scores(start: datetime, end: datetime) -> list[dict]:
    """
    AgentCore Online Evaluation の結果ログからスコアを集計する。
    EVAL_LOG_GROUP 環境変数が未設定の場合は空リストを返す。
    """
    if not EVAL_LOG_GROUP:
        return []

    query = """
fields score, evaluatorName
| filter ispresent(score)
| stats
    avg(score) as avg_score,
    min(score) as min_score,
    max(score) as max_score,
    count(*)   as count
    by evaluatorName
| sort evaluatorName
""".strip()

    rows = _run_logs_query(EVAL_LOG_GROUP, query, start, end)
    return [
        {
            "evaluator": r.get("evaluatorName", ""),
            "avg_score": round(float(r.get("avg_score", 0)), 3),
            "min_score": round(float(r.get("min_score", 0)), 3),
            "max_score": round(float(r.get("max_score", 0)), 3),
            "count":     int(float(r.get("count", 0))),
        }
        for r in rows
    ]


# ─────────────────────────────────────────────────────────
# 4. Bedrock InvokeModel で Slack 用レポートを生成
# ─────────────────────────────────────────────────────────

def format_with_llm(raw_data: dict, period_label: str) -> str:
    """収集したデータを Claude に渡して Slack mrkdwn 形式のレポートを生成する。"""
    prompt = f"""以下はAWS Digest Agentの運用データです（{period_label}）。
このデータをSlackのmrkdwn形式で週次レポートとして整形してください。

{json.dumps(raw_data, ensure_ascii=False, indent=2)}

出力ルール:
- Slack mrkdwn 形式のテキストのみ出力する（前置き・後書き不要）
- ヘッダーに *太字* を使い、セクションを区切る
- 絵文字で視認性を上げる
- lambda_metrics.invocations < lambda_metrics.expected の場合 ⚠️ で実行漏れを警告する
- lambda_metrics.errors > 0 の場合 🔴 で警告し調査を促す
- duration は ms から秒に変換して表示する（例: 47,230ms → 47.2秒）
- eval_scores がある場合: avg_score >= 0.8 → ✅ 良好、0.6〜0.8 → ⚠️ 要注視、< 0.6 → 🔴 要改善
- eval_scores が空の場合: 「評価スコア: 未設定（Online Evaluation 設定後に反映されます）」と記載する
""".strip()

    response = bedrock.invoke_model(
        modelId=REPORT_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1200,
        }),
    )
    return json.loads(response["body"].read())["content"][0]["text"]


# ─────────────────────────────────────────────────────────
# Lambda エントリーポイント
# ─────────────────────────────────────────────────────────

def handler(event, context):
    jst       = timezone(timedelta(hours=9))
    now_jst   = datetime.now(jst)
    end_utc   = datetime.now(timezone.utc)
    start_utc = end_utc - timedelta(days=REPORT_DAYS)

    period_label = (
        f"{(now_jst - timedelta(days=REPORT_DAYS)).strftime('%m/%d')}〜"
        f"{now_jst.strftime('%m/%d')}"
    )
    logger.info("週次レポート開始: %s", period_label)

    raw_data = {
        "period":         period_label,
        "lambda_metrics": collect_lambda_metrics(start_utc, end_utc),
        "article_stats":  collect_article_stats(start_utc, end_utc),
        "eval_scores":    collect_eval_scores(start_utc, end_utc),
    }
    logger.info("データ収集完了: %s", json.dumps(raw_data, ensure_ascii=False))

    slack_text = format_with_llm(raw_data, period_label)
    logger.info("LLMフォーマット完了")

    try:
        slack_client.chat_postMessage(
            channel=SLACK_CHANNEL_ID,
            text=slack_text,
            mrkdwn=True,
        )
        logger.info("Slack 投稿完了")
    except SlackApiError as e:
        logger.error("Slack 投稿失敗: %s", e.response["error"])
        raise

    return {"statusCode": 200, "period": period_label}
