"""Content summary via LLM — local (ollama) or cloud API (F60).

Feeds transcript text to an LLM and generates a structured `.summary.md`
with overview, key topics, notable moments with timestamps, and participants.

Supported backends:
  - ollama (local, free): POST http://localhost:11434/api/generate
  - Anthropic Claude API: via anthropic SDK
  - OpenAI-compatible: via requests to any /v1/chat/completions endpoint

Chunked processing: transcripts > 8K tokens are split, summarized per-chunk,
then the chunk summaries are summarized into a final output.
"""

import json
import os
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal


MAX_CHUNK_CHARS = 24000   # ~6K tokens at 4 chars/token
MAX_SUMMARY_WORDS = 500

SYSTEM_PROMPT = """You are a content analyst. Given a transcript from a live stream or video recording, produce a structured summary in Markdown with these sections:

## Overview
A 2-3 sentence overview of the content.

## Key Topics
- Bulleted list of main topics discussed

## Notable Moments
- [HH:MM:SS] Brief description of what happened

## Participants
- List of speakers/participants identified

Keep the summary under 500 words. Use timestamps from the transcript."""


def _load_transcript(recording_dir):
    """Load transcript text from .transcript.json or .srt files."""
    # Prefer .transcript.json (has timestamps)
    tj = os.path.join(recording_dir, ".transcript.json")
    if os.path.isfile(tj):
        try:
            with open(tj, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                lines = []
                for seg in data:
                    ts = seg.get("start", 0)
                    text = seg.get("text", seg.get("word", ""))
                    speaker = seg.get("speaker", "")
                    h = int(ts) // 3600
                    m = (int(ts) % 3600) // 60
                    s = int(ts) % 60
                    prefix = f"[{h}:{m:02d}:{s:02d}]"
                    if speaker:
                        prefix += f" {speaker}:"
                    lines.append(f"{prefix} {text}")
                return "\n".join(lines)
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    # Fallback to .srt
    for fn in os.listdir(recording_dir):
        if fn.endswith(".srt"):
            try:
                with open(os.path.join(recording_dir, fn), "r", encoding="utf-8") as f:
                    return f.read()
            except OSError:
                pass

    return ""


def _chunk_text(text, max_chars=MAX_CHUNK_CHARS):
    """Split text into chunks respecting line boundaries."""
    chunks = []
    current = []
    current_len = 0
    for line in text.splitlines():
        if current_len + len(line) > max_chars and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line)
    if current:
        chunks.append("\n".join(current))
    return chunks


# ── LLM backends ────────────────────────────────────────────────────

def _query_ollama(prompt, model="llama3", log_fn=None):
    """Query a local ollama instance."""
    try:
        body = json.dumps({
            "model": model,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "")
    except Exception as e:
        if log_fn:
            log_fn(f"[SUMMARY] ollama query failed: {e}")
        return ""


def _query_openai_compat(prompt, api_url, api_key, model="gpt-4o-mini", log_fn=None):
    """Query an OpenAI-compatible endpoint."""
    try:
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 2000,
        }).encode("utf-8")
        req = urllib.request.Request(
            api_url.rstrip("/") + "/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        if log_fn:
            log_fn(f"[SUMMARY] OpenAI-compat query failed ({api_url}): {e}")
        return ""


def _query_anthropic(prompt, api_key, model="claude-sonnet-4-20250514", log_fn=None):
    """Query the Anthropic Claude API."""
    try:
        body = json.dumps({
            "model": model,
            "max_tokens": 2000,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["content"][0]["text"]
    except Exception as e:
        if log_fn:
            log_fn(f"[SUMMARY] Anthropic query failed: {e}")
        return ""


def _query_llm(prompt, provider="ollama", model="", api_url="", api_key="",
               log_fn=None):
    """Dispatch to the appropriate LLM backend."""
    if provider == "ollama":
        return _query_ollama(prompt, model=model or "llama3", log_fn=log_fn)
    elif provider == "anthropic":
        return _query_anthropic(prompt, api_key=api_key,
                                model=model or "claude-sonnet-4-20250514", log_fn=log_fn)
    elif provider == "openai":
        return _query_openai_compat(prompt, api_url=api_url, api_key=api_key,
                                     model=model or "gpt-4o-mini", log_fn=log_fn)
    return ""


# ── Main summarize function ─────────────────────────────────────────

def summarize_recording(recording_dir, *, provider="ollama", model="",
                        api_url="", api_key="", log_fn=None):
    """Generate a summary for a recording directory.

    Returns the summary text (Markdown), or '' on failure.
    """
    transcript = _load_transcript(recording_dir)
    if not transcript or len(transcript.strip()) < 100:
        if log_fn:
            log_fn("[SUMMARY] No transcript found or too short (<100 chars)")
        return ""

    chunks = _chunk_text(transcript)

    if len(chunks) == 1:
        prompt = f"Summarize this stream transcript:\n\n{chunks[0]}"
        summary = _query_llm(prompt, provider, model, api_url, api_key, log_fn=log_fn)
    else:
        # Multi-chunk: summarize each, then summarize summaries
        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            prompt = (
                f"Summarize part {i+1}/{len(chunks)} of a stream transcript. "
                f"Focus on key events and topics:\n\n{chunk}"
            )
            cs = _query_llm(prompt, provider, model, api_url, api_key, log_fn=log_fn)
            if cs:
                chunk_summaries.append(cs)
        if not chunk_summaries:
            if log_fn:
                log_fn("[SUMMARY] All chunk summaries failed — no output")
            return ""
        combined = "\n\n---\n\n".join(chunk_summaries)
        prompt = (
            f"These are summaries of {len(chunk_summaries)} consecutive parts "
            f"of the same stream. Combine them into one final summary:\n\n{combined}"
        )
        summary = _query_llm(prompt, provider, model, api_url, api_key, log_fn=log_fn)

    if summary:
        # Save alongside recording
        out_path = os.path.join(recording_dir, ".summary.md")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(summary)
        except OSError:
            pass

    return summary


# ── Worker thread ───────────────────────────────────────────────────

class SummarizeWorker(QThread):
    """Run LLM summarization in the background."""

    done = pyqtSignal(bool, str)   # ok, summary_or_error
    log = pyqtSignal(str)

    def __init__(self, recording_dir, provider="ollama", model="",
                 api_url="", api_key=""):
        super().__init__()
        self._dir = recording_dir
        self._provider = provider
        self._model = model
        self._api_url = api_url
        self._api_key = api_key

    def run(self):
        try:
            self.log.emit(f"[SUMMARY] Generating summary via {self._provider}...")
            result = summarize_recording(
                self._dir,
                provider=self._provider,
                model=self._model,
                api_url=self._api_url,
                api_key=self._api_key,
                log_fn=self.log.emit,
            )
            if result:
                self.log.emit(f"[SUMMARY] Summary generated ({len(result)} chars)")
                self.done.emit(True, result)
            else:
                self.done.emit(False, "No summary generated (no transcript or LLM unreachable)")
        except Exception as e:
            self.log.emit(f"[SUMMARY] Error: {e}")
            self.done.emit(False, str(e))
