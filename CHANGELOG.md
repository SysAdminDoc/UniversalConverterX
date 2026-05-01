# Changelog

All notable changes to UniversalConverterX will be documented in this file.

## [v2.11.0] - 2026-05-01

### Added — 13 new pure-format conversion sidecars (no AI)

- **psdkit sidecar** — Photoshop / GIMP layered images: PSD/PSB/XCF -> flatten to PNG/JPEG/TIFF/WebP/BMP, or extract every visible layer as its own PNG. `info` op for layer-tree probe.
- **audiopro sidecar** — Niche audio codec conversion via FFmpeg: DSD (.dsf/.dff), APE, WavPack (.wv), TAK, TTA, ALAC, MLP/TrueHD, AC3, E-AC3, DTS, AMR/AMR-WB, SPEEX, GSM, WMA, MusePack, AU, VOC, Real Audio. `codecs` op probes which encoders the local FFmpeg has compiled in.
- **subocr sidecar** — Bitmap subtitle OCR: Blu-ray PGS (.sup) + DVD VobSub (.idx/.sub) -> SRT via FFmpeg subtitle decoder + Tesseract OCR pipeline. Configurable language pack.
- **subkit sidecar** — Text subtitle interchange beyond pysubs2: SAMI/SMI, TTML/DFXP, SCC (CEA-608 broadcast), EBU STL teletext, MicroDVD, JACoSub, LRC karaoke, SBV YouTube. Backed by pycaption + pysubs2.
- **dbtools sidecar** — Database / statistical-format conversion: SQLite, MS Access (.mdb/.accdb via mdbtools shellout), dBase (.dbf), SAS XPORT/.sas7bdat, SPSS .sav, Stata .dta, R Data (.rda/.rds) -> CSV/TSV/JSON-Lines/Parquet/SQLite.
- **textencode sidecar** — Charset recoding (utf-8 ↔ utf-16 ↔ latin-1 ↔ cp1252 ↔ shift_jis ↔ gb18030 ↔ big5 ↔ koi8-r ↔ iso-8859-x), line-ending normalization (LF/CRLF/CR), BOM management, encoding auto-detection via chardet.
- **hashkit sidecar** — File hashing + verification: MD5/SHA-1/SHA-224/256/384/512/SHA3-256/SHA3-512/BLAKE2b/BLAKE2s/BLAKE3/xxHash (32/64/128)/CRC32/Adler32. `generate` writes SHA256SUMS-style manifest or per-file `.sha256` sidecars; `verify` validates files against an existing SUMS manifest.
- **encodekit sidecar** — Binary text encoding: Base64/Base32/Base85/Hex encode + decode, plus `inline` op that wraps any file as a `data:<mime>;base64,...` URL.
- **iconkit sidecar** — Multi-resolution icon container generation: PNG -> Windows .ico (multi-res), Apple .icns (multi-layer with PNG-encoded slots from 16x16 to 1024x1024), Apple .iconset folder layout for use with `iconutil`.
- **plistkit sidecar** — Apple Property-List mutual conversion: binary plist <-> XML plist <-> JSON. Handles bytes (base64 round-trip) and dates safely through the JSON form.
- **hdrkit sidecar** — HDR / floating-point image conversion: Radiance HDR (.hdr/.pic/.rgbe), OpenEXR (.exr, half/float), PFM (Portable Float Map), 16-bit PNG, 16-bit TIFF. `tonemap` op renders 8-bit LDR via Reinhard / Drago / Mantiuk / linear tone-map operators (OpenCV).
- **music sidecar** — Music notation conversion: MusicXML / .mxl / MIDI / ABC / MuseScore .mscz / .mscx / GuitarPro (.gp, .gp3, .gp4, .gp5, .gpx). Backed by music21 + guitarpro library + MuseScore CLI shellout for .mscz round-trip.
- **hexkit sidecar** — Embedded firmware image conversion: Intel HEX (.hex/.ihex), Motorola SREC (.s19/.s28/.s37), TI-TXT (.txt), raw binary (.bin/.raw/.img). Backed by bincopy. `info` op probes segment layout and address range.

