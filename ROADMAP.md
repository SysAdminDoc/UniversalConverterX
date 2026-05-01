# ROADMAP

<!-- Researched and updated 2026-05-26. Sources in Appendix. -->

UniversalConverterX (UCX) v2.4 planning — WinUI 3 / .NET 8 / Windows-only desktop app. Local-first, no telemetry, no account required. Replaces Wondershare UniConverter without the paywall. Strategy pattern (13 native backends) + NDJSON sidecar pattern for Python AI engines.

---

## Current State (v2.3.0)

**Wired end-to-end:** Native Converter (1000+ formats, magic-byte routing), VideoCrush compressor (CRF + 2-pass, AV1/H.265/H.264, HW accel NVENC/AMF/QSV/D3D12), ClipForge editor (trim, crop, rotate, loudnorm, rewrap, undo/redo), StreamKeep downloader (yt-dlp, 1000+ sites), RecordCast screen/webcam/mic recorder, AlphaCut background remover (ONNX, shared model cache), FrameSnap (batch frame extraction), Format Inspector (FFprobe), VideoSubtitleRemover (subtitle inpainting), LipSight (visual lip reading), Demucs Vocal Remover (htdemucs_ft, 4-stem), Whisper STT (faster-whisper, all formats + word timestamps), CLI (`ucx`), Shell Extension (right-click).

**Stubbed / placeholder (page exists, no sidecar):** VideoEnhancer, ImageEnhancer, NoiseRemover, PhotoRestoration, VideoSummarizer, VoiceChanger, TextToSpeech, AiSubtitle, VideoStabilizer, SmartTrimmer, AutoReframe, AutoCrop, WatermarkEditor, AutoHighlight, IntroOutro, LensCorrection, VRConverter, ImageConverter, GifMaker, ImageUpscaler, AiPortrait, SlideshowMaker, MetadataEditor, AudioCompressor, BatchRename, DVD/CD.

**Source exists, no sidecar.py / route wired:** Vertigo (auto-reframe), GifStudio (WebView2 GIF editor), HEICShift (HEIC/AVIF/WebP converter).

**Editor gaps (ClipForge):** Upscale op and audio filter ops deferred to v2.4.

---

## Tier Definitions

| Tier | Meaning |
|------|---------|
| **Now** | v2.4 — security pins, missing sidecar.py files, stub pages ready to wire, .NET EOL deadline |
| **Next** | v2.5–v2.6 — high-value, scoped, no blocking dependency |
| **Later** | v3.x — meaningful but requires significant new infrastructure |
| **Under Consideration** | Needs more validation before committing resources |
| **Rejected** | Explicitly out of scope — reason given |

---

## v2.3.0 Shipped ✓

- ✓ Security: yt-dlp CVE-2026-26331 pin (`≥2026.02.21`)
- ✓ Security: ONNX Runtime upgrade to 1.25.x
- ✓ Shared ONNX model cache (`tools/_models/`, `UCX_MODEL_DIR`)
- ✓ VideoSubtitleRemover sidecar + WatermarkRemoverPage wired
- ✓ LipSight sidecar + LipReadingPage wired
- ✓ ClipForge: crop, rotate/flip, loudnorm (EBU R128 two-pass), rewrap ops
- ✓ Editor: Undo/Redo stack
- ✓ VideoCrush: D3D12 + NVENC/AMF/QSV hardware acceleration
- ✓ Demucs Vocal Remover sidecar + VocalRemoverPage wired
- ✓ Whisper STT sidecar (faster-whisper) + SpeechToTextPage wired
- ✓ RecordCast: webcam (DirectShow) + microphone capture

---

## v2.5.0 — "Universal" wave (in progress)

Goal: round out the "universal converter" promise by adding the categories that
make UCX a one-stop shop beyond media. Every item here pulls in well-trodden
OSS tooling and exposes it through the same NDJSON sidecar contract + WinUI 3
workspace pattern that v2.4 established.

- #33 **Document converter** ✓ Shipped v2.5 — DOCX / PDF / XLSX / PPTX / ODT / RTF / HTML mutual
  conversion via `libreoffice --headless --convert-to`. Sidecar discovers
  LibreOffice on PATH or via standard install dirs; emits `progress` per file
  in batch. Toolbox tile + dedicated `DocumentConverterPage`. Shipped:
  `tools/docconvert/sidecar.py` (pure-Python wrapper; one `subprocess.run` per
  input to avoid LibreOffice user-profile lock contention) + `build.ps1`
  (PyInstaller freeze, no third-party deps). New `DocumentConverterPage` with
  drag-drop card, format combo (pdf/docx/odt/rtf/txt/html/epub/xlsx/ods/csv/pptx/odp/png/svg),
  per-file status updates from `doc` events, output-dir picker, History
  integration. Toolbox section "Documents" added (sits between Disc and Other);
  nav search entry. Contract test: `doc` added to `KNOWN_EVENTS` (20 sidecars
  conform).
- #34 **Archive tool** — ZIP / 7Z / TAR / TAR.GZ / RAR (read-only) extraction
  + ZIP/7Z/TAR creation via 7-Zip's `7z.exe` CLI. Single sidecar, two ops:
  `pack` + `unpack`. Auto-locates `7z.exe` (Program Files / PATH). Glob-driven
  include / exclude.
- #35 **PDF tools** — merge / split / rotate / extract pages / encrypt /
  decrypt / linearize via pikepdf (built on qpdf). Pure-Python sidecar, no
  external binary required at runtime.
- #36 **Subtitle converter** — SRT ↔ VTT ↔ ASS ↔ SSA ↔ MicroDVD via pysubs2.
  Independent of clipforge's burn-in path; this is pure conversion + offset
  shift + retime. Pure-Python sidecar.
- #37 **Font converter** — TTF ↔ OTF ↔ WOFF ↔ WOFF2 via fonttools + brotli.
  Subsetting reserved for v2.6.
- #38 **eBook converter** — EPUB / MOBI / AZW3 / PDF / FB2 / TXT / HTML mutual
  conversion via Calibre's `ebook-convert`. Sidecar auto-locates the bundled
  CLI under standard Calibre install dirs.
- #39 **OCR (Tesseract)** — extract text from images and scanned PDFs to TXT /
  HOCR / PDF (searchable). Bundles `tesseract.exe` lookup under standard install
  dirs; downloads language data on demand to `tools/_models/tessdata/`.

## v2.4.0 Shipped ✓ (in progress)

- ✓ Sidecar bootstraps hardened against PyInstaller fork-bomb (frozen guard in demucs/whisper-stt/lipsight)
- ✓ #1 Security: yt-dlp pinned `≥2026.03.17` (was `≥2026.02.21`)
- ✓ #2 Security: ONNX Runtime pinned `≥1.25.1` in alphacut + videosubtitleremover (15+ CPU-kernel CVEs vs 1.25.0)
- ✓ #48 Stop tracking `obj/` — already in `.gitignore`; one-time `git rm -r --cached`
- ✓ #49 Sidecar NDJSON contract conformance test (`tests/sidecar_contract/check_contract.py`) — frozen-guard, error-code-field, known-events checks
- ✓ #50 Unified `tools/build-all.ps1` orchestrator with build report (`artifacts/build-reports/build-report.{json,md}`)
- ✓ #51 SidecarRunner no-progress watchdog — `stuck_sidecar` error code after `silenceTimeout` (default 10 min)
- ✓ #10 + #23 verified already shipped in v2.3 (lossless trim default-on; ClipForge rewrap op) — roadmap entries reclassified.
- ✓ #4 GIF Maker — new `gifstudio` sidecar (two-pass `palettegen`+`paletteuse`), `GifMakerPage` batch UI, route + Toolbox tile wired, contract test KNOWN_EVENTS extended.
- ✓ #5 HEICShift / Image Converter — new `heicshift` Pillow+pillow_heif sidecar, `ImageConverterPage` with format/quality/metadata controls, route + Toolbox tile wired (JXL/RAW deferred).
- ✓ #7 edge-tts Text-to-Speech — new `edge-tts` async sidecar (322 voices, MIT, no API key), TextToSpeechPage rebuilt with voice picker/rate/pitch/format controls + Save-to picker, ToolboxPage tile flipped Future → Ready.
- ✓ #11 RNNoise Noise Remover — new `rnnoise` sidecar via FFmpeg `arnndn` filter (no Python ML deps), NoiseRemoverPage rewritten with model picker + muxed/audio-only modes, ToolboxPage tile flipped Future → Ready.
- ✓ #3 Vertigo Auto-Reframe — new `vertigo` sidecar with FFmpeg static centre-crop + optional MediaPipe smart face-tracking, new `AutoReframePage`, route + Toolbox tile wired. Reframes to 9:16 / 1:1 / 4:5 / 3:4. Broader Vertigo pipeline tracked as UC item M.
- ✓ #8 Real-ESRGAN Image/Video Upscaler — new `realesrgan` sidecar wrapping the portable `realesrgan-ncnn-vulkan.exe` (no Python ML deps at runtime). ImageEnhancerPage + VideoEnhancerPage rewritten with model picker, scale 2/3/4, format/CRF controls, batch queue. Two Toolbox tiles flipped to Ready (image + video upscaler).
- ✓ #12 whisper.cpp GPU sidecar — new `whisper-cpp` sidecar wrapping `whisper-cli.exe` (Vulkan/CUDA, no Python deps). SpeechToTextPage now has a Backend combo (faster-whisper vs whisper.cpp) and a VAD pre-filter checkbox.
- ✓ #6 GFPGAN Photo Restoration — new `gfpgan` sidecar (Apache-2.0 face restoration via GFPGAN v1.4). PhotoRestorationPage wired with model picker, upscale 1–4, weight slider, batch queue + Finished pivot. Toolbox tile under AI added.
- ✓ #9 .NET 10 LTS migration — all 4 C# projects + test project bumped net8.0 → net10.0; WindowsAppSDK 1.5 → 1.7; Microsoft.Extensions.* + System.Text.Json + System.Drawing.Common 8.0.0 → 10.0.0; version 2.3.0 → 2.4.0 synced across all manifests, README badge, and repo CLAUDE.md. Build clean.
- ✓ #14 JumpList Integration — taskbar/Start menu quick-launch shortcuts to Converter / Compressor / Editor / Downloader / Recorder / Toolbox; activation via `--route <key>` parsed in `MainWindow_Activated`.
- ✓ #17 VAD Pre-Filter for Whisper STT — already shipped as part of #12 (`VadCheck` toggle in SpeechToTextPage; `--vad` flag passed to whisper-cpp sidecar).
- ✓ #54 Light + system-following theme — `<ResourceDictionary.ThemeDictionaries>` with Catppuccin Latte-inspired Light variant; SolidColorBrushes switched to `{ThemeResource}` so existing pages get live theme switching with zero per-page edits.
- ✓ #19 + #31 ProRes / DNxHR / FFV1 — 9 new VideoCrush presets (ProRes 4 tiers + 4444; DNxHR SQ/HQ/HQX/444; FFV1 archival). Sidecar bypasses CRF/two-pass for intermediate codecs; CompressorPage gained "Professional / archival" sub-combo.
- ✓ #20 D3D12 Hardware Encode — verified shipped in v2.2 (h264/hevc/av1_d3d12va selectable as the `d3d12` accelerator).
- ✓ #30 JPEG XL — heicshift sidecar gained `.jxl` read/write via opt-in `pillow-jxl-plugin`; ImageConverterPage exposes JXL as an output format with quality slider (100 = lossless).
- ✓ #15 Auto-Subtitle — AiSubtitlePage rewritten end-to-end (Backend + Model + Language + Format + burn-in toggle); FFmpeg `subtitles=` filter for hard-coded captions; ToolboxPage tile flipped Future → Ready.
- ✓ #16 Demucs 6-stem — VocalRemoverPage gained 6-stem option; sidecar handles `6stem` arg; auto-overrides to `htdemucs_6s` model.
- ✓ #22 Chapter Marks Editor — new `chaptermark` sidecar (read via ffprobe + write via FFMETADATA1 codec-copy mux); new ChapterMarksPage with editable rows + Add/Remove/Save As; Toolbox tile under "Other tools".
- ✓ #52 RecordCast system audio — `--system-audio` flag + device combo; auto-mixes mic + loopback with `amix=2`.
- ✓ #53 RecordCast region capture — `--region "x,y,w,h"` flag + preset & custom region UI. Pause/resume + drag-to-select overlay deferred to v2.5.

