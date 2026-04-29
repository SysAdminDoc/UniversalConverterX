# Roadmap

Forward-looking plans for VideoCrush — Python GUI video compressor with FFmpeg backend, preset profiles, and batch queue.

## Planned Features

### Encoding
- Hardware-accel presets: NVENC (H.264 / HEVC / AV1), AMF (AMD), QSV (Intel), VideoToolbox (macOS)
- Auto-detect GPU at startup, offer matching encoder as default
- Two-pass bitrate mode with target file size
- Constrained VBR + per-scene CRF (libaom-av1 / svt-av1 tune options)
- Smart-crop pass (remove letterboxing automatically before encode)
- HDR passthrough and tone-mapped SDR output for BT.2020 sources
- Subtitle handling: burn-in, passthrough, or strip (per-track toggle)
- Audio: re-encode / passthrough / downmix / loudness-normalize (EBU R128)

### UX
- Before/after thumbnail strip with SSIM + VMAF + file-size delta
- Queue with priority, pause, resume, reorder, failure-retry
- Drag-and-drop multi-file; folder-recurse with extension filter
- Per-file override of preset (change CRF on a single job without touching the profile)
- Live log pane with collapsible FFmpeg stderr per job

### Presets
- "Web upload (YouTube / X / Discord nitro / Discord free)" — sized for each platform's limits
- "Email friendly (< 10 MB)" with auto-resolution drop
- "Archive (AV1 CRF 30, slow)"
- "Smartphone (H.264 baseline)" for old devices
- "Lossless" (ffv1 / h264 lossless)
- Preset sharing via JSON export/import

### Automation
- Watch folder with rule-based routing (route .mov → one preset, .mkv → another)
- CLI: `videocrush --input ./in --preset web-1080p --out ./out`
- Scheduled runs via Task Scheduler integration
- Context-menu integration ("Compress with VideoCrush → Web 1080p")

### Distribution
- PyInstaller single-exe with ffmpeg bundled (or auto-download on first run)
- Signed releases, winget manifest, auto-update check
- Portable mode (no registry writes, settings in local folder)

## Competitive Research

- **HandBrake**: the gold standard. Queue, presets, CRF slider wording — mimic as far as sensible, differentiate on Windows-first integration and drag-drop.
- **Shutter Encoder**: broad format coverage, dense UI. We stay leaner but can borrow their preset library format for compatibility.
- **FFmpeg Batch AV Converter**: lightweight Windows wrapper. Proves there's a niche for a simpler-than-HandBrake Windows tool.
- **Compressor.io / Squoosh for video**: web-based. Good UX reference for the "drag a file, watch the size drop" first-time experience.

## Nice-to-Haves

- AI upscaling via Real-ESRGAN / Video2X as pre-pass
- Auto-subtitle via Whisper during encode
- Scene-detect cut + trim suggestions (ffmpeg select filter with preview)
- Built-in GIF creator with palette optimization
- Cloud-target upload (S3 / R2 / Backblaze / SFTP) after encode
- Battery-aware encoding (pause on battery, resume on AC)

## Open-Source Research (Round 2)

### Related OSS Projects
- https://github.com/codeforreal1/compressO — Tauri + React FFmpeg compressor, cross-platform
- https://github.com/eibols/ffmpeg_batch — FFmpeg Batch AV Converter, drag/drop + pause/resume + shutdown
- https://github.com/MattMcManis/Axiom — FFmpeg GUI for Windows, command script generator
- https://github.com/zbabac/VCT — Video Converter & Transcoder, full manual ffmpeg edit
- https://github.com/nikmedoed/easy-video-compress — ThreadPoolExecutor parallel + explorer context menu
- https://github.com/addyosmani/video-compress — ffmpeg.wasm in-browser reference
- https://github.com/awesomelistsio/awesome-ffmpeg — curated tool/resource index
- https://github.com/Mordekai66/Video-Compressor — Tkinter + real-time preview baseline

### Features to Borrow
- Pause/resume of active encodes with priority adjust (ffmpeg_batch)
- Command-script export — save the generated ffmpeg invocation as a reproducible .bat/.sh (Axiom)
- Explorer right-click "Compress here" context menu entry (easy-video-compress)
- Multi-worker ThreadPoolExecutor (default 4) for parallel batch items (easy-video-compress)
- Two-pass VBR mode toggle for target-filesize precision (Axiom)
- Drop M3U8/YouTube URL capture → download then transcode in one queue step (ffmpeg_batch)
- Subtitle track burn-in + passthrough options (ffmpeg_batch)
- Automatic post-queue shutdown/sleep (ffmpeg_batch)
- pngquant/jpegoptim/gifski pipeline for image siblings (compressO)
- Preset JSON export/import so teams can share compression profiles (Axiom)

### Patterns & Architectures Worth Studying
- Tauri shell over FFmpeg CLI (compressO) — keeps the heavy codec out of app memory, lets Rust drive progress parsing
- Frontend progress parse via ffmpeg `-progress pipe:1` + key=value lines instead of stderr regex (compressO, easy-video-compress)
- Queue model with per-item state (pending/running/paused/error/done) + persistable job spec JSON so crashes resume (ffmpeg_batch)
- NVENC/QSV/AMF autodetect at launch, cache result, expose in UI (Axiom)
- Dual encode path: quality-target (CRF) vs size-target (two-pass bitrate) — switch based on user intent, not codec (VCT)