### Added — 24 new presets

`psd-flatten-png`, `psd-extract-layers`, `dsd-to-flac`, `wma-to-mp3`, `pgs-to-srt`, `sami-to-srt`, `srt-to-lrc`, `access-to-csv`, `db-to-sqlite`, `recode-to-utf8`, `newline-lf`, `hash-sha256`, `hash-blake3`, `encode-base64`, `inline-data-url`, `png-to-ico`, `png-to-icns`, `plist-to-xml`, `plist-to-json`, `hdr-to-png16`, `hdr-tonemap-jpg`, `musicxml-to-midi`, `midi-to-musicxml`, `hex-to-bin`, `bin-to-hex`.

### Changed

- KNOWN_EVENTS extended with 18 new event types: `layered_image`, `layered_info`, `audio_codec`, `audio_codec_info`, `subtitle_ocr`, `subtitle_text`, `dbtable`, `text_encode`, `text_encode_info`, `file_hash`, `file_hash_manifest`, `file_hash_check`, `encoded_blob`, `icon_blob`, `plist_doc`, `hdr_image`, `score_doc`, `hex_image`, `hex_image_info`. Contract test: 78 sidecars conforming.
- 13 new Toolbox tiles route through `presets:engine` deep-link convention.
- Version 2.10.0 → 2.11.0 across all manifests.

## [v2.10.0] - 2026-05-01

### Added
- **NEW bgremove sidecar** — Modern image background removal: BiRefNet (CVPR 2024 SOTA, Apache-2.0), RMBG-2.0 (BRIA Apache-2.0), IS-Net, U2Net via rembg, SAM 2. Default backend `birefnet`.
- **NEW superres sidecar** — Modern image super-resolution via spandrel (the same loader used by ChaiNNer): HAT / HAT-L / DAT / SwinIR / SwinIR-Large / APISR / Real-ESRGAN / Real-CUGAN / SCUNet. Auto-downloads checkpoints from authors' repos. Default model `hat-l-x4`.
- **NEW facerestore sidecar** — Face restoration: CodeFormer with fidelity slider (`--w 0.0`-`1.0`) for identity-vs-quality control, plus GFPGAN v1.4 fallback.
- **NEW ocrpro sidecar** — Surya OCR (Apache-2.0): layout analysis + text recognition + tables + math + 90+ languages. Markdown or JSON output.
- **NEW premiumtts sidecar** — Best-in-class OSS TTS: Kokoro-82M (fast, 54 voices, 9 languages), F5-TTS (zero-shot voice cloning from 5-15 s reference clip), XTTS v2 (multilingual + cloning). Default backend `kokoro`.
- **NEW translatekit sidecar** — Offline neural translation: NLLB-200 (Meta, 200 languages) + MADLAD-400 (Google, 419 languages) + Helsinki OPUS-MT. Three ops: `text`, `file` (line-by-line), `srt` (timecode-preserving subtitle translation).
- **NEW inpaint sidecar** — Fast object removal via LaMa (Samsung Apache-2.0). Three mask sources: explicit mask image, `--bbox X,Y,W,H` rectangle, or `--auto-detect person,car,bird` (YOLOv11 + segmentation).
- **NEW audiomastering sidecar** — Reference-based mastering via Matchering 2.0 + EBU R128 loudness normalization (two-pass FFmpeg loudnorm). Streaming preset = -14 LUFS / -1 dBTP.
- **sdkit upgraded** — Now defaults to FLUX.1 schnell (Apache-2.0, 4-step SOTA). Catalog: FLUX.1 schnell/dev, SD 3.5 Large/Medium, SD 3 Medium, SDXL Turbo, SDXL 1.0, SD 2.1, SD 1.5, SD x4 upscaler. Aliases: `flux`, `sd35`, `sdxl`, `sdxl-turbo`. Per-model recommended steps + cfg auto-applied unless overridden.
- **whisper-stt upgraded** — Default model now `large-v3-turbo` (Whisper v3 Turbo, 2024-10, ~8x faster than v3). Adds Distil-Whisper variants (`distil-large-v3`, `distil-medium.en`, etc.), `--vad` flag (Silero VAD via faster-whisper), `--diarize` flag (pyannote 3.1 speaker diarization, requires `HF_TOKEN`).
- **videocrush upgraded** — New AV1 profiles powered by SVT-AV1 v2 (FFmpeg 7.1+): `archive-av1-fast` (preset 8, 4-6x faster), `archive-av1-quality` (preset 4, archive-grade), `stream-av1-1080p` (1080p YouTube/Vimeo upload).
- **pdfmarkdown upgraded** — Adds Docling (IBM Apache-2.0, best for technical PDFs with tables/math) and MinerU/magic-pdf (best for academic math-heavy content) as backends alongside pymupdf4llm and marker.
- **13 new presets** — `bg-remove-birefnet`, `bg-remove-rmbg2`, `superres-hat-x4`, `superres-anime-apisr`, `restore-face-codeformer`, `ocr-pro-surya`, `pdf-to-markdown-docling`, `tts-kokoro-bella`, `translate-to-spanish`, `translate-srt-japanese`, `loudnorm-streaming`, `inpaint-remove-people`, `to-av1-fast`, `to-av1-quality`, `sd-flux-schnell`.
- **8 new Toolbox tiles** — All v2.10 engines surface in the Toolbox via `presets:engine` deep-link route.

