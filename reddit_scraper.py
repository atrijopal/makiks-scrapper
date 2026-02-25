"""
Reddit Scraper — Extreme Relevance Overhaul
Searches Reddit globally for Matiks app mentions with strictly targeted queries.
No authentication required.
Output: data/reddit_raw.json
"""
import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime

OUTPUT_FILE = "/data/data/reddit_raw.json"
HEADERS     = {"User-Agent": "Matiks-Monitor-IITG/2.0 (brand monitoring bot)"}
MAX_PAGES   = 5

# Super-targeted queries to avoid "automatic transmission" Tagalog noise
QUERIES = [
    '"Matiks" math app',
    '"Matiks" IIT Guwahati',
    '"Matiks" puzzle startup',
    'Matiks app review',
]

# Hard blocklist - if these appear, it's 100% not the app
BLOCKLIST = {
    "motor", "e-bike", "gear", "transmission", "automatic", "atheist",
    "rap battle", "battle rap", "philippines", "pinas", "tagalog",
    "motorcycle", "scooter", "cars", "car model", "honda", "yamaha",
    "kawasaki", "suzuki", "pilipinas", "filipin", "tagalog slang",
}

# Strict keyword gate - at least one must appear in the context of "Matiks"
MANDATORY_KEYWORDS = {
    "math", "puzzle", "app", "game", "iit", "startup", "guwahati", 
    "playstore", "play store", "ios", "android", "streak", "brain", 
    "level", "download"
}

def is_relevant(record: dict) -> bool:
    """Apply strict heuristic filtering to eliminate noise before LLM stage."""
    title = (record.get("title", "") or "").lower()
    text  = (record.get("text", "") or "").lower()
    full_text = title + " " + text

    # Rule 1: Must contain "matiks" (standalone or case-insensitive)
    if "matiks" not in full_text:
        return False

    # Rule 2: Hard blocklist check
    if any(word in full_text for word in BLOCKLIST):
        return False

    # Rule 3: Mandatory keyword check
    if not any(word in full_text for word in MANDATORY_KEYWORDS):
        return False

    return True

def fetch_reddit(query: str, after=None):
    params = {
        "q": query,
        "sort": "new",
        "limit": "50",
        "type": "link,comment",
        "t": "all",
    }
    if after:
        params["after"] = after
    url = f"https://www.reddit.com/search.json?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))

def scrape():
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    new_records = []
    seen_ids = set()

    for query in QUERIES:
        after = None
        fetched = 0
        for page in range(MAX_PAGES):
            try:
                data = fetch_reddit(query, after)
            except Exception as e:
                print(f"[Reddit] Error on query '{query}': {e}")
                break

            children = data.get("data", {}).get("children", [])
            if not children: break

            for child in children:
                d = child["data"]
                post_id = d.get("id")
                if not post_id or post_id in seen_ids: continue

                record = {
                    "id": post_id,
                    "platform": "reddit",
                    "subreddit": d.get("subreddit", ""),
                    "title": d.get("title", ""),
                    "text": d.get("selftext", "") or d.get("body", "") or "",
                    "author": d.get("author", ""),
                    "score": d.get("score", 0),
                    "url": f"https://reddit.com{d.get('permalink', '')}",
                    "created_utc": datetime.fromtimestamp(d.get("created_utc", 0)).isoformat(),
                    "scraped_at": datetime.now().isoformat(),
                }

                if is_relevant(record):
                    new_records.append(record)
                    fetched += 1
                
                seen_ids.add(post_id)

            after = data.get("data", {}).get("after")
            if not after: break
            time.sleep(1.5) # respect rate limits

        print(f"[Reddit] Query '{query}': {fetched} relevant posts")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(new_records, f, ensure_ascii=False, indent=2)
    print(f"[Reddit] Total relevant: {len(new_records)}")

if __name__ == "__main__":
    scrape()
