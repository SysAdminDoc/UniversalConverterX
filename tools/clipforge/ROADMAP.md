# ClipForge Roadmap

All-in-one PyQt6 FFmpeg front-end with AI upscale (Real-ESRGAN) and frame interpolation (RIFE). This roadmap tracks what's next after v0.4.0.

## Planned Features

### Core / Pipeline
- Add hardware decode path (`-hwaccel cuda/d3d11va/qsv`) when the matching encoder is selected; surface failures in the console instead of silently falling back
- Add VP9/AV1 two-pass presets and CRF/CQ equivalence table so quality hints match the active codec
- Job queue: reorder, pause, resume, per-job priority, retry-failed; persist queue to disk so crashes don't lose work
- Add preset import/export (JSON) so users can share platform presets via gist/url
- Add project/session files (`.cfproj`) that snapshot inputs, in/out points, filters, and preset so a complex trim can be reopened
- Subclip extraction: "Split on markers" and "Split every N seconds/minutes" batch operations

### Filters & Effects
- Chained filter stack with drag-reorder, live preview of the `-filter_complex` graph
- Motion-tracked blur/redaction region for faces/plates
- Audio waveform + silence-cut filter (`silencedetect` + `select`) for fast talking-head edits
- Loudness target presets for YouTube (-14 LUFS), podcast (-16), broadcast (-23)

### UI/UX
- Timeline with frame thumbnails across the full duration (not just the filmstrip row), scrub preview on hover
- Keyboard-driven trim mode (`I`/`O` + `J`/`K`/`L` transport) — document-only, not bound to global shortcuts
- Detachable preview pane for multi-monitor setups
- Log panel: filter by level (info/warn/error), copy-as-markdown button for bug reports
- Per-panel "Reset to defaults" button

### Integrations
- Thumbnail/contact-sheet generator (NxM grid → PNG/JPG) as a dedicated panel
- YouTube-style chapter file (`chapters.txt`) → mux into MP4/MKV as metadata
- SubRip OCR pipeline for hardsubs (Tesseract) → exportable `.srt`
- Optional yt-dlp integration: paste a URL to pull source video into the workspace

### Performance
- Scene-change detection for smarter two-pass keyframe placement
- Parallel batch worker pool with a configurable thread cap tied to encoder concurrency
- Cache ffprobe metadata per file path+mtime so the Streams panel is instant on re-open
- Pre-flight disk-space check before batch jobs; warn if output dir has < estimated size * 1.2

### Packaging
- Single-exe PyInstaller build for Windows with `freeze_support()` + runtime hook guards
- Portable `.zip` bundle with `ffmpeg`, `realesrgan-ncnn-vulkan`, `rife-ncnn-vulkan` vendored
- GitHub Actions release workflow cross-building Windows / macOS / Linux artifacts
- Auto-update check against GitHub releases API with opt-out setting

## Competitive Research

- **HandBrake** — Best-in-class preset system and queue UX; ClipForge should steal the "add to queue" button placement and the side-by-side preset tree.
- **Shutter Encoder** — Covers a huge surface area (subs, DVD, broadcast) with a single UI; useful reference for tool grouping and sidebar taxonomy.
- **LosslessCut** — The gold standard for frame-accurate lossless trims with keyboard control; mirror its `I`/`O` + marker workflow.
- **FFmpeg Batch AV Converter** — Text-driven power tool; the "FFmpeg command preview" idea is validated there and worth making editable, not just read-only.

## Nice-to-Haves

- Optional GPU upscaler swap (waifu2x-ncnn-vulkan, anime4k) alongside Real-ESRGAN
- Built-in "Discord-safe" auto-bitrate solver that hits an exact target file size in one pass via VBR bitrate math
- Drag-and-drop `.srt` onto the player to preview burned subs before export
- Color grade panel with 1D/3D LUT stacking and side-by-side before/after split
- Project watermark presets (logo PNG with position, opacity, fade-in/out)
- Mini web UI mode for headless render boxes (Flask + the same FFmpeg core)

## Open-Source Research (Round 2)

