"""
run_reddit_pipeline.py
======================
Standalone script to:
  1. Scrape Reddit for Matiks startup mentions (strict — no Filipino noise)
  2. Merge with existing data (keeps Play Store / App Store records intact)
  3. Run LLM classification (Gemini or Ollama) on new Reddit records
  4. Update data.js for the dashboard

Run from the SCRAPPER directory:
  python run_reddit_pipeline.py

Works with LOCAL Windows paths (no Docker needed).
"""

import json
import os
import sys
import time
import datetime
import urllib.request
import urllib.parse
import urllib.error

# ── Local Paths (override Docker /data/data paths) ───────────────────────────
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
DATA_DIR        = os.path.join(BASE_DIR, "data")
REDDIT_RAW      = os.path.join(DATA_DIR, "reddit_raw.json")
MENTIONS_FILE   = os.path.join(DATA_DIR, "mentions.json")
ENRICHED_FILE   = os.path.join(DATA_DIR, "mentions_enriched.json")
CONFIG_FILE     = os.path.join(BASE_DIR, "config.env")
DATA_JS         = os.path.join(DATA_DIR, "data.js")
WORD_CLOUD_FILE = os.path.join(DATA_DIR, "word_cloud.json")
ALERTS_FILE     = os.path.join(DATA_DIR, "critical_alerts.json")

os.makedirs(DATA_DIR, exist_ok=True)

# ── Config loader ─────────────────────────────────────────────────────────────
def load_config():
    cfg = {}
    if not os.path.exists(CONFIG_FILE):
        return cfg
    with open(CONFIG_FILE) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                cfg[k.strip()] = v.strip()
    return cfg

# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 1 — Reddit Scraper
# ═══════════════════════════════════════════════════════════════════════════════

HEADERS  = {"User-Agent": "Matiks-Monitor-IITG/2.0 (brand monitoring bot)"}
MAX_PAGES = 8   # up from 5 — more pages = more posts

# Targeted queries specifically for the Matiks math-puzzle startup
QUERIES = [
    '"Matiks" math app',
    '"Matiks" IIT Guwahati',
    '"Matiks" puzzle startup',
    '"Matiks" puzzle game',
    'Matiks app review',
    'Matiks startup math',
    '"Matiks" android game',
    '"Matiks" iOS game',
]

# Hard blocklist — any post containing these = definitely not the startup
BLOCKLIST = {
    "motor", "e-bike", "gear", "transmission", "automatic", "atheist",
    "rap battle", "battle rap", "philippines", "pinas", "tagalog",
    "motorcycle", "scooter", "honda", "yamaha", "kawasaki", "suzuki",
    "pilipinas", "filipin", "tagalog slang", "motorbike",
}

# At least ONE of these must appear to pass the gate
# (Kept intentionally loose so real user posts like "really love matiks" pass
#  as long as they come from a startup-focused query)
APP_KEYWORDS = {
    "math", "puzzle", "app", "game", "iit", "startup", "guwahati",
    "playstore", "play store", "ios", "android", "streak", "brain",
    "level", "download", "review", "score", "challenge", "practice",
    "arithmetic", "calculation", "learning", "education",
}

def is_relevant(record: dict) -> bool:
    """Strict relevance filter: keep only Matiks startup posts."""
    title     = (record.get("title", "") or "").lower()
    text      = (record.get("text",  "") or "").lower()
    full_text = title + " " + text

    # Must mention matiks at all
    if "matiks" not in full_text:
        return False

    # Blocklist: definitely not the startup
    if any(word in full_text for word in BLOCKLIST):
        return False

    # Must have at least one app-context keyword
    if not any(word in full_text for word in APP_KEYWORDS):
        return False

    return True


