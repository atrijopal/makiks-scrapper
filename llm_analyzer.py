"""
LLM Analyzer — enriches every mention record using Ollama (local) or Gemini (cloud).

Supported backends (auto-detected in priority order):
  1. Ollama  — runs locally at http://localhost:11434 (no API key needed)
               Recommended model: llama3.2:3b (fits on RTX 4050 6GB VRAM)
  2. Gemini  — cloud fallback if Ollama is not running (needs GEMINI_API_KEY)

Tasks performed per record:
  1. RELEVANCE GATE    — 0-10 score: is this actually about the Matiks app?
                         Posts scoring < 7 are marked irrelevant and hidden in dashboard.
  2. TOPIC CLASSIFY    — bug_report | feature_request | praise |
                         question | competitor_comparison | general | irrelevant
  3. NUANCED SENTIMENT — very_negative | negative | mixed | positive | very_positive
  4. KEY PHRASES       — top 3 meaningful phrases from the post
  5. CRITICAL ALERT    — true if topic=bug_report AND sentiment=very_negative

Output: data/mentions_enriched.json
        data/critical_alerts.json
        data/word_cloud.json
        data/weekly_digest.txt (Sundays only)
"""
import json
import os
import re
import time
import datetime
import urllib.request
import urllib.error
from typing import List, Dict, Optional

# ── Config ────────────────────────────────────────────────────────────────────
CONFIG_FILE     = "/data/config.env"
INPUT_FILE      = "/data/data/mentions.json"
OUTPUT_FILE     = "/data/data/mentions_enriched.json"
ALERTS_FILE     = "/data/data/critical_alerts.json"
DIGEST_FILE     = "/data/data/weekly_digest.txt"
WORD_CLOUD_FILE = "/data/data/word_cloud.json"
CHECKPOINT_FILE = "/data/data/.enrichment_checkpoint.json"   # NEW: progress saver

# Ollama settings (local LLM — preferred, no rate limits)
OLLAMA_URL   = "http://host.docker.internal:11434"   # from inside Docker
OLLAMA_MODEL = "llama3.2:3b"                          # fits on RTX 4050 6GB

# Gemini fallback settings
GEMINI_MODEL = "gemini-2.0-flash-lite"

BATCH_SIZE    = 5      # smaller batches = fewer tokens lost on failure
RATE_LIMIT_S  = 0.5   # Ollama runs locally, no need to wait long
MAX_TEXT_LEN  = 400
RELEVANCE_MIN = 7      # posts scoring below this → marked irrelevant

OLLAMA_RETRIES = 3     # retry attempts for Ollama network errors
OLLAMA_TIMEOUT = 180   # seconds — generous for slow models

VALID_TOPICS = {
    "bug_report", "feature_request", "praise",
    "question", "competitor_comparison", "general", "irrelevant",
}
VALID_SENTIMENTS = {
    "very_negative", "negative", "mixed", "positive", "very_positive",
}


# ── Credential loader ─────────────────────────────────────────────────────────

def load_config() -> Dict[str, str]:
    config: Dict[str, str] = {}
    if not os.path.exists(CONFIG_FILE):
        return config
    with open(CONFIG_FILE) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                config[k.strip()] = v.strip()
    return config


# ── LLM backends ─────────────────────────────────────────────────────────────