### Changed
- KNOWN_EVENTS extended with `matte_image`, `matte_model`, `upscale_image`, `upscale_model`, `face_restore`, `ocr_pro`, `tts_audio`, `tts_voice`, `translation`, `translation_lang`, `inpaint_image`, `master_audio`. Contract test passes 65 sidecars.
- Version 2.9.0 → 2.10.0 across all manifests.

## [v2.9.0] - 2026-05-01

### Added
- **gametools sidecar** — Pure-Python ROM patcher (IPS / BPS / UPS), iNES + SMC header strip, N64 byteswap (z64 / v64 / n64), header probe, plus CHD ↔ CUE/BIN/ISO/GDI via MAME `chdman` wrapper.
- **datasci sidecar** — Tabular and array data interchange across CSV / TSV / JSON-Lines / Parquet / Feather / Arrow / Avro / ORC / HDF5 / NumPy NPY-NPZ / Matlab MAT / NetCDF / FITS. `info` op probes shape + dtype + columns.
- **i18nkit sidecar** — Localization-format mutual conversion: PO / POT / MO / XLIFF (1.2 + 2.0) / TMX / RESX / iOS .strings / JSON-i18n / YAML / CSV. Internal MessageEntry normalization keeps comments + keys.
- **pointcloud sidecar** — Point cloud / 3D scan formats: PLY / PCD / XYZ / PTS / OBJ via Open3D, LAS / LAZ via laspy + lazrs, E57 via pye57. `info` op reports point count + bounds.
- **diskimage sidecar** — VM disk image conversion via qemu-img: RAW / IMG / QCOW2 / VMDK / VHD / VHDX / VDI / QED / Parallels HDS. Optional QCOW2 compression flag.
- **mailimport sidecar** — Outlook PST / OST extraction via libpff (`pypff`). Walks every folder; ops: `to-eml` (per-message), `to-mbox` (single Unix mailbox), `list` (folder inventory only).
- **UniversalConvertPage** — New top-level UX page. Drop or pick any file(s); UCX intersects extensions against every loaded preset's `InputTypes` and renders matching presets ranked by full-coverage first. Click "Convert..." on any match to run that preset against the same files. Doubles as the answer to "what can I do with this file?".
- **13 new presets** — `rom-strip-header`, `n64-to-z64`, `cue-to-chd`, `chd-to-cue`, `csv-to-parquet`, `parquet-to-csv`, `po-to-xliff`, `xliff-to-po`, `las-to-ply`, `e57-to-las`, `vmdk-to-qcow2`, `qcow2-to-vmdk`, `pst-to-mbox`, `pst-to-eml`.
- **7 new Toolbox tiles** — `presets:gametools`, `presets:datasci`, `presets:i18nkit`, `presets:pointcloud`, `presets:diskimage`, `presets:mailimport`, plus the killer `universal-convert` tile.

