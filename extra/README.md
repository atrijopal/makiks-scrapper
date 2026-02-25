# Matiks Social Monitoring System

> **Automated social listening for the Matiks app** — scrapes Reddit, Play Store, X/Twitter, and LinkedIn, scores every mention with BM25 relevance + VADER sentiment, optionally enriches with Google Gemini LLM (topics, key phrases, critical bug alerts), and displays everything on a live filterable dashboard.

---

## Quick Start (Copy-Paste)

```powershell
cd e:\SCRAPPER

# 1. Build image (once)
docker-compose build

# 2. Start container
docker-compose up -d

# 3. Run scrapers
docker exec n8n python3 /data/scripts/reddit_scraper.py
docker exec n8n python3 /data/scripts/playstore_scraper.py
docker exec n8n python3 /data/scripts/twitter_scraper.py

# 4. Aggregate + VADER sentiment
docker exec n8n python3 /data/scripts/aggregate.py

# 5. BM25 search scoring + LLM (optional)
docker exec n8n python3 /data/scripts/llm_analyzer.py

# 6. Open dashboard
start e:\SCRAPPER\dashboard\index.html
```

---

## Full Documentation

→ See the **[Step-by-Step Walkthrough](walkthrough.md)** for complete instructions including:
- One-time Docker setup
- What each scraper does + expected output
- Dashboard features and how to use them
- Setting up Google Gemini LLM (free)
- Running the LinkedIn scraper
- n8n workflow automation setup
- Troubleshooting guide

---

## File Reference

| File | Purpose |
|---|---|
| `DockerFile` | Custom n8n + Python image |
| `docker-compose.yml` | Defines n8n + linkedin-scraper services |
| `config.env` | Your credentials (never commit this) |
| `n8n_workflow.json` | Import into n8n for 6-hourly automation |
| `scripts/reddit_scraper.py` | Reddit scraper with noise filter |
| `scripts/playstore_scraper.py` | Google Play Store review scraper |
| `scripts/twitter_scraper.py` | X/Twitter mention scraper |
| `scripts/linkedin_scraper.py` | LinkedIn scraper (needs credentials + Playwright) |
| `scripts/aggregate.py` | Merge all sources + VADER sentiment |
| `scripts/search_engine.py` | BM25 + TF-IDF + fuzzy (no API needed) |
| `scripts/llm_analyzer.py` | Gemini enrichment — topics, key phrases, critical flags |
| `dashboard/index.html` | Open in browser to view all mentions |
| `data/mentions.json` | Unified mention data (auto-generated) |
| `data/mentions_enriched.json` | + BM25 scores + LLM fields (auto-generated) |
| `data/critical_alerts.json` | Bug reports with very negative sentiment |
| `data/word_cloud.json` | Top co-occurring keywords |
| `data/weekly_digest.txt` | Gemini weekly summary (Sundays) |
| `data/scraper.log` | All scraper run logs |

---

## Architecture

```
n8n (every 6h)
    ├── reddit_scraper.py ──────────┐
    ├── twitter_scraper.py ─────────┼──► aggregate.py ──► llm_analyzer.py ──► data.js ──► dashboard
    └── playstore_scraper.py ───────┘    (VADER)          (BM25 + Gemini)
```

### Intelligence Stack

| Layer | What it does | Needs API? |
|---|---|---|
| VADER sentiment | positive / neutral / negative + score | No |
| BM25 relevance | Ranks posts by relevance to Matiks reference | No |
| TF-IDF cosine | Near-duplicate detection across posts | No |
| Fuzzy match | Catches "matics", "matick" misspellings | No |
| Word co-occurrence | Builds keyword cloud from all mentions | No |
| Gemini topic classify | bug_report / feature_request / praise / question | Yes (free) |
| Gemini nuanced sentiment | very_negative → very_positive | Yes (free) |
| Gemini key phrases | Top 3 meaningful phrases per post | Yes (free) |
| Gemini critical alert | Bug + very_negative → pulsing red banner | Yes (free) |
| Gemini weekly digest | Human-readable team summary | Yes (free) |

---

## Credentials Setup

Open `config.env` and fill in:

```
LINKEDIN_EMAIL=your@email.com
LINKEDIN_PASSWORD=yourpassword

# Get free key at: https://aistudio.google.com/app/apikey
GEMINI_API_KEY=AIzaSy_your_key_here
```

> ⚠️ `config.env` is in `.gitignore` — never commit it.