---

## NOW (v2.4)

### Security / Dependency Pins

#### 1. Pin yt-dlp ≥ 2026.03.17 ✓ Shipped v2.4
2026-03-17 release includes extractor fixes and is current stable. Current pin is `≥2026.02.21`. Bump in `sidecar/streamkeep/requirements.txt` and installer manifest. **Impact 3 / Effort 1.** [S-1] Shipped at [`tools/streamkeep/requirements.txt`](tools/streamkeep/requirements.txt) — installer manifests carry no version pin so no other change required.

#### 2. Pin ONNX Runtime ≥ 1.25.1 ✓ Shipped v2.4
ORT 1.25.1 patches heap out-of-bounds read/write, Pad Reflect vulnerability, transpose optimizer bug, and 12 additional CPU kernel CVEs present in 1.25.0. CUDA 12.0+ is now the minimum GPU compute requirement (CUDA 11.x support dropped). Update `requirements.txt` in all ONNX-using sidecars (alphacut, lipsight, videosubtitleremover). **Impact 4 / Effort 1.** [S-2] Shipped: alphacut bumped from `>=1.25.0`; videosubtitleremover got a new explicit `onnxruntime>=1.25.1` floor (it pulls ORT transitively via `rapidocr-onnxruntime`); lipsight has no ORT path so no action needed there.

### Missing Sidecar / Route Wiring

#### 3. Vertigo Auto-Reframe sidecar ✓ Shipped v2.4
Source code exists in `tools/vertigo/`; no `sidecar.py` yet. MediaPipe face/body tracking → center-of-interest crop → output 9:16, 1:1, or 4:5. Wire to AutoReframePage. **Impact 4 / Effort 3.** [plan] Shipped: new [`tools/vertigo/sidecar.py`](tools/vertigo/sidecar.py) with `reframe` + `list-aspects` ops. Two modes: `static` is pure FFmpeg centred-crop (zero deps); `smart` samples frames at 1 Hz with MediaPipe face detection, smooths the largest-face track over a 5-frame window, and drives a piecewise-linear `crop=W:H:'<x_expr>'` over time. Falls back to static if MediaPipe / OpenCV not bundled or no faces found. Aspects: 9:16, 1:1, 4:5, 3:4. [`tools/vertigo/build.ps1`](tools/vertigo/build.ps1) bundles cv2 + mediapipe by default with `-NoSmart` switch for a lean static-only build. New [`Views/Pages/AutoReframePage`](src/UniversalConverterX.UI/Views/Pages/AutoReframePage.xaml) with aspect combo, static/smart radio group, CRF slider, batch queue. Route `auto-reframe` wired in `MainWindow.xaml.cs`, ToolboxPage tile flipped Planned → Ready ("Powered by Vertigo"). Note: this sidecar deliberately ships only the reframe op; the broader Vertigo editor pipeline (animated captions, B-roll, hook scoring, scene detection) remains under-consideration as roadmap item M.

#### 4. GifStudio route wiring ✓ Shipped v2.4
WebView2-hosted GIF editor source exists. Wire route in `MainWindow.xaml.cs` and add `sidecar.py` for FFmpeg → palette optimization → GIF pipeline with loop count and delay controls. **Impact 3 / Effort 2.** [plan] Shipped: new [`tools/gifstudio/sidecar.py`](tools/gifstudio/sidecar.py) two-pass FFmpeg `palettegen`+`paletteuse` pipeline with `make` + `list-presets` ops, [`tools/gifstudio/build.ps1`](tools/gifstudio/build.ps1) PyInstaller freeze, [`Views/Pages/GifMakerPage.xaml`](src/UniversalConverterX.UI/Views/Pages/GifMakerPage.xaml) batch queue UI with width / fps / loop / start / duration controls, route `gif-maker` wired in `MainWindow.xaml.cs`, ToolboxPage tile flipped Planned → Ready. Contract test KNOWN_EVENTS extended with `preset`.

#### 5. HEICShift sidecar ✓ Shipped v2.4
HEIC/HEIF decode + AVIF/WebP/JPEG output. No `sidecar.py` yet. Uses `Pillow-heif` + FFmpeg for metadata pass-through and ICC profile defaults. Wire to ImageConverterPage. **Impact 3 / Effort 2.** [plan] Shipped: new [`tools/heicshift/sidecar.py`](tools/heicshift/sidecar.py) Pillow + pillow_heif converter with `convert` + `list-formats` ops, alpha-flatten on white when target lacks alpha, ICC + EXIF pass-through with explicit `--strip-icc` / `--strip-exif` opt-outs, and frozen-guard. Build script [`tools/heicshift/build.ps1`](tools/heicshift/build.ps1) bundles `Pillow>=10.0.0` + `pillow-heif>=0.16.0` via PyInstaller `--collect-all pillow_heif`. New page [`Views/Pages/ImageConverterPage.xaml`](src/UniversalConverterX.UI/Views/Pages/ImageConverterPage.xaml) with format combo (jpeg/png/webp/avif/heic/tiff/bmp), quality slider, EXIF/ICC strip checkboxes, batch queue + finished pivot. Route `image-converter` wired in `MainWindow.xaml.cs`, ToolboxPage tile flipped Planned → Ready. JPEG XL + RAW deferred (need libjxl / rawpy build matrix).

#### 6. GFPGAN Photo Restoration sidecar ✓ Shipped v2.4
PhotoRestorationPage stub exists. GFPGAN v1.4 (Apache 2.0) restores old/degraded photos and enhances faces. Pair with Real-ESRGAN for full-photo restoration pipeline (GFPGAN on faces, Real-ESRGAN on background). `pip install gfpgan` — CPU + GPU. Wire to PhotoRestorationPage. **Impact 4 / Effort 3.** [R-5b] Shipped: new [`tools/gfpgan/sidecar.py`](tools/gfpgan/sidecar.py) NDJSON wrapper around `gfpgan.GFPGANer.enhance()` with frozen-guard + dev-mode pip-install fallback. Two ops: `restore` (one image in/out, configurable upscale 1-4 + weight 0.0-1.0 + only-center-face), `list-models`. [`tools/gfpgan/build.ps1`](tools/gfpgan/build.ps1) bundles gfpgan + basicsr + facexlib + torch via PyInstaller `--collect-all`. PhotoRestorationPage rewritten end-to-end: GFPGAN model picker, upscale combo, restoration-strength slider with mood label, only-centre-face checkbox, batch queue, Finished pivot, 15-min watchdog timeout. New ToolboxPage tile under AI category flipped to Ready. Models intentionally not vendored; [`tools/gfpgan/models/.gitkeep`](tools/gfpgan/models/.gitkeep) cites GFPGANv1.4.pth (~330 MB, Apache-2.0) from upstream releases.

#### 7. edge-tts Text-to-Speech sidecar ✓ Shipped v2.4
TextToSpeechPage stub exists. `edge-tts` 7.2.8 (MIT) provides 100+ neural voices in 50+ languages via Microsoft Edge TTS — no API key, voices cached locally after first use. Expose: voice selection, speed ×0.5–2.0, pitch, output format (MP3/WAV/OGG). **Impact 4 / Effort 2.** [S-7] Shipped: new [`tools/edge-tts/sidecar.py`](tools/edge-tts/sidecar.py) async wrapper around `edge-tts.Communicate.stream()` with `list-voices` (locale-filterable) + `speak` ops; native MP3 output, ffmpeg transcode pipeline for WAV/FLAC/OGG/Opus/M4A targets when ffmpeg is on `PATH`; frozen-guard. [`tools/edge-tts/build.ps1`](tools/edge-tts/build.ps1) PyInstaller freeze with `--collect-all edge_tts`. [`Views/Pages/TextToSpeechPage`](src/UniversalConverterX.UI/Views/Pages/TextToSpeechPage.xaml) rebuilt: locale filter combo, voice picker populated from sidecar enumeration, rate/pitch sliders with live labels, format combo, Save-to picker, char counter, ProgressBar + cancel. ToolboxPage tile flipped Future → Ready ("Powered by edge-tts").

