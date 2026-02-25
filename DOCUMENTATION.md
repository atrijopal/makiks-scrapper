# Matiks Social Monitoring System — Complete Technical Documentation

> **Version:** 2.0 (February 2026)
> **Stack:** Docker · n8n · Python 3.11 · Chart.js · VADER · BM25 · Gemini 2.0 Flash · Ollama

---

## 🎬 Demo

[![Watch the demo](https://img.youtube.com/vi/Xvw-GnwbdZA/maxresdefault.jpg)](https://youtu.be/Xvw-GnwbdZA)

> 📺 [Watch on YouTube →](https://youtu.be/Xvw-GnwbdZA)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [File Structure](#2-file-structure)
3. [One-Time Setup (Fresh Install)](#3-one-time-setup-fresh-install)
4. [Credentials Configuration](#4-credentials-configuration)
5. [Running the Pipeline Manually](#5-running-the-pipeline-manually)
6. [n8n Automation Setup](#6-n8n-automation-setup)
7. [How Each Scraper Works — In Depth](#7-how-each-scraper-works--in-depth)
8. [Data Aggregation & VADER Sentiment](#8-data-aggregation--vader-sentiment)
9. [LLM Analyzer — In Depth](#9-llm-analyzer--in-depth)
10. [Intelligence Stack Summary](#10-intelligence-stack-summary)
11. [Dashboard Guide](#11-dashboard-guide)
12. [Reconnecting n8n After Restart](#12-reconnecting-n8n-after-restart)
13. [Troubleshooting](#13-troubleshooting)
14. [Quick Reference Cheatsheet](#14-quick-reference-cheatsheet)

---

## 1. System Overview

The **Matiks Monitor** is a fully automated brand intelligence pipeline. It runs every 6 hours via n8n, scrapes four data sources (Reddit, Google Play Store, Apple App Store, Twitter/X), applies multi-layer sentiment analysis and LLM classification, and serves results via a live filterable dashboard — all inside a single Docker container.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          n8n Scheduler (every 6h)                        │
│                                    │                                     │
│  ┌──────────────┐  ┌─────────────────────┐  ┌──────────┐  ┌──────────┐  │
│  │reddit_scraper│  │ playstore_scraper   │  │appstore  │  │ twitter  │  │
│  │  (4 queries) │  │ (200 new + 100 rel) │  │scraper   │  │ scraper  │  │
│  └──────┬───────┘  └──────────┬──────────┘  └────┬─────┘  └────┬─────┘  │
│         └──────────────────────┴────────────────┴──────────────┘        │
│                                      │                                   │
│                                 aggregate.py                             │
│                      (merge · deduplicate · VADER sentiment)             │
│                                      │                                   │
│                               llm_analyzer.py                            │
│                    (BM25 scoring · cache · Ollama → Gemini fallback)     │
│                                      │                                   │
│                          data.js  ·  mentions_enriched.json              │
│                                      │                                   │
│                            dashboard/index.html                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### What gets scraped

| Source           | What                                             | Volume per run |
|------------------|--------------------------------------------------|----------------|
| Reddit           | Posts + comments mentioning "Matiks"             | Up to 200      |
| Google Play Store| Reviews for `com.matiks.app`                    | Up to 300      |
| Apple App Store  | Reviews for Matiks (App ID 6471803517)           | Up to 100      |
| Twitter / X      | Tweets mentioning "Matiks" (last 7 days)         | Up to 100      |

---

## 2. File Structure

```
e:\SCRAPPER\
│
├── DockerFile                      ← Multi-stage build: Python 3.11 + n8n
├── docker-compose.yml              ← Defines the container and mounts
├── config.env                      ← All secrets (never commit this)
├── n8n_workflow.json               ← Import into n8n UI
│
├── reddit_scraper.py               ← Reddit: targeted queries + 3-rule filter
├── playstore_scraper.py            ← Google Play: accumulating review store
├── appstore_scraper.py             ← Apple App Store scraper
├── twitter_scraper.py              ← Twitter/X: twscrape + blocklist
├── aggregate.py                    ← Merge all sources + VADER sentiment
├── llm_analyzer.py                 ← BM25 + cache + Ollama/Gemini LLM
├── search_engine.py                ← BM25 / TF-IDF / Levenshtein fuzzy
│
├── dashboard/
│   └── index.html                  ← Open in browser (reads data/data.js)
│
└── data/                           ← Auto-generated outputs
    ├── reddit_raw.json
    ├── playstore_raw.json
    ├── appstore_raw.json
    ├── twitter_raw.json
    ├── mentions.json               ← After aggregate.py
    ├── mentions_enriched.json      ← After llm_analyzer.py
    ├── data.js                     ← Dashboard data (JS global variable)
    ├── critical_alerts.json        ← bug_report + very_negative only
    ├── word_cloud.json             ← Top co-occurring keywords
    ├── weekly_digest.txt           ← Sunday LLM summary
    ├── .enrichment_checkpoint.json ← Crash-safe progress saver
    └── scraper.log                 ← Timestamped run history
```

> **Path mapping:** Inside Docker, `e:\SCRAPPER\` mounts as `/data`.
> So `e:\SCRAPPER\reddit_scraper.py` → `/data/reddit_scraper.py` inside the container.

---

## 3. One-Time Setup (Fresh Install)

### Prerequisites

- **Docker Desktop** installed and running (Windows: requires WSL 2 + Hyper-V)
- **Python files** in `e:\SCRAPPER\` (all scripts)
- **Dashboard** at `e:\SCRAPPER\dashboard\index.html`

### Step 1 — Fill in credentials

Open `config.env` and set at minimum the Gemini API key:

```env
GEMINI_API_KEY=AIzaSy_your_actual_key_here
```

Get a free key at: https://aistudio.google.com/app/apikey

### Step 2 — Build the Docker image

```powershell
cd e:\SCRAPPER
docker-compose build
```

This uses a **multi-stage build**:
- Stage 1 (`python:3.11-alpine`): installs all Python packages (`google-play-scraper`, `app-store-scraper`, `vaderSentiment`, `rank_bm25`, `python-Levenshtein`, `fuzzywuzzy`, `twscrape`)
- Stage 2 (`n8nio/n8n:latest`): copies Python + installed packages into the official n8n image

Expected output: `Successfully built ...` and `Successfully tagged custom-n8n-python:latest`

Only needs to run once, or again after changes to `DockerFile`.

### Step 3 — Start the container

```powershell
docker-compose up -d
```

n8n starts on port **5678**. Verify:

```powershell
docker ps
# Should show: n8n   custom-n8n-python   Up X minutes
```

### Step 4 — Create data folder inside container

```powershell
docker exec n8n mkdir -p /data/data
```

### Step 5 — Open n8n

Go to http://localhost:5678. First time: create an account (email + password, stored locally in the `n8n_data` Docker volume).

### Step 6 — Import the workflow

1. In n8n: click **Workflows** (left sidebar)
2. Click **+ New** → **Import from file**
3. Select `e:\SCRAPPER\n8n_workflow.json`
4. Click **Save**

### Step 7 — Run the pipeline manually (first test)

```powershell
docker exec n8n python3 /data/reddit_scraper.py
docker exec n8n python3 /data/playstore_scraper.py
docker exec n8n python3 /data/appstore_scraper.py
docker exec n8n python3 /data/twitter_scraper.py
docker exec n8n python3 /data/aggregate.py
docker exec n8n python3 /data/llm_analyzer.py
```

### Step 8 — Open the dashboard

```powershell
start e:\SCRAPPER\dashboard\index.html
```

---

## 4. Credentials Configuration

`config.env` is the single file for all secrets. Loaded at runtime by `llm_analyzer.py` and `twitter_scraper.py`.

```env
# ── Google Gemini (LLM enrichment) ───────────────────────────────────────
# Free tier: 15 req/min, 1,500 req/day, 1M tokens/day
# Get key: https://aistudio.google.com/app/apikey
GEMINI_API_KEY=your_key_here

# ── Twitter / X (optional but recommended) ───────────────────────────────
# Without these, twscrape uses guest tokens (heavily rate-limited)
# Use any free Twitter account
TWITTER_USERNAME=your_handle
TWITTER_PASSWORD=your_password
TWITTER_EMAIL=your@email.com

# ── Slack (optional) ──────────────────────────────────────────────────────
# Create webhook: https://api.slack.com/apps → Incoming Webhooks
SLACK_WEBHOOK_URL=
```

> ⚠️ `config.env` should be in `.gitignore`. Never commit it. Never share it.

---

## 5. Running the Pipeline Manually

```powershell
# 1. Scrapers (run in any order — they are independent)
docker exec n8n python3 /data/reddit_scraper.py
docker exec n8n python3 /data/playstore_scraper.py
docker exec n8n python3 /data/appstore_scraper.py
docker exec n8n python3 /data/twitter_scraper.py

# 2. Merge + VADER sentiment
docker exec n8n python3 /data/aggregate.py

# 3. BM25 + LLM enrichment (only new records sent to LLM)
docker exec n8n python3 /data/llm_analyzer.py

# Force weekly digest (even if not Sunday)
docker exec n8n python3 /data/llm_analyzer.py --digest
```

### Check logs

```powershell
docker exec n8n tail -50 /data/data/scraper.log   # last 50 lines
docker exec n8n tail -f /data/data/scraper.log     # live watch
```

---

## 6. n8n Automation Setup

### Workflow structure

```
Every 6 Hours
      │
      ├──► Reddit Scraper ────────────────┐
      ├──► Play Store Reviews ────────────┤ Merge 1
      ├──► App Store Reviews  ────────────┤    │
      └──► Twitter / X ──────────────────┘    │
                                          Merge 2
                                              │
                                      Aggregate + VADER
                                              │
                                      BM25 + LLM Enrichment
                                              │
                                      Check Critical Alerts
                                              │
                                      Critical? ──► Log Critical
                                              └──► Log OK
```

### Activating the workflow

1. Open http://localhost:5678
2. Open the **Matiks Social Monitor** workflow
3. Toggle **Active** (top right) → turns green
4. n8n now runs every 6 hours automatically

### Running immediately

1. Open the workflow
2. Click **Execute Workflow** (▶ button)
3. Watch nodes light up — green = success, red = failed

### Retry logic configured on each node

- `maxTries: 3` — retries up to 3 times on failure
- `waitBetweenTries: 30000` — 30s wait between retries
- Prevents temporary network blips from failing the entire run

---

## 7. How Each Scraper Works — In Depth

### 7.1 reddit_scraper.py — Efficient Noise-Free Scraping

Reddit has a major ambiguity problem: "Matiks" in Filipino/Tagalog means "automatic" and is commonly used in discussions about motorcycles, car transmissions, and rap battles. Without filtering, ~80% of raw results are noise.

#### Targeted query design

Instead of a single broad search, four precision queries are used:

```python
QUERIES = [
    '"Matiks" math app',        # exact phrase + context word
    '"Matiks" IIT Guwahati',    # exact phrase + brand origin
    '"Matiks" puzzle startup',  # exact phrase + product type
    'Matiks app review',        # review intent signals
]
```

Using exact-quoted `"Matiks"` for the first three queries forces Reddit's search to match the literal string, dramatically reducing false positives.

#### Three-rule relevance filter (runs before any API call is saved)

Every candidate post passes through `is_relevant()` in sequence:

```
Rule 1 — Brand presence check
  "matiks" must appear in title or body text (case-insensitive).
  Rejects posts returned by broad subreddit results that don't mention Matiks at all.

Rule 2 — Hard blocklist
  Immediately drops any post containing any of:
  motor, e-bike, gear, transmission, automatic, atheist, rap battle,
  battle rap, philippines, pinas, tagalog, motorcycle, scooter, cars,
  honda, yamaha, kawasaki, suzuki, pilipinas, filipin, tagalog slang

  These cover all known Tagalog/Filipino-language false positive patterns.
  A single blocklist word = instant discard, no further processing.

Rule 3 — Mandatory keyword gate
  At least one of these must be present:
  math, puzzle, app, game, iit, startup, guwahati, playstore,
  play store, ios, android, streak, brain, level, download

  This ensures the post has at least one signal that it's about an app
  or the Matiks brand's known context.
```

Only posts passing all three rules are saved to `reddit_raw.json`.

#### Pagination and rate limiting

- Fetches up to **5 pages × 50 posts = 250 candidates per query**
- Uses Reddit's `after` cursor token for pagination
- Sleeps **1.5 seconds** between pages to stay within Reddit's unauthenticated rate limit (~60 req/min)
- No API key required — uses Reddit's public JSON API with a descriptive `User-Agent`

#### Deduplication

`seen_ids` is a Python `set()` maintained across all queries in the same run. If the same post appears in multiple query results (common for brand monitoring), it is added only once.

#### Output

Appends to (does not overwrite) `data/reddit_raw.json` — new posts are merged with existing ones by `aggregate.py`'s deduplication.

---

### 7.2 playstore_scraper.py — Accumulating Review Store

Uses the `google-play-scraper` Python library. No API key required.

- **App ID:** `com.matiks.app`
- Fetches **200 newest** + **100 most-relevant** reviews per run
- Deduplicates by `reviewId` (unique per reviewer)
- **Accumulates:** new reviews are appended to the existing file, not overwriting it
- Handles the library's internal pagination automatically
- Output: `data/playstore_raw.json`

---

### 7.3 appstore_scraper.py — Apple Reviews

Uses the `app-store-scraper` Python library.

- **App name:** `matiks-math-and-brain-games`
- **App ID:** `6471803517`
- **Country:** `us` (US App Store)
- Fetches up to **100 reviews** per run
- Output: `data/appstore_raw.json`

---

### 7.4 twitter_scraper.py — Last-7-Days Tweets

Uses `twscrape` (the modern replacement for the defunct `snscrape` library).

- **Search query:** `Matiks since:YYYY-MM-DD lang:en` (auto-computed last 7 days)
- Applies the **same blocklist** as the Reddit scraper to filter Tagalog noise
- Works in two modes:
  - **Guest token mode** (no credentials): works but Twitter rate-limits heavily
  - **Logged-in mode** (credentials in `config.env`): much higher rate limits
- **Graceful failure:** always writes a valid (possibly empty) JSON array, so subsequent pipeline steps never crash due to a missing file
- Output: `data/twitter_raw.json`

---

## 8. Data Aggregation & VADER Sentiment

### aggregate.py — Merge, Deduplicate, Score

`aggregate.py` is the central merge step. It:

1. **Reads** all four raw JSON files in order: `reddit_raw.json`, `twitter_raw.json`, `playstore_raw.json`, `appstore_raw.json`
2. **Deduplicates** on a composite key `{platform}_{id}` — prevents the same review from appearing twice if scrapers overlap
3. **Sorts** all records by `created_at` (newest first)
4. **Runs VADER** sentiment on each record

#### VADER sentiment scoring

VADER (Valence Aware Dictionary and sEntiment Reasoner) is a lexicon-based model specifically optimised for social media text. It understands:
- Capitalisation ("GREAT" scores higher than "great")
- Punctuation ("great!!!" > "great")
- Negation ("not good" scores negative)
- Emojis and emoticons

Each record gets a `sentiment` object:

```json
{
  "label":    "positive",   // positive | neutral | negative
  "compound": 0.7351,       // overall score: -1.0 to +1.0
  "pos":      0.582,        // proportion of positive tokens
  "neu":      0.418,        // proportion of neutral tokens
  "neg":      0.000         // proportion of negative tokens
}
```

Thresholds:
- `compound >= 0.05` → **positive**
- `compound <= -0.05` → **negative**
- otherwise → **neutral**

The text used for sentiment varies by platform:
- Reddit: `title + " " + body` (combined)
- Play Store / App Store / Twitter: `text` field only

#### Output

- `data/mentions.json` — full enriched JSON with `meta` + `records`
- `data/data.js` — same data as a JS global (`window.MATIKS_DATA = ...`) so the dashboard works over `file://` protocol without a local server

---

## 9. LLM Analyzer — In Depth

`llm_analyzer.py` is the most sophisticated component. It adds four LLM-powered fields per record, plus BM25/fuzzy search enrichment — all with a crash-safe caching architecture.

### 9.1 Backend Auto-Detection and Fallback Chain

On every run, the analyzer checks for available LLM backends in priority order:

```
Step 1: Check Ollama
  → HTTP GET http://host.docker.internal:11434/api/tags (5s timeout)
  → Verify model "llama3.2:3b" is in the pulled models list
  → If YES: use Ollama (local, no API costs, no rate limits)

Step 2: Check Gemini
  → Read GEMINI_API_KEY from config.env
  → If valid key present AND Ollama not available: use Gemini

Step 3: BM25-only mode
  → If neither backend available:
    Run BM25 + fuzzy scoring only (no topic/sentiment from LLM)
    Dashboard still works, just without topic/key_phrase columns
```

#### Ollama → Gemini automatic mid-run fallback

Even during an active enrichment run, if Ollama fails on a batch (network error, model crash, timeout), `call_llm()` automatically falls back to Gemini for that batch:

```python
def call_llm(prompt, api_key, use_ollama):
    if use_ollama:
        try:
            return call_ollama(prompt)
        except Exception as ollama_err:
            if api_key:
                print(f"[LLM] Ollama failed. Falling back to Gemini...")
                return call_gemini(api_key, prompt)
            raise
    if api_key:
        return call_gemini(api_key, prompt)
    raise RuntimeError("No LLM backend available")
```

This means: even if your GPU runs out of VRAM halfway through a batch, the cloud backend picks up seamlessly.

---

### 9.2 Incremental Processing (LLM Cache)

The most API-efficient design decision: **only new records are sent to the LLM on each run**.

On startup, `llm_analyzer.py`:
1. Loads `mentions_enriched.json` from the previous run
2. Builds an in-memory cache: `{record_id → enriched_record}`
3. Compares with the current `mentions.json`
4. Only sends records **without** `key_phrases` (the completion marker) to the LLM

```python
# Cache previously enriched records
enriched_cache = {}
for r in prev["records"]:
    if r.get("id") and r.get("topic") and r.get("key_phrases"):
        enriched_cache[r["id"]] = r

# Only send new ones to LLM
new_recs = [r for r in records if r["id"] not in enriched_cache]
```

**Practical impact:** After the first full run (e.g. 300 records, ~5 minutes), subsequent runs only process the ~20–50 new records since the last run. This cuts API usage by >85% in steady state.

---

### 9.3 Crash-Safe Checkpointing

A separate `CHECKPOINT_FILE` (`.enrichment_checkpoint.json`) persists progress after every batch of 5 records:

```
Run starts → load checkpoint (if exists)
  Batch 1/60 processed → save checkpoint
  Batch 2/60 processed → save checkpoint
  ...
  Power outage at Batch 35 ←── without this, all 35 batches lost
  ...
Run restarts → load checkpoint, skip first 34 already-done batches
  Batch 35/60 resumes from where it crashed
  ...
  All done → clear checkpoint
```

This is critical for large initial scrapes (300+ records) that can take 5–10 minutes of real API calls.

---

### 9.4 Batch Processing and Rate Limiting

Records are sent in **batches of 5** to the LLM. A single batch prompt contains all 5 posts and asks for a JSON array of 5 result objects.

Why batches of 5?
- Fewer API calls (efficiency)
- Small enough that a partial failure only loses 5 records, not 50
- Fits comfortably within Gemini's context window

Between batches:
- **Ollama:** 0.5 second sleep (local, no rate limits)
- **Gemini:** same 0.5s by default, plus **automatic 429 retry logic**:
  - First 429 → wait 60 seconds
  - Second 429 → wait 120 seconds
  - Third 429 → wait 180 seconds
  - Fourth attempt fails → marks batch as failed, uses defaults

---

### 9.5 What the LLM Classifies

Each batch prompt provides full context about the Matiks brand and asks for five fields per post:

#### Relevance score (0–10)
- 10: Explicitly about the math app, puzzles, IIT, app store feedback
- 7–9: Mentions "Matiks" app in a general gaming or productivity context
- 3–6: Ambiguous
- 0–2: Definitely motorcycles, Tagalog slang, rap battles

Posts with `relevance < 7` are automatically marked `topic = "irrelevant"` regardless of what the LLM classified them as (double safety check in `safe_enrich()`).

#### Topic classification
```
bug_report          → User reporting a crash, freeze, or broken feature
feature_request     → User asking for a new capability
praise              → Positive experience, compliment
question            → User asking for help or clarification
competitor_comparison → Comparing Matiks to another app
general             → On-topic but doesn't fit the above
irrelevant          → Not about the Matiks app
```

#### LLM sentiment (nuanced, 5-class)
```
very_negative  → Strongly negative language, frustration, anger
negative       → Generally negative tone
mixed          → Both positive and negative elements
positive       → Generally positive tone
very_positive  → Enthusiastic praise, strong recommendation
```

This is more granular than VADER's 3-class output and handles sarcasm and context better.

#### Key phrases (top 3)
Three meaningful phrases extracted from the post. These appear as teal chips on dashboard cards and help reviewers quickly scan without reading the full text.

#### Critical alert flag
```python
is_critical = (topic == "bug_report") AND (llm_sentiment == "very_negative")
```

Re-derived from the actual classified values (not blindly trusted from LLM output) in `safe_enrich()`. Critical records appear in `critical_alerts.json` and trigger the red pulsing banner on the dashboard.

---

### 9.6 Response Parsing with Graceful Degradation

LLMs occasionally return malformed JSON. The parser has a 4-level recovery chain:

```
Level 1: Direct JSON parse
  → json.loads(response) — works 95% of the time

Level 2: Find JSON array bounds
  → Scan for first "[" and last "]", try parsing that substring
  → Handles responses with leading prose ("Sure! Here are the results: [...]")

Level 3: Partial object recovery
  → Regex-extract all complete {...} objects individually
  → Pads missing objects with empty dicts
  → Allows partial batch to succeed even with truncated response

Level 4: Full fallback
  → Returns [{}] * batch_size
  → safe_enrich() applies safe defaults to all fields
  → Run continues, records get "general" topic, "mixed" sentiment
```

---

### 9.7 Weekly Digest Generation

On Sundays (or with `--digest` flag), the analyzer generates a human-readable weekly summary:

```powershell
docker exec n8n python3 /data/llm_analyzer.py --digest
```

The digest prompt provides:
- Total mentions count and platform breakdown
- Top 10 negative mentions (verbatim)
- Top 10 positive mentions (verbatim)
- Bug reports and feature requests (up to 5 each)

And asks the LLM to write a 300-word executive summary covering:
1. This week's situation in 2 sentences
2. Top issues to fix
3. What users love
4. Feature requests to consider
5. One recommendation

Output saved to `data/weekly_digest.txt`.

---

### 9.8 Word Cloud Generation

`search_engine.py`'s `get_word_cloud_data()` computes the top co-occurring keywords across all enriched records. Stopwords and single-character tokens are excluded. Output: `data/word_cloud.json`.

---

## 10. Intelligence Stack Summary

| Layer                 | Tool               | API Key? | Output field                          |
|-----------------------|--------------------|----------|---------------------------------------|
| Sentiment (fast)      | VADER              | No       | `sentiment.label`, `sentiment.compound` |
| Relevance scoring     | BM25               | No       | `bm25_score`                           |
| Duplicate detection   | TF-IDF cosine      | No       | `is_near_duplicate`                    |
| Misspelling detection | Levenshtein fuzzy  | No       | `fuzzy_brand_match`                    |
| Keyword cloud         | Co-occurrence      | No       | `word_cloud.json`                      |
| Topic classification  | Gemini 2.0 Flash   | Yes (free)| `topic`                               |
| Nuanced sentiment     | Gemini 2.0 Flash   | Yes (free)| `llm_sentiment`                       |
| Key phrase extraction | Gemini 2.0 Flash   | Yes (free)| `key_phrases`                         |
| Critical alert        | Rule-based         | No       | `is_critical`                          |
| Weekly digest         | Gemini 2.0 Flash   | Yes (free)| `weekly_digest.txt`                   |
| (Alternative) All LLM | Ollama llama3.2:3b | No       | Same as above, local GPU              |

### Gemini Free Tier Limits

- 15 requests per minute
- 1,500 requests per day
- 1 million tokens per day

With batches of 5 and incremental processing, a typical run uses 5–15 API requests (only new records). The free tier is more than sufficient for this use case.

### Ollama Local Alternative

If you have an NVIDIA GPU (≥6GB VRAM), you can run LLM enrichment entirely locally:

```powershell
# Install Ollama from https://ollama.com
ollama pull llama3.2:3b      # ~2GB download, fits in RTX 4050 6GB VRAM
```

The analyzer auto-detects Ollama at startup and prefers it over Gemini. No API costs, no rate limits, no internet required for inference.

---

## 11. Dashboard Guide

Open `e:\SCRAPPER\dashboard\index.html` in any browser. It reads from `data\data.js`.

### Header bar

| Element              | What it does                                                          |
|----------------------|-----------------------------------------------------------------------|
| Updated timestamp    | Shows when `llm_analyzer.py` last ran + which backend was used       |
| Hide dupes checkbox  | Hides near-duplicate posts (cross-posted Reddit content)              |
| ↻ Refresh button     | Re-reads `data.js` without reloading the page                        |

### Stats ribbon

Each number is **clickable** — clicking applies that platform filter.

| Stat         | Meaning                                               |
|--------------|-------------------------------------------------------|
| Total        | All records in `mentions_enriched.json`               |
| Reddit       | Mentions from Reddit                                  |
| Play Store   | Reviews from Google Play                              |
| App Store    | Reviews from Apple App Store                          |
| Twitter / X  | Tweets mentioning Matiks                              |
| Positive     | VADER-scored positive mentions                        |
| Negative     | VADER-scored negative mentions                        |
| 🚨 Critical  | Bug reports with very_negative LLM sentiment          |

### Filters

- **Platform** — filter to one source
- **Search box** — fuzzy text search across title + body
- **Sentiment** — Positive / Neutral / Negative / 🚨 Critical
- **Topic** — Bug / Feature / Praise / Question (visible after LLM enrichment)
- **Date range** — override the default 7-day window
- **Sort** — Newest / BM25 Relevance / Most Negative / Most Positive

### Cards

Each card shows: platform badge, sentiment badge, topic badge, date, title, text (3-line clamp), key phrases (teal chips), relevance bar, sentiment bar, star rating / engagement stats, and a **View →** link to the original.

### Charts

| Chart                   | What it shows                                       |
|-------------------------|-----------------------------------------------------|
| Daily Mentions          | Bar chart of all mentions over time                 |
| Sentiment Trend         | 7-day rolling average pos/neg/neutral               |
| Platform Breakdown      | Donut chart by source                               |
| Play Store Rating Trend | Average star rating over time                       |
| Reddit Engagement       | Top 15 posts by score + comments                    |
| Topic Breakdown         | LLM-classified topic distribution                   |

### Critical alerts

When `is_critical: true` records exist, a **red pulsing banner** appears at the top of the page. Clicking it filters to show only critical issues. These are also exported to `data/critical_alerts.json` for Slack/email alerting.

---

## 12. Reconnecting n8n After Restart

### Scenario A — Container stopped, data intact

```powershell
docker ps                    # check if running
cd e:\SCRAPPER
docker-compose up -d         # start it
docker ps                    # confirm
```

Go to http://localhost:5678 — workflow and data are preserved in the `n8n_data` Docker volume.

### Scenario B — Workflow shows Inactive

1. Go to http://localhost:5678
2. Open **Matiks Social Monitor**
3. Toggle **Active** → click it

### Scenario C — Workflow lost (volume deleted)

```powershell
# Re-import from JSON
# n8n UI → Workflows → Import from file → e:\SCRAPPER\n8n_workflow.json
# Save → toggle Active
```

### Scenario D — Complete rebuild

```powershell
cd e:\SCRAPPER
docker-compose down
docker volume rm scrapper_n8n_data
docker-compose build --no-cache
docker-compose up -d
docker exec n8n mkdir -p /data/data
# Then re-import workflow and re-run pipeline
```

> 📌 Your `data/` folder (raw JSON, enriched data) is on your PC at `e:\SCRAPPER\data\`. It is **not** in the Docker volume and survives any Docker rebuild.

### Scenario E — Port 5678 in use

```powershell
netstat -ano | findstr :5678
# Change "5678:5678" → "5679:5678" in docker-compose.yml
# Access n8n at http://localhost:5679
```

### Health check

```powershell
docker ps | findstr n8n                                         # container running
curl http://localhost:5678/healthz                              # n8n web OK
docker exec n8n python3 --version                               # Python OK
docker exec n8n python3 -c "import vaderSentiment; print('OK')" # packages OK
docker exec n8n ls /data/data/                                  # data folder OK
```

---

## 13. Troubleshooting

### Container won't start
```powershell
docker-compose logs n8n
# Common fix: port conflict → change "5678:5678" to "5679:5678" in docker-compose.yml
```

### `python3: not found` inside container
```powershell
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Play Store returns 0 reviews
```powershell
docker exec n8n pip3 install --upgrade google-play-scraper
docker exec n8n python3 /data/playstore_scraper.py
```

### Twitter returns 0 tweets

1. Add Twitter credentials to `config.env` (best fix)
2. Wait 1 hour (guest token cooldown)
3. Verify there are recent tweets mentioning Matiks

### Reddit returns false positives

Add words to `BLOCKLIST` in `reddit_scraper.py`:
```python
BLOCKLIST = {
    "motor", "e-bike", ...,
    "your_new_word_here",
}
```
Then re-run scraper and aggregate.

### LLM enrichment is slow

Normal. Gemini processes in batches of 5 with rate limiting. For 300 records: ~5 minutes first run. After that, only new records (~20–50 per run) are sent — very fast.

### Dashboard shows "No data found"
```powershell
dir e:\SCRAPPER\data\data.js         # check it exists
docker exec n8n python3 /data/aggregate.py
docker exec n8n python3 /data/llm_analyzer.py
```

Also check the browser console (F12) for path errors. `index.html` looks for `../data/data.js`.

### Dashboard shows "No mentions in last 7 days"

Correct if your data is older than 7 days. Use the **date pickers** in the filter bar to extend the range, or clear them to show all time.

### n8n nodes show red after workflow run
```powershell
docker exec n8n tail -100 /data/data/scraper.log
```
Most common cause: script path is wrong. All scripts must be at `/data/script_name.py`.

---

## 14. Quick Reference Cheatsheet

### Start everything

```powershell
cd e:\SCRAPPER
docker-compose up -d
# Then go to http://localhost:5678 and activate the workflow
```

### Full pipeline (manual)

```powershell
docker exec n8n python3 /data/reddit_scraper.py
docker exec n8n python3 /data/playstore_scraper.py
docker exec n8n python3 /data/appstore_scraper.py
docker exec n8n python3 /data/twitter_scraper.py
docker exec n8n python3 /data/aggregate.py
docker exec n8n python3 /data/llm_analyzer.py
```

### Check status

```powershell
docker ps                                               # container running?
docker-compose logs --tail=20 n8n                       # container logs
docker exec n8n tail -30 /data/data/scraper.log         # scraper logs
```

### Restart / Rebuild

```powershell
docker-compose restart                                  # quick restart
docker-compose down && docker-compose up -d             # full stop+start
docker-compose build --no-cache && docker-compose up -d # full rebuild
```

### Key URLs

| URL                                          | Purpose                        |
|----------------------------------------------|--------------------------------|
| http://localhost:5678                         | n8n workflow editor            |
| `e:\SCRAPPER\dashboard\index.html`            | Live monitoring dashboard      |
| https://aistudio.google.com/app/apikey        | Get free Gemini API key        |
| https://ollama.com                            | Download Ollama (local LLM)    |
| https://play.google.com/store/apps/details?id=com.matiks.app | Play Store listing |
| https://apps.apple.com/us/app/matiks-math-and-brain-games/id6471803517 | App Store listing |

### Output files

| File                          | Generated by        | Contains                                  |
|-------------------------------|---------------------|-------------------------------------------|
| `data/reddit_raw.json`        | reddit_scraper.py   | Raw Reddit posts (noise-filtered)         |
| `data/playstore_raw.json`     | playstore_scraper.py| Raw Play Store reviews (accumulating)     |
| `data/appstore_raw.json`      | appstore_scraper.py | Raw App Store reviews                     |
| `data/twitter_raw.json`       | twitter_scraper.py  | Raw tweets                                |
| `data/mentions.json`          | aggregate.py        | Merged + VADER sentiment                  |
| `data/data.js`                | aggregate / llm     | Dashboard data (JS global)                |
| `data/mentions_enriched.json` | llm_analyzer.py     | + BM25 + topic + llm_sentiment + phrases  |
| `data/critical_alerts.json`   | llm_analyzer.py     | Bug reports with very_negative sentiment  |
| `data/word_cloud.json`        | llm_analyzer.py     | Top keyword co-occurrences                |
| `data/weekly_digest.txt`      | llm_analyzer.py     | Sunday executive summary                  |
| `data/.enrichment_checkpoint.json` | llm_analyzer.py | Crash-safe mid-run progress saver    |
| `data/scraper.log`            | All scripts         | Timestamped run history                   |
