#!/usr/bin/env python3
"""UCX Video Summarizer sidecar — transcript-driven condensed summaries.

Pipeline (ROADMAP Item 55): Whisper transcription -> extractive summary +
chapter detection -> optional condensed highlight reel via FFmpeg concat.

Distinct from Auto Highlight (scenedetect), which ranks *visual* scene/motion
energy. This engine works on *spoken content*: it produces a written summary,
timestamped chapters, and an optional speech-driven highlight cut.

Design choices:
  * The default summarizer is EXTRACTIVE (TextRank over transcript sentences).
    It is pure-stdlib, fully offline, needs no model download or GPU, and is
    deterministic — so it always works and is unit-testable. This honours the
    offline-first charter where a local LLM may be absent.
  * An optional `--engine ollama` path calls a local Ollama server for an
    abstractive summary, but only when the server is reachable; otherwise it
    transparently falls back to extractive.
  * Input may be an existing transcript (--transcript, any of srt/vtt/json/txt)
    or a media file (--input), in which case the whisper-stt sidecar is invoked
    to transcribe first.

NDJSON events: log / progress / complete / error (see ../README.md contract).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent / "_lib"))

try:
    from ucx_sidecar import (  # type: ignore
        emit, find_ffmpeg, find_ffprobe, probe_media, run_ffmpeg,
    )
except Exception:  # pragma: no cover - fallback keeps the sidecar self-contained
    def emit(event: str, **fields: object) -> None:
        sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def find_ffmpeg(anchor=None):
        import shutil
        return shutil.which("ffmpeg")

    def find_ffprobe(anchor=None):
        import shutil
        return shutil.which("ffprobe")

    def probe_media(ffprobe, source, timeout=30):
        try:
            r = subprocess.run(
                [ffprobe, "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams", str(source)],
                capture_output=True, text=True, timeout=timeout)
            return json.loads(r.stdout) if r.returncode == 0 else None
        except Exception:
            return None

    run_ffmpeg = None  # type: ignore


def log(message: str, level: str = "info") -> None:
    emit("log", level=level, message=message)


def progress(percent: float, stage: str = "", eta: int | None = None) -> None:
    emit("progress", percent=round(percent, 1), stage=stage, eta_seconds=eta)


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Transcript parsing ───────────────────────────────────────────────────────

_STOPWORDS = set("""
a an and are as at be but by for from has have he her his i in is it its of on
or that the their them they this to was were will with you your we our us not
so if then than too very can just also about into over out up down our my me
he's she's it's i'm you're we're they're don't doesn't do does did what which
who whom when where why how all any both each few more most other some such no
nor only own same s t can't cannot could would should ought am been being had
having here there once again further once
""".split())

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")
_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def _parse_ts_srt(text: str) -> float:
    text = text.strip().replace(",", ".")
    h, m, s = text.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_transcript(path: Path) -> list[dict]:
    """Return [{start, end, text}] from an srt/vtt/json/txt transcript."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()

    if suffix == ".json":
        data = json.loads(raw)
        segs = data.get("segments", data) if isinstance(data, dict) else data
        out = []
        for s in segs:
            if not isinstance(s, dict):
                continue
            out.append({
                "start": float(s.get("start", 0.0)),
                "end": float(s.get("end", s.get("start", 0.0))),
                "text": str(s.get("text", "")).strip(),
            })
        return [s for s in out if s["text"]]

    if suffix in (".srt", ".vtt"):
        segs: list[dict] = []
        arrow = re.compile(r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})")
        blocks = re.split(r"\n\s*\n", raw)
        for block in blocks:
            lines = [ln for ln in block.splitlines() if ln.strip()]
            if not lines:
                continue
            ts_line = next((ln for ln in lines if arrow.search(ln)), None)
            if not ts_line:
                continue
            m = arrow.search(ts_line)
            start, end = _parse_ts_srt(m.group(1)), _parse_ts_srt(m.group(2))
            idx = lines.index(ts_line)
            text = " ".join(lines[idx + 1:]).strip()
            text = re.sub(r"<[^>]+>", "", text)  # strip vtt cue tags
            if text:
                segs.append({"start": start, "end": end, "text": text})
        return segs

    # Plain text: one pseudo-segment; timings unknown.
    text = " ".join(ln.strip() for ln in raw.splitlines() if ln.strip())
    return [{"start": 0.0, "end": 0.0, "text": text}] if text else []