### Changed
- KNOWN_EVENTS extended with `rom_patch`, `rom_info`, `disc_image`, `data_table`, `data_info`, `locale_doc`, `point_cloud`, `point_cloud_info`, `disk_image`, `disk_image_info`, `email_index`. Contract test passes 57 sidecars.
- Version 2.8.0 → 2.9.0 across all manifests (csproj × 3, PowerShell module psd1, README badge, CLAUDE.md, `ucx serve` `/healthz`).
- Route table in `MainWindow.xaml.cs` gains `universal-convert` → `UniversalConvertPage`.

## [v2.8.0] - 2026-04-30

### Added
- **sdkit sidecar** — Stable Diffusion via `diffusers`. Ops: `txt2img`, `img2img`, `inpaint`, `upscale-x4`, `models`. fp16/bf16/fp32 dtype selector; cuda/cpu device selector. Default model `runwayml/stable-diffusion-v1-5`. Emits `sd_image` per generation, `sd_model` per discoverable pipeline.
- **speechenhance sidecar** — DeepFilterNet 3 SOTA neural speech denoise + dereverb. Single `enhance` op with `--atten` dB attenuation cap. Emits `speech_enhance` per file, writes `<stem>_dfn3.wav`.
- **stemkit sidecar** — Music source separation via `audio-separator` (BS-Roformer, MelBand-Roformer, htdemucs FT/MMI, UVR-MDX, VR-Arch, Spleeter). Friendly aliases: `vocals` / `vocals-roformer` / `4stem` / `4stem-fast` / `6stem` / `karaoke` / `denoise` / `dereverb`. Output format wav/flac/mp3.
- **pdfmarkdown sidecar** — PDF → Markdown via `pymupdf4llm` (default, fast layout-aware) or `marker` (LLM-grade backend). Optional `--page-chunks` for one-chunk-per-page output.
- **vectorkit sidecar** — Inkscape headless wrapper for AI / EPS / PS / EMF / WMF / SVG / SVGZ / CDR / VSD ↔ SVG / PDF / EPS / PS / EMF / WMF / PNG. Auto-discovers Inkscape via `INKSCAPE_PATH` env or standard install paths.
- **lutgen sidecar** — 3D LUT generator. Builds .cube and .3dl LUTs from before/after image pairs by binning source RGB and averaging target RGB into the cube; iterative neighbour-fill for sparse bins. Identity LUT generator for testing.
- **fontsubset sidecar** — Webfont subsetter via `fontTools.subset`. Subset by `--text` string or `--unicodes` ranges; output WOFF2/WOFF/sfnt with optional zopfli compression and CFF desubroutinization.
- **8 new presets** — `pdf-to-markdown`, `ai-to-svg`, `svg-to-pdf-vector`, `separate-vocals`, `separate-4-stem`, `enhance-speech`, `subset-webfont`, `identity-lut`.
- **7 new Toolbox tiles** — `presets:sdkit`, `presets:speechenhance`, `presets:stemkit`, `presets:pdfmarkdown`, `presets:vectorkit`, `presets:lutgen`, `presets:fontsubset`. All route into the unified PresetsPage filtered by engine.

### Changed
- KNOWN_EVENTS extended with `sd_image`, `sd_model`, `speech_enhance`, `stem_track`, `stem_models`, `pdf_md`, `vector_doc`, `lut_cube`, `font_subset`. Contract test passes 51 sidecars.
- Version 2.7.0 → 2.8.0 across all manifests (csproj × 3, PowerShell module psd1, README badge, CLAUDE.md, `ucx serve` `/healthz`).

## [v2.3.0] - 2026-05-01

