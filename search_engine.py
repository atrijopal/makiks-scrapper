"""
Search Engine — local BM25 + TF-IDF + fuzzy matching for Matiks mention analysis.

Algorithms:
  1. BM25          — relevance scores for each record vs Matiks reference query
  2. TF-IDF cosine — cross-platform near-duplicate detection
  3. Fuzzy match   — catches misspellings (Matics, Matick, Mattiks) in scrapers
  4. Co-occurrence — which words appear most with "matiks" (feeds word cloud)

No API needed — runs entirely offline.
"""
import json
import math
import re
import string
from collections import Counter, defaultdict
from typing import List, Dict, Tuple

# ── BM25 constants ─────────────────────────────────────────────────────────────
BM25_K1 = 1.5   # term saturation
BM25_B  = 0.75  # length normalisation

# Reference document: what we consider a relevant Matiks post
MATIKS_REFERENCE = (
    "matiks app math puzzle game ios android play store review "
    "education learning startup iit guwahati problem solving level "
    "multiplayer competitive leaderboard score rating bug crash feature"
)

# Fuzzy match targets — the scraper will expand queries to catch these
BRAND_VARIANTS = [
    "matiks", "matics", "matick", "mattiks", "maatiks",
    "matix", "mattics", "matks",
]

STOPWORDS = {
    "the", "a", "an", "is", "it", "in", "on", "at", "to", "for",
    "of", "and", "or", "but", "with", "this", "that", "are", "was",
    "be", "have", "has", "had", "not", "do", "does", "did", "will",
    "can", "i", "you", "he", "she", "we", "they", "my", "your",
    "its", "their", "so", "as", "by", "from", "up", "out", "if",
    "about", "than", "then", "just", "like", "more", "also",
}


# ── Tokeniser ──────────────────────────────────────────────────────────────────

def tokenise(text: str) -> List[str]:
    text = text.lower()
    # Replace punctuation with space to prevent "hello.world" -> "helloworld"
    text = text.translate(str.maketrans(string.punctuation, " " * len(string.punctuation)))
    return [w for w in text.split() if w and w not in STOPWORDS and len(w) > 1]


# ── BM25 ───────────────────────────────────────────────────────────────────────

class BM25:
    def __init__(self, corpus: List[List[str]]):
        self.n = len(corpus)
        self.avgdl = sum(len(d) for d in corpus) / max(self.n, 1)
        self.df: Dict[str, int] = defaultdict(int)
        self.corpus = corpus

        for doc in corpus:
            for term in set(doc):
                self.df[term] += 1

    def score(self, query_tokens: List[str], doc_tokens: List[str]) -> float:
        tf = Counter(doc_tokens)
        dl = len(doc_tokens)
        score = 0.0
        for term in query_tokens:
            if term not in self.df:
                continue
            idf = math.log((self.n - self.df[term] + 0.5) / (self.df[term] + 0.5) + 1)
            freq = tf[term]
            numerator = freq * (BM25_K1 + 1)
            denominator = freq + BM25_K1 * (1 - BM25_B + BM25_B * dl / self.avgdl)
            score += idf * (numerator / denominator)
        return round(score, 4)

    def score_all(self, query_tokens: List[str]) -> List[float]:
        return [self.score(query_tokens, doc) for doc in self.corpus]


# ── TF-IDF cosine similarity (for deduplication) ──────────────────────────────

def build_tfidf_vectors(docs: List[List[str]]) -> Tuple[List[Dict[str, float]], Dict[str, float]]:
    """Return (tfidf_vectors, idf_map)."""
    n = len(docs)
    df: Dict[str, int] = defaultdict(int)
    for doc in docs:
        for term in set(doc):
            df[term] += 1

    idf = {term: math.log((n + 1) / (count + 1)) for term, count in df.items()}

    vectors = []
    for doc in docs:
        tf = Counter(doc)
        dl = len(doc)
        vec = {term: (count / max(dl, 1)) * idf.get(term, 0) for term, count in tf.items()}
        vectors.append(vec)

    return vectors, idf


def cosine_sim(v1: Dict[str, float], v2: Dict[str, float]) -> float:
    common = set(v1) & set(v2)
    if not common:
        return 0.0
    dot = sum(v1[k] * v2[k] for k in common)
    mag1 = math.sqrt(sum(x ** 2 for x in v1.values()))
    mag2 = math.sqrt(sum(x ** 2 for x in v2.values()))
    return dot / (mag1 * mag2 + 1e-9)