def check_ollama() -> bool:
    """Return True if Ollama is reachable AND the required model is available."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8"))
            # Verify the specific model is pulled
            models = [m.get("name", "") for m in data.get("models", [])]
            model_base = OLLAMA_MODEL.split(":")[0]
            available = any(
                m == OLLAMA_MODEL or m.startswith(model_base + ":")
                for m in models
            )
            if not available:
                print(
                    f"[LLM] Ollama running but model '{OLLAMA_MODEL}' not found.\n"
                    f"      Available: {models}\n"
                    f"      Run: ollama pull {OLLAMA_MODEL}"
                )
            return available
    except Exception:
        return False


def call_ollama(prompt: str) -> str:
    """Call local Ollama with retries on transient errors."""
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 1024},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_exc: Optional[Exception] = None
    for attempt in range(1, OLLAMA_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["response"]
        except Exception as exc:
            last_exc = exc
            wait = 5 * attempt
            print(f"\n  [Ollama] Attempt {attempt}/{OLLAMA_RETRIES} failed: {exc}. Retrying in {wait}s...", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Ollama: all {OLLAMA_RETRIES} attempts failed — last error: {last_exc}")


def call_gemini(api_key: str, prompt: str) -> str:
    """POST to Gemini generateContent endpoint, return text response."""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={api_key}"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="ignore")
            if e.code == 429 and attempt < 3:
                wait = 60 * (attempt + 1)
                print(f"\n  [rate-limit] 429 — waiting {wait}s before retry {attempt+1}/3...", flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f"Gemini HTTP {e.code}: {str(body_text)[:300]}")
    raise RuntimeError("Gemini: max retries exceeded")


def call_llm(prompt: str, api_key: Optional[str], use_ollama: bool) -> str:
    """
    Unified dispatcher with automatic fallback:
      Ollama → try Ollama; if it raises, fall back to Gemini if key is set.
      Gemini-only → call Gemini directly.
    """
    if use_ollama:
        try:
            return call_ollama(prompt)
        except Exception as ollama_err:
            if api_key:
                print(f"\n  [LLM] Ollama failed ({ollama_err}). Falling back to Gemini...", flush=True)
                return call_gemini(api_key, prompt)
            raise
    if api_key:
        return call_gemini(api_key, prompt)
    raise RuntimeError("No LLM backend available (Ollama down, no Gemini key)")


# ── Prompt builders ───────────────────────────────────────────────────────────

def build_batch_prompt(batch: List[Dict]) -> str:
    items = []
    for i, r in enumerate(batch):
        text = (r.get("title", "") + " " + r.get("text", "")).strip()
        text = text[:MAX_TEXT_LEN]
        platform = r.get("platform", "unknown")
        items.append(f'{i+1}. [platform={platform}] """{text}"""')

    records_block = "\n".join(items)

    return f"""You are a brand relevance classifier for "Matiks" — an IIT Guwahati startup's math puzzle mobile game.

CORE CONTEXT:
1. Matiks is a math/brain training app with puzzles, streaks, and levels.
2. Founded by IIT Guwahati alumni.
3. IGNORE EVERYTHING ELSE: "Matiks" in Tagalog/Filipino means "automatic" (cars, bikes, transmission).
4. DELETE ANY POST about Rap Battles, atheism, Philippines politics, or motorcycles. These are 0% relevant.

RELEVANCE SCORING (0-10):
- 10: Explicitly about the math app, puzzles, IIT, or app store feedback.
- 7-9: Mentions "Matiks" app in a general gaming or productivity context.
- 3-6: Ambiguous mentions.
- 0-2: Definitely motorcycles, cars, Tagalog slang, rap battles, or atheist posts.

For each numbered post, return a JSON array of {len(batch)} objects:
- "relevance": integer 0-10
- "topic": bug_report | feature_request | praise | question | competitor_comparison | general | irrelevant
  (If relevance < 7, topic MUST be "irrelevant")
- "llm_sentiment": very_negative | negative | mixed | positive | very_positive
- "key_phrases": array of 3 meaningful phrases
- "is_critical": true ONLY if topic=bug_report AND llm_sentiment=very_negative

Return ONLY the raw JSON array, no explanation, no markdown fences.

Posts:
{records_block}
"""


def build_digest_prompt(records: List[Dict], since_date: str) -> str:
    sample_negatives = [r for r in records if r.get("llm_sentiment") in ("very_negative", "negative")][:10]
    sample_positives = [r for r in records if r.get("llm_sentiment") in ("very_positive", "positive")][:10]
    sample_bugs      = [r for r in records if r.get("topic") == "bug_report"][:5]
    sample_features  = [r for r in records if r.get("topic") == "feature_request"][:5]

    def fmt(lst):
        return "\n".join(f"- {(r.get('title') or r.get('text',''))[:120]}" for r in lst) or "None"

    platform_counts: Dict[str, int] = {}
    for r in records:
        p = r.get("platform", "unknown")
        platform_counts[p] = platform_counts.get(p, 0) + 1

    return f"""You are writing a weekly monitoring digest for "Matiks" — a math puzzle mobile app.