#### 8. Real-ESRGAN Image/Video Upscaler sidecar ✓ Shipped v2.4
ImageUpscalerPage and VideoEnhancerPage stubs exist. Use `realesrgan-ncnn-vulkan` portable binary (Intel/AMD/NVIDIA GPU via Vulkan, no Python, ships in `tools/`). Models on first use → `tools/_models/`: `RealESRGAN_x4plus` (photo 4×), `RealESRGAN_x4plus_anime_6B` (anime 4×), `realesr-general-x4v3` (fast general). SHA-256 verified. **Impact 5 / Effort 3.** [R-5] Shipped: new [`tools/realesrgan/sidecar.py`](tools/realesrgan/sidecar.py) NDJSON wrapper around the portable `realesrgan-ncnn-vulkan.exe` (no Python ML deps at runtime). Three ops: `upscale-image`, `upscale-video` (extract → ncnn-vulkan → re-encode with audio passthrough), `list-models`. [`tools/realesrgan/build.ps1`](tools/realesrgan/build.ps1) downloads the upstream Windows release with SHA-256 verification + freezes the Python wrapper. Two pages rewritten end-to-end: [`ImageEnhancerPage`](src/UniversalConverterX.UI/Views/Pages/ImageEnhancerPage.xaml) (model picker, scale 2/3/4, format combo, TTA toggle, batch queue) and [`VideoEnhancerPage`](src/UniversalConverterX.UI/Views/Pages/VideoEnhancerPage.xaml) (model picker auto-selecting `realesr-animevideov3`, scale 2/3/4, x264 CRF slider, 60-min watchdog timeout per file). Toolbox tiles flipped Planned → Ready: image upscaler + new "Video Upscaler" tile. Routes already existed in `MainWindow.xaml.cs`; nav search entries added.

### Platform Migration

#### 9. .NET 10 LTS Migration ✓ Shipped v2.4
.NET 8 mainstream support ends **2026-11-10** — hard deadline. .NET 10 (GA, LTS, supported until 2028-11) is the successor. HandBrake 1.11 already requires .NET 10 Desktop Runtime on Windows. Steps: update `<TargetFramework>` in all `.csproj` files, audit WinAppSDK compatibility, update CI workflow. **Impact 5 / Effort 3.** [R-1, S-NET10] Shipped: bumped `Directory.Build.props` (root + src/) from `net8.0` → `net10.0` and LangVersion 12 → 13. Per-project `TargetFramework` updated for all four C# projects (Core, Console, ShellExtension, UI) plus the test project. WindowsAppSDK 1.5.240311000 → 1.7.250606001. Microsoft.Extensions.* family bumped 8.0.0 → 10.0.0; System.Text.Json 8.0.6 → 10.0.0; System.Drawing.Common 8.0.0 → 10.0.0; CommunityToolkit.Mvvm 8.2.2 → 8.4.0; Spectre.Console 0.48 → 0.49. Removed `<EnablePreviewFeatures>true</EnablePreviewFeatures>` from Core (the .NET 10 analyzer escalates CA2252 to errors against UI consumers; Core wasn't actually using preview language features). Version strings synced: 2.3.0 → 2.4.0 across all `<Version>` elements + README badge + repo CLAUDE.md. Build verified clean Debug|x64; only advisory warnings (NU1510 prune, MVVMTK0045 AOT-partial-property suggestions, CA2024 EndOfStream-in-async edge case).

### AI Engine Quality

#### 10. Lossless Trim Mode (stream copy, no re-encode) ✓ Shipped v2.3 (verified v2.4)
Add a `--lossless` flag to ClipForge that routes trim through `ffmpeg -c copy`. Expose as a "Lossless Cut" toggle — default for trim-only operations. Zero quality loss, 10–100× faster than transcoding. **Impact 5 / Effort 2.** [R-3] Already in tree: `tools/clipforge/sidecar.py:133` runs `ffmpeg ... -c copy`; `EditorPage.xaml:272` exposes `LosslessCheck` defaulted to `IsChecked="True"`; `EditorPage.xaml.cs:524` passes `--lossless` through.

#### 11. RNNoise Noise Remover sidecar ✓ Shipped v2.4
NoiseRemoverPage stub exists. RNNoise (Mozilla, BSD-licensed) removes broadband background noise from speech audio. Python sidecar via `rnnoise_python` or ONNX export. Single-pass, <1 s overhead per minute. **Impact 4 / Effort 2.** [R-9] Shipped via FFmpeg's built-in `arnndn` filter (zero Python ML deps, ships with FFmpeg ≥4.4): new [`tools/rnnoise/sidecar.py`](tools/rnnoise/sidecar.py) with `denoise` + `list-models` ops. Model resolution walks `--model` → `RNNOISE_MODEL` env → `UCX_MODEL_DIR/rnnoise/` → bundled `tools/rnnoise/models/`; `cb.rnnn` is the auto-default when present. Output supports muxed (video pass-through, audio replaced) or audio-only modes; codec selection drives off the output extension. NoiseRemoverPage rewritten end-to-end: model picker (auto-discovered + Refresh), mode/format combos, drag-drop batch queue, ProgressBar + cancel. ToolboxPage tile flipped Future → Ready. Models intentionally not vendored — `tools/rnnoise/models/.gitkeep` cites trusted sources (xiph/rnnoise, GregorR/rnnoise-models).

#### 12. whisper.cpp GPU sidecar (Vulkan/CUDA) ✓ Shipped v2.4
Current Whisper sidecar uses faster-whisper (Python/CUDA). Add secondary path: whisper.cpp v1.8.4 single `.exe`, Vulkan GPU, no Python dependency, 6 model sizes. v1.8.4 adds Silero VAD v6.2.0 (auto-skip silence, reduce hallucinations), GPU device selection (`-g`), and 12× speedup on Intel iGPU. Route: prefer whisper.cpp if CUDA unavailable; prefer faster-whisper if CUDA 12.0+ present. **Impact 3 / Effort 3.** [R-8] Shipped: new [`tools/whisper-cpp/sidecar.py`](tools/whisper-cpp/sidecar.py) NDJSON wrapper around `whisper-cli.exe`. Three ops: `transcribe` (auto-resamples to 16 kHz mono via FFmpeg, parses progress + segments from whisper-cli output), `list-models` (GGUF discovery), `list-backends` (probes `--help` for vulkan/cuda/coreml/vad flags). [`tools/whisper-cpp/build.ps1`](tools/whisper-cpp/build.ps1) downloads the upstream Windows release with SHA-256 verification (placeholder pin emits a warning until first vetted download). SpeechToTextPage gained a Backend combo (faster-whisper / whisper.cpp) plus a VAD checkbox; the existing C# routing now switches sidecar name + arg shape per backend. Models intentionally not vendored; [`tools/whisper-cpp/models/.gitkeep`](tools/whisper-cpp/models/.gitkeep) lists model sizes + canonical source (huggingface.co/ggerganov/whisper.cpp).

### Repo & CI Hygiene

#### 48. Drop tracked `obj/` from git ✓ Shipped v2.4
`.gitignore` lists `obj/` and `bin/` but the directories are still tracked from before the rule was added. v2.3.0's release commit alone added ~16k lines of build-artifact churn (`project.assets.json` etc.). One-time fix: `git rm -r --cached **/obj **/bin`, then commit. Prevents every release from polluting diffs and review. **Impact 3 / Effort 1.** Shipped via `git rm -r --cached` over 31 tracked files.

#### 49. Sidecar contract conformance test (CI gate) ✓ Shipped v2.4
The v2.3 wave shipped a regression class: lipsight bootstrapped without a `getattr(sys, 'frozen', False)` short-circuit (PyInstaller fork-bomb risk) and emitted `error` events with no `code` field (every failure showed as `"unknown"` in the UI). Add a Python unit test under `tests/sidecar_contract/` that grep-validates every `tools/*/sidecar.py` for: (a) frozen-guard before any `pip install` invocation, (b) `code` field on every emitted `error` event, (c) NDJSON event names match the documented set. Wire to GitHub Actions PR check. Sub-task of existing #46. **Impact 4 / Effort 1.** Shipped as [`tests/sidecar_contract/check_contract.py`](tests/sidecar_contract/check_contract.py) — AST-walking, no pytest dependency, runs from `tools/build-all.ps1` (#50) before any build.

#### 50. Unified `tools/build-all.ps1` orchestrator ✓ Shipped v2.4
Each sidecar has its own `build.ps1`; v2.4 ships 4 new frozen sidecars (demucs, whisper-stt, lipsight, GFPGAN, edge-tts, RNNoise once added) with no single entry point. Build a top-level `tools/build-all.ps1 [-Tools demucs,whisper-stt] [-Clean] [-Parallel]` that fans out across `tools/*/build.ps1`, gathers exit codes, and writes a build report. CI artifact upload becomes one step instead of N. **Impact 3 / Effort 1.** Shipped at [`tools/build-all.ps1`](tools/build-all.ps1) with `-Tools`, `-Clean`, `-SkipContract`, `-Parallel` switches and JSON+Markdown build reports under `artifacts/build-reports/`.

#### 51. SidecarRunner no-progress watchdog ✓ Shipped v2.4
`SidecarRunner.RunAsync` honors cancellation tokens but has no defense against silent hangs — a sidecar that emits no `progress`/`log`/`stem`/`segment` events for N minutes (configurable, default 600 s) sits forever. Add a watchdog timer that resets on every NDJSON event; when it fires, log a stuck-process warning and call `process.Kill(entireProcessTree: true)`. Pattern reference: NVMe Patcher's `EventLogWatcher` push model in [`win11-nvme-driver-patcher/src/NVMeDriverPatcher.Watchdog/Program.cs`](../win11-nvme-driver-patcher/src/NVMeDriverPatcher.Watchdog/Program.cs). **Impact 4 / Effort 2.** [internal-nvme] Shipped via linked CTS in `SidecarRunner.RunAsync` — distinct `stuck_sidecar` error code, opt-in `silenceTimeout` parameter for sidecars that legitimately run quietly during model load / network upload.

