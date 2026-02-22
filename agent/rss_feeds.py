"""
AWS RSSフィード一覧

MORNING_FEEDS : 朝9時通知 — What's New（新機能・アップデート速報）
NOON_FEEDS    : 昼12時通知 — 技術ブログ全カテゴリ（読み物・詳細解説）
"""

# 朝9時: 新機能・アップデートの速報のみ
MORNING_FEEDS: dict[str, str] = {
    "What's New":            "https://aws.amazon.com/about-aws/whats-new/recent/feed/",
    "Amazon Linux Security": "https://alas.aws.amazon.com/alas.rss",
}

# 昼12時: 技術ブログ全カテゴリ
NOON_FEEDS: dict[str, str] = {
    "AWS News":           "https://aws.amazon.com/blogs/aws/feed",
    "Security":           "https://aws.amazon.com/blogs/security/feed",
    "Machine Learning":   "https://aws.amazon.com/blogs/machine-learning/feed",
    "Architecture":       "https://aws.amazon.com/blogs/architecture/feed",
    "Compute":            "https://aws.amazon.com/blogs/compute/feed",
    "Database":           "https://aws.amazon.com/blogs/database/feed",
    "Containers":         "https://aws.amazon.com/blogs/containers/feed",
    "Big Data":           "https://aws.amazon.com/blogs/big-data/feed",
    "Developer":          "https://aws.amazon.com/blogs/developer/feed",
    "DevOps":             "https://aws.amazon.com/blogs/devops/feed",
    "Networking":         "https://aws.amazon.com/blogs/networking-and-content-delivery/feed",
    "IoT":                "https://aws.amazon.com/blogs/iot/feed",
    "Open Source":        "https://aws.amazon.com/blogs/opensource/feed",
    "Management Tools":   "https://aws.amazon.com/blogs/mt/feed",
    "Startups":           "https://aws.amazon.com/blogs/startups/feed",
    "AWS Japan":          "https://aws.amazon.com/jp/blogs/news/feed",
}
