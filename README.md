# Matiks Social Monitor

> Automated brand intelligence — Reddit · Google Play · App Store · Twitter/X monitored every 6 hours, with LLM-powered classification and a live dashboard.

## 🎬 Demo

[![Watch the demo](https://img.youtube.com/vi/Xvw-GnwbdZA/maxresdefault.jpg)](https://youtu.be/Xvw-GnwbdZA)

> 📺 [Watch on YouTube →](https://youtu.be/Xvw-GnwbdZA)

---

## What It Does

- Scrapes 4 platforms for mentions of the Matiks app every 6 hours
- Auto-filters noise (Tagalog false positives, off-topic posts)
- Runs VADER sentiment analysis + Gemini LLM classification
- Serves a live filterable dashboard via a local HTML file
- Sends critical alerts (bug reports + very negative sentiment) to a separate file

---

## Tech Stack

| Component        | Technology                                      |
|------------------|-------------------------------------------------|
| Scheduler        | n8n (self-hosted, runs in Docker)               |
| Container        | Docker Desktop (Windows, WSL 2)                 |
| Python runtime   | Python 3.11 (inside the Docker image)           |
| Fast sentiment   | VADER (lexicon-based, no API)                   |
| Relevance scoring| BM25 + TF-IDF + Levenshtein fuzzy               |
| LLM (primary)   | Ollama `llama3.2:3b` (local GPU, optional)      |
| LLM (fallback)  | Google Gemini 2.0 Flash (free tier)             |
| Dashboard        | Vanilla HTML + Chart.js (no server needed)      |

---

## Prerequisites

Before you begin, make sure you have:

- **Windows 10/11** with WSL 2 enabled
- **Docker Desktop** ([download](https://www.docker.com/products/docker-desktop/)) — must be running
- **Git** (optional, for cloning)
- A free **Google Gemini API key** ([get one here](https://aistudio.google.com/app/apikey))

---

## Installation Guide

### Step 1 — Clone / Download the project

```powershell
# Option A: Git clone
git clone https://github.com/your-org/matiks-monitor.git e:\SCRAPPER

# Option B: Download ZIP and extract to e:\SCRAPPER
```

### Step 2 — Enable WSL 2 & start Docker Desktop

1. Open **Docker Desktop** from your Start menu
2. Wait for the whale icon in the system tray to stop animating (~1 minute)
3. Verify Docker is running:
   ```powershell
   docker info
   ```
   You should see `Server:` info — not an error.

> If Docker Desktop won't start: Run it as Administrator, or enable Hyper-V/Virtualization in BIOS.

### Step 3 — Configure credentials

Open `e:\SCRAPPER\config.env` in any text editor and fill in your keys:

```env
# REQUIRED — get free key at https://aistudio.google.com/app/apikey
GEMINI_API_KEY=AIzaSy_your_actual_key_here

# OPTIONAL — improves Twitter scraping reliability
TWITTER_USERNAME=your_twitter_handle
TWITTER_PASSWORD=your_password
TWITTER_EMAIL=your@email.com

# OPTIONAL — Slack alerting
SLACK_WEBHOOK_URL=
```

> ⚠️ Never commit `config.env` to Git. It should be in `.gitignore`.

### Step 4 — Build the Docker image

```powershell
cd e:\SCRAPPER
docker-compose build
```

This builds a custom image with n8n + Python 3.11 + all required packages. Runs once (or after `DockerFile` changes).

Expected: `Successfully tagged custom-n8n-python:latest`

### Step 5 — Start the container

```powershell
docker-compose up -d
```

Starts n8n in the background on port **5678**. Verify:

```powershell
docker ps
# Should show: n8n   custom-n8n-python   Up X seconds
```

### Step 6 — Create the data output folder

```powershell
docker exec n8n mkdir -p /data/data
```

---

## n8n Setup

### Open n8n

Go to **http://localhost:5678** in your browser.

**First time only:** Create a local account (email + password). This is stored in the Docker volume — it's only local to your machine.

### Import the workflow

1. In n8n, click **Workflows** in the left sidebar
2. Click **+ New** → **Import from file**
3. Browse to `e:\SCRAPPER\n8n_workflow.json` and select it
4. Click **Save**

### Activate the schedule

1. Open the **Matiks Social Monitor** workflow
2. Click the **Active** toggle (top right) — it turns green
3. The pipeline now runs automatically **every 6 hours**

### Run immediately (first test)

Click **Execute Workflow** (▶ button, top right of the workflow editor).
- **Green node** = success
- **Red node** = failed (click it to see the error)

Each scraper node has `maxTries: 3` with 30-second waits between retries.

---

## Running the Pipeline Manually (Without n8n)

```powershell
# Run all scrapers
docker exec n8n python3 /data/reddit_scraper.py
docker exec n8n python3 /data/playstore_scraper.py
docker exec n8n python3 /data/appstore_scraper.py
docker exec n8n python3 /data/twitter_scraper.py

# Merge + VADER sentiment
docker exec n8n python3 /data/aggregate.py

# LLM enrichment + topic classification
docker exec n8n python3 /data/llm_analyzer.py

# Force weekly digest generation (any day)
docker exec n8n python3 /data/llm_analyzer.py --digest
```

---

## Opening the Dashboard

```powershell
start e:\SCRAPPER\dashboard\index.html
```

Or open the file directly in Chrome / Edge / Firefox.

The dashboard reads `data\data.js` which is auto-updated by `llm_analyzer.py` after every run.

---

## Optional: Local LLM with Ollama (No API Key Needed)

If you have an NVIDIA GPU with ≥6GB VRAM, you can run LLM classification locally for free:

```powershell
# 1. Install Ollama from https://ollama.com
# 2. Pull the model (~2GB download)
ollama pull llama3.2:3b

# 3. Run normally — the analyzer auto-detects Ollama and prefers it over Gemini
docker exec n8n python3 /data/llm_analyzer.py
```

The fallback chain is: **Ollama → Gemini → BM25-only** (automatic, no config needed).

---

## After a PC Restart

Docker Desktop doesn't always auto-start. After a reboot:

```powershell
# 1. Open Docker Desktop from Start menu and wait ~1 minute
# 2. Start the container
cd e:\SCRAPPER
docker-compose up -d

# 3. Go to http://localhost:5678 — your workflow and data are intact
```

If the workflow shows as **Inactive**, just toggle the **Active** switch back on.

---

## File Structure

```
e:\SCRAPPER\
├── DockerFile                  ← Builds n8n + Python 3.11 image
├── docker-compose.yml          ← Container config (port 5678, volumes)
├── config.env                  ← Credentials (never commit)
├── n8n_workflow.json           ← Import this into n8n
├── reddit_scraper.py           ← Reddit scraper (noise-filtered)
├── playstore_scraper.py        ← Google Play Store reviews
├── appstore_scraper.py         ← Apple App Store reviews
├── twitter_scraper.py          ← Twitter/X scraper
├── aggregate.py                ← Merge + VADER sentiment
├── llm_analyzer.py             ← BM25 + LLM enrichment
├── search_engine.py            ← BM25 / TF-IDF / fuzzy utilities
├── dashboard/
│   └── index.html              ← Open this in your browser
└── data/                       ← Auto-generated outputs
    ├── mentions_enriched.json
    ├── critical_alerts.json
    ├── data.js
    └── scraper.log
```

---

## Common Issues

| Problem | Fix |
|---------|-----|
| `Docker: cannot find file specified` | Docker Desktop is not running. Start it from Start menu. |
| `python3: not found` | Rebuild: `docker-compose build --no-cache && docker-compose up -d` |
| Play Store returns 0 reviews | `docker exec n8n pip3 install --upgrade google-play-scraper` |
| Twitter returns 0 tweets | Add Twitter credentials to `config.env` or wait 1 hour for rate limit reset |
| Dashboard shows "No data" | Run `aggregate.py` and `llm_analyzer.py` manually |
| n8n at localhost:5678 unreachable | `docker-compose up -d` to start the container |
| Port 5678 already in use | Change `"5678:5678"` to `"5679:5678"` in `docker-compose.yml` |

For detailed troubleshooting, see [DOCUMENTATION.md](./DOCUMENTATION.md).

---

## Documentation

See **[DOCUMENTATION.md](./DOCUMENTATION.md)** for:
- Deep-dive on scraping efficiency and noise filtering
- LLM fallback chain and incremental caching
- Dashboard filter and chart reference
- Full troubleshooting guide
