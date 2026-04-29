"""T3b · Segment proposals via local TextTiling.

**Goal** — on import of a long clip (>10 min), surface a ranked list of
candidate 30-90 s segments the user can jump their trim handles into.
The original ROADMAP line pointed at the ClipsAI fork; that library is
MIT but its dep chain drags in WhisperX + torch, which we refuse on
charter grounds. This module achieves the same product outcome with the
already-cached faster-whisper word stream plus numpy.

Charter compliance:
    * No LLM step. Ranking is a deterministic weighted sum over local
      signals (?-count, laughter, silence gap, length fit). "Stop
      before the LLM step" is the explicit charter line.
    * No network. Everything runs on the in-memory caption stream.
    * No new heavy dep. Pure stdlib (math, re, dataclass) — the
      TextTiling sweep is fast enough without numpy vectorisation.

Algorithm
---------

1. **Token stream** — flatten the caption list into
   ``(t, lowercase_word)``. Stop-words stripped via a tiny embedded
   set; no NLTK dependency.

2. **TextTiling-style cohesion** — slide two adjacent K-token windows
   over the stream and compute Jaccard similarity between their
   content-word sets. Low-similarity "valleys" are topic boundaries.
   Boundary candidates are also promoted when a silence gap
   (``gap_seconds``) appears between successive captions. Stop-words
   stripped via small per-language frozensets unioned into
   ``_STOP_WORDS`` (en/es/fr/de/pt/it); no NLTK dependency.

3. **Segment assembly** — walk the boundary list greedily, collecting
   adjacent topics until the running duration enters the
   ``[min_sec, max_sec]`` window, then emit a :class:`SegmentProposal`.

4. **Score** — weighted sum of:

   * ``questions`` — how many question-mark chunks the segment carries
     (engagement signal baked into 2026 creator research).
   * ``laughter`` — matches any of {haha, hehe, lol, [laughter], *laughs*}.
   * ``silence_gap_edge`` — whether a long silence abuts either side
     (good cut point → higher fidelity).
   * ``length_fit`` — triangular preference around ``target_sec``.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_left
from dataclasses import dataclass, field

from .caption_types import Caption


# ---------------------------------------------------------------- tunables

DEFAULT_MIN_SEC = 30.0
DEFAULT_MAX_SEC = 90.0
DEFAULT_TARGET_SEC = 45.0
DEFAULT_TOP_N = 8
DEFAULT_MIN_CLIP_SEC_FOR_PROPOSALS = 600.0  # only propose on > 10 min clips

_WINDOW_TOKENS = 20         # TextTiling window size (content words)
_BOUNDARY_VALLEY_THRESHOLD = 0.35   # Jaccard <= this flags a topic boundary
_SILENCE_BOUNDARY_SEC = 2.5 # silence gap that promotes a boundary by itself

# A deliberately small stop-list. Keeping it inline means zero network /
# zero NLTK / zero polyglot dep, and the sets are stable across the
# locales that actually matter for short-form creators. Contractions like
# "'ll" / "'s" are intentionally omitted because the tokenizer strips
# surrounding apostrophes and filters len<=1, so those forms never reach
# the stop-check in the first place.
#
# Each language ships as its own frozenset so native speakers reviewing
# the list can spot-check one language at a time. `_STOP_WORDS` is the
# union used by the tokenizer; language leaks across sets are fine (the
# cost is a *slightly* smaller token stream, not a correctness hazard).
_STOP_WORDS_EN: frozenset[str] = frozenset(
    """
    a an and are as at be but by for from had has have he her him his how i
    in is it its just me my no not of on or our she so than that the their
    them there these they this to too us was we were what when where which
    who why will with would you your yours like do did does don doesn
    hey yeah ok okay oh uh um well right really
    """.split()
)
_STOP_WORDS_ES: frozenset[str] = frozenset(
    """
    a al algo algunos ante antes aunque como con contra cual de del desde donde
    durante el ella ellas ellos en entre era eran es esa ese eso esta este esto
    estaba estaban estar estos fue fueron ha habia hacia hay la las le les lo
    los mas me mi mis mucho muy nada ni no nos nosotros o otros para pero poco
    por porque que quien se ser si sin sobre solo son soy su sus tambien te
    tener tengo ti todo todos tu tus un una uno unos ya yo
    bueno vale eh este hola
    """.split()
)
_STOP_WORDS_FR: frozenset[str] = frozenset(
    """
    a au aux avec ce ces cet cette comme dans de des du elle elles en est et
    eu il ils j je la le les leur leurs lui mais me mes moi mon ne nos notre
    nous on ont ou par pas pour qu que qui sa sans se ses son sont sur ta te
    tes toi ton tous tout tu un une vos votre vous y plus fait etait bien
    alors donc voila ben ouais ouai euh
    """.split()
)
_STOP_WORDS_DE: frozenset[str] = frozenset(
    """
    aber als am an auch auf aus bei bin bis das dass dem den der des die doch
    ein eine einem einen einer eines er es fur hab habe haben hat hatte ich
    ihm ihn ihr im in ist ja kann mehr mein mich mir mit nach nicht nichts noch
    nur ob oder sein seine sich sie sind so um und uns unsere war waren was
    weil wenn wer werden wie wir wird wo zu zum zur
    naja halt also genau eben mal
    """.split()
)
_STOP_WORDS_PT: frozenset[str] = frozenset(
    """
    a ao aos as com como da das de dela delas dele deles do dos e ela elas
    ele eles em entre era eram es essa esse essas esses esta este estas estes
    eu foi foram ha isso isto la lhe lhes mais mas me meu meus minha minhas
    muito na nao nas no nos nossa nossas nosso nossos num numa o os ou para
    pela pelas pelo pelos por porque quando que quem se sem ser seu seus sim
    sobre sua suas ta tambem te tem tinha tu tua tuas um uma umas uns voce
    voces voce-s ai entao bom oi ne pois
    """.split()
)
_STOP_WORDS_IT: frozenset[str] = frozenset(
    """
    a al alla alle alli allo anche c che chi ci come con contro cui da dal
    dalla dalle dallo degli dei del della delle dello di dove e ed egli era
    essi fu ha hai ho il in io la le lei li lo loro ma me mi mia mio ne nei
    nel nella nelle nello noi non nostro o per piu piu' poi qualche quale
    quando quello questo sei si sia sono su sua sue sui sul sulla suo ti tra
    tu tua tuo un una uno voi vostro
    bene allora dai eh bho
    """.split()
)

_STOP_WORDS: frozenset[str] = (
    _STOP_WORDS_EN
    | _STOP_WORDS_ES
    | _STOP_WORDS_FR
    | _STOP_WORDS_DE
    | _STOP_WORDS_PT
    | _STOP_WORDS_IT
)

# Laughter / engagement token fingerprints.
_LAUGH_RE = re.compile(
    r"\b(haha+|hehe+|hihi+|lol|lmao|rofl|omg|wow+|yay+|woo+)\b|\[\s*laughter\s*\]|\*\s*laughs\s*\*",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(r"\?")
_WORD_RE = re.compile(r"[A-Za-z']+")


# ---------------------------------------------------------------- types


@dataclass(frozen=True)
class SegmentProposal:
    """A candidate 30-90 s jump-to-region with a human-readable hint."""

    start: float           # seconds in the source clip
    end: float
    title_hint: str        # first ~60 chars of the segment's transcript
    score: float           # 0..1
    questions: int
    laughter_hits: int
    silence_gap_before: float
    silence_gap_after: float
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


# ---------------------------------------------------------------- public api


def propose_segments(
    captions: list[Caption],
    *,
    min_sec: float = DEFAULT_MIN_SEC,
    max_sec: float = DEFAULT_MAX_SEC,
    target_sec: float = DEFAULT_TARGET_SEC,
    top_n: int = DEFAULT_TOP_N,
    cancel_cb=None,
) -> list[SegmentProposal]:
    """Return up to ``top_n`` ranked :class:`SegmentProposal` records.

    Empty caption lists and clips shorter than ``min_sec`` both return
    an empty list — callers should gate on clip duration before calling.

    ``cancel_cb`` is a zero-arg callable polled at the outer loop heads
    of the TextTiling sweep / assembly / scoring. When it returns truthy
    the function short-circuits and returns whatever proposals were
    already finalised (possibly the empty list). Wire from a
    ``QThread._cancel`` flag for responsive cancel on very long clips.
    """
    if not captions or target_sec <= 0 or min_sec <= 0 or max_sec <= min_sec:
        return []

    total_span = captions[-1].end - captions[0].start
    if total_span < min_sec:
        return []

    if cancel_cb and cancel_cb():
        return []

    tokens = _token_stream(captions)
    if len(tokens) < _WINDOW_TOKENS * 2:
        # Too short for TextTiling — treat the whole clip as a single segment.
        segs = [(captions[0].start, captions[-1].end)]
    else:
        boundaries = _boundaries(tokens, captions, cancel_cb=cancel_cb)
        if cancel_cb and cancel_cb():
            return []
        segs = _assemble_segments(
            boundaries,
            min_sec=min_sec,
            max_sec=max_sec,
            target_sec=target_sec,
            cancel_cb=cancel_cb,
        )

    # Precompute the sorted caption-start index once per call so the
    # straddling-pair gap lookups inside `_score_segment` drop from an
    # O(N) linear scan to an O(log N) bisect per candidate. Saves the
    # bulk of the scoring pass on hour-plus transcripts where segments
    # can reach into the hundreds.
    starts = [c.start for c in captions]
    proposals: list[SegmentProposal] = []
    for seg_start, seg_end in segs:
        if cancel_cb and cancel_cb():
            return []
        if seg_end - seg_start < min_sec:
            continue
        prop = _score_segment(
            seg_start, seg_end, captions, target_sec,
            cancel_cb=cancel_cb, starts=starts,
        )
        if prop is None:  # cancel fired mid-scoring
            return []
        # Drop pure-silence regions: a segment that covers a gap between
        # topic clusters and holds no transcribed content isn't a useful
        # jump-to candidate.
        if not prop.title_hint:
            continue
        proposals.append(prop)

    proposals.sort(key=lambda p: p.score, reverse=True)
    return proposals[:top_n]


def should_propose_for_duration(duration_sec: float) -> bool:
    """Gate: should the caller bother computing proposals at all?

    Surfaces the "only on clips > 10 min" ROADMAP charter in one place.
    """
    return duration_sec >= DEFAULT_MIN_CLIP_SEC_FOR_PROPOSALS


# ---------------------------------------------------------------- tokenisation


def _token_stream(captions: list[Caption]) -> list[tuple[float, str]]:
    """Flatten ``captions`` to ``(time, content_word)`` pairs.

    Uses per-word timings when available (karaoke preset), otherwise
    spreads words evenly across the caption span. Stop-words filtered.
    """
    tokens: list[tuple[float, str]] = []
    for cap in captions:
        text = cap.text or ""
        if cap.words:
            for w in cap.words:
                lower = w.text.lower()
                for m in _WORD_RE.finditer(lower):
                    tok = m.group(0).strip("'")
                    if tok and tok not in _STOP_WORDS and len(tok) > 1:
                        tokens.append((w.start, tok))
        else:
            matches = list(_WORD_RE.finditer(text.lower()))
            if not matches:
                continue
            span = max(1e-6, cap.end - cap.start)
            n = len(matches)
            for i, m in enumerate(matches):
                tok = m.group(0).strip("'")
                if tok and tok not in _STOP_WORDS and len(tok) > 1:
                    t = cap.start + (i / max(1, n - 1)) * span if n > 1 else cap.start
                    tokens.append((t, tok))
    return tokens


# ---------------------------------------------------------------- boundaries


def _boundaries(
    tokens: list[tuple[float, str]],
    captions: list[Caption],
    *,
    cancel_cb=None,
) -> list[float]:
    """TextTiling-style boundary timestamps, augmented with silence gaps."""
    out: set[float] = {captions[0].start, captions[-1].end}

    # 1) topic-shift valleys via Jaccard between adjacent windows
    K = _WINDOW_TOKENS
    for i in range(K, len(tokens) - K):
        # Poll at a coarse interval; boundary search is usually fast but
        # can take tens of ms on hour-long transcripts.
        if cancel_cb and (i & 0xff) == 0 and cancel_cb():
            return sorted(out)
        left = {t for _, t in tokens[i - K:i]}
        right = {t for _, t in tokens[i:i + K]}
        if not left or not right:
            continue
        sim = len(left & right) / len(left | right)
        if sim <= _BOUNDARY_VALLEY_THRESHOLD:
            out.add(tokens[i][0])

    # 2) silence-gap boundaries (more reliable than pure lexical signal)
    for a, b in zip(captions, captions[1:]):
        gap = b.start - a.end
        if gap >= _SILENCE_BOUNDARY_SEC:
            # boundary sits on the *end* of the silence so the next segment
            # doesn't start mid-quiet-air
            out.add(b.start)

    sorted_bounds = sorted(out)
    # Dedup near-duplicates (< 0.5 s apart) so we don't fragment uselessly.
    tight: list[float] = []
    for b in sorted_bounds:
        if not tight or b - tight[-1] >= 0.5:
            tight.append(b)
    return tight


def _assemble_segments(
    boundaries: list[float],
    *,
    min_sec: float,
    max_sec: float,
    target_sec: float,
    cancel_cb=None,
) -> list[tuple[float, float]]:
    """Walk boundary list forward, emitting segments that land in
    ``[min_sec, max_sec]`` — never crossing ``max_sec``. Greedy, not
    globally optimal, but deterministic and fast."""
    segs: list[tuple[float, float]] = []
    if len(boundaries) < 2:
        return segs

    i = 0
    while i < len(boundaries) - 1:
        if cancel_cb and cancel_cb():
            return segs
        start = boundaries[i]
        # pick the boundary that best matches target_sec but stays within max_sec
        best_j = i + 1
        best_score = math.inf
        found = False
        for j in range(i + 1, len(boundaries)):
            end = boundaries[j]
            span = end - start
            if span < min_sec:
                continue
            if span > max_sec:
                break
            score = abs(span - target_sec)
            if score < best_score:
                best_score = score
                best_j = j
                found = True
        if not found:
            # no boundary in-window; hard-cap at the nearest one above min_sec
            # even if it exceeds max_sec -> the scorer will dock it for length_fit.
            fallback_found = False
            for j in range(i + 1, len(boundaries)):
                if boundaries[j] - start >= min_sec:
                    best_j = j
                    fallback_found = True
                    break
            if not fallback_found:
                break
        segs.append((start, boundaries[best_j]))
        i = best_j
    return segs


# ---------------------------------------------------------------- scoring


def _score_segment(
    start: float,
    end: float,
    captions: list[Caption],
    target_sec: float,
    *,
    cancel_cb=None,
    starts: list[float] | None = None,
) -> SegmentProposal | None:
    """Deterministic 0-1 score. Higher == stronger candidate.

    Returns ``None`` if ``cancel_cb`` fires during the caption filter —
    scoring can dominate wall-time on transcripts with thousands of
    captions, so propagating cancel all the way here keeps user-cancel
    responsive on pathologically long clips.
    """
    inside: list[Caption] = []
    for c in captions:
        if cancel_cb and cancel_cb():
            return None
        if c.end > start and c.start < end:
            inside.append(c)
    joined = " ".join(c.text for c in inside if c.text).strip()

    questions = len(_QUESTION_RE.findall(joined))
    laughter = len(_LAUGH_RE.findall(joined))

    # Silence-gap edges — reward segments flanked by quiet air; easier to cut.
    gap_before = _gap_before(start, captions, starts=starts)
    gap_after = _gap_after(end, captions, starts=starts)
    edge_bonus = 0.0
    if gap_before >= _SILENCE_BOUNDARY_SEC:
        edge_bonus += 0.15
    if gap_after >= _SILENCE_BOUNDARY_SEC:
        edge_bonus += 0.15

    # Length fit — triangular preference around target_sec.
    duration = max(0.0, end - start)
    length_fit = max(0.0, 1.0 - abs(duration - target_sec) / max(target_sec, 1e-6))

    # Base signal weighting — tuned so that a segment with both a question
    # and a laugh in the middle outranks a quiet segment purely on length.
    signal = (
        min(1.0, questions / 3.0) * 0.40
        + min(1.0, laughter / 2.0) * 0.20
        + length_fit * 0.40
    )

    score = min(1.0, max(0.0, signal + edge_bonus))

    reasons: list[str] = []
    if questions:
        reasons.append(f"{questions} question" + ("s" if questions != 1 else ""))
    if laughter:
        reasons.append(f"{laughter} laugh-hit" + ("s" if laughter != 1 else ""))
    if gap_before >= _SILENCE_BOUNDARY_SEC:
        reasons.append("silence before")
    if gap_after >= _SILENCE_BOUNDARY_SEC:
        reasons.append("silence after")
    if length_fit > 0.85:
        reasons.append("ideal length")

    title_hint = _title_hint_from(joined)

    return SegmentProposal(
        start=start,
        end=end,
        title_hint=title_hint,
        score=float(score),
        questions=questions,
        laughter_hits=laughter,
        silence_gap_before=gap_before,
        silence_gap_after=gap_after,
        reasons=tuple(reasons),
    )


def _straddling_gap(
    t: float,
    captions: list[Caption],
    starts: list[float] | None,
) -> float:
    """O(log N) straddling-pair gap lookup.

    Returns ``b.start - a.end`` for the pair where ``a.end <= t <= b.start``,
    or ``0.0`` if ``t`` lands inside a caption or outside the span. Callers
    that scan many segments against the same caption list should pass
    the precomputed ``starts`` array so we don't rebuild it per lookup.
    """
    n = len(captions)
    if n < 2:
        return 0.0
    if starts is None:
        starts = [c.start for c in captions]
    # First index whose start >= t. The straddling pair, if any, is
    # (idx - 1, idx). Both ends of the span short-circuit to zero.
    idx = bisect_left(starts, t)
    if idx == 0 or idx >= n:
        return 0.0
    a = captions[idx - 1]
    b = captions[idx]
    if a.end <= t <= b.start:
        return max(0.0, b.start - a.end)
    return 0.0


def _gap_before(
    t: float,
    captions: list[Caption],
    *,
    starts: list[float] | None = None,
) -> float:
    """Silence duration immediately preceding ``t``.

    Thin wrapper over :func:`_straddling_gap` — finds the pair
    ``(a, b)`` that straddles ``t`` (``a.end <= t <= b.start``) and
    returns ``b.start - a.end``. If ``t`` lands inside a caption the
    gap is zero. Returns zero on empty / single-entry input.
    """
    return _straddling_gap(t, captions, starts)


def _gap_after(
    t: float,
    captions: list[Caption],
    *,
    starts: list[float] | None = None,
) -> float:
    """Silence duration immediately following ``t``.

    Mirror of :func:`_gap_before` — same straddling-pair semantics; the
    two names preserve the call-site documentation ("gap before segment
    start" vs. "gap after segment end").
    """
    return _straddling_gap(t, captions, starts)


def _title_hint_from(joined: str, *, max_len: int = 60) -> str:
    """First sentence-ish slice, capped at ``max_len``."""
    cleaned = " ".join(joined.split())
    if not cleaned:
        return ""
    # End at the first terminal punctuation we find inside the cap.
    for end in ("?", ".", "!"):
        idx = cleaned.find(end, 5)
        if 0 <= idx < max_len:
            return cleaned[: idx + 1].strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len - 1].rstrip() + "\u2026"
