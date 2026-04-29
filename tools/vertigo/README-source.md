<div align="center">

<img src="assets/icon.png" alt="Vertigo" width="140"/>

# Vertigo

**Vertical video studio for short-form creators.**

![version](https://img.shields.io/badge/version-0.12.3-cba6f7?style=for-the-badge)
![license](https://img.shields.io/badge/license-MIT-a6e3a1?style=for-the-badge)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-89b4fa?style=for-the-badge)
![python](https://img.shields.io/badge/python-3.10%2B-f9e2af?style=for-the-badge)

From the Latin *vertere*, to turn. Turns raw footage of any shape into polished 9:16 for YouTube Shorts, TikTok, and Instagram Reels.

</div>

---

## Features

- **Premium PyQt6 UI** — polished System / Mocha / Graphite / Latte themes, frameless custom titlebar, calm editor surfaces, refined focus states, accessible controls.
- **Four reframe modes:**
  - **Center Crop** — static center column, zero analysis.
  - **Smart Track** — MediaPipe face detection; viewport pans to follow subjects with smoothed, *scene-aware* keyframes that never cross a hard cut.
  - **Blur Letterbox** — full source frame on a softly blurred backdrop.
  - **Manual** — drag the viewport on the live preview to lock any column.
- **Platform presets** — YouTube Shorts, TikTok, Instagram Reels, Square (1:1). One click switches output geometry and encoder target bitrate.
- **Batch queue** — drop many clips at once, preview any one, then **Export All** to a folder. Per-item status indicator.
- **Trim timeline** — dual-thumb in/out range slider directly on the preview. Exports respect the trim window via FFmpeg `-ss` / `-t`.
- **Four one-click trim helpers** — *Suggest segments* (TextTiling-ranked candidates on clips > 10 min, now with min / target / max length sliders; **requires AI captions to be generated first** so the segmenter has a transcript to work with), *Find highlights* (energy-ranked moments, Lighthouse + fallback), *Trim silences* (longest speech-contiguous sections via auto-editor), *Tighten to speech* (outer speech edges via Silero VAD). Each pops a menu of candidates; picking one drops the trim handles in place.
- **Export thumbnails** — one-click save of six representative PNG cover frames (Katna-ranked when installed, evenly-spaced cv2 frames otherwise).
- **Adjustments panel** — live brightness / contrast / saturation sliders; applied via FFmpeg `eq=` filter appended to the reframe chain.
- **Scene detection** — PySceneDetect (with a histogram-delta fallback) segments the timeline to stabilize Smart Track.
- **Hardware encoding** — auto-detects NVIDIA NVENC, Intel QuickSync, AMD AMF, Apple VideoToolbox, and the libx264/libx265 CPU encoders. Pick one in the Output tab, drive a single quality slider, tune the speed preset.
- **AI captions** — optional faster-whisper transcription (opt-in lazy install) with SRT burn-in. Word-wrapped, mobile-safe styling baked directly into the exported pixels.
- **Text overlays** — title cards, top straps, lower-thirds, and bottom captions. Per-overlay time range, color, and font size. Preset library for common Shorts/Reels motifs. All burned into the output via `drawtext=` filter chain.
- **Live crop viewport** overlaid on the preview player so you see the target frame before rendering.
- **Async FFmpeg encoding** with real-time progress bar and a scrolling log panel.
- **Turnkey bootstrap** — single-command launch, auto-installs missing Python deps on first run.
- **Binary builds** — `pyinstaller --clean vertigo.spec` produces single-file Windows, macOS `.app`, and Linux exes. GitHub Actions workflow builds all three on every tag push (or `workflow_dispatch`) and uploads to a draft release via `gh release upload --clobber`.

## Optional integrations

Each module under `core/` below is usable on its own and ships with a clean fallback when the heavy dependency is absent. Install only what you need:

```bash
pip install -r requirements-optional.txt   # everything, or
pip install silero-vad                     # cherry-pick
```

**Licensing note.** Vertigo itself is MIT. The opt-in deps carry their own licenses (see `requirements-optional.txt` for per-package detail). Two surfaces deserve calling out:

- **`boxmot` is AGPL-3.0.** Desktop builds are fine — Vertigo never bundles `boxmot`, so installing it on your own machine is your own decision. If you redistribute Vertigo as a hosted / SaaS product alongside `boxmot`, AGPL-3.0 network copyleft kicks in.
- **`pyannote.audio` model weights** are often CC-BY-NC-4.0 (non-commercial) on HuggingFace. The Python code is MIT, but the default diarization checkpoint requires you to accept the HF model card's terms before use.

| Module | What it adds | Heavy dep | Fallback when missing |
|---|---|---|---|
| `core.vad` | Silero voice-activity detection → "tighten silences" trim | `silero-vad` (ONNX, <2 MB) | raises with clear install hint |
| `core.animated_captions` | pycaps per-word animated caption overlays (pop / bounce / karaoke) | `pycaps` | keeps the ASS/SRT output |
| `core.tracker_boxmot` | BoT-SORT / ByteTrack / DeepOCSORT speaker tracking with stable IDs across occlusion | `boxmot` (AGPL-3.0) | existing `SpeakerTracker` |
| `core.auto_edit` | Silence- and motion-driven cut planning from auto-editor | `auto-editor` CLI | raises with install hint |
| `core.highlights` | Lighthouse moment retrieval with optional text query | `lighthouse-ml` | sliding-window `hook_score` fallback |
| `core.cluster_track` | Per-frame face clustering + temporal-persistence filter (RetargetVid port) | none (numpy) | — |
| `core.diarize` | pyannote speaker diarization ("who spoke when") | `pyannote.audio` + HF token | raises with clear error |
| `core.broll` | Transcript → keywords → Pexels stock search → CLIP re-rank → overlay plan | `keybert` / `open_clip_torch` / Pexels API key | stdlib keyword picker + Pexels native rank |
| `core.keyframes` | Katna-ranked thumbnails for clip cards and poster export | `Katna` | evenly-spaced cv2 frames |

## Install

```bash
git clone https://github.com/SysAdminDoc/Vertigo.git
cd Vertigo
python vertigo.py
```

First run bootstraps PyQt6, OpenCV, NumPy, Pillow, MediaPipe, and PySceneDetect. You must also have **FFmpeg** on `PATH`:

```bash
# Windows
winget install Gyan.FFmpeg
# macOS
brew install ffmpeg
# Linux (Debian/Ubuntu)
sudo apt install ffmpeg
```

## Use

1. Launch `python vertigo.py`.
2. Drop a video on the preview area (or click to browse).
3. Pick a platform preset (Shorts / TikTok / Reels / Square).
4. Pick a reframe mode. For Smart Track, MediaPipe scans the clip and returns tracking keyframes.
5. Click **Export Vertical** and choose an output path. Progress streams in the log panel.

## Architecture

```
vertigo.py                entry + dependency bootstrap + PyInstaller freeze-support
vertigo.spec              PyInstaller build spec (single-file, per-OS icon)
.github/workflows/build.yml  Multi-OS CI + GitHub Release upload
pytest.ini                pytest-qt binding pin (PyQt6)
core/
  _lazy.py                shared pip-install helper with frozen-build guard + threading.Lock
  caption_types.py        Caption + Word dataclasses (lifted from subtitles for clean imports)
  crashlog.py             persistent breadcrumb log — survives frozen-build stderr drop
  probe.py                ffprobe wrapper (VideoInfo dataclass)
  presets.py              platform output presets (Shorts/TikTok/Reels/Square)
  detect.py               MediaPipe face tracker (Haar fallback)
  cameraman.py            SmoothedCameraman + SpeakerTracker (Smart Track smoothing)
  scenes.py               scene detection (PySceneDetect + histogram fallback)
  cluster_track.py        RetargetVid temporal-persistence filter (pure numpy)
  encoders.py             hardware encoder detection (NVENC/QSV/AMF/VT + CPU)
  subtitles.py            faster-whisper wrapper (lazy install) + SRT/ASS writers + karaoke
  caption_styles.py       CaptionPreset dataclass + six bundled looks + style_for_height
  caption_layout.py       face-aware caption alignment heuristic ({\an8} overrides)
  face_samples.py         face sampler used by caption_layout (2 fps MediaPipe)
  overlays.py             TextOverlay dataclass + drawtext filter chain
  reframe.py              FFmpeg filter graph per mode + Adjustments dataclass
  encode.py               FFmpeg subprocess + progress parsing + trim + burn-in
  preflight.py            pre-export sanity checks (codec, duration, free disk)
  dryrun.py               plan-only report (TRACK / LETTERBOX / CENTER strategy)
  hook_score.py           0-100 first-3-second engagement score (no torch)
  segment_proposals.py    T3b — local TextTiling segmenter + silence-gap + length-fit ranker
  animated_captions.py    pycaps post-encode composite (opt-in, Apache-2.0)
  auto_edit.py            auto-editor CLI interop for silence-cut planning
  vad.py                  Silero VAD (opt-in, ONNX, no PyTorch)
  tracker_boxmot.py       BoT-SORT / ByteTrack / DeepOCSORT (opt-in, AGPL-3.0)
  highlights.py           Lighthouse moment retrieval + sliding-window fallback
  diarize.py              pyannote speaker diarization (opt-in, HF token required)
  broll.py                transcript -> keywords -> Pexels -> CLIP b-roll planner
  keyframes.py            Katna-ranked thumbnails (opt-in) + cv2 fallback
ui/
  theme.py                semantic theme tokens + QSS stylesheet generation
  tokens.py               palette / typography tokens consumed by theme.py
  titlebar.py             frameless draggable titlebar + theme picker + brand mark
  assets.py               bundle-aware asset resolver (source + PyInstaller)
  widgets.py              GlassPanel, ModeCard, Toast, FadingTabWidget
  mode_icons.py           painted ReframeMode card icons
  file_drop.py            multi-file drag-drop import zone
  file_dialogs.py         open/save dialog helpers with preset memory
  range_slider.py         dual-thumb trim slider + playhead + shot-boundary ticks
  video_player.py         QMediaPlayer preview + crop-viewport overlay + trim row buttons
  batch_queue.py          queue panel with per-item status + entry_removed signal
  adjustments_panel.py    brightness / contrast / saturation sliders
  output_panel.py         encoder / quality / speed controls
  subtitles_panel.py      AI caption generation + burn-in toggle + animated-style picker
  overlays_panel.py       text-overlay editor (titles / lower-thirds)
  panels.py               shared panel-builder helpers
  main_window.py          composition + wiring + batch driver
  main_controller.py      worker orchestration + export finaliser + segments gate
workers/
  detect_worker.py        QThread: runs FaceTracker
  encode_worker.py        QThread: runs encode.run() + partial-output unlink on cancel
  subtitle_worker.py      QThread: runs faster-whisper transcription
  scene_worker.py         QThread: background scene detection on clip load
  vad_worker.py           QThread: runs Silero VAD for "tighten to speech"
  highlights_worker.py    QThread: runs core.highlights.score_spans
  auto_edit_worker.py     QThread: runs auto-editor CLI for "trim silences"
  pycaps_worker.py        QThread: runs core.animated_captions post-encode composite
  segment_proposals_worker.py  QThread: runs core.segment_proposals.propose_segments
assets/
  icon.svg / icon.png / icon.ico + size variants (16/32/48/128/256/512)
  wordmark.svg           typography-focused brand wordmark
  build_icons.py         procedural Pillow renderer (SVG + PNG + ICO)
  runtime_hook_mp.py     PyInstaller fork-bomb guard (freeze_support)
  logo_prompts.md        5 AI image prompts for high-end brand generation
```

## Reframe strategy reference

| Mode | FFmpeg summary | When to use |
| --- | --- | --- |
| Center | `crop,scale` static | Subject already centered |
| Smart Track | `crop=...:x=<piecewise lerp>,scale` | Talking heads, walking subjects |
| Blur Letterbox | `split, blur+crop bg, scale fg, overlay` | Preserve full frame, no loss |
| Manual | `crop` with locked offset | Total creative control |

## Test

```bash
python -m pytest -q
```

`pytest.ini` pins `pytest-qt` to PyQt6 so local environments that also have PySide6 installed still exercise the shipped widget stack.

## Build binaries

```bash
pip install pyinstaller
pyinstaller --clean vertigo.spec
# dist/Vertigo.exe   (Windows)
# dist/Vertigo.app   (macOS)
# dist/Vertigo       (Linux)
```

Or push a tag and let CI build all three — see `.github/workflows/build.yml`. A `workflow_dispatch` run with a tag input lands three artifacts on a draft release.

## Requirements

- Python 3.10+
- FFmpeg / ffprobe on PATH
- PyQt6, OpenCV, MediaPipe, NumPy, Pillow, PySceneDetect (auto-installed)

## License

MIT — see [LICENSE](LICENSE).
