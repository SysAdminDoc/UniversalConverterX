# ROADMAP

Backlog for FrameSnap. Stays a single-window, mouse-first, Catppuccin-themed desktop app for
browsing video and exporting precise frames.

## Planned Features

### Playback engine
- **PyAV (libav) backend option** alongside OpenCV's FFmpeg wrapper — faster seek, accurate
  timestamp handling, wider format coverage for MXF/ProRes/HEVC 10-bit.
- **Hardware-accelerated decode** via PyAV's `hwaccel='d3d11va'` / `vaapi` / `videotoolbox`.
- **Audio waveform track** under the scrubber — helps mark frames on audio cues.
- **Multi-audio-track indicator** in the info bar.

### Frame precision
- **Frame-accurate seek toggle** — force keyframe-accurate vs exact-frame (slower) seek.
- **Proxy-cache generation** — optional low-res proxy built on open for huge 4K files, swapped at
  playback, full-res only on export.
- **GPU thumbnail strip** along the scrubber (not just hover preview).

### Marking
- **Auto-mark by scene detection** using `PySceneDetect` content-aware algorithm.
- **Auto-mark on chapter markers** in MP4/MKV.
- **Marker groups / tags** — color + label groupings, export per-group.
- **Timestamped comments** per mark for shot-notes workflows.
- **Ripple delete** — remove a mark and shift subsequent mark labels.

### Export
- **Burn-in overlays** — timestamp, frame number, mark label baked into the image export; opt-in.
- **Export crop region** — define a rectangle once, apply to every exported frame.
- **Animated WebP + AVIF export** in addition to GIF.
- **EXR / TIFF 16-bit** export paths for color-pipeline work (requires OpenEXR binding).
- **Contact sheet enhancements** — per-sheet title, watermark, configurable grid shape, PDF
  output.
- **FFmpeg command echo** — show the equivalent `ffmpeg -ss X -vframes 1 ...` for each mark so
  users can scripted-replay.

### Sessions
- **Session merge** — combine two `.fsnap` files against the same video.
- **Session diff** — compare two sessions, show which marks differ.
- **Session templates** — save a set of relative-timestamp marks (e.g. "every 30s") as a
  template, apply to any new video.

### UI / UX
- **Multi-video drag-drop** — open as a queue, same marks/settings reused per file.
- **Batch export marker list from a CSV/JSON** — non-interactive CLI mode.
- **High-DPI rendering audit** — verify 125% / 150% / 200% scaling on Windows stays pixel-sharp.
- **Alternative themes** — Catppuccin Latte light mode, GitHub Dark, AMOLED black.

### Distribution
- **PyInstaller signed builds** for Windows (include `multiprocessing.freeze_support()` guard at
  entry point — OpenCV + PyAV both use multiprocessing internally on some paths).
- **macOS `.app` notarized** and Homebrew cask.
- **Linux AppImage + Flatpak**.

## Competitive Research

- **VideoProc Converter AI** — "extract frames" wizard + AI upscale. FrameSnap should not chase
  the AI angle; differentiate on precision + session portability.
- **ScreenToGif** — open-source, Windows-only; its frame editor is a model for granular per-frame
  edit workflows.
- **Shotcut / DaVinci Resolve** — full NLEs with frame export. FrameSnap stays in the "I only want
  stills and a few GIFs" niche rather than competing.
- **Kreatli / VideoToJPG.com / Teamz Converter** — rising browser-based, WASM-powered
  competitors. Desktop edge: >2GB files, local processing, no upload cap.
- **VLC "Save video snapshot"** — the 1-click baseline everyone compares to; match its speed for
  single-shot extractions.

## Nice-to-Haves

- **Frame similarity search** — perceptual hash across all frames, find near-duplicate frames;
  useful for dedup before contact-sheet export.
- **OCR on extracted frames** (Tesseract) — export a `frames.txt` of detected text per mark.
- **QR/barcode detection** on the current frame for debugging-shot workflows.
- **Custom scrubber shortcuts** — configurable mouse-wheel step size per video (persisted per
  file).
- **Cloud sync of sessions** — optional `.fsnap` + video-hash in Dropbox/GDrive so marks travel
  with the user.
- **Side-by-side A/B viewer** for comparing two files at the same frame position.

## Open-Source Research (Round 2)

### Related OSS Projects
- **KimSource/video-frame-extractor** — https://github.com/KimSource/video-frame-extractor — Python GUI wrapping ffmpeg; PyInstaller-built exe.
- **noarche/FrameExtractor** — https://github.com/noarche/FrameExtractor — Portable exe; per-video count-based sampling.
- **EnragedAntelope/youtube-screenshot-extractor** — https://github.com/EnragedAntelope/youtube-screenshot-extractor — yt-dlp-fed 1000-site extractor; scene detection + keyframe + aesthetic filter.
- **Gifcurry** — https://github.com/lettier/gifcurry — Haskell GUI+CLI; powerful trim/crop/text-overlay pipeline worth mirroring.
- **ScreenToGif** — https://github.com/NickeManarin/ScreenToGif — C#/WPF; live frame-editor with per-frame annotate/delete.
- **Video Frame Extractor Pro** (Qt+OpenCV topic entry) — https://github.com/topics/frame-extraction — Qt frame extractor worth studying for scrubber UX.

### Features to Borrow
- yt-dlp-fed input (`EnragedAntelope`) — accept a YouTube/Vimeo/TikTok URL, resolve best stream, scrub in place. Removes manual download step.
- PySceneDetect content/adaptive detection (`EnragedAntelope`) — "snap to scene boundary" button that finds nearest cut.
- Blur/aesthetic filter at export (`EnragedAntelope` — CLIP/LAION scorer) — discard out-of-focus candidates in batch runs.
- Per-frame annotate (ScreenToGif) — reuse its frame-list + undo stack model for exported contact sheets.
- Batch-sampling presets from `noarche/FrameExtractor` — "every N seconds" / "N uniform frames" / "all I-frames".
- GIF + MP4 export in addition to stills (`Gifcurry`) — reuse ffmpeg already in the project.
- Text overlay with timing (`Gifcurry`) — watermark/label stills at export.

### Patterns & Architectures Worth Studying
- **OpenCV `VideoCapture.set(CAP_PROP_POS_FRAMES)` vs ffmpeg `-ss` seek** — OpenCV is accurate-per-frame but slow; ffmpeg `-ss` before `-i` is fast but keyframe-only. Most extractors pick one; the good ones implement "fast seek + fine adjust" (ffmpeg for rough, OpenCV for exact).
- **Decoupled producer/consumer queue**: decoder thread fills a bounded frame queue; GUI thread consumes. Keeps UI at 60fps during scrub. Used in the Qt+OpenCV topic entry.
- **PyAV over subprocess ffmpeg**: libavformat bindings give per-frame PTS without parsing stderr; cleaner than spawning ffmpeg per export.
- **MediaInfo sidecar** (`EnragedAntelope`): probe codec/framerate/HDR flags once, cache in sqlite keyed by file hash — skip re-probe on re-open.
