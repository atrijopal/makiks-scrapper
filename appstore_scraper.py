"""
App Store Scraper — fetches reviews for Matiks on iOS.
Uses app-store-scraper library.
Output: data/appstore_raw.json
"""
import json
import os
from datetime import datetime
from app_store_scraper import AppStore

OUTPUT_FILE = "/data/data/appstore_raw.json"

def scrape():
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    print("[App Store] Fetching reviews for 'matiks-math-and-brain-games'...")
    
    # Initialize the scraper
    # name: matiks-math-and-brain-games
    # id: 6471803517 (found via search)
    matiks = AppStore(country='us', app_name='matiks-math-and-brain-games', app_id=6471803517)
    
    # Fetch all reviews (or a reasonable limit)
    matiks.review(how_many=100)
    
    records = []
    for r in matiks.reviews:
        # Convert to our schema
        record = {
            "id": f"ios_{hash(r['userName'] + str(r['date']))}",
            "platform": "appstore",
            "title": r.get("title", ""),
            "text": r.get("review", ""),
            "author": r.get("userName", ""),
            "score": r.get("rating", 0),
            "version": r.get("version", ""),
            "created_utc": r.get("date").isoformat() if isinstance(r.get("date"), datetime) else str(r.get("date")),
            "scraped_at": datetime.now().isoformat(),
        }
        records.append(record)
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        
    print(f"[App Store] Done. Fetched {len(records)} reviews.")

if __name__ == "__main__":
    scrape()