def fetch_reddit(query: str, after=None):
    params = {
        "q": query,
        "sort": "new",
        "limit": "100",
        "type": "link,comment",
        "t": "all",
    }
    if after:
        params["after"] = after
    url = f"https://www.reddit.com/search.json?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def stage1_scrape():
    print("\n" + "="*60)
    print("STAGE 1 — Reddit Scraper")
    print("="*60)

    # Load existing records to avoid re-adding
    existing = []
    if os.path.exists(REDDIT_RAW):
        try:
            with open(REDDIT_RAW, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []

    seen_ids = {r["id"] for r in existing}
    new_records = list(existing)
    new_count = 0

    for query in QUERIES:
        after = None
        q_new = 0
        for page in range(MAX_PAGES):
            try:
                data = fetch_reddit(query, after)
            except Exception as e:
                print(f"  [Reddit] Error on query '{query}': {e}")
                break

            children = data.get("data", {}).get("children", [])
            if not children:
                break

            for child in children:
                d = child["data"]
                post_id = d.get("id")
                if not post_id or post_id in seen_ids:
                    continue

                record = {
                    "id":          post_id,
                    "platform":    "reddit",
                    "subreddit":   d.get("subreddit", ""),
                    "title":       d.get("title", ""),
                    "text":        d.get("selftext", "") or d.get("body", "") or "",
                    "author":      d.get("author", ""),
                    "score":       d.get("score", 0),
                    "url":         f"https://reddit.com{d.get('permalink', '')}",
                    "created_utc": datetime.datetime.fromtimestamp(
                                       d.get("created_utc", 0)
                                   ).isoformat(),
                    "scraped_at":  datetime.datetime.now().isoformat(),
                }

                if is_relevant(record):
                    new_records.append(record)
                    seen_ids.add(post_id)
                    q_new += 1
                    new_count += 1
                else:
                    seen_ids.add(post_id)  # still mark seen so we don't retry

            after = data.get("data", {}).get("after")
            if not after:
                break
            time.sleep(1.5)  # rate limit

        print(f"  Query '{query}': +{q_new} new relevant posts")

    with open(REDDIT_RAW, "w", encoding="utf-8") as f:
        json.dump(new_records, f, ensure_ascii=False, indent=2)

    print(f"\n  Total Reddit records: {len(new_records)} (+{new_count} new)")
    return new_records


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 2 — Aggregate (merge Reddit into mentions.json)
# ═══════════════════════════════════════════════════════════════════════════════

def stage2_aggregate(reddit_records):
    print("\n" + "="*60)
    print("STAGE 2 — Aggregate & VADER Sentiment")
    print("="*60)

    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        analyzer = SentimentIntensityAnalyzer()
    except ImportError:
        print("  [Warning] vaderSentiment not installed — skipping VADER scores")
        analyzer = None

    def get_sentiment(text):
        if not analyzer or not text:
            return {"label": "neutral", "compound": 0.0}
        s = analyzer.polarity_scores(text)
        c = s["compound"]
        label = "positive" if c >= 0.05 else ("negative" if c <= -0.05 else "neutral")
        return {"label": label, "compound": round(c, 4),
                "pos": round(s["pos"], 4), "neu": round(s["neu"], 4),
                "neg": round(s["neg"], 4)}

    # Load existing non-reddit records from current mentions.json
    existing_records = []
    if os.path.exists(MENTIONS_FILE):
        try:
            with open(MENTIONS_FILE, encoding="utf-8") as f:
                prev = json.load(f)
            existing_records = [
                r for r in prev.get("records", [])
                if r.get("platform") != "reddit"
            ]
        except Exception as e:
            print(f"  [Warning] Could not read mentions.json: {e}")

    # Enrich Reddit records with VADER
    enriched_reddit = []
    for r in reddit_records:
        text = (r.get("title", "") + " " + r.get("text", "")).strip()
        r["sentiment"] = get_sentiment(text)
        enriched_reddit.append(r)

    all_records = existing_records + enriched_reddit
    # Sort newest first
    all_records.sort(
        key=lambda r: (r.get("created_utc") or r.get("created_at") or r.get("scraped_at") or ""),
        reverse=True,
    )

    # Stats
    platform_counts = {}
    sentiment_counts = {"positive": 0, "neutral": 0, "negative": 0}
    for r in all_records:
        p = r.get("platform", "unknown")
        platform_counts[p] = platform_counts.get(p, 0) + 1
        label = r.get("sentiment", {}).get("label", "neutral")
        if label in sentiment_counts:
            sentiment_counts[label] += 1

    meta = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(all_records),
        "by_platform": platform_counts,
        "by_sentiment": sentiment_counts,
    }

    output = {"meta": meta, "records": all_records}
    with open(MENTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  Total records: {len(all_records)}")
    print(f"  By platform:  {platform_counts}")
    print(f"  By sentiment: {sentiment_counts}")
    return all_records, meta


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 3 — LLM Classification (Gemini or Ollama)
# ═══════════════════════════════════════════════════════════════════════════════

GEMINI_MODEL  = "gemini-2.0-flash"
OLLAMA_URL    = "http://localhost:11434"
OLLAMA_MODEL  = "llama3.2:3b"
BATCH_SIZE    = 5
RATE_LIMIT_S  = 1.0
MAX_TEXT_LEN  = 400
RELEVANCE_MIN = 7

VALID_TOPICS = {
    "bug_report", "feature_request", "praise",
    "question", "competitor_comparison", "general", "irrelevant",
}
VALID_SENTIMENTS = {
    "very_negative", "negative", "mixed", "positive", "very_positive",
}

import re


def check_ollama():
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode())
            models = [m.get("name", "") for m in data.get("models", [])]
            base = OLLAMA_MODEL.split(":")[0]
            return any(m == OLLAMA_MODEL or m.startswith(base + ":") for m in models)
    except Exception:
        return False