### Related OSS Projects
- **Zulko/moviepy** — https://github.com/Zulko/moviepy — MIT Python video editor backed by ffmpeg; reference for concat/composite/timing primitives.
- **TNTwise/REAL-Video-Enhancer** — https://github.com/TNTwise/REAL-Video-Enhancer — Desktop app for upscale / interpolation / decompress / denoise on Linux/Windows/MacOS; pre-compiled ffmpeg + portable Python.
- **valkjsaaa/ffmpeg-smart-trim** — https://github.com/valkjsaaa/ffmpeg-smart-trim — Precise trim with minimum re-encoding at segment boundaries only.
- **addyosmani/video-compress** — https://github.com/addyosmani/video-compress — React + ffmpeg.wasm client-side compression; reference for a future browser companion.
- **dinoosauro/ffmpeg-web** — https://github.com/dinoosauro/ffmpeg-web — Web + Electron UI; two-engine strategy (wasm vs native).
- **EncodeGUI / encode-gooey** — reference for AI-transcoder UX with upscaling features built in.
- **ffmpeg-gui topic** — https://github.com/topics/ffmpeg-gui — broader catalog of GUI wrappers.
- **topic: video-crop** — https://github.com/topics/video-crop — includes GUIs that emit 22 presets across 16:9 / 4:3 / 1:1 aspect groups.

### Features to Borrow
- **Upscale + interpolation on the same job graph** (REAL-Video-Enhancer) — a source video runs through `decompress → RIFE (2x/4x) → Real-ESRGAN (2x/4x) → encode` as a single chained job with shared frame cache, not three separate passes that re-extract frames.
- **NCNN/Vulkan backend path** (REAL-Video-Enhancer) — portable binaries for non-CUDA users (AMD/Intel Arc/Apple); avoids the CUDA gating that limits ClipForge's AI features today.
- **Decompress / denoise model pre-pass** (REAL-Video-Enhancer) — a `hqdn3d` + `scxvid`-style denoise *before* upscale dramatically improves final quality; expose as a toggle on the Upscale card.
- **Segment-precise trim** (ffmpeg-smart-trim) — re-encode only the 1–2 sec around the cut points and stream-copy the middle; gives both "frame precise" and "fast" in one mode.
- **22-preset aspect-ratio crop grid** (video-crop topic) — single pane with 22 crop presets grouped by aspect; cleaner than the current 5-preset row.
- **Live FFmpeg command preview + copyable** (already in ClipForge) — extend by adding a "Generate bash script" button that emits the whole batch as a self-contained `.sh`/`.ps1`, so power users can rerun on a server.
- **Two-engine strategy** (dinoosauro/ffmpeg-web) — same UI, WASM fallback, for the future web-companion deliverable.
- **MoviePy-style composition timeline** (Zulko/moviepy) — expose a mini-timeline where Trim + Fade + Overlay can be stacked as a pipeline, not just one-op-at-a-time; important for the "combine filters" use case.
- **Real-ESRGAN-Video and RIFE-v4.22 updates** — upstream RIFE has moved to 4.22/4.25 with better motion handling; pin + document the active version and an upgrade lane.

### Patterns & Architectures Worth Studying
- **Frame-cache directory shared across AI passes** (REAL-Video-Enhancer) — `workdir/{jobid}/frames/` reused by upscale then interpolation, so the extract step doesn't happen twice.
- **Executable auto-detection** (REAL-Video-Enhancer, EncodeGUI) — at startup, probe for `ffmpeg`/`ffprobe`/`realesrgan-ncnn-vulkan`/`rife-ncnn-vulkan` on PATH; if missing, auto-download platform-specific binaries from BtbN/FFmpeg-Builds + the NCNN upstream releases.
- **Qt worker with queue + cancel tokens** — ClipForge already uses PyQt threads; borrowing the MoviePy subprocess-supervisor pattern (stdout tailing + periodic progress parse) simplifies cancel semantics.
- **Resumable frame pipeline** (REAL-Video-Enhancer) — cache per-frame outputs with content-hash keys so interrupted upscale jobs resume where they stopped; matches ClipForge's existing "resume interrupted jobs" ethos.
- **JSON-schema'd preset format shared with CLI** (already present) — ensure presets round-trip perfectly with `clipforge-cli` headless mode, which is the most valuable forgeable feature.
