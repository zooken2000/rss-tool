"""
ローカルテストスクリプト（AgentCore不要）

Step 1: RSSフェッチのみテスト（AWS不要）
Step 2: エージェント全体テスト（AWS認証情報が必要）

Usage:
  .venv/bin/python test_local.py                   # Step1のみ（過去25時間）
  .venv/bin/python test_local.py --hours 200       # Step1のみ（過去200時間）
  .venv/bin/python test_local.py --full            # Step1 + Step2（過去25時間）
  .venv/bin/python test_local.py --full --hours 200  # Step1 + Step2（過去200時間）
"""

import json
import sys
import os
import textwrap
from datetime import datetime, timedelta, timezone

# agent.py と同じディレクトリで実行するための設定
sys.path.insert(0, os.path.dirname(__file__))


# ─────────────────────────────────────────────
# Step 1: RSSフェッチ単体テスト（AWS不要）
# ─────────────────────────────────────────────

def test_rss_fetch(hours: int = 25):
    print("=" * 60)
    print(f"Step 1: RSSフェッチテスト（過去{hours}時間、AWS不要）")
    print("=" * 60)

    import feedparser
    from rss_feeds import MORNING_FEEDS, NOON_FEEDS
    RSS_FEEDS = {**MORNING_FEEDS, **NOON_FEEDS}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    total = 0

    for category, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            recent = []
            for entry in feed.entries:
                for attr in ("published_parsed", "updated_parsed"):
                    parsed = entry.get(attr)
                    if parsed:
                        try:
                            pub_dt = datetime(*parsed[:6], tzinfo=timezone.utc)
                            if pub_dt > cutoff:
                                recent.append({
                                    "title": entry.get("title", ""),
                                    "link": entry.get("link", ""),
                                    "published": pub_dt.isoformat(),
                                })
                            break
                        except (ValueError, TypeError):
                            continue

            status = f"{len(recent)}件" if recent else "0件（新着なし）"
            print(f"  [{category}] {status}")
            if recent:
                print(f"    最新: {recent[0]['title'][:60]}...")
            total += len(recent)

        except Exception as e:
            print(f"  [{category}] エラー: {e}")

    print()
    print(f"合計: {total}件（過去25時間以内）")
    return total > 0


# ─────────────────────────────────────────────
# Step 2: Strands Agent 全体テスト（AWS必要）
# ─────────────────────────────────────────────

def test_agent_full(hours: int = 25):
    print()
    print("=" * 60)
    print(f"Step 2: Strands Agent全体テスト（過去{hours}時間、AWS認証情報が必要）")
    print("=" * 60)

    from strands import Agent, tool
    import feedparser
    from rss_feeds import MORNING_FEEDS, NOON_FEEDS
    RSS_FEEDS = {**MORNING_FEEDS, **NOON_FEEDS}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    @tool
    def fetch_recent_articles() -> str:
        """AWS RSSフィードから過去24時間以内に公開された記事を取得して返す。"""
        articles = []
        for category, url in RSS_FEEDS.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    for attr in ("published_parsed", "updated_parsed"):
                        parsed = entry.get(attr)
                        if parsed:
                            try:
                                pub_dt = datetime(*parsed[:6], tzinfo=timezone.utc)
                                if pub_dt > cutoff:
                                    articles.append({
                                        "category": category,
                                        "title": entry.get("title", ""),
                                        "summary": entry.get("summary", entry.get("description", ""))[:300],
                                        "link": entry.get("link", ""),
                                        "published": pub_dt.isoformat(),
                                    })
                                break
                            except (ValueError, TypeError):
                                continue
            except Exception as e:
                print(f"  警告: [{category}] フィード取得失敗: {e}")
                continue
        articles = articles[:1]
        print(f"  → フェッチ完了: {len(articles)}件（テスト用1件）")
        return json.dumps(articles, ensure_ascii=False)

    system_prompt = textwrap.dedent("""
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
    """).strip()

    agent = Agent(
        tools=[fetch_recent_articles],
        system_prompt=system_prompt,
    )

    print("  Claudeに問い合わせ中...")
    result = agent(
        "fetch_recent_articles ツールで記事を取得し、日本語に翻訳・要約してJSON配列で返してください。"
    )

    # result.message は {'role': 'assistant', 'content': [{'text': '...'}]} 形式
    msg = result.message if hasattr(result, "message") else {}
    raw = msg.get("content", [{}])[0].get("text", "") if isinstance(msg, dict) else str(msg)

    try:
        articles = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("["), raw.rfind("]") + 1
        articles = json.loads(raw[start:end]) if start != -1 and end > start else []

    # 結果表示（Slackメッセージのプレビュー）
    print()
    print(f"処理結果: {len(articles)}件")
    print()
    print("=" * 60)
    print("📰 Slack メッセージプレビュー")
    print("=" * 60)
    from datetime import date
    print(f"*📡 AWS Daily Digest — {date.today()}*")
    print(f"本日の更新: {len(articles)}件")
    print()
    for a in articles:
        imp = a.get("importance", "LOW")
        imp_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(imp, "⚪")
        print(f"{'━' * 50}")
        print(f"{imp_emoji}  *[{a.get('category')}]* {imp}")
        print(f"*{a.get('title_ja')}*")
        print()
        print(f"📌 *概要*")
        print(f"> {a.get('summary_ja', '')}")
        print()
        print(f"🔄 *変更点*")
        print(f"> {a.get('change', '')}")
        print()
        print(f"✅ *メリット*")
        print(f"> {a.get('benefit', '')}")
        print()
        print(f"🔗 {a.get('link')}")
        print()

    return articles


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────

if __name__ == "__main__":
    full_mode = "--full" in sys.argv

    # --hours N で取得時間範囲を変更（デフォルト25時間）
    hours = 25
    if "--hours" in sys.argv:
        idx = sys.argv.index("--hours")
        try:
            hours = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            pass

    ok = test_rss_fetch(hours=hours)

    if full_mode:
        if not ok:
            print("\n⚠ 新着記事が0件のためStep2をスキップします")
        else:
            test_agent_full(hours=hours)
    else:
        print()
        print("💡 翻訳・要約もテストする場合: .venv/bin/python test_local.py --full --hours 200")