def call_ollama(prompt):
    body = json.dumps({
        "model": OLLAMA_MODEL, "prompt": prompt,
        "stream": False, "options": {"temperature": 0.1, "num_predict": 1024},
    }).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/generate", data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode())["response"]
        except Exception as e:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("Ollama: all retries failed")


def call_gemini(api_key, prompt):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={api_key}")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
    }).encode()
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                r = json.loads(resp.read().decode())
                return r["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode("utf-8", errors="ignore")
            if e.code == 429 and attempt < 3:
                wait = 60 * (attempt + 1)
                print(f"    [rate-limit] 429 — waiting {wait}s...", flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f"Gemini HTTP {e.code}: {body_txt[:200]}")
    raise RuntimeError("Gemini: max retries exceeded")


def call_llm(prompt, api_key, use_ollama):
    if use_ollama:
        try:
            return call_ollama(prompt)
        except Exception as e:
            if api_key:
                print(f"    [LLM] Ollama failed ({e}), falling back to Gemini...")
                return call_gemini(api_key, prompt)
            raise
    if api_key:
        return call_gemini(api_key, prompt)
    raise RuntimeError("No LLM backend available")


def build_batch_prompt(batch):
    items = []
    for i, r in enumerate(batch):
        text = (r.get("title", "") + " " + r.get("text", "")).strip()[:MAX_TEXT_LEN]
        items.append(f'{i+1}. [r/{r.get("subreddit","?")}] """{text}"""')

    return f"""You are a brand relevance classifier for "Matiks" — an IIT Guwahati startup's math puzzle mobile game.

CORE CONTEXT:
- Matiks is a math/brain training app with puzzles, streaks, and daily challenges.
- Founded by IIT Guwahati alumni.
- IMPORTANT: "Matiks" in Tagalog/Filipino means "automatic" (cars, bikes, gears). Ignore those.
- Any post about motorcycles, cars, rap battles, Philippines, or atheism = relevance 0.

RELEVANCE SCORING (0-10):
- 9-10: Directly about the Matiks math app (puzzles, bugs, features, IIT).
- 7-8: General mention in gaming/tech/education context.
- 4-6: Ambiguous.
- 0-3: Motorcycles, Tagalog slang, Filipino politics, rap battles = NOT the app.

For each of the {len(batch)} numbered posts return a JSON array of {len(batch)} objects:
- "relevance": integer 0-10
- "topic": bug_report | feature_request | praise | question | competitor_comparison | general | irrelevant
  (If relevance < 7, topic MUST be "irrelevant")
- "llm_sentiment": very_negative | negative | mixed | positive | very_positive
- "key_phrases": array of up to 3 meaningful phrases from the post
- "is_critical": true ONLY if topic=bug_report AND llm_sentiment=very_negative

Return ONLY the raw JSON array.

Posts:
{chr(10).join(items)}
"""


def parse_response(text, batch_size):
    text = re.sub(r"^```[a-z]*\n?", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\n?```$", "", text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass
    s, e = text.find("["), text.rfind("]") + 1
    if s >= 0 and e > s:
        try:
            return json.loads(text[s:e])
        except Exception:
            pass
    recovered = []
    for m in re.finditer(r'\{[^{}]+\}', text, re.DOTALL):
        try:
            recovered.append(json.loads(m.group()))
        except Exception:
            pass
    if recovered:
        recovered.extend([{}] * (batch_size - len(recovered)))
        return recovered[:batch_size]
    return [{}] * batch_size


def safe_enrich(record, llm_data):
    r = dict(record)
    try:
        r["relevance"] = max(0, min(10, int(float(llm_data.get("relevance", 5) or 5))))
    except (TypeError, ValueError):
        r["relevance"] = 5

    topic = str(llm_data.get("topic", "general")).strip().lower()
    r["topic"] = topic if topic in VALID_TOPICS else "general"
    if r["relevance"] < RELEVANCE_MIN:
        r["topic"] = "irrelevant"

    sentiment = str(llm_data.get("llm_sentiment", "mixed")).strip().lower()
    r["llm_sentiment"] = sentiment if sentiment in VALID_SENTIMENTS else "mixed"

    kp = llm_data.get("key_phrases", [])
    r["key_phrases"] = [str(p) for p in kp[:3]] if isinstance(kp, list) else []

    r["is_critical"] = (r["topic"] == "bug_report" and r["llm_sentiment"] == "very_negative")
    return r


def stage3_llm(all_records, meta, api_key, use_ollama):
    print("\n" + "="*60)
    print("STAGE 3 — LLM Classification")
    print("="*60)

    if use_ollama:
        print(f"  Backend: Ollama ({OLLAMA_URL}) model={OLLAMA_MODEL}")
    elif api_key:
        print(f"  Backend: Gemini ({GEMINI_MODEL})")
    else:
        print("  No LLM backend — skipping classification")

    # Load previously enriched records as cache
    enriched_cache = {}
    if os.path.exists(ENRICHED_FILE):
        try:
            with open(ENRICHED_FILE, encoding="utf-8") as f:
                prev = json.load(f)
            for r in prev.get("records", []):
                if r.get("id") and r.get("topic") and r.get("key_phrases"):
                    enriched_cache[r["id"]] = r
            print(f"  Cache: {len(enriched_cache)} previously classified records")
        except Exception as e:
            print(f"  [Warning] Could not load cache: {e}")

    # Split into cached vs new
    merged = []
    to_classify = []
    for r in all_records:
        rid = r.get("id", "")
        if rid in enriched_cache:
            merged.append(enriched_cache[rid])
        else:
            merged.append(r)
            to_classify.append(r)

    print(f"  Records to classify: {len(to_classify)}")

    if (use_ollama or api_key) and to_classify:
        total_batches = (len(to_classify) + BATCH_SIZE - 1) // BATCH_SIZE
        enriched_by_id = {}

        for bn in range(total_batches):
            batch = to_classify[bn * BATCH_SIZE:(bn + 1) * BATCH_SIZE]
            print(f"    Batch {bn+1}/{total_batches} ({len(batch)} records)...", end=" ", flush=True)
            try:
                response = call_llm(build_batch_prompt(batch), api_key, use_ollama)
                results  = parse_response(response, len(batch))
                for i, rec in enumerate(batch):
                    llm_data = results[i] if i < len(results) else {}
                    enriched_by_id[rec["id"]] = safe_enrich(rec, llm_data)
                print("✓")
            except Exception as e:
                print(f"✗ ({e})")
                for rec in batch:
                    enriched_by_id[rec["id"]] = safe_enrich(rec, {})

            if bn < total_batches - 1:
                time.sleep(RATE_LIMIT_S)

        # Apply enrichment back
        merged = [enriched_by_id.get(r.get("id"), r) for r in merged]
    elif not to_classify:
        print("  All records already classified — nothing to do.")

    # Stats
    by_topic = {}
    critical_count = 0
    for r in merged:
        t = r.get("topic", "general")
        by_topic[t] = by_topic.get(t, 0) + 1
        if r.get("is_critical"):
            critical_count += 1

    backend = "ollama" if use_ollama else ("gemini" if api_key else "none")
    meta.update({
        "llm_backend":     backend,
        "llm_enriched":    backend != "none",
        "search_enriched": False,
        "last_analyzed":   datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "new_this_run":    len(to_classify),
        "by_topic":        by_topic,
        "critical_count":  critical_count,
    })

    # Sort newest first
    merged.sort(
        key=lambda r: (r.get("created_utc") or r.get("created_at") or ""),
        reverse=True,
    )

    output = {"meta": meta, "records": merged}

    # Write mentions_enriched.json
    with open(ENRICHED_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Write data.js (dashboard reads this)
    with open(DATA_JS, "w", encoding="utf-8") as f:
        f.write("// Auto-generated by run_reddit_pipeline.py\n")
        f.write("window.MATIKS_DATA = ")
        json.dump(output, f, ensure_ascii=False)
        f.write(";\n")

    # Critical alerts
    alerts = [r for r in merged if r.get("is_critical")]
    with open(ALERTS_FILE, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)

    # Reddit summary
    reddit_enriched = [r for r in merged if r.get("platform") == "reddit"]
    print(f"\n  ✓ data.js updated")
    print(f"  Total records: {len(merged)}")
    print(f"  Reddit classified: {len(reddit_enriched)}")
    print(f"  Topics: {by_topic}")
    print(f"  Critical alerts: {critical_count}")

    # Print Reddit breakdown
    print("\n  Reddit records:")
    for r in reddit_enriched:
        print(f"    [{r.get('topic','?'):<22}] rel={r.get('relevance','?')} | {(r.get('title') or r.get('text',''))[:55]}")

    return output


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\nMatiks Reddit Pipeline")
    print("Strict filtering: no Filipino/motorcycle noise")
    print(f"Data directory: {DATA_DIR}\n")

    cfg     = load_config()
    api_key = cfg.get("GEMINI_API_KEY", "")
    if not api_key or api_key == "your_gemini_api_key_here":
        api_key = None

    use_ollama = check_ollama()
    if use_ollama:
        print(f"[LLM] Ollama reachable at {OLLAMA_URL} ✓")
    elif api_key:
        print(f"[LLM] Using Gemini ({GEMINI_MODEL})")
    else:
        print("[LLM] No backend found — classification will be skipped")
        print("      Add GEMINI_API_KEY to config.env or start Ollama\n")

    reddit_records          = stage1_scrape()
    all_records, meta       = stage2_aggregate(reddit_records)
    stage3_llm(all_records, meta, api_key, use_ollama)

    print("\n✅ Pipeline complete! Refresh the dashboard to see Reddit data.")
