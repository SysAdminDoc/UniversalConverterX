# Roadmap

Forward-looking plans for UniversalConverter X — the all-in-one media tool for Windows. WinUI 3 + .NET 8 shell with native Converter (1000+ formats, 13 backends) plus Compressor, Editor, Downloader, Recorder, and a 29-tool Toolbox. v2.0.0 today (layout pass + sidecar staging). Phased integration follows.

## Phased Integration

### v2.0.x — Layout & Native Converter (current)
- WonderShare-style NavigationView shell with sidebar modules and Toolbox tile grid (done).
- Tab routing for Home / Converter / Compressor / Editor / Downloader / Recorder / Toolbox / Account (done).
- Native Converter remains fully functional inside the new shell (done).
- `tools/` sidecar staging directory with NDJSON CLI contract (done).

### v2.1 — Core Modules Wired
- **Compressor** powered by VideoCrush sidecar with preset profiles (web 1080p, email <10MB, archive AV1).
- **Editor** powered by ClipForge sidecar — trim, crop, rotate, upscale (Real-ESRGAN), filter, audio adjust, batch.
- **Downloader** powered by StreamKeep sidecar — Kick/Twitch/Rumble native + yt-dlp fallback for 1000+ sites.
- **Recorder** powered by first-party RecordCast sidecar — fixed-duration Windows desktop capture via FFmpeg gdigrab.
- **Format Inspector** toolbox workspace for signatures, FFprobe stream metadata, and conversion target suggestions.
- **Frame Snapshot** toolbox workspace for batch timestamped still extraction and image-sequence samples via FFmpeg.
- Settings UI — preferences pane, theme switcher, tool-path overrides.

### v2.2 — AI Toolbox Wave 1
- **Background Remover** powered by AlphaCut (8 ONNX segmentation models, ProRes/WebM alpha output).
- **Subtitle Remover** powered by VideoSubtitleRemover (AI inpainting).
- **Lip Reading** powered by LipSight (visual speech recognition).
- Shared ONNX model cache across AI sidecars.

### v2.3 — Toolbox Wave 2
- **Auto Reframe** powered by Vertigo (9:16 / 1:1 / 4:5 with MediaPipe face tracking).
- **GIF Maker** powered by GifStudio (WebView2 host).
- **Image Converter** — HEICShift's metadata/ICC defaults absorbed into UCX's existing libvips/libjxl strategies.

### v2.4 — Recorder + Account
- Webcam, microphone, and system audio capture on top of the v2.1 screen recorder.
- Optional account sync for presets and license entitlements (still fully offline by default).

### v2.5+ — AI Toolbox Wave 2 (gap-fillers)
- Caption Generator (Whisper), Vocal Remover, Voice Changer, TTS, STT, Image Upscaler standalone, Auto Highlight, Auto Crop, Watermark add/remove, Noise Remover.
- DVD/CD modules — defer until demand confirmed; consider `cdrtools`/`growisofs` wrappers if pursued.

## Planned Features

### UniConverter-Style UX Parity Audit (2026-04-29)
- **Public reference reviewed:** Wondershare UniConverter 17 public landing page positions the app as an all-in-one AI video converter and enhancer with Convert, Enhance, Compress, Record, AI Lab, Toolbox, solution/persona guidance, and strong download/pricing CTAs.
- **Built in this pass:** Light AI-suite visual direction, richer Home dashboard, first-class AI Lab navigation, guided search, workflow cards for Convert/Enhance/Compress/Download/Record/Toolbox, and Settings access to the existing settings window.
- **Highest remaining GUI gaps:** real media preview panes, persistent job history, before/after quality comparisons, per-file output overrides, GPU/hardware acceleration visibility, guided solution presets, AI model cache management, richer partial-success recovery, and richer recorder device selection.
- **Highest remaining feature gaps:** video/image enhancer, AI subtitle translation, video summarizer, watermark/object remover, old photo restoration, webcam/audio recorder capture, chapter generation, metadata repair/editing, and social-format auto-reframe.
- **Behavior standard:** tools should use a consistent Import -> Preview -> Queue -> Export flow with visible engine, estimated output size, cancellation, retry, and local-processing trust signals.

### Converter Backends
- FFmpeg: hardware-accel presets per GPU (NVENC / AMF / QSV / VCE) auto-detected from adapter list
- ImageMagick 7 Q16-HDRI builds as default over Q8 for photography workflows
- WebP / AVIF / JPEG XL quality-vs-size slider with live preview sample
- Adds: `qpdf`, `mutool`, `xpdf` for PDF splitting/merging/optimizing separate from Ghostscript
- OCR step (tesseract) that converts image/PDF → searchable PDF or TXT
- Adds: `dcmtk` for DICOM → PNG/JPG/NIfTI (clinic/imaging use case; ties into VoyanceFirewall / XRayAcquisition)
- 3D: glTF → GLB, OBJ → STL via Assimp + Blender headless
- Font conversion (TTF ↔ OTF ↔ WOFF ↔ WOFF2) via fonttools