### Added
- **Demucs Vocal Remover** — `htdemucs_ft` model (MIT), 2-stem and 4-stem separation. VocalRemoverPage fully wired with queue UI, per-stem output to `<name>_stems/` subdirectory, model/format/quality controls, and cancel support.
- **Whisper STT** — `faster-whisper` primary (CUDA + CPU), `openai-whisper` fallback. SpeechToTextPage fully wired with queue UI, model size selector, language selector, output format (SRT/VTT/TXT/JSON/TSV), word timestamps toggle, and translate mode. Segment-level progress events.
- **RecordCast webcam + microphone** — DirectShow device enumeration via `ffmpeg -list_devices`. `ScreenToggle`/`WebcamToggle` source selector, webcam device dropdown, audio device dropdown. `list-devices` NDJSON sidecar op. Webcam + screen mux via FFmpeg dshow.
- **`ISidecarRunner.RunAsync` raw event callback** — New optional `Action<string, JsonElement>? onRawEvent` parameter added to both interface and implementation. Backward-compatible (all existing callers unaffected). Used by RecordCast for `device` events during enumeration.

### Changed
- `ToolboxTile` `ai-vocal` status: `"Future"` → `"Ready"` (engine: Demucs).
- `ToolboxTile` `ai-stt` status: `"Future"` → `"Ready"` (engine: Whisper).
- Version 2.2.0 → 2.3.0 across `Directory.Build.props` (root + src), `UniversalConverterX.UI.csproj`, `app.manifest`, `build-installer.ps1`, `SettingsWindow.xaml`, `HomePage.xaml`, README badge, ROADMAP header.

## [v2.2.0] - 2026-04-30

### Added
- **ClipForge crop op** — `-vf crop=W:H:X:Y` with CRF re-encode; W/H/X/Y inputs in Editor panel.
- **ClipForge rotate/flip op** — 90°/180°/270° transpose and horizontal/vertical flip via `transpose` filter chain; no-re-encode path for lossless rotations not yet supported (stream copy skipped for correctness).
- **ClipForge loudnorm op** — EBU R128 two-pass normalization. Pass 1 parses measured levels from FFmpeg stderr JSON; pass 2 targets configurable LUFS target (default −14 LUFS). Falls back to single-pass if JSON parsing fails.
- **ClipForge rewrap op** — Stream-copy container remux (`-c copy`). Adds `-movflags +faststart` for MP4/MOV/M4V. No re-encode; lossless and instant.
- **EditorPage multi-op UI** — `OperationCombo` selector (Trim / Crop / Rotate / Normalize Audio / Rewrap Container) with conditional panel reveal per op. Quality (CRF) panel hidden for lossless ops. Per-op output suffixes: `_trimmed`, `_cropped`, `_rotated`, `_normalized`, `_rewrapped`.
- **VideoCrush hardware acceleration** — `--hwaccel` flag (none / nvenc / amf / qsv / d3d12). `_HW_ENCODER` table maps codec × accelerator to FFmpeg encoder; VP9 and unsupported combos fall back to software.
- **CompressorPage HW accel dropdown** — Five-item combo (Software / NVIDIA NVENC / AMD AMF / Intel QSV / D3D12) above preset profiles. Selection passed as `--hwaccel` to videocrush.
- **Shared ONNX model cache** — `SidecarRunner` resolves `tools/_models/` and injects `UCX_MODEL_DIR` env var for all sidecar launches. AlphaCut sidecar reads `UCX_MODEL_DIR` (or `--model-dir` arg) and passes `model_dir` to `ProcessingWorker`. Future ONNX sidecars point to the same directory.

### Security
- Pinned `yt-dlp>=2026.02.21` in streamkeep/requirements.txt — fixes CVE-2026-26331 (command injection via `--netrc-cmd`).
- Pinned `onnxruntime>=1.25.0` in alphacut/requirements.txt — fixes heap OOB and integer overflow; aligns with ONNX Runtime 1.25 security advisory.

### Changed
- Version 2.1.0 → 2.2.0 across `Directory.Build.props` (root + src), `UniversalConverterX.UI.csproj`, `app.manifest`, `build-installer.ps1`, `SettingsWindow.xaml`, `HomePage.xaml`, README badge, ROADMAP header.

## [v2.1.0] - 2026-04-29

First three sidecar engines wired end-to-end. Compressor, Editor, and Downloader modules are functional.

