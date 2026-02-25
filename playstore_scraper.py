"""
Google Play Store Scraper — fetches reviews for the Matiks app.
Uses google-play-scraper library (already installed in container).
Output: data/playstore_raw.json
"""
import json
import os
from datetime import datetime

from google_play_scraper import reviews, Sort, app

APP_ID = "com.matiks.app"
OUTPUT_FILE = "/data/data/playstore_raw.json"
FETCH_COUNT = 200  # reviews per run


def load_existing(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def scrape():
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    existing = load_existing(OUTPUT_FILE)
    existing_ids = {r["id"] for r in existing}

    new_records = []

    # Fetch newest reviews
    try:
        result, _ = reviews(
            APP_ID,
            lang="en",
            country="us",
            sort=Sort.NEWEST,
            count=FETCH_COUNT,
        )
    except Exception as e:
        print(f"[PlayStore] Error fetching reviews: {e}")
        result = []

    for r in result:
        review_id = str(r.get("reviewId", ""))
        if review_id in existing_ids:
            continue

        at = r.get("at")
        created_at = at.strftime("%Y-%m-%dT%H:%M:%S") if at else ""

        record = {
            "id": review_id,
            "platform": "playstore",
            "text": r.get("content", ""),
            "author": r.get("userName", ""),
            "rating": r.get("score", 0),
            "thumbs_up": r.get("thumbsUpCount", 0),
            "app_version": r.get("reviewCreatedVersion", ""),
            "reply_text": r.get("replyContent", ""),
            "url": f"https://play.google.com/store/apps/details?id={APP_ID}",
            "created_at": created_at,
            "scraped_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        }
        new_records.append(record)
        existing_ids.add(review_id)

    # Also fetch most relevant reviews
    try:
        result2, _ = reviews(
            APP_ID,
            lang="en",
            country="us",
            sort=Sort.MOST_RELEVANT,
            count=100,
        )
        for r in result2:
            review_id = str(r.get("reviewId", ""))
            if review_id in existing_ids:
                continue
            at = r.get("at")
            created_at = at.strftime("%Y-%m-%dT%H:%M:%S") if at else ""
            record = {
                "id": review_id,
                "platform": "playstore",
                "text": r.get("content", ""),
                "author": r.get("userName", ""),
                "rating": r.get("score", 0),
                "thumbs_up": r.get("thumbsUpCount", 0),
                "app_version": r.get("reviewCreatedVersion", ""),
                "reply_text": r.get("replyContent", ""),
                "url": f"https://play.google.com/store/apps/details?id={APP_ID}",
                "created_at": created_at,
                "scraped_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            }
            new_records.append(record)
            existing_ids.add(review_id)
    except Exception as e:
        print(f"[PlayStore] Error fetching most-relevant reviews: {e}")

    all_records = existing + new_records
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)

    print(f"[PlayStore] Done. New: {len(new_records)}, Total: {len(all_records)}")


if __name__ == "__main__":
    scrape()