---

## NEXT (v2.5–v2.6)

### Platform Upgrades

#### 13. WinAppSDK 2.0 Upgrade
UCX targets WinAppSDK 1.5. WinAppSDK 2.0.1 (released 2026-04-29) ships:
- **`SystemBackdropElement`**: place Mica/Acrylic anywhere in XAML layout — closes the major WinUI 3 in-content backdrop gap UCX works around today
- **Storage Pickers v2**: file type grouping, persistent `SettingsIdentifier` per tool (remembers last folder), multi-folder picking, `SuggestedStartFolder`, `Title`
- **Windows ML refactor**: `Microsoft.Windows.AI.MachineLearning` base package, ORT 1.24.5 bundled, new `AIFeatureReadyState` values for Copilot+ PC NPU detection
- **WebView2 drag support**: drag text/HTML/images out of WebView2 (useful for GifStudio)
- **`PopupAnchor`** relative popup positioning

Requires package family name review; migration guide available. **Impact 4 / Effort 3.** [S-5]

#### 14. JumpList Integration ✓ Shipped v2.4
Windows JumpList provides quick-launch toolbox entries from the taskbar icon without opening the app. WinUI Gallery 2.8 ships a reference implementation. Map most-used tools (Convert, Compress, Trim, Record) to JumpList tasks via `JumpList.LoadCurrentAsync()`. **Impact 3 / Effort 1.** [S-8] Shipped: `App.OnLaunched` calls `ConfigureJumpListAsync` once on first activation, populating six tasks (Converter / Compressor / Editor / Downloader / Recorder / Toolbox) under a "UCX shortcuts" group. Each `JumpListItem` carries `--route <key>` arguments; `MainWindow_Activated` parses `Environment.GetCommandLineArgs()` and routes the new instance to the requested page. Best-effort wrapped in try/catch so locked-down profiles or packaged-vs-unpackaged differences never block app launch.

#### 54. Light + system-following theme ✓ Shipped v2.4
UCX is dark-only (App.xaml `RequestedTheme="Dark"` + brand brushes hard-coded against `BrandSurface*` darks). User CLAUDE.md states "Include a light theme option when practical." Add `Themes/LightTheme.xaml` with a parallel brand palette, drive selection from a Settings option (Dark / Light / System), persist via `SettingsService`, and bind via `RequestedTheme = Application.Current.RequestedTheme`. Pattern reference: [`Images/src/Images/Themes/DarkTheme.xaml`](../Images/src/Images/Themes/DarkTheme.xaml) + Catppuccin variants used in the Images viewer. **Impact 3 / Effort 3.** [internal-images] Shipped via `<ResourceDictionary.ThemeDictionaries>` with `Default` (existing dark) + `Light` (Catppuccin Latte-inspired) keys for every BrandXxx color. SolidColorBrush definitions in `App.xaml` switched from `{StaticResource BrandX}` → `{ThemeResource BrandX}` so the brushes reactively re-resolve their `Color` property when the theme dictionary changes — zero per-page churn (every consumer keeps using `{StaticResource SurfaceBrush}` etc.). Settings already had a Theme combo wired to `App.ApplyTheme(ElementTheme)` which sets `FrameworkElement.RequestedTheme` on the XamlRoot, so live theme switching now propagates through the entire UI immediately.

#### 55. Code signing for release artifacts
Shipped `UniversalConverterX.exe` is unsigned today, so first launch hits SmartScreen "Unknown publisher" — major trust friction and a hard blocker for #45 (WinGet/Microsoft Store). Acquire a code-signing certificate (DigiCert / Sectigo / SignPath OSS), wire `signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256` into the release workflow before `gh release upload`. Apply to UI exe, console exe, shell extension dll, and each frozen sidecar. **Impact 5 / Effort 2** (cert procurement + workflow plumb; SmartScreen reputation builds once signed releases ship).

### AI Features

#### 15. Auto-Subtitle sidecar (Whisper → SRT/VTT) ✓ Shipped v2.4
AiSubtitlePage stub exists. Extend whisper-stt sidecar to output SRT/VTT subtitle files alongside transcripts. Optional burn-in path: `ffmpeg -vf subtitles=...` for hard-coded subtitles. Optional LibreTranslate post-pass for translated subtitles. **Impact 5 / Effort 2.** [R-7, R-8] Shipped: AiSubtitlePage rewritten end-to-end with Backend (whisper-stt / whisper-cpp) + Model + Language + Format combos. Both whisper sidecars already produce SRT/VTT — page wires the right arg shape per backend. Optional burn-in checkbox runs `ffmpeg -vf subtitles='<path>' -c:v libx264 ...` after transcription with proper Windows path escaping for the FFmpeg filter graph. ToolboxPage tile flipped Future → Ready ("Powered by Whisper"). LibreTranslate post-pass remains under-consideration for v2.5.

#### 16. Demucs Full Stem Separation (4/6 stem) ✓ Shipped v2.4
Extend VocalRemoverPage to expose a stem selector: 4-stem (drums/bass/vocals/other) and 6-stem (adds guitar/piano) via `htdemucs_6s` model. Output each stem as a separate WAV/FLAC file with clear names for DAW import. Note: demucs upstream archived 2025-01-01; PyPI package still functional. **Impact 4 / Effort 2.** [R-6] Shipped: StemCombo gained "6-stem (+guitar / piano — needs htdemucs_6s)" option; demucs sidecar's `resolve_stems()` handles `6stem` arg explicitly. VocalRemoverPage auto-overrides the model to `htdemucs_6s` when 6-stem is selected (otherwise the user would silently miss the guitar/piano stems with a default htdemucs_ft).

#### 17. VAD Pre-Filter for Whisper STT ✓ Shipped v2.4 (with #12)
Integrate Silero VAD v6.2.0 (available in whisper.cpp v1.8.4 and as standalone `silero-vad` pip package) as a pre-processing step before transcription — skips silence regions, reduces hallucinations. Expose as a toggle in SpeechToTextPage. **Impact 3 / Effort 2.** [R-8] Shipped together with the whisper.cpp sidecar in #12 — VadCheck toggle in `SpeechToTextPage.xaml` adds `--vad` to the whisper-cli invocation when checked. The standalone `silero-vad` pip package is still available as a future upgrade for the Python-side `whisper-stt` (faster-whisper) backend if needed.

