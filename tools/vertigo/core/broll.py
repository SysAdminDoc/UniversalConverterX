"""B-roll auto-insertion — transcript → keywords → stock clips.

End-to-end pipeline assembled from three small pieces:

  1. **Keyword extraction** from transcript segments. Uses KeyBERT if
     installed, otherwise a noun-phrase fallback that leans only on
     stdlib ``re`` — so the module is usable without any new deps.
  2. **Stock search** against Pexels (requires free API key). A thin
     wrapper on ``pypexels`` if present, direct ``requests`` HTTP
     otherwise.
  3. **CLIP re-ranking** of candidate clips against the query keyword
     via ``open_clip_torch``. Falls back to Pexels' native ranking
     when CLIP isn't installed.

Everything is optional and each step has a clean failure mode. The
output is a list of ``BRollInsert`` records the encode pipeline can
overlay using FFmpeg ``concat`` or ``overlay`` — the rendering side
lives in ``core.encode``; this module only *plans*.

API-key handling: we never commit keys. Callers pass ``pexels_api_key=``
explicitly, or set ``PEXELS_API_KEY`` in the environment.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_MAX_INSERTS = 3
DEFAULT_INSERT_DURATION_SEC = 3.0
DEFAULT_PEXELS_TIMEOUT = 8.0


@dataclass(frozen=True)
class KeywordHit:
    """A keyword extracted from a transcript segment."""
    t: float        # segment start, seconds
    keyword: str
    score: float    # 0..1, extractor-specific


@dataclass(frozen=True)
class StockCandidate:
    """A single Pexels video candidate returned from search."""
    url: str        # HLS or direct MP4 URL for download
    preview_url: str
    duration_sec: float
    width: int
    height: int
    keyword: str
    native_score: float  # Pexels' internal relevance ranking

    @property
    def is_landscape(self) -> bool:
        return self.width >= self.height


@dataclass(frozen=True)
class BRollInsert:
    """A planned b-roll overlay/cut-away."""
    start: float       # insert start, seconds (main timeline)
    duration: float    # insert duration, seconds
    keyword: str
    source_url: str    # downloadable MP4 URL
    mode: str = "overlay"  # "overlay" (PiP over main) or "replace"
    score: float = 0.0


# ---------------------------------------------------------------- keywords

def is_keybert_available() -> bool:
    try:
        import keybert  # noqa: F401
        return True
    except ImportError:
        return False


def extract_keywords(
    segments: Iterable,    # iterable of core.subtitles.Caption
    *,
    max_per_segment: int = 1,
    min_segment_gap_sec: float = 5.0,
) -> list[KeywordHit]:
    """Return keyword hits ordered by timeline.

    Every ``min_segment_gap_sec`` we pick the top keyword from the
    surrounding transcript. KeyBERT powers the scoring when available;
    otherwise a cheap TF-IDF-style noun-phrase scorer falls out of
    ``_keywords_fallback``.
    """
    seg_list = list(segments)
    if not seg_list:
        return []

    # Pre-extract keywords per segment
    if is_keybert_available():
        extractor = _keybert_extractor()
    else:
        extractor = _keywords_fallback

    hits: list[KeywordHit] = []
    last_emit = -min_segment_gap_sec
    for cap in seg_list:
        text = getattr(cap, "text", "") or ""
        if not text.strip():
            continue
        start = float(getattr(cap, "start", 0.0))
        if start - last_emit < min_segment_gap_sec:
            continue
        candidates = extractor(text, top_n=max_per_segment)
        if not candidates:
            continue
        for kw, score in candidates:
            hits.append(KeywordHit(t=start, keyword=kw, score=float(score)))
        last_emit = start
    return hits


def _keybert_extractor():
    from keybert import KeyBERT
    model = KeyBERT()

    def _run(text: str, top_n: int) -> list[tuple[str, float]]:
        raw = model.extract_keywords(
            text,
            keyphrase_ngram_range=(1, 2),
            stop_words="english",
            top_n=top_n,
        )
        return [(kw, float(sc)) for kw, sc in raw]

    return _run


def _keywords_fallback(text: str, top_n: int = 1) -> list[tuple[str, float]]:
    """Dependency-free noun-phrase picker.

    Counts capitalised words and longest content words in the passage.
    Not as good as KeyBERT, but good enough to drive demo b-roll for
    free.
    """
    # Strip obvious filler
    lowered = text.lower()
    tokens = re.findall(r"[a-zA-Z][a-zA-Z\-']{2,}", lowered)
    stop = _STOPWORDS
    counts: dict[str, int] = {}
    for tok in tokens:
        if tok in stop:
            continue
        counts[tok] = counts.get(tok, 0) + 1
    if not counts:
        return []
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    total = sum(counts.values()) or 1
    return [(tok, cnt / total) for tok, cnt in ranked[: max(1, top_n)]]


_STOPWORDS = {
    "the", "and", "that", "this", "with", "from", "have", "has", "had",
    "you", "your", "will", "would", "could", "should", "about", "into",
    "they", "them", "their", "there", "here", "then", "than", "just",
    "what", "when", "where", "which", "while", "been", "more", "most",
    "some", "many", "much", "also", "over", "under", "other", "every",
    "because", "through", "really", "very", "well", "like", "know",
    "going", "get", "got", "right", "one", "two", "three", "make", "made",
    "take", "taken", "come", "came", "say", "said", "see", "saw", "think",
    "thought", "now", "then", "how", "why", "who", "want", "wants",
}


# ---------------------------------------------------------------- pexels search

def search_pexels(
    keyword: str,
    *,
    api_key: str | None = None,
    per_page: int = 5,
    timeout: float = DEFAULT_PEXELS_TIMEOUT,
) -> list[StockCandidate]:
    """Search Pexels video for ``keyword`` and return up to ``per_page``
    candidates.

    Prefers the ``pypexels`` package when installed; otherwise uses a
    plain ``urllib`` request. Never raises on network error — returns
    an empty list so the caller can fall back to no-b-roll gracefully.
    """
    key = api_key or os.environ.get("PEXELS_API_KEY", "").strip()
    if not key or not keyword.strip():
        return []

    try:
        return _search_pexels_http(keyword, key, per_page, timeout)
    except Exception:
        return []


def _search_pexels_http(
    keyword: str, api_key: str, per_page: int, timeout: float
) -> list[StockCandidate]:
    """Direct HTTP call — keeps the module importable without pypexels
    and sidesteps its archived-but-functional quirks."""
    import json
    import urllib.parse
    import urllib.request

    url = (
        "https://api.pexels.com/videos/search?"
        + urllib.parse.urlencode({"query": keyword, "per_page": max(1, per_page)})
    )
    req = urllib.request.Request(url, headers={"Authorization": api_key})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    out: list[StockCandidate] = []
    for idx, video in enumerate(data.get("videos") or []):
        best = _best_video_file(video.get("video_files") or [])
        if best is None:
            continue
        out.append(
            StockCandidate(
                url=best.get("link", ""),
                preview_url=video.get("image", ""),
                duration_sec=float(video.get("duration") or 0.0),
                width=int(best.get("width") or video.get("width") or 0),
                height=int(best.get("height") or video.get("height") or 0),
                keyword=keyword,
                # Pexels doesn't publish a score, so rank by order and
                # normalise into 0..1.
                native_score=max(0.0, 1.0 - (idx / max(1, per_page))),
            )
        )
    return out


def _best_video_file(files: list[dict]) -> dict | None:
    """Pick the smallest HD file so downloads stay snappy."""
    if not files:
        return None
    # Prefer mp4 @ <= 1280 width, then any mp4, then first file.
    candidates = [f for f in files if (f.get("file_type") or "").endswith("mp4")]
    candidates.sort(key=lambda f: (f.get("width") or 0))
    for f in candidates:
        if (f.get("width") or 0) >= 854:
            return f
    return candidates[0] if candidates else files[0]


# ---------------------------------------------------------------- CLIP rank

def is_clip_available() -> bool:
    try:
        import open_clip  # noqa: F401
        return True
    except ImportError:
        return False


def rank_candidates(
    keyword: str,
    candidates: list[StockCandidate],
    *,
    top_k: int = 1,
) -> list[StockCandidate]:
    """Re-rank candidates by CLIP text↔frame similarity when available.

    When ``open_clip`` isn't installed or no candidate has a thumbnail,
    we just return the top-``k`` by Pexels' native relevance ranking.
    """
    if not candidates:
        return []
    if not is_clip_available():
        return sorted(candidates, key=lambda c: -c.native_score)[: max(1, top_k)]

    try:
        return _rank_with_clip(keyword, candidates, top_k)
    except Exception:
        return sorted(candidates, key=lambda c: -c.native_score)[: max(1, top_k)]


def _rank_with_clip(
    keyword: str, candidates: list[StockCandidate], top_k: int
) -> list[StockCandidate]:
    import io
    import urllib.request
    import open_clip
    import torch
    from PIL import Image

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k"
    )
    tokenizer = open_clip.get_tokenizer("ViT-B-32")

    text_features = None
    scores: list[tuple[float, StockCandidate]] = []
    for cand in candidates:
        if not cand.preview_url:
            scores.append((cand.native_score, cand))
            continue
        try:
            with urllib.request.urlopen(cand.preview_url, timeout=DEFAULT_PEXELS_TIMEOUT) as resp:
                img = Image.open(io.BytesIO(resp.read())).convert("RGB")
        except Exception:
            scores.append((cand.native_score, cand))
            continue

        image = preprocess(img).unsqueeze(0)
        with torch.no_grad():
            img_feat = model.encode_image(image)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            if text_features is None:
                tokens = tokenizer([keyword])
                text_features = model.encode_text(tokens)
                text_features = text_features / text_features.norm(dim=-1, keepdim=True)
            sim = float((img_feat @ text_features.T).squeeze().item())
        # Blend CLIP similarity with Pexels' native ranking so a weak
        # CLIP signal doesn't override a clear thematic match.
        scores.append((0.7 * sim + 0.3 * cand.native_score, cand))

    scores.sort(key=lambda s: -s[0])
    return [c for _s, c in scores[: max(1, top_k)]]


# ---------------------------------------------------------------- planner

def plan_broll_inserts(
    captions: Iterable,         # core.subtitles.Caption list
    *,
    clip_duration_sec: float,
    pexels_api_key: str | None = None,
    max_inserts: int = DEFAULT_MAX_INSERTS,
    insert_duration_sec: float = DEFAULT_INSERT_DURATION_SEC,
) -> list[BRollInsert]:
    """End-to-end planner: transcript → inserts.

    Returns at most ``max_inserts`` b-roll placements. Each placement
    starts at a keyword hit in the transcript and lasts
    ``insert_duration_sec`` seconds (or the remaining clip time,
    whichever is smaller).

    An empty list is a valid answer — happens when there's no API key,
    no keywords, no network, or no candidates survive ranking. The
    caller should treat b-roll as an enhancement, not a requirement.
    """
    hits = extract_keywords(captions)
    if not hits or clip_duration_sec <= 0:
        return []

    # Dedupe by keyword, keep the earliest hit for each.
    seen: dict[str, KeywordHit] = {}
    for h in hits:
        if h.keyword not in seen:
            seen[h.keyword] = h
    ordered = sorted(seen.values(), key=lambda h: h.t)

    inserts: list[BRollInsert] = []
    for hit in ordered:
        if len(inserts) >= max_inserts:
            break
        candidates = search_pexels(hit.keyword, api_key=pexels_api_key)
        best = rank_candidates(hit.keyword, candidates, top_k=1)
        if not best:
            continue
        pick = best[0]
        dur = min(
            insert_duration_sec,
            max(1.0, pick.duration_sec or insert_duration_sec),
            max(0.0, clip_duration_sec - hit.t),
        )
        if dur <= 0.5:
            continue
        inserts.append(
            BRollInsert(
                start=hit.t,
                duration=dur,
                keyword=hit.keyword,
                source_url=pick.url,
                score=pick.native_score,
            )
        )
    return inserts


# ---------------------------------------------------------------- helpers

def ensure_pypexels_installed() -> bool:
    if _pypexels_available():
        return True
    from ._lazy import pip_install
    if not pip_install("pypexels>=1.0.2"):
        return False
    return _pypexels_available()


def _pypexels_available() -> bool:
    try:
        import pypexels  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_keybert_installed() -> bool:
    if is_keybert_available():
        return True
    from ._lazy import pip_install
    if not pip_install("keybert>=0.8"):
        return False
    return is_keybert_available()


def ensure_open_clip_installed() -> bool:
    if is_clip_available():
        return True
    from ._lazy import pip_install
    if not pip_install("open_clip_torch>=2.26"):
        return False
    return is_clip_available()