Data from {since_date} to today:
- Total mentions: {len(records)}
- By platform: {platform_counts}
- Critical bugs flagged: {sum(1 for r in records if r.get('is_critical'))}

Top negative mentions:
{fmt(sample_negatives)}

Top positive mentions:
{fmt(sample_positives)}

Bug reports:
{fmt(sample_bugs)}

Feature requests:
{fmt(sample_features)}

Write a concise weekly digest (max 300 words) for the Matiks team covering:
1. Executive summary (2 sentences)
2. Top issues to fix this week
3. What users love (keep doing this)
4. Feature requests to consider
5. One recommendation

Write in plain text, no markdown, professional tone.
"""


# ── Result parser ─────────────────────────────────────────────────────────────

def parse_batch_response(response_text: str, batch_size: int) -> List[Dict]:
    """
    Extract JSON array from LLM response.
    Handles: markdown fences, leading prose, truncated arrays (partial recovery).
    """
    text = response_text.strip()

    # Strip markdown code fences
    text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```$", "", text, flags=re.MULTILINE)
    text = text.strip()

    # 1. Try direct parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # 2. Find the JSON array bounds and parse
    start = text.find("[")
    end   = text.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    # 3. Partial recovery: extract complete {...} objects one by one
    recovered = []
    for m in re.finditer(r'\{[^{}]+\}', text, re.DOTALL):
        try:
            obj = json.loads(m.group())
            recovered.append(obj)
        except json.JSONDecodeError:
            continue
    if recovered:
        print(f"  [LLM] Partial parse: recovered {len(recovered)}/{batch_size} objects from malformed response")
        # Pad with empty dicts for missing records
        recovered.extend([{}] * (batch_size - len(recovered)))
        return recovered[:batch_size]

    # 4. Complete fallback
    print(f"  [LLM] Warning: could not parse response at all — using defaults for {batch_size} records")
    return [{}] * batch_size


def safe_enrich(record: Dict, llm_data: Dict) -> Dict:
    """Merge LLM output into record, sanitising all values defensively."""
    # Relevance — guard against None / non-numeric
    raw_rel = llm_data.get("relevance", 5)
    try:
        record["relevance"] = max(0, min(10, int(float(raw_rel))))
    except (TypeError, ValueError):
        record["relevance"] = 5

    topic = str(llm_data.get("topic", "general")).strip().lower()
    record["topic"] = topic if topic in VALID_TOPICS else "general"

    # Auto-enforce: low relevance → irrelevant
    if record["relevance"] < RELEVANCE_MIN:
        record["topic"] = "irrelevant"

    sentiment = str(llm_data.get("llm_sentiment", "mixed")).strip().lower()
    record["llm_sentiment"] = sentiment if sentiment in VALID_SENTIMENTS else "mixed"

    kp = llm_data.get("key_phrases", [])
    record["key_phrases"] = [str(p) for p in kp[:3]] if isinstance(kp, list) else []

    # Re-derive is_critical from actual values (don't blindly trust LLM)
    record["is_critical"] = (
        record["topic"] == "bug_report"
        and record["llm_sentiment"] == "very_negative"
    )
    return record


# ── Checkpointing ─────────────────────────────────────────────────────────────

def load_checkpoint() -> Dict[str, Dict]:
    """Load partially-enriched records from a previous interrupted run."""
    if not os.path.exists(CHECKPOINT_FILE):
        return {}
    try:
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_checkpoint(enriched_by_id: Dict[str, Dict]) -> None:
    """Persist enriched records to checkpoint after every batch."""
    try:
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(enriched_by_id, f, ensure_ascii=False)
    except Exception as e:
        print(f"  [LLM] Checkpoint save failed: {e}")


def clear_checkpoint() -> None:
    try:
        os.remove(CHECKPOINT_FILE)
    except FileNotFoundError:
        pass


# ── Main enrichment pipeline ──────────────────────────────────────────────────

def enrich_records(
    records: List[Dict],
    api_key: Optional[str],
    use_ollama: bool,
) -> List[Dict]:
    """
    Process all records in batches of BATCH_SIZE.
    - Skips already-enriched records (non-empty key_phrases).
    - Resumes from checkpoint if a previous run was interrupted.
    - Saves checkpoint after every batch for crash-safety.
    """
    # Separate what still needs enriching
    to_enrich    = [r for r in records if not r.get("key_phrases")]
    already_done = [r for r in records if r.get("key_phrases")]
    print(f"[LLM] Records to enrich: {len(to_enrich)} | Already done: {len(already_done)}")

    # Resume from checkpoint
    checkpoint = load_checkpoint()
    if checkpoint:
        print(f"[LLM] Resuming from checkpoint: {len(checkpoint)} records already processed this run")

    enriched_by_id: Dict[str, Dict] = dict(checkpoint)  # id → enriched record
    still_to_do = [r for r in to_enrich if r.get("id") not in enriched_by_id]
    print(f"[LLM] Actually sending to LLM: {len(still_to_do)} records")

    total_batches = (len(still_to_do) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num in range(total_batches):
        batch = still_to_do[batch_num * BATCH_SIZE : (batch_num + 1) * BATCH_SIZE]
        print(f"  Batch {batch_num + 1}/{total_batches} ({len(batch)} records)...", end=" ", flush=True)

        prompt = build_batch_prompt(batch)
        try:
            response = call_llm(prompt, api_key, use_ollama)
            results  = parse_batch_response(response, len(batch))

            for i, record in enumerate(batch):
                llm_data = results[i] if i < len(results) else {}
                enriched = safe_enrich(dict(record), llm_data)
                enriched_by_id[record.get("id", "")] = enriched

            print("✓")
        except Exception as e:
            print(f"✗ ({e})")
            # Keep defaults for failed records so pipeline continues
            for record in batch:
                enriched_by_id[record.get("id", "")] = safe_enrich(dict(record), {})

        # Checkpoint after every batch — crash-safe
        save_checkpoint(enriched_by_id)

        if batch_num < total_batches - 1:
            time.sleep(RATE_LIMIT_S)

    # Merge: checkpoint enrichments + already_done (preserve original order from caller)
    result = []
    for r in records:
        rid = r.get("id", "")
        if rid in enriched_by_id:
            result.append(enriched_by_id[rid])
        else:
            result.append(r)

    clear_checkpoint()
    return result


# ── Weekly digest ─────────────────────────────────────────────────────────────

def generate_digest(
    records: List[Dict],
    api_key: Optional[str],
    use_ollama: bool = False,
    force: bool = False,
) -> None:
    """Generate and save weekly digest. Only runs on Sundays unless force=True."""
    today = datetime.datetime.utcnow()
    if not force and today.weekday() != 6:
        print("[LLM] Digest: skipping (not Sunday). Run with --digest to force.")
        return

    since = (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    week_records = [
        r for r in records
        if (r.get("created_utc") or r.get("created_at") or "") >= since
    ]

    print(f"[LLM] Generating weekly digest for {len(week_records)} records since {since}...")
    prompt = build_digest_prompt(week_records, since)
    try:
        digest_text = call_llm(prompt, api_key, use_ollama)
        with open(DIGEST_FILE, "w", encoding="utf-8") as f:
            f.write(f"=== Matiks Weekly Digest — {today.strftime('%Y-%m-%d')} ===\n\n")
            f.write(digest_text)
        print(f"[LLM] Digest saved → {DIGEST_FILE}")
    except Exception as e:
        print(f"[LLM] Digest generation failed: {e}")


# ── Entry point ───────────────────────────────────────────────────────────────

def analyze():
    import sys
    force_digest = "--digest" in sys.argv

    config  = load_config()
    api_key = config.get("GEMINI_API_KEY", "")
    if not api_key or api_key == "your_gemini_api_key_here":
        api_key = None

    # Detect which LLM backend to use
    use_ollama = check_ollama()
    if use_ollama:
        print(f"[LLM] Backend: Ollama ({OLLAMA_URL}) model={OLLAMA_MODEL} ✓")
    elif api_key:
        print(f"[LLM] Backend: Gemini ({GEMINI_MODEL}) — Ollama not reachable")
    else:
        print("[LLM] No LLM backend available — BM25/search scores only")
        print("      Start Ollama, or add GEMINI_API_KEY to config.env")

    # Load raw mentions
    if not os.path.exists(INPUT_FILE):
        print(f"[LLM] {INPUT_FILE} not found — run aggregate.py first")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = data.get("records", [])
    meta    = data.get("meta", {})
    print(f"[LLM] Loaded {len(records)} records from mentions.json")

    # ── Load previously enriched records as a cache (by ID) ──────────────────
    enriched_cache: Dict[str, Dict] = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                prev = json.load(f)
            for r in prev.get("records", []):
                if r.get("id") and r.get("topic") and r.get("key_phrases"):
                    enriched_cache[r["id"]] = r
            print(f"[LLM] Cache: {len(enriched_cache)} previously enriched records")
        except Exception as e:
            print(f"[LLM] Could not load cache: {e}")

    # ── Merge: use cached version where available, flag new ones ─────────────
    merged   = []
    new_recs = []

    for r in records:
        rid = r.get("id", "")
        if rid in enriched_cache:
            merged.append(enriched_cache[rid])
        else:
            merged.append(r)
            new_recs.append(r)

    print(f"[LLM] New records needing enrichment: {len(new_recs)}")

    # ── Step 1: Search engine enrichment (only on new records) ───────────────
    from search_engine import enrich_with_search_scores, get_word_cloud_data
    print("[Search] Running BM25 + TF-IDF + fuzzy on new records...")
    if new_recs:
        new_recs = enrich_with_search_scores(new_recs)
        new_by_id = {r["id"]: r for r in new_recs}
        merged = [new_by_id.get(r.get("id"), r) for r in merged]

    word_cloud = get_word_cloud_data(merged)
    with open(WORD_CLOUD_FILE, "w", encoding="utf-8") as f:
        json.dump(word_cloud, f, ensure_ascii=False, indent=2)
    print(f"[Search] Word cloud saved ({len(word_cloud)} terms)")

    # ── Step 2: LLM enrichment (only new records) ────────────────────────────
    if (use_ollama or api_key) and new_recs:
        enriched_new = enrich_records(new_recs, api_key, use_ollama)
        enriched_by_id = {r.get("id"): r for r in enriched_new}
        merged = [enriched_by_id.get(r.get("id"), r) for r in merged]
    elif (use_ollama or api_key) and not new_recs:
        print("[LLM] All records already enriched — nothing to do.")

    # ── Step 3: Critical alerts ───────────────────────────────────────────────
    alerts = [r for r in merged if r.get("is_critical")]
    with open(ALERTS_FILE, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)
    print(f"[LLM] Critical alerts: {len(alerts)}")

    if force_digest or datetime.datetime.utcnow().weekday() == 6:
        generate_digest(merged, api_key, use_ollama, force=force_digest)

    # ── Step 4: Update meta ───────────────────────────────────────────────────
    backend_used = "ollama" if use_ollama else ("gemini" if api_key else "none")
    meta["llm_backend"]     = backend_used
    meta["llm_enriched"]    = backend_used != "none"
    meta["search_enriched"] = True
    meta["last_analyzed"]   = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["new_this_run"]    = len(new_recs)

    # Topic/critical counts — always computed (not just when api_key present)
    meta["by_topic"]       = {}
    meta["critical_count"] = 0
    for r in merged:
        t = r.get("topic", "general")
        meta["by_topic"][t] = meta["by_topic"].get(t, 0) + 1
        if r.get("is_critical"):
            meta["critical_count"] += 1

    # ── Step 5: Sort and write ────────────────────────────────────────────────
    merged.sort(
        key=lambda r: (r.get("created_utc") or r.get("created_at") or ""),
        reverse=True,
    )

    output = {"meta": meta, "records": merged}
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Update data.js for dashboard
    js_file = "/data/data/data.js"
    with open(js_file, "w", encoding="utf-8") as f:
        f.write("// Auto-generated by llm_analyzer.py\n")
        f.write("window.MATIKS_DATA = ")
        json.dump(output, f, ensure_ascii=False)
        f.write(";\n")

    print(f"\n[LLM Analyzer] Done.")
    print(f"  Total: {len(merged)} | New this run: {len(new_recs)} | Backend: {backend_used}")
    print(f"  Topics: {meta.get('by_topic', {})}")
    print(f"  Critical alerts: {meta.get('critical_count', 0)}")
    print(f"  Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    analyze()