### Added
- **UniConverter-style UX pass** — refreshed the WinUI resource palette to a light AI-suite direction, replaced the sparse Home launcher with a guided dashboard, added first-class AI Lab navigation, and added workflow/persona/tool cards aligned to the public UniConverter 17 feature surface.
- **Converter queue parity pass** — replaced the flat converter drop zone with a UniConverter-style queue layout: Converting / Finished tabs, Add Files / Add Folder actions, output location controls, per-file status/progress rows, finished result cards, and open-folder recovery.
- **Compressor queue parity pass** — upgraded Compressor from a single-file panel to a batch queue with Compressing / Finished tabs, Add Files / Add Folder, output folder selection, aggregate source/result/savings metrics, per-file progress, and finished result recovery.
- **Downloader queue parity pass** — replaced the single active download panel with queued URL intake, Downloading / Finished tabs, captured per-job options, per-job progress/log preview, sequential Download All, cancellation, and open-folder recovery.
- **Editor queue parity pass** — upgraded Editor from a single loaded-file trim flow to a batch edit queue with Add Files / Add Folder, Editing / Finished tabs, shared trim and re-encode settings, output-folder selection, per-file progress, cancellation, and finished result recovery.
- **Recorder screen-capture pass** — replaced the disabled Recorder placeholder with a queued recording workflow and a first-party `recordcast` FFmpeg sidecar for fixed-duration Windows desktop capture, per-session progress, cancellation, output-folder selection, and finished result recovery.
- **Format Inspector toolbox tool** — converted the Toolbox Format Inspector tile from a placeholder into a real workspace for batch file inspection, signature detection, conversion target suggestions, FFprobe stream metadata, selectable reports, and open-folder recovery.
- **Frame Snapshot toolbox tool** — converted the Toolbox Frame Snapshot tile from a placeholder into a real workspace for batch video still extraction, timestamp/interval plans, PNG/JPEG/WebP output, per-file progress, cancellation, and open-folder recovery.
- **Premium polish pass** — refined shared design tokens, typography, button sizing, shell trust cues, Home readiness hierarchy, Toolbox status semantics, AI Lab roadmap honesty, placeholder recovery actions, and Settings save/discard confidence.
- **Queue safety confirmations** — added consistent confirmation dialogs before clearing queued work across converter, compressor, downloader, editor, recorder, format inspector, and frame snapshot workspaces.
- **Settings trust polish** — replaced generic About links and simulated update checks with concrete repository destinations, releases access, and honest shell-registration guidance.
- **Converter recommendation panel** — added local file-type output guidance and one-click profile shortcuts for Smart Match, Web MP4, Audio MP3, and Image WebP workflows.
- **AI Lab page** — central route for planned Video Enhancer, Image Enhancer, Background Remover, Watermark Remover, Subtitle & Translation, Video Summarizer, Noise Remover, Vocal Remover, Voice Changer, TTS/STT, and photo restoration scope cards.
- **Search-driven navigation** — sidebar search and Home search now suggest modules/tools and route directly to the matching workspace.
- **`SidecarRunner` service** — generic launcher for `tools/<name>/<name>.exe` sidecars. Walks up from `AppContext.BaseDirectory` to locate the binary, falls back to `%LocalAppData%/UniversalConverterX/tools/`. Streams stdout NDJSON line-by-line, parses `progress`/`log`/`complete`/`error` events, supports cancellation by killing the process tree.
- **VideoCrush sidecar (Compressor)** — `tools/videocrush/sidecar.py` reimplements the FFmpeg two-pass / CRF compression logic without the PyQt6 dependency. Presets: `web-1080p`, `email-10mb`, `archive-av1`. AV1 falls back to single-pass since SVT-AV1's two-pass is unreliable through FFmpeg. `tools/videocrush/build.ps1` freezes via PyInstaller.
- **Compressor page wired** — drag/drop or browse → preset radio → live progress overlay (FFmpeg pass1/pass2 split, ETA, log tail) → result-size and savings calculation. Cancel kills the sidecar process tree.
- **ClipForge sidecar (Editor, trim op)** — `tools/clipforge/sidecar.py` exposes a `trim` op with `--start`, `--end`, `--lossless`, `--crf`, `--preset` flags. Lossless mode stream-copies (fast, keyframe-bounded); re-encode mode is frame-accurate. Crop/upscale/filter/audio extensions land as additional ops in v2.2+.
- **Editor page wired (trim slice)** — drag/drop or browse → start/end time inputs (seconds) → lossless toggle → CRF slider with quality hint label → Export.
- **StreamKeep sidecar (Downloader)** — `tools/streamkeep/sidecar.py` uses yt-dlp's Python API, covering 1000+ sites: YouTube, Twitch VODs, Vimeo, X/Twitter, Facebook, Instagram, Reddit, podcasts, direct URLs. Subcommands: `probe` (metadata + format list), `download` (with merge, audio-only, subtitle, format selectors). Native Kick/Rumble/SoundCloud extractors from StreamKeep's `streamkeep/` package land in v2.2+.
- **Downloader page wired** — paste URL → quality / container / audio-only / subtitle options → Download → live progress with speed and ETA, log tail, total bytes. Output defaults to `~/Downloads/UniversalConverterX/`. "Open Output Folder" launches Explorer at the target.