# ── Sentence model ───────────────────────────────────────────────────────────

def build_sentences(segments: list[dict]) -> list[dict]:
    """Split segments into sentences, each inheriting its segment's timing."""
    sentences: list[dict] = []
    for seg in segments:
        parts = _SENT_SPLIT.split(seg["text"].strip())
        for part in parts:
            part = part.strip()
            if len(part) < 2:
                continue
            tokens = [w.lower() for w in _WORD_RE.findall(part)]
            words = [w for w in tokens if w not in _STOPWORDS and len(w) > 1]
            if not words:
                continue
            sentences.append({
                "text": part,
                "start": seg["start"],
                "end": seg["end"],
                "words": words,
            })
    return sentences


def _similarity(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    overlap = len(sa & sb)
    if overlap == 0:
        return 0.0
    denom = math.log(len(sa) + 1) + math.log(len(sb) + 1)
    return overlap / denom if denom else 0.0


def textrank(sentences: list[dict], iterations: int = 40, damping: float = 0.85) -> list[float]:
    """Classic TextRank sentence centrality scores."""
    n = len(sentences)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    sim = [[0.0] * n for _ in range(n)]
    row_sum = [0.0] * n
    for i in range(n):
        for j in range(i + 1, n):
            s = _similarity(sentences[i]["words"], sentences[j]["words"])
            sim[i][j] = sim[j][i] = s
        row_sum[i] = sum(sim[i])
    scores = [1.0 / n] * n
    for _ in range(iterations):
        new = [0.0] * n
        for i in range(n):
            rank = 0.0
            for j in range(n):
                if i != j and row_sum[j] > 0:
                    rank += sim[j][i] / row_sum[j] * scores[j]
            new[i] = (1 - damping) / n + damping * rank
        if max(abs(new[k] - scores[k]) for k in range(n)) < 1e-6:
            scores = new
            break
        scores = new
    return scores


# ── Keyword / chapter detection ──────────────────────────────────────────────

def _tf_idf_keywords(docs: list[list[str]], top: int = 5) -> list[list[str]]:
    df: dict[str, int] = {}
    for doc in docs:
        for w in set(doc):
            df[w] = df.get(w, 0) + 1
    n = max(1, len(docs))
    out: list[list[str]] = []
    for doc in docs:
        tf: dict[str, int] = {}
        for w in doc:
            tf[w] = tf.get(w, 0) + 1
        scored = [
            (w, (c / len(doc)) * math.log((n + 1) / (df.get(w, 0) + 1)) + 1.0)
            for w, c in tf.items()
        ] if doc else []
        scored.sort(key=lambda kv: kv[1], reverse=True)
        out.append([w for w, _ in scored[:top]])
    return out


def detect_chapters(sentences: list[dict], scores: list[float], duration: float) -> list[dict]:
    """Split the timeline into chapters, titling each by its top keywords."""
    if not sentences:
        return []
    span = duration if duration > 0 else (sentences[-1]["end"] or len(sentences))
    # Scale chapter count to length: ~1 per 2 minutes, clamped 2..12.
    count = min(12, max(2, round(span / 120.0))) if span > 0 else min(6, max(2, len(sentences) // 8))
    count = min(count, len(sentences))
    if count <= 1:
        count = 1
    per = max(1, math.ceil(len(sentences) / count))
    groups: list[list[int]] = []
    for i in range(0, len(sentences), per):
        groups.append(list(range(i, min(i + per, len(sentences)))))
    docs = [[w for idx in g for w in sentences[idx]["words"]] for g in groups]
    keywords = _tf_idf_keywords(docs, top=4)
    chapters = []
    for gi, g in enumerate(groups):
        best = max(g, key=lambda idx: scores[idx]) if g else g[0]
        start = sentences[g[0]]["start"]
        kw = keywords[gi] if gi < len(keywords) else []
        title = " ".join(w.capitalize() for w in kw[:3]) or sentences[g[0]]["text"][:48]
        chapters.append({
            "start": start,
            "title": title,
            "highlight": sentences[best]["text"],
            "keywords": kw,
        })
    # First chapter must start at 0 for YouTube compatibility.
    if chapters:
        chapters[0]["start"] = 0.0
    return chapters


# ── Summary selection ────────────────────────────────────────────────────────

_LENGTH_SENTENCES = {"brief": 4, "standard": 7, "detailed": 14, "executive": 5}


def select_summary(sentences: list[dict], scores: list[float], length: str) -> list[dict]:
    want = _LENGTH_SENTENCES.get(length, 7)
    want = min(want, len(sentences))
    ranked = sorted(range(len(sentences)), key=lambda i: scores[i], reverse=True)[:want]
    ranked.sort()  # restore chronological order for readability
    return [sentences[i] for i in ranked]


# ── Timestamp formatting ─────────────────────────────────────────────────────

def fmt_ts(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ── Output formatters ────────────────────────────────────────────────────────

def render_output(fmt: str, summary: list[dict], chapters: list[dict],
                  include_chapters: bool, source_name: str) -> str:
    sents = [s["text"].strip() for s in summary]

    if fmt == "markdown":
        lines = [f"# Summary — {source_name}", ""]
        for s in sents:
            lines.append(f"- {s}")
        if include_chapters and chapters:
            lines += ["", "## Chapters", ""]
            for c in chapters:
                lines.append(f"- **{fmt_ts(c['start'])}** {c['title']} — {c['highlight']}")
        return "\n".join(lines) + "\n"

    if fmt == "chapters":
        lines = []
        source = chapters if (include_chapters and chapters) else []
        for c in source:
            lines.append(f"{fmt_ts(c['start'])} {c['title']}")
        if not lines:  # fall back to summary sentences with timestamps
            for s in summary:
                lines.append(f"{fmt_ts(s['start'])} {s['text'].strip()}")
        return "\n".join(lines) + "\n"

    if fmt == "youtube":
        lines = [" ".join(sents), ""]
        if chapters:
            lines.append("Chapters:")
            for c in chapters:
                lines.append(f"{fmt_ts(c['start'])} {c['title']}")
            lines.append("")
        tags = []
        for c in chapters:
            for w in c.get("keywords", []):
                tag = "#" + re.sub(r"[^A-Za-z0-9]", "", w)
                if len(tag) > 2 and tag not in tags:
                    tags.append(tag)
        if tags:
            lines.append(" ".join(tags[:8]))
        return "\n".join(lines).strip() + "\n"

    # plain text
    para = " ".join(sents)
    if include_chapters and chapters:
        para += "\n\nChapters:\n" + "\n".join(
            f"  {fmt_ts(c['start'])}  {c['title']}" for c in chapters)
    return para + "\n"


# ── Optional Ollama abstractive path ─────────────────────────────────────────

def ollama_summary(full_text: str, length: str, model: str) -> str | None:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    if not host.startswith("http"):
        host = "http://" + host
    instruction = {
        "brief": "in 3-5 concise bullet points",
        "standard": "in one clear paragraph",
        "detailed": "in a multi-section overview",
        "executive": "as a 5-sentence executive brief",
    }.get(length, "in one clear paragraph")
    prompt = (
        "Summarize the following transcript " + instruction +
        ". Focus on the key points only.\n\nTRANSCRIPT:\n" + full_text[:12000])
    body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    try:
        req = urllib.request.Request(host + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        text = (data.get("response") or "").strip()
        return text or None
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        log(f"Ollama backend unreachable ({exc}); using offline extractive summary.", "warn")
        return None


# ── Whisper transcription (media input) ──────────────────────────────────────

def transcribe_media(media: Path, model: str, language: str) -> list[dict] | None:
    """Invoke the whisper-stt sidecar to produce a JSON transcript."""
    from tempfile import NamedTemporaryFile
    import shutil

    whisper_dir = _here.parent / "whisper-stt"
    exe = None
    for cand in (whisper_dir / "ucx-whisper-stt.exe", whisper_dir / "whisper-stt.exe",
                 whisper_dir / "dist" / "ucx-whisper-stt.exe"):
        if cand.is_file():
            exe = [str(cand)]
            break
    script = whisper_dir / "sidecar.py"
    if exe is None and script.is_file():
        exe = [sys.executable, str(script)]
    if exe is None:
        log("whisper-stt sidecar not found; cannot transcribe media directly.", "error")
        return None

    tmp = Path(NamedTemporaryFile(suffix=".json", delete=False).name)
    try:
        cmd = exe + ["--input", str(media), "--output", str(tmp),
                     "--model", model, "--language", language, "--format", "json"]
        log(f"Transcribing {media.name} with Whisper ({model})...")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event") == "progress":
                # Whisper occupies the first 60% of the summarizer timeline.
                progress(min(60.0, ev.get("percent", 0) * 0.6),
                         ev.get("stage", "transcribing"))
            elif ev.get("event") == "error":
                log(f"Whisper error: {ev.get('message')}", "error")
        proc.wait()
        if proc.returncode != 0 or not tmp.is_file():
            return None
        return parse_transcript(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True) if tmp.is_dir() else tmp.unlink(missing_ok=True)


# ── Highlight reel (speech-driven concat) ────────────────────────────────────

def render_highlight_reel(media: Path, out_path: Path, sentences: list[dict],
                          scores: list[float], count: int) -> bool:
    ffmpeg = find_ffmpeg(_here)
    ffprobe = find_ffprobe(_here)
    if not ffmpeg:
        log("FFmpeg not found; skipping highlight reel.", "warn")
        return False
    timed = [i for i in range(len(sentences)) if sentences[i]["end"] > sentences[i]["start"]]
    if not timed:
        log("Transcript has no usable timestamps; skipping highlight reel.", "warn")
        return False
    top = sorted(timed, key=lambda i: scores[i], reverse=True)[:max(1, count)]
    top.sort(key=lambda i: sentences[i]["start"])
    has_audio = True
    if ffprobe:
        payload = probe_media(ffprobe, media)
        if payload:
            streams = payload.get("streams", [])
            has_audio = any(s.get("codec_type") == "audio" for s in streams)
            has_video = any(s.get("codec_type") == "video" for s in streams)
            if not has_video:
                log("Input has no video stream; skipping highlight reel.", "warn")
                return False
    filters, labels = [], []
    for k, idx in enumerate(top):
        start = float(sentences[idx]["start"])
        end = float(sentences[idx]["end"])
        if end <= start:
            end = start + 2.0
        filters.append(f"[0:v:0]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{k}]")
        labels.append(f"[v{k}]")
        if has_audio:
            filters.append(f"[0:a:0]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{k}]")
            labels.append(f"[a{k}]")
    n = len(top)
    if has_audio:
        filters.append("".join(labels) + f"concat=n={n}:v=1:a=1[outv][outa]")
    else:
        filters.append("".join(labels) + f"concat=n={n}:v=1:a=0[outv]")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(media),
           "-filter_complex", ";".join(filters), "-map", "[outv]"]
    if has_audio:
        cmd += ["-map", "[outa]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
    total = sum(float(sentences[i]["end"]) - float(sentences[i]["start"]) for i in top)
    if run_ffmpeg is not None:
        code = run_ffmpeg(cmd, total, "render highlight reel", event_emitter=emit,
                          start_percent=90.0, end_percent=99.0,
                          completion_stage="highlight reel ready")
    else:
        code = subprocess.run(cmd, capture_output=True).returncode
    if code != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        out_path.unlink(missing_ok=True)
        log("Highlight reel rendering failed.", "warn")
        return False
    return True


# ── Command ──────────────────────────────────────────────────────────────────

def run_summarize(args: argparse.Namespace) -> int:
    if not args.transcript and not args.input:
        return fail("missing_input", "Provide --transcript or --input.")

    segments: list[dict] = []
    source_name = "transcript"
    media_path: Path | None = None

    if args.transcript:
        tpath = Path(args.transcript)
        if not tpath.is_file():
            return fail("missing_input", f"Transcript not found: {args.transcript}")
        source_name = tpath.stem
        progress(5.0, "Reading transcript")
        segments = parse_transcript(tpath)
    else:
        media_path = Path(args.input)
        if not media_path.is_file():
            return fail("missing_input", f"Input not found: {args.input}")
        source_name = media_path.stem
        segments = transcribe_media(media_path, args.whisper_model, args.language) or []
        if not segments:
            return fail("transcription_failed",
                        "Could not obtain a transcript. Build the whisper-stt sidecar "
                        "or supply --transcript.")

    if args.input and not media_path:
        media_path = Path(args.input)

    if not segments:
        return fail("empty_transcript", "The transcript contained no usable text.")

    progress(65.0, "Analyzing transcript")
    sentences = build_sentences(segments)
    if not sentences:
        return fail("empty_transcript", "No sentences could be extracted from the transcript.")

    duration = max((s["end"] for s in segments), default=0.0)
    scores = textrank(sentences)
    progress(75.0, "Selecting key points")
    summary = select_summary(sentences, scores, args.summary_length)
    chapters = detect_chapters(sentences, scores, duration)

    # Optional abstractive rewrite via a reachable local LLM.
    used_engine = "extractive"
    if args.engine in ("ollama", "auto"):
        full_text = " ".join(s["text"] for s in segments)
        llm = ollama_summary(full_text, args.summary_length, args.ollama_model)
        if llm:
            used_engine = "ollama"
            summary = [{"text": line.lstrip("-* ").strip(), "start": 0.0, "end": 0.0}
                       for line in llm.splitlines() if line.strip()] or summary
        elif args.engine == "ollama":
            log("Requested Ollama engine unavailable; produced offline summary instead.", "warn")

    progress(85.0, "Writing summary")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    body = render_output(args.summary_format, summary, chapters,
                         include_chapters=not args.no_chapters, source_name=source_name)
    out_path.write_text(body, encoding="utf-8")

    transcript_out = None
    if args.export_transcript:
        tp = Path(args.export_transcript)
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_text("\n".join(
            f"[{fmt_ts(s['start'])}] {s['text']}" for s in segments), encoding="utf-8")
        transcript_out = str(tp)

    reel_out = None
    if args.highlight_reel and media_path is not None and media_path.is_file():
        if render_highlight_reel(media_path, Path(args.highlight_reel),
                                 sentences, scores, args.highlight_count):
            reel_out = str(args.highlight_reel)

    progress(100.0, "Done", eta=0)
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size,
         engine=used_engine, chapters=len(chapters), sentences=len(summary),
         transcript=transcript_out, highlight_reel=reel_out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="videosummary",
                                description="UCX Video Summarizer sidecar")
    sub = p.add_subparsers(dest="command")
    s = sub.add_parser("summarize", help="Summarize a transcript or media file")
    s.add_argument("--input", help="Media file to transcribe then summarize")
    s.add_argument("--transcript", help="Existing transcript (srt/vtt/json/txt)")
    s.add_argument("--output", required=True, help="Summary output file path")
    s.add_argument("--summary-length", default="standard",
                   choices=["brief", "standard", "detailed", "executive"])
    s.add_argument("--summary-format", default="text",
                   choices=["text", "markdown", "chapters", "youtube"])
    s.add_argument("--language", default="auto", help="Whisper language (auto/en/...)")
    s.add_argument("--whisper-model", default="large-v3-turbo",
                   help="Whisper model for the --input transcription path")
    s.add_argument("--engine", default="extractive",
                   choices=["extractive", "ollama", "auto"],
                   help="extractive (offline TextRank) or ollama (local LLM if reachable)")
    s.add_argument("--ollama-model", default="llama3.2",
                   help="Ollama model name when --engine ollama")
    s.add_argument("--no-chapters", action="store_true",
                   help="Do not include chapter timestamps")
    s.add_argument("--export-transcript", help="Also write the timestamped transcript here")
    s.add_argument("--highlight-reel", help="Render a condensed speech-driven video here")
    s.add_argument("--highlight-count", type=int, default=6,
                   help="Number of clips in the highlight reel (default 6)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "summarize":
        return fail("unknown_command", "Usage: sidecar.py summarize --output <path> [...]")
    try:
        return run_summarize(args)
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user")
    except Exception as exc:  # pragma: no cover - defensive
        return fail("unhandled", f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
