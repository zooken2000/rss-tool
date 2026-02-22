"""
AWS Daily Digest — Strands Agent
- RSSフィードから過去24時間の記事を取得
- Claude (Bedrock) で日本語翻訳・要約・重要度スコアリング
- 結果をJSON形式でLambdaへ返却（Slack通知はLambdaが担当）

モード:
  morning : 朝9時  — What's New のみ（新機能・アップデート速報）
  noon    : 昼12時 — 技術ブログ全カテゴリ（読み物・詳細解説）
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool

from rss_feeds import MORNING_FEEDS, NOON_FEEDS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()

FETCH_HOURS = 25    # 取得対象の時間範囲（少し余裕を持たせる）
MAX_ARTICLES = 30   # Claudeに渡す最大記事数

SYSTEM_PROMPT = """
あなたはAWSの最新情報を日本語でまとめるアシスタントです。

fetch_recent_articles ツールで記事一覧を取得し、各記事を以下のルールで処理してください。

## 処理ルール
1. タイトルを自然な日本語に翻訳する（AWS Japan Blog はそのまま使用）
2. 重要度を以下の基準で判定する
   - HIGH  : セキュリティ脆弱性・新サービスリリース・大型アップデート
   - MEDIUM: 既存サービスの機能追加・価格変更・リージョン展開
   - LOW   : ブログ記事・事例紹介・パートナー情報
3. 元のカテゴリラベルをそのまま使用する
4. 各記事について以下の3点を日本語で記述する
   - summary_ja : 何が発表されたかの概要（1〜2文）
   - change     : 従来との変更点・今回新しくなった点（1〜2文）。従来の情報がない場合は「新規リリース」と記載
   - benefit    : このアップデートによってユーザーが得られる具体的なメリット（1〜2文）

## 出力形式
JSON配列のみを返してください。前置き・後書き・コードブロック記号は不要です。

[
  {
    "category": "カテゴリ名",
    "title_ja": "日本語タイトル",
    "summary_ja": "何が発表されたかの概要",
    "change": "従来との変更点・新しくなった点",
    "benefit": "ユーザーが得られる具体的なメリット",
    "importance": "HIGH | MEDIUM | LOW",
    "link": "https://..."
  }
]

記事が0件の場合は空配列 [] を返してください。
""".strip()


def _parse_entry_datetime(entry: Any) -> datetime | None:
    """エントリの公開日時を取得する。published_parsed → updated_parsed の順で試みる。"""
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None) or entry.get(attr)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
    return None


def _build_fetch_tool(feeds: dict[str, str]):
    """指定フィード一覧を使うfetch_recent_articlesツールを生成する。"""

    @tool
    def fetch_recent_articles() -> str:
        """
        AWS RSSフィードから過去24時間以内に公開された記事を取得して返す。
        返却値はJSON文字列（記事の配列）。
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=FETCH_HOURS)
        articles = []

        for category, url in feeds.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    pub_dt = _parse_entry_datetime(entry)
                    if pub_dt is None or pub_dt <= cutoff:
                        continue
                    articles.append({
                        "category": category,
                        "title": entry.get("title", ""),
                        "summary": entry.get("summary", entry.get("description", "")),
                        "link": entry.get("link", ""),
                        "published": pub_dt.isoformat(),
                    })
            except Exception as e:
                logger.warning("フィード取得エラー [%s]: %s", url, e)
                continue

        if len(articles) > MAX_ARTICLES:
            priority = ["What's New", "Security", "AWS News", "Machine Learning"]
            articles = sorted(
                articles,
                key=lambda a: priority.index(a["category"]) if a["category"] in priority else len(priority)
            )[:MAX_ARTICLES]

        logger.info("取得記事数: %d件", len(articles))
        return json.dumps(articles, ensure_ascii=False)

    return fetch_recent_articles


def _parse_result(result: Any) -> list:
    """AgentResult から記事リストを取り出す。"""
    msg = result.message if hasattr(result, "message") else {}
    raw = msg.get("content", [{}])[0].get("text", "") if isinstance(msg, dict) else str(msg)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("["), raw.rfind("]") + 1
        if start != -1 and end > start:
            return json.loads(raw[start:end])
        logger.error("JSONパース失敗: %s", raw)
        return []


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AgentCore エントリーポイント

    payload:
      mode: "morning" | "noon"  （デフォルト: "morning"）
    """
    mode = payload.get("mode", "morning")
    feeds = MORNING_FEEDS if mode == "morning" else NOON_FEEDS
    logger.info("invoke開始 mode=%s feeds=%d件", mode, len(feeds))

    fetch_tool = _build_fetch_tool(feeds)
    agent = Agent(tools=[fetch_tool], system_prompt=SYSTEM_PROMPT)

    result = agent(
        "fetch_recent_articles ツールで記事を取得し、日本語に翻訳・要約してJSON配列で返してください。"
    )

    articles = _parse_result(result)
    logger.info("処理完了: %d件", len(articles))
    return {"mode": mode, "articles": articles}


if __name__ == "__main__":
    app.run()