### Changed
- Settings navigation now opens the existing settings window instead of a placeholder page.
- Version 2.0.0 → 2.1.0 across `Directory.Build.props` (root + src), all csproj, app.manifest, WiX, MSIX, build-installer.ps1, SettingsWindow.xaml, README badges, HomePage footer.



## [v2.0.0] - 2026-04-29

Major scope expansion: from a context-menu file converter into a full all-in-one media tool — a Wondershare UniConverter alternative.

### Added
- **NavigationView shell** — Wondershare-style left sidebar with Home / Converter / Compressor / Editor / Downloader / Recorder / Toolbox / Account.
- **Home page** — hero, search, quick-launch module tiles, recent files area.
- **Toolbox page** — categorized tile grid with 29 specialized tools across Image, Video, AI, Audio, Disc, and Other.
- **Module shells** — Compressor, Video Editor, Downloader, and Recorder pages with mocked-up final-state UI.
- **Placeholder page** — generic "Coming Soon" landing for tiles whose backing engines arrive in later phases.
- **`tools/` directory — all 10 sidecar engines ported in.** Source code (~12 MB total) for VideoCrush, ClipForge, StreamKeep, AlphaCut, VideoSubtitleRemover, LipSight, Vertigo, FrameSnap, GifStudio, HEICShift now lives under the UCX repo. Build artifacts (`build/`, `dist/`, `__pycache__`, frozen `.exe`s, `.git`, AI working files) were stripped during the port. Each tool retains its `LICENSE`, original README (renamed to `README-source.md`), `requirements.txt`, and small assets.
- Per-tool sidecar README documenting UCX module mapping, integration phase, entry point, and runtime.
- Top-level [`tools/README.md`](tools/README.md) audit table with deliberate skip list (MediaForge, MediaDL, yt_livestream_downloader, Tunerize, Stock-Video-Collector, NovaCut, OpenCut).
- NDJSON sidecar contract documented in `tools/README.md`.

### Changed
- `MainWindow` no longer hosts the Converter UI directly — moved to `Views/Pages/ConverterPage.xaml`.
- App startup window resized to 1280x820 to fit sidebar + content.
- Title bar extended into client area with tall preferred height.
- Version bumped to 2.0.0 across `Directory.Build.props`, all csproj files, app.manifest, WiX, MSIX, build scripts, and SettingsWindow.

## [v1.0.0] - 2026-04

- Added: CI/CD build workflow.
- Added: Initial release with 13 converter backends (FFmpeg, ImageMagick, Pandoc, libvips, libjxl, etc.) covering 1000+ formats.
- Added: Right-click context menu integration via SharpShell.
- Added: CLI (`ucx`) with convert / list / info / config / tools commands.
- Added: WinUI 3 desktop UI with drag-and-drop and batch progress.