def find_near_duplicates(records: List[dict], threshold: float = 0.85) -> List[str]:
    """Return list of record IDs that are near-duplicates of an earlier record."""
    texts = [get_text(r) for r in records]
    tokenised = [tokenise(t) for t in texts]
    vectors, _ = build_tfidf_vectors(tokenised)

    duplicates = set()
    for i in range(len(vectors)):
        if records[i]["id"] in duplicates:
            continue
        for j in range(i + 1, len(vectors)):
            if records[j]["id"] in duplicates:
                continue
            # Only deduplicate within the same platform (cross-platform reposts are ok)
            if records[i].get("platform") == records[j].get("platform"):
                sim = cosine_sim(vectors[i], vectors[j])
                if sim >= threshold:
                    duplicates.add(records[j]["id"])  # keep the earlier one
    return list(duplicates)


# ── Fuzzy matching ─────────────────────────────────────────────────────────────

def fuzzy_distance(a: str, b: str) -> int:
    """Basic Levenshtein distance (no external library needed)."""
    la, lb = len(a), len(b)
    dp = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        dp[i][0] = i
    for j in range(lb + 1):
        dp[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[i][j] = min(dp[i-1][j] + 1, dp[i][j-1] + 1, dp[i-1][j-1] + cost)
    return dp[la][lb]


def fuzzy_contains_brand(text: str, max_distance: int = 1) -> bool:
    """Return True if text contains a brand variant within max_distance edits."""
    words = re.findall(r'\b\w{4,}\b', text.lower())
    for word in words:
        for variant in BRAND_VARIANTS:
            if abs(len(word) - len(variant)) <= max_distance:
                if fuzzy_distance(word, variant) <= max_distance:
                    return True
    return False


# ── Co-occurrence analysis ─────────────────────────────────────────────────────

def compute_cooccurrence(records: List[dict], top_n: int = 50) -> List[Dict]:
    """
    Find the top_n words that co-occur with 'matiks' across all records.
    Used to generate the dashboard word cloud.
    """
    word_count: Dict[str, int] = defaultdict(int)

    for r in records:
        text = get_text(r).lower()
        if "matiks" not in text:
            continue
        tokens = tokenise(text)
        for token in tokens:
            if token != "matiks" and len(token) > 3:
                word_count[token] += 1

    sorted_words = sorted(word_count.items(), key=lambda x: -x[1])[:top_n]
    return [{"word": w, "count": c} for w, c in sorted_words]


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_text(record: dict) -> str:
    return " ".join(filter(None, [
        record.get("title", ""),
        record.get("text", ""),
    ]))


# ── Main entry point ───────────────────────────────────────────────────────────

def enrich_with_search_scores(records: List[dict]) -> List[dict]:
    """
    Adds to each record:
      - bm25_score        : float — relevance to Matiks reference query
      - is_near_duplicate : bool  — near-duplicate of an earlier record (same platform)
      - fuzzy_brand_match : bool  — contains a Matiks name variant (misspelling)

    Also returns co-occurrence data as a separate list (written to meta).
    """
    texts = [get_text(r) for r in records]
    tokenised = [tokenise(t) for t in texts]

    # BM25 scoring
    bm25 = BM25(tokenised)
    query_tokens = tokenise(MATIKS_REFERENCE)
    scores = bm25.score_all(query_tokens)

    # Near-duplicate detection
    duplicate_ids = set(find_near_duplicates(records))

    # Apply scores
    for i, record in enumerate(records):
        record["bm25_score"] = scores[i]
        record["is_near_duplicate"] = record["id"] in duplicate_ids
        record["fuzzy_brand_match"] = fuzzy_contains_brand(get_text(record))

    return records


def get_word_cloud_data(records: List[dict]) -> List[Dict]:
    return compute_cooccurrence(records)


if __name__ == "__main__":
    # Quick self-test
    import os
    data_file = "/data/data/mentions.json"
    if not os.path.exists(data_file):
        print("No mentions.json found — run aggregate.py first")
    else:
        with open(data_file) as f:
            data = json.load(f)
        records = data.get("records", [])
        enriched = enrich_with_search_scores(records)
        # Print top 10 by BM25
        top10 = sorted(enriched, key=lambda r: -r["bm25_score"])[:10]
        print("\n🔍 Top 10 most relevant posts (BM25):")
        for r in top10:
            print(f"  [{r['platform']:10}] score={r['bm25_score']:.2f}  {r.get('title', r.get('text',''))[:60]}")

        # Duplicates
        dups = [r for r in enriched if r["is_near_duplicate"]]
        print(f"\n🔁 Near-duplicates found: {len(dups)}")

        # Word cloud
        cloud = get_word_cloud_data(records)
        print(f"\n☁️  Top co-occurring words: {[w['word'] for w in cloud[:15]]}")