#### 18. Scene Detection + Smart Split (PySceneDetect sidecar) ✓ Shipped v2.4
SmartTrimmerPage stub exists. PySceneDetect v0.6.7 as sidecar: detect scene cuts → output timestamped chapter list (CSV/OTIO/EDL CMX 3600). Actions: auto-split into segments, insert as chapter markers, or feed into ClipForge batch trim. OTIO/EDL formats (v0.6.6+) enable direct DaVinci Resolve import. FFmpeg `silencedetect` filter as companion for audio-based splits. **Impact 4 / Effort 3.** [R-18, R-3] Shipped: new `tools/scenedetect/sidecar.py` wrapping PySceneDetect 0.6.7+. Subcommand `detect --input ... --detector content|threshold --threshold N --min-scene-len N [--output-csv path] [--output-edl path]`. Per-frame progress callback drives the standard `progress` event; one `scene` event per detected cut with `index/start_seconds/end_seconds/start_frame/end_frame/start_tc/end_tc`. CSV export = spreadsheet-friendly; EDL export = CMX 3600 (DaVinci Resolve / Premiere Pro). `tools/scenedetect/build.ps1` PyInstaller freeze with `--collect-all scenedetect` + `opencv-python-headless`. New `SceneDetectPage` with file picker, detector / threshold / min-scene-len controls, scene list bound to `ObservableCollection<SceneRow>` (#index | start TC | end TC | duration), Export CSV / Export EDL buttons. New Toolbox tile under Video tools (sits next to the Planned Smart Trimmer stub). Contract test: added `scene` to `KNOWN_EVENTS` (19 sidecars conform). Frozen-guard not needed -- sidecar bundles deps at build time, no runtime pip.

### Recorder & Capture

#### 52. RecordCast system-audio loopback (WASAPI) ✓ Shipped v2.4
RecordCast captures microphone via DirectShow but cannot record desktop audio — every screencast that wants narration over a video/game/Zoom playback needs system loopback. FFmpeg supports it via `-f dshow -i audio=virtual-audio-capturer` or, preferred, WASAPI loopback (no virtual driver install). Detect Windows version, prefer WASAPI on Windows 10+, fall back to dshow. Expose an "Include system audio" toggle on RecorderPage alongside the existing mic combo, and a "Mic + system" mix mode. Most-requested gap-filler in screen-recorder competitor reviews. **Impact 4 / Effort 2.** Shipped: recordcast sidecar gained `--system-audio <device>` (empty string = `virtual-audio-capturer` default). When both mic + loopback are present, FFmpeg `-filter_complex amix=inputs=2:duration=longest:dropout_transition=2[a]` mixes them into a single AAC track. RecorderPage gained a "Capture system audio (loopback)" checkbox + a system-audio device combo populated with detected loopback devices (Stereo Mix / What U Hear / virtual-audio-capturer / loopback).

#### 53. RecordCast region capture + pause/resume ✓ Shipped v2.4 (region; pause/resume deferred)
Screen recorder is full-screen-only today. (a) Region capture: `gdigrab -offset_x N -offset_y N -video_size WxH` already supports rect; add a region picker overlay (transparent `Window` with adornment for drag-to-select), persist last region in settings. (b) Pause/resume: stop the active ffmpeg process on Pause, write segment to `_part01.mp4`, restart on Resume into `_part02.mp4`, on Stop run `ffmpeg -f concat -i list.txt -c copy` to merge — lossless join, no re-encode. **Impact 4 / Effort 3.** Region shipped: recordcast sidecar gained `--region "x,y,w,h"` flag passed through to gdigrab. RecorderPage gained Region card with three preset sizes (1920×1080 / 1280×720 / 800×600 at origin) plus a Custom... mode revealing X/Y/W/H text boxes. Drag-to-select overlay window remains a v2.5 polish task. Pause/resume is also deferred — the current API surface (queue → start → stop) makes pause non-trivial; tracking as a v2.5 follow-up.

### Encoder Improvements

#### 19. ProRes / DNxHR Export Presets ✓ Shipped v2.4
HandBrake 1.11 and FFmpeg 8.1 both added ProRes and DNxHR (Avid) encoders. Add professional-tier presets to VideoCrush and the native Converter: ProRes 422, ProRes 4444, DNxHR HQ, DNxHR SQ. Target audience: video editors who need intermediate codecs for NLE handoff. **Impact 3 / Effort 2.** [R-1, S-3] Shipped: 9 new VideoCrush presets — ProRes 422 (Proxy / LT / SQ / HQ) + ProRes 4444 + DNxHR (SQ / HQ / HQX / 444). Sidecar bypasses CRF/two-pass for `prores_ks` / `dnxhd` codecs and routes through a profile-driven encode path with correct pixel formats per profile. CompressorPage gained a "Professional / archival ▾" radio + sub-combo exposing all presets. CLI `--prores-profile` and `--dnxhd-profile` flags added.

#### 20. D3D12 Hardware Encode (H.264 + AV1) ✓ Shipped v2.4 (with #2.2)
FFmpeg 8.1 added `h264_d3d12va` and `av1_d3d12va` encoders alongside the existing `hevc_d3d12va`. VideoCrush already uses D3D12 for GPU-accelerated resize (`scale_d3d12`). Expose D3D12 encode as a selectable hardware accelerator alongside NVENC/AMF/QSV. Also surfaces AMD VCN AV1 10-bit encode option from HandBrake 1.11. **Impact 3 / Effort 2.** [S-3, R-1] Verified shipped already in v2.2.0 — VideoCrush sidecar's `_HW_ENCODER` map at `tools/videocrush/sidecar.py:109-114` includes the `d3d12` accelerator with `h264_d3d12va` / `hevc_d3d12va` / `av1_d3d12va`; CompressorPage HW combo at line 230 has the "D3D12 (Windows)" item.

### Editor & Toolbox

#### 21. Timeline Waveform + Thumbnail Strip ✓ Shipped v2.4
ClipForge needs a visual waveform + keyframe thumbnail strip below the seek bar before editor feature expansion. Pre-extract thumbnails at 1 fps via `ffmpeg -vf fps=1` and waveform image via `ffmpeg -vf showwavespic`. Display in a `ScrollViewer` → `Image` strip bound to seek position. **Impact 5 / Effort 3.** [R-3] ✓ Shipped v2.4: new `op_timeline` in `tools/clipforge/sidecar.py` writes `tn_NNNNN.jpg` thumbnails (configurable fps + height, scaled fast_bilinear, JPEG q5) plus a `waveform.png` rendered with `showwavespic=s=2400x80:colors=0x6dd3ff` to a per-clip output dir; emits one `thumb` event per generated frame for streaming UI updates. New `TimelinePreviewPage` (`Views/Pages/TimelinePreviewPage.xaml`) with file picker, fps + thumb-height NumberBoxes, horizontal `ScrollViewer` over an `ItemsControl`-backed thumbnail strip (each cell is 120×80 with bottom-overlay timecode label), waveform `Image` below, seek `Slider` bound to clip duration that auto-scrolls the strip to keep the cursor centred. Toolbox tile under Video tools + nav search entry. Output dir under `%TEMP%\ucx_timeline_<guid>\` so multiple sessions don't collide; "Open output folder" reveals it in Explorer. Contract test: added `thumb` to `KNOWN_EVENTS`. EditorPage integration deferred to a follow-up that consumes the same sidecar op (the visible Toolbox surface ships the value today).

#### 22. Chapter Marks Editor (MKV/MP4) ✓ Shipped v2.4
Edit embedded chapter markers in MKV and MP4 files via FFmpeg metadata. Expose as a toolbox workspace (MetadataEditor stub adjacent). LosslessCut's most-used feature class for podcast/long-form audiences. **Impact 3 / Effort 2.** [R-3] Shipped: new `chaptermark` sidecar with `read` (ffprobe `-show_chapters` → NDJSON `chapter` events) + `write` (build FFMETADATA1 chapter file → `ffmpeg -i src -i chapters.ffmeta -map_metadata 1 -codec copy out` — fast lossless mux, no re-encode). New `ChapterMarksPage` with file picker, editable list of chapter rows (start, end, title), Add Chapter / Remove buttons, Save As... picker. New Toolbox tile under "Other tools" + nav search entry.

#### 23. Rewrap Without Re-encode (Container Swap) ✓ Shipped v2.3
`ffmpeg -c copy` container remux — MKV↔MP4↔MOV↔TS without quality loss. 10–100× faster than transcoding. Expose as a "Rewrap" option in both Converter and Toolbox. **Impact 4 / Effort 1.** [R-3] Shipped: `tools/clipforge/sidecar.py:331` `op_rewrap`; ClipForge editor exposes a "Rewrap" operation tile with target-extension picker (mp4/mkv/mov/ts). Future polish: surface in the Converter's main format picker too (separate item if demand).

#### 24. Multi-Track Stream Management ✓ Shipped v2.4
Add/remove audio, subtitle, and data tracks from a video container without re-encoding. LosslessCut's most-requested feature class. Expose as a track manager panel in ClipForge sidebar. **Impact 4 / Effort 3.** [R-3] Shipped: three new clipforge ops -- `track-list` (ffprobe enumeration; emits one `track` event per stream with codec / language / title / channels / dimensions / default flag), `track-remove` (builds an `-map 0:N` chain that includes every stream EXCEPT the comma-separated drop list, with `-c copy -map_metadata 0` for lossless mux; refuses to strip every stream), `track-add` (attach an external audio or subtitle file as a new stream via `-map 0 -map 1 -c copy`, with optional ISO-639 `--language` and `--title` metadata applied via `-metadata:s:N`). New `TrackManagerPage` with file picker, track list cards (#index | colored codec_type chip | codec/dimensions/channels/language detail | tick-to-remove checkbox), Apply changes button (Save As... picker, lossless mux), Add track... button (file picker + lang/title ContentDialog form). Toolbox tile under Video tools + nav search entry. Contract test: added `track` to `KNOWN_EVENTS` (19 sidecars conform).

### Library & Automation

#### 25. Watch Folder Automation ✓ Shipped v2.4
Monitor a folder via `FileSystemWatcher`; apply a user-defined conversion profile to new files automatically. Queue fed into existing conversion pipeline. Unmanic and Tdarr prove sustained demand for this pattern. **Impact 4 / Effort 3.** [R-9, R-10] Shipped: `IWatchFolderService` (`src/UniversalConverterX.UI/Services/WatchFolderService.cs`) — singleton, eager-resolved at app launch so saved profiles begin watching immediately. Each profile (name / folder / glob filter / action / preset / output dir / enabled) persists to `%LocalAppData%\UniversalConverterX\watches.json`. Per-profile `FileSystemWatcher`; debounced via 3-sample stable-size detection + exclusive-open probe before processing (rejects files still being written). Maps Compress action -> videocrush sidecar, Convert action -> clipforge `rewrap`. New `WatchFoldersPage` with profile cards (toggle switch / edit / remove), New Watch ContentDialog form, recent activity log (200-event ring). New Toolbox tile under "Other tools" + nav search entry. PowerShell side covered by `Watch-MediaFolder` cmdlet shipped with #27.

#### 26. Conversion History Dashboard ✓ Shipped v2.4
Persistent SQLite log of every job (timestamp, source, target, engine, duration, size delta, exit code). History page with search, filter, re-run, and aggregate "space saved" display. **Impact 3 / Effort 2.** [R-10, R-13] Shipped: `IHistoryService` (`src/UniversalConverterX.UI/Services/HistoryService.cs`) backed by `Microsoft.Data.Sqlite` 10.0.0; DB at `%LocalAppData%\UniversalConverterX\history.db` with `history` table (id PK / timestamp_utc / engine / action / source_path / output_path / source_bytes / output_bytes / duration_sec / success / error_code / error_message / profile) plus indexes on timestamp + engine. `LogAsync` / `QueryAsync(search, limit)` / `SummarizeAsync` (count + ok + fail + total source/output bytes + space-saved aggregate via SQL CASE) / `DeleteAsync` / `ClearAsync`. New `HistoryPage` with stat header (total / ok / fail / saved), AutoSuggestBox debounced live filter, scrollable card list with Open-output (Explorer `/select`), Re-run (routes to engine's primary page), Forget. Hooked: `WatchFolderService` logs every auto-job; `CompressorPage` logs every videocrush job (skip on user cancel so failed-count stays meaningful). New Toolbox tile + nav search entry; Toolbox row uses HistoryPage's `\uE81C` Library glyph. Eager-resolved at app launch alongside the watch service.

#### 27. PowerShell Module (`UniversalConverterX.psm1`) ✓ Shipped v2.4
`Convert-MediaFile`, `Compress-MediaFile`, `Get-MediaInfo`, `Watch-MediaFolder` cmdlets. Each wraps `ucx` CLI with typed parameters and `Write-Progress` output. Target: sysadmin batch workflows. **Impact 3 / Effort 2.** Shipped: `integrations/powershell/UniversalConverterX.psm1` + `.psd1` manifest (v2.4.0) + README. Discovery cmdlets (`Get-UcxRoot`/`Get-UcxExe`/`Get-UcxSidecar`/`Test-Ucx`) resolve install via `$env:UCX_HOME` → module dir → `Program Files` → `LocalAppData`. `Compress-MediaFile` uses an `Invoke-UcxNdjson` helper that parses sidecar NDJSON: `progress` → `Write-Progress` (percent + stage), `log` → `Write-Warning`/`Write-Verbose` by level, `error` → `Write-Error` with sidecar error code; other domain events (`format`/`voice`/`chapter`) forward to the pipeline. `Watch-MediaFolder` is a `FileSystemWatcher`-backed watcher with `-Action Convert|Compress` (covers W-25 via PowerShell). Strict-mode clean, ASCII-only (no unicode dashes), array-of-`Join-Path` cells parenthesised for PS 5.1 parser.

#### 28. REST API Server Mode ✓ Shipped v2.4
`ucx serve` binds to `127.0.0.1:PORT`. OpenAPI endpoints: `POST /convert`, `GET /jobs/{id}`, `GET /tools`. Enables integration with n8n, Power Automate Desktop, and custom scripts without shell subprocess. LosslessCut and Transmute both ship HTTP APIs. **Impact 3 / Effort 3.** [R-2, R-3] Shipped: `src/UniversalConverterX.Console/Commands/ServeCommand.cs` -- `ucx serve [--port 17654] [--host 127.0.0.1]`. Built on `System.Net.HttpListener` (zero new package deps; ASP.NET Core not pulled in). Endpoints: `GET /healthz` -> `{ok,version}`; `GET /tools` -> per-sidecar `{name,available,path}` list (walks for `tools/<name>/dist/<name>.exe`); `POST /convert` -> body `{engine,args[]}` spawns the sidecar in-process and returns `{job_id}`; `GET /jobs/{id}` -> `{running,exit,events_total,started,finished}`; `GET /jobs/{id}/events?since=N` streams accumulated NDJSON from the cursor. `JobManager` tracks live `Process`es and kills them on Ctrl+C / shutdown so server exit doesn't leak ffmpeg children. Stderr is wrapped into NDJSON `{event:"log",level:"stderr"}` envelopes so the consumer can treat all lines uniformly. Smoke-tested: `/healthz` returns `{"ok":true,"version":"2.4.0"}`, `/tools` enumerates all 19 sidecars with availability flags.

### Quality & Reliability

#### 29. VMAF Quality Analysis Tool ✓ Shipped v2.4
VMAF comparison workspace in Format Inspector: reference + distorted → per-frame score chart + mean/harmonic-mean. Uses `ffmpeg -vf libvmaf`. Surfaces quality budget signal for VideoCrush. **Impact 3 / Effort 3.** [R-11] Shipped: new `op_vmaf` in `tools/clipforge/sidecar.py` (no new sidecar — clipforge already wraps ffmpeg/ffprobe). Runs `ffmpeg -i distorted -i reference -lavfi libvmaf=log_path=...:log_fmt=json -f null -` to a temp JSON file, parses per-frame VMAF scores, emits `vmaf` events (downsampled to ~200 events for long clips), and a final `vmaf_summary` event with mean / harmonic_mean / min / max / pooled_mean / pooled_harmonic / below_70_percent. Harmonic mean follows Netflix's pooling guidance (penalises worst-frame outliers more than arithmetic mean). New `VmafAnalysisPage` with reference / distorted file pickers, run button, large-stat header (Mean / Harmonic / Min / % below 70), live event log. Toolbox tile + nav search entry under "Other tools". Contract test: added `vmaf` and `vmaf_summary` to `KNOWN_EVENTS` (`tests/sidecar_contract/check_contract.py` -> 18 sidecars conform).

#### 30. JPEG XL Encode/Decode ✓ Shipped v2.4
Surface JPEG XL as a conversion target in the native Converter with a quality slider (via `libjxl`, planned UCX dependency). Shutter Encoder ships this as a named output option. **Impact 3 / Effort 1.** [R-11] Shipped: heicshift sidecar gained `.jxl` input/output via opt-in `pillow-jxl-plugin` (best-effort install in build.ps1 — frozen sidecar degrades to a clean `missing_jxl_plugin` error if the wheel didn't install). Quality slider drives lossy encode (`quality=N, effort=7`); `quality=100` switches to true lossless. ImageConverterPage format combo gained "JPEG XL (.jxl)" entry; ImageExtensions list accepts `.jxl` for input.

#### 31. FFV1 Archival Codec Preset ✓ Shipped v2.4
Add an "Archive (FFV1 + FLAC in MKV)" preset to VideoCrush. FFV1 is lossless, checksummed. FFmpeg 8.1 shipped Vulkan FFV1 encode/decode. **Impact 3 / Effort 1.** [R-11, S-3] Shipped via the new `archive-ffv1` preset in `tools/videocrush/sidecar.py` PRESETS dict — uses `-c:v ffv1 -level 3 -coder 1 -context 1 -g 1 -slices 24 -slicecrc 1` (slice-CRC checksums) with FLAC audio. Sidecar warns if the user asked for a non-MKV container. CompressorPage's Professional sub-combo lists "FFV1 + FLAC archival (lossless, MKV)" as a selectable preset.

### Accessibility

#### 32. Windows Narrator + Keyboard Navigation Audit ✓ Shipped v2.4
Audit all WinUI 3 pages for: `AutomationProperties.Name` on unlabeled controls, tab-stop order, focus ring visibility, progress bar accessible names. HandBrake 1.11.0 shipped screen reader fixes as a named release feature — this is now user-visible parity work. **Impact 4 / Effort 3.** [R-1] Shipped first audit pass: every `IconButtonStyle` icon-only Button now carries an explicit `AutomationProperties.Name` mirroring its `ToolTipService.ToolTip` (Windows Narrator reads the AP.Name first; tooltip alone can be skipped depending on Narrator settings) -- 22 buttons across 21 pages annotated. Every `ProgressBar` (32 instances across 25 pages, including the new Watch / History / VMAF / SceneDetect / Timeline / TrackManager workspaces) gets `AutomationProperties.Name="Progress"` so screen readers announce the role correctly when value updates. `IconButtonStyle` already declares `UseSystemFocusVisuals=True` so keyboard focus rings render. Subsequent passes (tab-stop ordering review, ComboBox label coverage, focus management across pages) will land in v2.5. Build clean (no XAML compiler errors).

---

## LATER (v3.x)

### 33. Gyroflow Video Stabilization
Gyroflow uses gyroscope data embedded by cameras (GoPro, Sony, DJI, Insta360, Canon, Blackmagic, RED) for precision digital stabilization. Integration: spawn as sidecar, expose camera model selection and smoothness slider. More accurate than optical-flow-only stabilizers. **Impact 4 / Effort 4.** [R-14]

### 34. Conditional Transcode Rules (Plugin Stack)
Tdarr-style rule editor: user builds a conditional chain ("only transcode if not H.265", "add stereo AAC if absent"). Implemented as a Watch Folder extension with a composable rule DSL. **Impact 4 / Effort 5.** [R-10]

### 35. Word-Level Transcript Editor
Cap 0.4.82 ships a word-level transcript editor with ripple-delete. UCX could add this to SpeechToTextPage: each word is a clickable span; selecting and deleting ripple-trims the underlying audio/video. Requires significant XAML editor component work. **Impact 3 / Effort 4.** [R-19]

### 36. OCR: Image/PDF → Searchable PDF / TXT
Tesseract OCR wrapper. Input: image files or scanned PDFs. Output: searchable PDF (hOCR overlay) or plain TXT. **Impact 3 / Effort 3.**

### 37. DICOM → PNG/JPG/NIfTI
`dcmtk` wrapper for radiology/medical imaging workflows. DICOM frames → PNG sequence or NIfTI volume. **Impact 2 / Effort 3.**

### 38. Font Conversion (TTF ↔ OTF ↔ WOFF ↔ WOFF2)
`fonttools` Python wrapper. **Impact 2 / Effort 2.**

### 39. i18n / Localization Framework
Add `Resources.resw` per-language files; switch WinUI 3 text bindings to resource lookups. Priority languages: French, German, Spanish, Chinese Simplified, Japanese. FileConverter ships 25+ languages as a reference. **Impact 4 / Effort 4.** [R-15]

### 40. H.266 / VVC Encoding
VVC offers ~50% bitrate reduction vs H.265 at equivalent quality. FFmpeg integration via `libvvenc`. CPU-only (no GPU path yet); position as archival tier. Shutter Encoder already ships this. **Impact 2 / Effort 3.** [R-11]

### 41. ProRes RAW Decode + Encode
FFmpeg 8.0 shipped ProRes RAW decode (Vulkan); encode is in review for 8.1.x. Target: professional camera workflows (Sony FX series, Canon Cinema). **Impact 2 / Effort 3.** [S-3]

### 42. FunASR / SenseVoice Streaming STT
SenseVoice supports 31 languages and real-time streaming transcription. Alternative to Whisper for non-English-primary users. Configurable backend selector in SpeechToTextPage. **Impact 3 / Effort 4.** [R-16]

### 43. MV-HEVC / Stereoscopic Output
FFmpeg 7.1 added MV-HEVC decode for Apple Vision Pro, Quest. Expose MV-HEVC muxing for side-by-side stereoscopic input. VR Converter stub exists. **Impact 2 / Effort 4.** [S-3]

### 44. IAMF Spatial Audio Support
FFmpeg 8.1 added IAMF Ambisonic Audio mux/demux. Spatial audio for next-gen streaming/VR. Zero competition in Windows desktop converter space. **Impact 2 / Effort 3.** [S-3]

### 45. WinGet / MSIX Distribution
Publish UCX to `winget install UCX` and optionally Microsoft Store. WinAppSDK 2.0 ships an improved MSIX validator. Chocolatey/Scoop as complementary channels. Prerequisite: WinAppSDK 2.0 upgrade (#13). **Impact 3 / Effort 3.** [S-5]

### 46. Integration Test Suite
End-to-end tests for conversion pipelines: reference input → expected output format detection + FFprobe metadata roundtrip. CLI + sidecar contract only (no UI tests). Target: CI gatekeeping for backend regressions. **Impact 3 / Effort 3.**

### 47. User Documentation / Wiki
In-app help overlay or GitHub Wiki: quick-start per module, supported format matrix, sidecar requirements, CLI reference, common workflows. Zero user docs beyond README today. **Impact 3 / Effort 2.**

### 56. Crash reporter + in-app diagnostics page
No crash logging today — unhandled exceptions surface as a SmartScreen-styled crash dialog with no log capture, leaving sysadmin users blind. Catch `AppDomain.CurrentDomain.UnhandledException` + `TaskScheduler.UnobservedTaskException` + `App.UnhandledException`, dump structured reports (timestamp, version, OS build, GPU, last 3 sidecar runs, stack trace) to `%LocalAppData%\UniversalConverterX\crashes\`. Add a Diagnostics page (under Settings) that lists last 10 crash files, last 10 sidecar failures, system info, and a "Copy diagnostic bundle" button. Pattern references: [`Images/src/Images/Services/CrashLog.cs`](../Images/src/Images/Services/CrashLog.cs) (C# WPF reference) and [`Vertigo/core/crashlog.py`](../Vertigo/core/crashlog.py) (Python sidecar-side). **Impact 4 / Effort 3.** [internal-images, internal-vertigo]

### 57. Format-routing drag-drop on title bar / tray
Drop any file on the app chrome (title bar, tray icon, anywhere outside a module-specific drop zone) → app sniffs MIME / magic bytes via the existing FormatInspector, navigates to the matching module (video → Converter; image → ImageConverter; audio → VocalRemover or STT depending on user pref; .srt → AiSubtitle, etc.), and pre-loads the file. Polish item with high discoverability payoff — surfaces the toolbox without users hunting through the nav. Re-uses existing `IFormatDetectionService` from `UniversalConverterX.Core`. **Impact 3 / Effort 2.**

### 58. SBOM (Software Bill of Materials) generation
Required for Microsoft Store submission, increasingly expected for WinGet manifests, and a security posture signal for sysadmin users vetting installs. Generate CycloneDX 1.5 JSON for: (a) C# projects via `dotnet sbom-tool generate`, (b) frozen Python sidecars via `cyclonedx-py environment` against each tool's `requirements.txt`. Merge into one repo-level SBOM in the release workflow; attach to the GitHub release. Prerequisite: WinAppSDK 2.0 (#13) and WinGet/MSIX (#45). **Impact 2 / Effort 2.**

---

## UNDER CONSIDERATION

### A. Windows AI / Phi Silica Integration
WinAppSDK 2.0 exposes `AIFeatureReadyState` to detect Copilot+ NPU hardware. If present, Phi Silica (on-device LLM, NPU-optimized, ~3B param) enables: VideoSummarizer (Whisper transcript → structured summary), caption polish, intelligent preset selection. `TextSummarizer`, `TextRewriter`, `TextToTable` are built-in WinRT skills — zero inference setup. Leapfrog opportunity: no OSS competitor does NPU-native summarization. Prerequisite: WinAppSDK 2.0 upgrade (#13). Limitation: Copilot+ PC hardware required — needs graceful fallback for non-Copilot+ users. [S-5, S-PHI]

### B. Parakeet TDT Transcription Engine
Cap 0.4.82 ships NVIDIA Parakeet TDT as a Whisper alternative — reportedly faster on compatible hardware. Less community validation than Whisper; limited language coverage vs Whisper's 100 languages. Validate before committing. [R-19]

### C. "What's New" Onboarding Dialog
LosslessCut shows a "what's new" modal after each update, surfacing new tools to users who don't read changelogs. UCX has no onboarding. Worth adding for major releases (v2.4, v2.5) to surface stub-to-live tool transitions. Low effort; high discoverability payoff. [R-3]

### D. Pandoc Document Converter Integration
Pandoc 3.9 converts 50+ markup formats (DOCX, ODT, LaTeX, Markdown, EPUB, PPTX, HTML, etc.). Fills the non-AV document gap. Complexity: ~100 MB self-contained binary; Haskell runtime or static build required. Validate demand before committing. [S-6]

### E. Calibre Ebook Pipeline (EPUB ↔ MOBI ↔ AZW3)
`ebook-convert` CLI. Adds an ebook format category UCX currently lacks. Binary is ~300 MB. Demand signal unclear for this user base. [S-6]

### F. 3D Format Conversion (glTF / OBJ / STL)
Via Assimp + Blender headless. Very niche. Validate before v3.x work begins.

### G. Library Statistics Dashboard
File count, codec distribution, space saved over time — visualized in a WebView2 pane. Prerequisite: History dashboard (#26) must be live. Tdarr and File_Converter_Pro validate the UX. [R-10, R-13]

### H. Gyroflow NLE Plugin Handoff
Export `.gcsv` metadata for Gyroflow + launch Gyroflow from UCX — lower effort than full stabilization integration (#33). Assess before committing to full integration. [R-14]

### I. AI Voice Changer (VoiceChangerPage)
VoiceChangerPage stub exists. Requires a real-time or offline voice conversion model: RVC (Retrieval-based Voice Conversion), so-vits-svc, or ONNX-exported RVVC. Real-time path needs low-latency audio I/O (<30 ms buffer). Batch path (file-in → file-out) is feasible with existing sidecar pattern and ONNX/PyTorch. Demand signal: high on YouTube/streaming; model licensing varies. Validate model source + license before committing. [R-9]

### J. AutoHighlight / AutoCrop / AiPortrait
AutoHighlightPage, AutoCropPage, AiPortrait stubs exist. AutoHighlight: detect interesting moments via audio energy + scene change → extract clips. AutoCrop: AI-based content-aware crop (needs object detection model). AiPortrait: portrait background blur/replacement. All three require additional AI models not yet in the model cache. Evaluate together as a "smart editing" batch during v2.5 scoping.

### K. Proxy / clipping workflow for ClipForge
Premiere/Resolve standard pattern: on import of 4K+ source, auto-generate low-res proxies (typically 1080p H.264 or 720p ProRes Proxy) for editor preview/scrubbing, then swap back to originals at export render time. Eliminates timeline lag on consumer hardware. Reusable reference implementation already lives at [`OpenCut/opencut/core/proxy_gen.py`](../OpenCut/opencut/core/proxy_gen.py) and [`proxy_swap.py`](../OpenCut/opencut/core/proxy_swap.py) — port the FFmpeg recipe and the proxy-to-original relink table into a `clipforge` sidecar op. Validate demand from UCX user feedback before committing — 4K editing on UCX is currently rare. [internal-opencut]

### L. Live LUFS / true-peak meter in editor preview
Companion to ClipForge's existing `loudnorm` op (#10 shipped). During preview playback, surface integrated/momentary LUFS + true-peak in dB above the seek bar so users know what target to dial in *before* re-rendering. Implementation path: pipe a parallel `ffmpeg -af ebur128 -f null -` analysis to a small async loop that emits NDJSON loudness frames, render in a thin overlay strip. Pairs naturally with the planned waveform strip (#21). Validate demand among podcast / VO users.

### M. Borrow Vertigo's auto-edit + scene/keyframe modules into ClipForge
Vertigo already ships [`auto_edit.py`](../Vertigo/core/auto_edit.py), [`scenes.py`](../Vertigo/core/scenes.py), [`keyframes.py`](../Vertigo/core/keyframes.py), [`hook_score.py`](../Vertigo/core/hook_score.py), [`reframe.py`](../Vertigo/core/reframe.py), [`subtitles.py`](../Vertigo/core/subtitles.py), [`cameraman.py`](../Vertigo/core/cameraman.py) — overlapping with planned ClipForge work in #18 (PySceneDetect), #21 (waveform/thumbnails), #15 (auto-subtitle), J (AutoHighlight). Rather than re-implement, evaluate vendoring `Vertigo/core/*.py` modules into `tools/clipforge/` as the scene/keyframe engine. License compatibility (MIT) is given; risk is binary size + sidecar surface area. Decision: spike a port of one module (`scenes.py` → ClipForge SceneDetect op) before committing. [internal-vertigo]

### N. Borrow Vertigo's encode-pipeline patterns for VideoCrush hardware-decode chain
Vertigo's [`encode.py`](../Vertigo/core/encode.py) and [`encoders.py`](../Vertigo/core/encoders.py) already model NVENC/AMF/QSV preset selection plus the gnarly fallback chain when a GPU encoder is reported but unusable (driver mismatch, codec not supported on this generation). UCX VideoCrush (#20) re-derives this. Worth a one-pass diff to harvest what Vertigo already proved out. [internal-vertigo]

---

## REJECTED

| Item | Reason |
|------|---------|
| Cloud file processing (Cloudconvert/Convertio/etc.) | Contradicts core philosophy: local processing, no telemetry, no third-party access to files |
| OIDC / SSO multi-user server | Desktop-local product; server/multi-user mode contradicts scope |
| Mobile (Android / iOS) | Windows-only by design; WinUI 3 has no mobile target; not on the table for any version |
| CD optical ripping | Optical drive ownership is rare in 2026; `cdrtools` GPL-2 license conflict; low demand |
| Blu-ray rip | CSS/AACS/BDMV circumvention is legally prohibited in most jurisdictions (DMCA §1201, EU Directive) |
| DRM circumvention of any kind | Legal liability; explicitly refused with error dialog if DRM is detected |
| Cryptocurrency / blockchain metadata | Irrelevant to domain |
| Autonomous cloud AI inference (Replicate/HuggingFace API calls) | Requires outbound network, API keys, and sends user media to third parties |
| Scheduled DVR recording | Out of scope for conversion/editing tool; RecordCast is manual-trigger only |
| Global keyboard shortcuts | Explicitly excluded per project conventions |

---

## Architecture Notes

**Offline / resilience:** UCX is 100% offline by design. No network calls are made during conversion. Model downloads and yt-dlp update checks are the only network operations — both opt-in and skippable. All AI inference runs locally via ONNX Runtime or whisper.cpp.

**Sidecar contract (NDJSON):** All Python AI sidecars communicate via stdout NDJSON lines. Events: `progress` (0–100%), `log` (informational), `complete` (with output path), `error` (with message). `SidecarRunner.cs` is the C# orchestrator; new sidecars must conform to this contract.

**Binary discovery:** `SidecarRunner` walks from `AppContext.BaseDirectory` upward looking for `tools/<name>/<name>.exe`, then falls back to `%LocalAppData%\UniversalConverterX\tools\`. All sidecars are PyInstaller-frozen Windows executables.

**Model cache:** `tools/_models/` is the shared ONNX model directory. Sidecars receive a `--model-dir` CLI argument. Models are downloaded on first use and verified by SHA-256.

**Platform ceiling:**
- .NET 8 LTS EOL: **2026-11-10** — migration to .NET 10 is NOW-tier (item #9)
- WinAppSDK 1.5 → 2.0.1 upgrade is NEXT-tier (item #13)
- CUDA minimum for ONNX Runtime ≥ 1.25.0: **CUDA 12.0+** (CUDA 11.x dropped) — update GPU sidecar setup docs

**Demucs maintenance risk:** The `facebookresearch/demucs` GitHub repository was archived (read-only) on 2025-01-01. The PyPI package (`demucs`) remains functional; `python -m demucs` with `htdemucs_ft`/`htdemucs_6s` models still works via PyPI. No active maintainer. Track community fork activity; if no fork emerges by v3.0 planning, evaluate alternative stem separation models (e.g., Demucs community fork, Open-Unmix).

**Engine versions (current):** FFmpeg static build (see `tools/README.md`); yt-dlp pin ≥ 2026.03.17; ONNX Runtime ≥ 1.25.1; ImageMagick 7.1.2-21+; WinAppSDK 1.5.x → target 2.0.1; whisper.cpp v1.8.4 (secondary sidecar, item #12).

---

## Security Posture

| Component | Current Risk | Remediation |
|-----------|-------------|-------------|
| yt-dlp (StreamKeep) | Pin drift; extractor bugs | Pin ≥ 2026.03.17 (NOW #1) |
| ONNX Runtime (all ONNX sidecars) | Heap OOB, integer overflow in CPU kernels; 15+ CVEs in 1.25.0 | Pin ≥ 1.25.1 (NOW #2) |
| ONNX Runtime GPU path | CUDA 11.x support dropped in 1.25.0 | Require CUDA 12.0+ in GPU setup docs |
| NDJSON IPC contract | Path traversal via `output_path` field | Validate all output paths are under designated output dir (in progress) |
| FFmpeg (VideoCrush, ClipForge, RecordCast) | Regular CVE cadence; static build | Pin to vetted stable build; track FFmpeg security advisories |
| ImageMagick (native Converter) | CVE-active project; frequent memory safety issues | Pin to 7.1.2-21+; do not process untrusted remote input |
| Process isolation | Sidecars run in-process with user privileges | Job-object-based sandbox evaluation deferred to v3.x |

---

## Appendix: Sources

### OSS Competitors
- [R-1] https://github.com/HandBrake/HandBrake/releases — HandBrake v1.11.0/1.11.1: ProRes encoder, DNxHR encoder, AMD VCN AV1 10-bit, PCM/MOV support, .NET 10 Desktop Runtime required, screen reader accessibility fixes
- [R-2] https://github.com/transmute-app/transmute — Transmute: self-hosted Docker converter, REST API, OIDC, 7 themes
- [R-3] https://github.com/mifi/lossless-cut/releases — LosslessCut 3.68.0: expression-based segment selection, overview waveform, system language, reduce-motion setting, 1000-segment limit
- [R-4] https://github.com/C4illin/ConvertX — ConvertX: self-hosted TypeScript, VTracer, Markitdown, Dasel, dvisvgm
- [R-5] https://github.com/xinntao/Real-ESRGAN — Real-ESRGAN 0.3.0: 4× photo + anime upscaler, ncnn-Vulkan portable exe; last release April 2022 — model is stable
- [R-5b] https://github.com/TencentARC/GFPGAN — GFPGAN v1.4: blind face restoration, Apache 2.0
- [R-6] https://github.com/facebookresearch/demucs — Demucs v4 (htdemucs): 4/6-stem music separation, MIT license; **repo archived 2025-01-01, PyPI package still functional**
- [R-7] https://github.com/openai/whisper — Whisper: multilingual ASR, 6 model sizes (75 MB–2.9 GB), turbo model 8× speed
- [R-8] https://github.com/ggml-org/whisper.cpp/releases — whisper.cpp v1.8.4: Silero VAD v6.2.0, `-g` GPU device selection, 12× Intel iGPU speedup, Vulkan CI
- [R-9] https://github.com/Unmanic/unmanic — Unmanic: watch-folder library optimiser, FFmpeg plugin system
- [R-10] https://github.com/HaveAGitGat/Tdarr — Tdarr: distributed conditional transcode, plugin stack, library stats, job reports
- [R-11] https://www.shutterencoder.com/en/ — Shutter Encoder: VMAF, loudness analysis, H.266, FFV1, JPEG XL, ProRes, AI functions
- [R-12] https://github.com/staxrip/staxrip — StaxRip: AviSynth/VapourSynth scripting GUI for advanced encoding
- [R-13] https://github.com/Hyacinthe-primus/File_Converter_Pro — File_Converter_Pro: SQLite gamification/stats, i18n .lang JSON
- [R-14] https://github.com/gyroflow/gyroflow — Gyroflow: gyro-based video stabilization, GPU rendering, 40+ camera sources
- [R-15] https://github.com/Tichau/FileConverter — FileConverter: 20k+ stars, 25+ languages, SharpShell context menu
- [R-16] https://github.com/alibaba-damo-academy/FunASR — FunASR/SenseVoice: 31-language ASR, VAD, speaker diarization
- [R-17] https://github.com/ozmartian/vidcutter — VidCutter: PyQt5 trim/cut tool, cross-platform
- [R-18] https://github.com/Breakthrough/PySceneDetect/releases — PySceneDetect 0.6.7: EDL CMX 3600 + OTIO export, FFmpeg 8.0 bundled, DaVinci Resolve compatible
- [R-19] https://github.com/CapSoftware/Cap/releases — Cap 0.4.82–0.4.84: Parakeet TDT transcription, word-level transcript editor, CRF export optimize, HLS segmented upload

### Platform / Framework
- [S-1] https://github.com/yt-dlp/yt-dlp/releases — CVE-2026-26331 fixed in 2026.02.21; 2026.03.17 is current stable with extractor fixes
- [S-2] https://github.com/microsoft/onnxruntime/releases — ORT 1.25.0: CUDA ≥ 12.0 minimum, CUDA Plugin EP, 15+ security fixes; ORT 1.25.1: additional heap OOB + Pad Reflect patches
- [S-3] https://ffmpeg.org/index.html#news — FFmpeg 8.0 "Huffman" (ProRes RAW Vulkan, Vulkan FFV1, D3D12 filters, Whisper filter); FFmpeg 8.1 "Hoare" (D3D12 H.264/AV1 encode, scale_d3d12, Vulkan ProRes encode, EXIF, IAMF, AMD VCN AV1 10-bit)
- [S-4] https://github.com/ImageMagick/ImageMagick/releases — ImageMagick 7.1.2-21 latest stable
- [S-5] https://github.com/microsoft/WindowsAppSDK/releases — WinAppSDK 2.0.1: SystemBackdropElement, Storage Pickers v2 (SettingsIdentifier, multi-folder, SuggestedStartFolder), Windows ML refactor, ORT 1.24.5 bundled, WebView2 drag, AIFeatureReadyState
- [S-6] https://github.com/jgm/pandoc/releases — Pandoc 3.9.0.2: DOCX/ODT/Typst/EPUB/Markdown/HTML/LaTeX universal converter
- [S-7] https://github.com/rany2/edge-tts — edge-tts 7.2.8: Microsoft Edge Neural TTS client, 100+ voices, MIT license, CBR offset math fixed
- [S-8] https://github.com/microsoft/WinUI-Gallery/releases — WinUI Gallery 2.8: JumpList reference implementation, .NET 9, nullable reference types enabled
- [S-NET10] https://dotnet.microsoft.com/en-us/download/dotnet/10.0 — .NET 10.0.7 GA LTS; .NET 8 mainstream support ends 2026-11-10
- [S-PHI] https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica — Phi Silica NPU API: TextSummarizer, TextRewriter, TextToTable built-in WinRT skills (Copilot+ PC only, via WinAppSDK 2.0)

### Community Signal
- https://github.com/topics/file-converter — GitHub topic: OSS landscape survey
- https://github.com/topics/video-converter?l=c%23 — C# video converter topic
- https://handbrake.fr/features.php — HandBrake feature reference (queue, RF slider, HW accel)

### Internal Sources
- [plan] — Phase 0 repo reconnaissance: source code confirmed at `tools/vertigo/`, `tools/gifstudio/`, `tools/heicshift/` with no corresponding `sidecar.py`; pages confirmed in `ToolboxPage.xaml.cs` and `MainWindow.xaml.cs` route table
- [internal-images] — `~/repos/Images/` (v0.1.2) — C# .NET 9 WPF photo viewer with Catppuccin theming. Reference files: `src/Images/Themes/DarkTheme.xaml`, `src/Images/Services/CrashLog.cs`, `src/Images/Services/WindowChrome.cs`. Source for theme switching pattern (#54) and crash logger pattern (#56).
- [internal-nvme] — `~/repos/win11-nvme-driver-patcher/` (v4.6.0) — C# .NET 9 watchdog Windows Service. Reference: `src/NVMeDriverPatcher.Watchdog/Program.cs` push-model `EventLogWatcher` pattern, `/install` and `/uninstall` self-service plumbing, async pipe drain to avoid deadlock. Pattern source for SidecarRunner watchdog (#51).
- [internal-opencut] — `~/repos/OpenCut/` (v1.9.3) — Premiere Pro CEP extension, Python/Flask + JS. Reference: `opencut/core/proxy_gen.py`, `proxy_swap.py`, `gpu_preview_pipeline.py`, `live_preview.py`, `preview_cache.py`, `render_cache.py`. Production-grade proxy editing pipeline reusable for ClipForge (item K).
- [internal-vertigo] — `~/repos/Vertigo/` (v0.12.2) — Python/PyQt6 9:16 vertical-video studio. Reference: `core/auto_edit.py`, `scenes.py`, `keyframes.py`, `hook_score.py`, `reframe.py`, `subtitles.py`, `cameraman.py`, `encode.py`, `encoders.py`, `crashlog.py`, `tracker_boxmot.py`, `face_samples.py`. Heavily overlapping with planned ClipForge engine work — vendoring candidate (items M, N) and crash-log pattern source (#56).