### UX
- Preset pipelines: "web upload (1080p H.264 + AAC 192k)", "email friendly (<10 MB)", "archive (AV1 CRF 28)"
- Drag-and-drop multi-file with per-file output override
- Preview pane: before/after thumbnails with file-size delta and quality score (SSIM/VMAF for video)
- Context-menu templates — right-click → "Convert to JPG (85%)" without opening the GUI
- Batch CSV import — convert a list of source paths with per-row parameters

### CLI
- `ucx <from> <to> --profile web-1080p --recurse`
- Pipeline chaining (`ucx in.mkv --filter denoise --to mp4 --then --upload ...`)
- JSON output mode for scripting
- Progress telemetry as NDJSON for integration with other TUIs

### Automation & Integration
- Watch folder — auto-convert anything dropped into it
- PowerShell module: `Convert-MediaFile -Input a.mov -Profile WebHD`
- Cloud targets: upload converted output to S3 / Azure Blob / SFTP
- Scheduled conversion rules (Task Scheduler integration)

### Tooling Management
- `ucx tools` subsystem: verify, install, update every backend from a single UI pane
- Embedded vs system-path toggle per tool (ships portable backends, users can point at existing installs)
- Backend version pinning + SHA verification on download

## Competitive Research

- **HandBrake**: gold standard for video, excellent presets. Borrow their "queue" metaphor and x264/x265 RF slider wording.
- **XnConvert / IrfanView Batch**: image-specific. Their per-file parameter table is the pattern for our batch CSV import.
- **File Converter (Tichau)**: de-facto Windows context-menu converter; 20k+ GitHub stars. Main complaint is limited format coverage — we ship more. Steal the UX of right-click → preset choice.
- **Pandoc / LibreOffice headless / Calibre**: already wrapped. Keep current versions tracked and surface version strings in the About pane.

## Nice-to-Haves

- AI upscale step (Real-ESRGAN / Video2X) as optional pre-pass
- Subtitles extract/burn/translate (Whisper + DeepL) pipeline
- GIF/APNG creator from video with cropping + palette optimization
- Perceptual quality budgeter — "keep SSIM ≥ 0.95" auto-picks CRF
- Server mode — REST API for LAN clients
- DRM detection + explicit refusal (avoid liability)

## Open-Source Research (Round 2)

### Related OSS Projects
- https://github.com/Tichau/FileConverter — Windows shell-extension converter (SharpShell + ffmpeg + ImageMagick + Ghostscript)
- https://github.com/jgm/pandoc — universal markup converter, embedded as a back-end
- https://github.com/KingConverter/KingConverter — Electron GUI over ffmpeg + sharp
- https://github.com/Hyacinthe-primus/File_Converter_Pro — PySide6 multi-engine fallback pattern
- https://github.com/NathanTBeene/UniversalFileConverter — FFmpeg preset-driven conversions
- https://github.com/dbohdan/sharpshell — upstream shell-extension framework for right-click integration
- https://github.com/ImageMagick/ImageMagick — canonical image engine
- https://github.com/FFmpeg/FFmpeg — canonical AV engine
- https://github.com/libretro/video-decoder-samples — niche: hardware-accelerated decode paths
- https://github.com/kovidgoyal/calibre — ebook conversion engine; reusable for EPUB/MOBI/AZW3 flows

### Features to Borrow
- SharpShell-based right-click context menu (Tichau/FileConverter) — proven pattern for Explorer integration
- Multi-engine fallback cascade: try Pandoc → LaTeX → LibreOffice → Ghostscript (File_Converter_Pro)
- Quality-preset-per-format system (Hyacinthe-primus) — curated CRF/bitrate presets indexed by format pair
- Bundled ffmpeg binary with path auto-discovery at runtime (File_Converter_Pro)
- Calibre ebook pipeline integration (EPUB ↔ MOBI ↔ AZW3 ↔ PDF) via `ebook-convert` CLI
- Batch queue with per-file retry + partial-success reporting (KingConverter)
- Hardware acceleration detection (NVENC/QuickSync/AMF) with fallback to software (FFmpeg standard practice)
- Pandoc `--lua-filter` support for custom doc transforms (jgm/pandoc)
- Server mode via REST API with upload → job → download endpoints (existing roadmap; borrow FFmpeg-REST-API patterns)
- Perceptual quality budgeter ("SSIM ≥ 0.95 picks CRF") using VMAF/SSIM tools (FFmpeg libvmaf)

### Patterns & Architectures Worth Studying
- Engine-as-driver abstraction: each converter (ffmpeg/imagemagick/pandoc/calibre/ghostscript) exposes a uniform `convert(src, dst, opts)` interface
- Format-pair routing table: (src_ext, dst_ext) → engine(s) with priority and capability flags
- Streaming progress parsing: regex ffmpeg's stderr `frame=... time=...` into a progress callback
- Shell-extension out-of-process worker: the .dll stays tiny, actual work happens in a spawned service to avoid Explorer crashes on failures
- DRM detection via format signatures + explicit refusal dialog — already on roadmap; borrow Calibre's licensed-DRM-error path
