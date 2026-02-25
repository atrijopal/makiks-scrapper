"""
Twitter/X Scraper — searches for "Matiks" mentions.

Uses `twscrape` (https://github.com/vladkens/twscrape) which works WITHOUT
a paid API key by using guest tokens or account-based auth.

Install (already in Dockerfile): pip install twscrape

OPTIONAL — for higher rate limits, add Twitter credentials to config.env:
    TWITTER_USERNAME=your_username
    TWITTER_PASSWORD=your_password
    TWITTER_EMAIL=your@email.com  (sometimes required by Twitter)

Without credentials, twscrape uses guest tokens (lower limits, may be blocked
more easily). The scraper gracefully writes an empty file on any failure so
the rest of the pipeline always continues.

Output: data/twitter_raw.json
"""
import asyncio
import json
import os
from datetime import datetime, timedelta

OUTPUT_FILE = "/data/data/twitter_raw.json"
CONFIG_FILE  = "/data/config.env"
QUERY       = "Matiks"
DAYS_BACK   = 7
MAX_RESULTS = 100

# Relevance gate — mirror the reddit scraper logic
BLOCKLIST = {
    "motor", "e-bike", "gear", "transmission", "automatic", "atheist",
    "rap battle", "battle rap", "philippines", "pinas", "tagalog",
    "motorcycle", "scooter", "honda", "yamaha", "kawasaki",
}


def load_config() -> dict:
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    config[k.strip()] = v.strip()
    return config


def load_existing(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return []
    return []


def is_relevant(text: str) -> bool:
    """Filter out non-app Matiks mentions (Tagalog noise etc.)"""
    text_lower = text.lower()
    if "matiks" not in text_lower:
        return False
    if any(w in text_lower for w in BLOCKLIST):
        return False
    return True


async def scrape_async():
    try:
        from twscrape import API
        from twscrape.logger import set_log_level
        set_log_level("ERROR")
    except ImportError:
        print("[Twitter/X] twscrape not installed. Run: pip install twscrape")
        return [], []

    existing     = load_existing(OUTPUT_FILE)
    existing_ids = {r["id"] for r in existing}
    config       = load_config()

    api = API()

    # Add credentials if available — gives higher rate limits
    tw_user  = config.get("TWITTER_USERNAME", "")
    tw_pass  = config.get("TWITTER_PASSWORD", "")
    tw_email = config.get("TWITTER_EMAIL", "")

    if tw_user and tw_pass:
        try:
            await api.pool.add_account(tw_user, tw_pass, tw_email, "")
            await api.pool.login_all()
            print(f"[Twitter/X] Logged in as @{tw_user}")
        except Exception as e:
            print(f"[Twitter/X] Login failed ({e}), using guest tokens")
    else:
        print("[Twitter/X] No Twitter credentials in config.env — using guest tokens")
        print("           Add TWITTER_USERNAME / TWITTER_PASSWORD for better reliability")

    since    = (datetime.utcnow() - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
    search_q = f"{QUERY} since:{since} lang:en"
    print(f"[Twitter/X] Searching: {search_q}")

    new_records = []

    try:
        async for tweet in api.search(search_q, limit=MAX_RESULTS):
            tweet_id = str(tweet.id)
            if tweet_id in existing_ids:
                continue

            text = tweet.rawContent or ""
            if not is_relevant(text):
                continue

            record = {
                "id":            tweet_id,
                "platform":      "twitter",
                "text":          text,
                "author":        tweet.user.username if tweet.user else "",
                "display_name":  tweet.user.displayname if tweet.user else "",
                "followers":     tweet.user.followersCount if tweet.user else 0,
                "like_count":    tweet.likeCount or 0,
                "retweet_count": tweet.retweetCount or 0,
                "reply_count":   tweet.replyCount or 0,
                "url":           str(tweet.url) if tweet.url else "",
                "created_at":    tweet.date.isoformat() if tweet.date else "",
                "scraped_at":    datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            }
            new_records.append(record)
            existing_ids.add(tweet_id)

    except Exception as e:
        print(f"[Twitter/X] Search error: {e}")
        print("[Twitter/X] Twitter heavily rate-limits guest scraping. Add credentials for reliability.")

    return existing + new_records, new_records


def scrape():
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    try:
        all_records, new_records = asyncio.run(scrape_async())
    except Exception as e:
        print(f"[Twitter/X] Fatal error: {e}")
        all_records = load_existing(OUTPUT_FILE)
        new_records = []

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)

    print(f"[Twitter/X] Done. New: {len(new_records)}, Total: {len(all_records)}")


if __name__ == "__main__":
    scrape()
