# ROADMAP

<!-- Researched and updated 2026-04-30. Sources in Appendix. -->

UniversalConverterX (UCX) v2.2.0 — WinUI 3 / .NET 8 / Windows-only desktop app. Local-first, no telemetry, no account required. Replaces Wondershare UniConverter without the paywall. Strategy pattern (13 native backends) + NDJSON sidecar pattern for Python AI engines.

---

## Current State (v2.2.0)

**Wired end-to-end:** Native Converter (1000+ formats, magic-byte routing), VideoCrush compressor (CRF + 2-pass, AV1/H.265/H.264, HW accel NVENC/AMF/QSV/D3D12), ClipForge editor (trim, crop, rotate, loudnorm, rewrap), StreamKeep downloader (yt-dlp, 1000+ sites), RecordCast screen recorder, AlphaCut background remover (ONNX, shared model cache), FrameSnap (batch frame extraction), Format Inspector (FFprobe), CLI (`ucx`), Shell Extension (right-click).

**Stubbed / placeholder (page exists, no sidecar):** VideoEnhancer, ImageEnhancer, NoiseRemover, PhotoRestoration, WatermarkRemover, VideoSummarizer, VocalRemover, VoiceChanger, SpeechToText, TextToSpeech, AiSubtitle, VideoStabilizer, SmartTrimmer, AutoReframe, AutoCrop, WatermarkEditor, AutoHighlight, IntroOutro, LensCorrection, VRConverter, ImageConverter, GifMaker, ImageUpscaler, AiPortrait, SlideshowMaker, MetadataEditor, AudioCompressor, BatchRename, DVD/CD.

**Editor gaps (ClipForge):** Upscale and audio filter ops deferred to v2.3.

**Recorder gaps (RecordCast):** Only desktop screen capture; webcam, microphone, system audio deferred.

---

## Tier Definitions

| Tier | Meaning |
|------|---------|
| **Now** | v2.2 — either already stubbed and needs sidecar, or security/regression critical |
| **Next** | v2.3–v2.5 — high-value, scoped, no blocking dependency |
| **Later** | v3.x — meaningful but requires significant new infrastructure |
| **Under Consideration** | Needs more validation before committing resources |
| **Rejected** | Explicitly out of scope — reason given |

---

## NOW (v2.2)

### 1. Security: yt-dlp CVE-2026-26331 pin update
Pin StreamKeep's yt-dlp to ≥ 2026.02.21 (command injection via `--netrc-cmd`). Update `requirements.txt` in streamkeep sidecar and re-freeze. **Impact 5 / Effort 1.** [S-1]

### 2. Security: ONNX Runtime upgrade to 1.25.x
ORT 1.25.0 fixes heap OOB read/write, Pad Reflect vulnerability, integer overflow, and multiple input validation bugs across CPU kernels. Raises CUDA minimum to 12.0; CUDA Plugin EP now available. Update all Python sidecars that import `onnxruntime`. **Impact 4 / Effort 2.** [S-2]

### 3. Shared ONNX Model Cache (`tools/_models/`)
AlphaCut, VideoSubtitleRemover, and future ONNX sidecars should all resolve models from a single `tools/_models/` directory. Models download on first use, shared across sidecars. Eliminates duplicate ~500 MB downloads. Implementation: SidecarRunner passes `--model-dir` flag; each sidecar honours it. **Impact 4 / Effort 2.**

### 4. VideoSubtitleRemover sidecar (subtitle inpainting)
Port `VideoSubtitleRemover` Python source to UCX NDJSON sidecar contract. Wires to existing SubtitleRemoverPage. **Impact 4 / Effort 3.** [R-4]

### 5. LipSight sidecar (visual lip reading)
Port LipSight Python source to NDJSON sidecar. Wires to LipReadingPage. **Impact 3 / Effort 3.**

### 6. Editor: Crop + Rotate
ClipForge sidecar already handles trim via FFmpeg. Add `-vf crop=W:H:X:Y` and `-vf transpose=N` passes to ClipForge. Expose in ClipForge UI and wire to existing page controls. This is the single highest-demand incomplete ClipForge feature — crop is table stakes for any video editor. **Impact 5 / Effort 2.** [R-3]

### 7. Editor: Audio Normalize (LUFS / R128)
Add FFmpeg `loudnorm` filter to ClipForge as an optional pass. Target: EBU R128 / -14 LUFS (streaming default). Expose as a toggle in the editor UI. Requires no new sidecar; add to ClipForge command builder. **Impact 4 / Effort 1.** [R-11]

### 8. Editor: Undo / Redo
ClipForge currently applies operations destructively. Maintain an in-memory operations stack. This is baseline editor UX. LosslessCut ships this; our editor page needs it before feature expansion. **Impact 4 / Effort 2.** [R-3]

### 9. Lossless Trim Mode (stream copy, no re-encode)
Add a `--lossless` flag to ClipForge that routes trim through `ffmpeg -c copy` instead of re-encoding. Huge quality and speed win for cut-to-post workflows; LosslessCut is built entirely on this. Expose as a "Lossless Cut" toggle in the editor — default for trim-only operations. **Impact 5 / Effort 2.** [R-3]

### 10. Demucs Vocal Remover sidecar
VocalRemoverPage stub exists. Implement `demucs` (htdemucs_ft model, 9 dB SDR) as an NDJSON sidecar. Output vocals + accompaniment tracks. Demucs v4 is MIT-licensed, ONNX-exportable. Model cache via `tools/_models/`. **Impact 5 / Effort 3.** [R-6]

### 11. whisper.cpp Speech-to-Text sidecar
SpeechToTextPage stub exists. Use `whisper.cpp` C++ binary (not Python Whisper) — no Python dependency, supports GPU via Vulkan, ships as a single `.exe`, all 6 model sizes from tiny (75 MB) to large (2.9 GB). Download model on first use to `tools/_models/`. Output: SRT/VTT/TXT formats. **Impact 5 / Effort 3.** [R-7, R-8]

### 12. D3D12 Hardware Acceleration in VideoCrush
FFmpeg 8.1 added D3D12 H.264/AV1 encoding and `scale_d3d12`/`deinterlace_d3d12` filters. Expose a hardware acceleration dropdown (None / NVENC / AMF / QSV / D3D12) in VideoCrush UI. Auto-detect available encoders via `ffmpeg -encoders`. **Impact 4 / Effort 2.** [S-3]

### 13. Recorder: Webcam + Microphone
RecordCast currently captures desktop only. Add webcam (DirectShow `dshow` device source) and microphone inputs to the RecordCast sidecar. Multi-source mux via FFmpeg. Wires to existing RecorderPage device selection stubs. **Impact 4 / Effort 3.**

---

## NEXT (v2.3–v2.5)

### 14. Vertigo Auto-Reframe sidecar (v2.3)
Already in CLAUDE.md schedule. 9:16/1:1/4:5 output with MediaPipe face tracking. Wires to AutoReframePage. **Impact 4 / Effort 3.**

### 15. GifStudio (v2.3)
WebView2 host, already in CLAUDE.md. Palette optimization, loop control, delay editor. **Impact 3 / Effort 2.**

### 16. HEICShift (v2.3)
HEIC/HEIF decode + metadata/ICC profile defaults. Absorbed into libvips/libjxl strategy chain. **Impact 3 / Effort 2.**

### 17. WinAppSDK 2.0 Upgrade
UCX targets WinAppSDK 1.5. WinAppSDK 2.0 (released 2026-04-29) ships: `SystemBackdropElement` for in-app Mica/Acrylic anywhere in XAML layout, updated Storage Pickers (multi-folder select, file type grouping, persistent session ID, suggested start folders), Windows ML refactor to `Microsoft.Windows.AI.MachineLearning`, WebView2 drag support, and various WinUI 3 bug fixes. Upgrade requires package family name change. **Impact 4 / Effort 3.** [S-5]

### 18. Real-ESRGAN Image Upscaler sidecar
ImageUpscalerPage stub exists. Use `realesrgan-ncnn-vulkan` executable (Intel/AMD/NVIDIA GPU via Vulkan, no Python, portable binary). Models: `RealESRGAN_x4plus` (photo), `RealESRGAN_x4plus_anime_6B` (anime), `realesr-general-x4v3` (tiny, general). Download on first use to `tools/_models/`. **Impact 5 / Effort 3.** [R-5]

### 19. GFPGAN Face Restoration sidecar
PhotoRestorationPage stub exists. GFPGAN v1.4 (Apache 2.0) restores old/degraded photos and enhances faces. Combine with Real-ESRGAN background enhancement for full-photo restoration pipeline. **Impact 4 / Effort 3.** [R-5]

### 20. Demucs Full Stem Separation
Extend Vocal Remover sidecar (item 10) to expose 4-stem (drums/bass/vocals/other) and experimental 6-stem (adds guitar/piano) separation. Output each stem as a separate WAV/FLAC file. Name stems clearly for DAW import. **Impact 4 / Effort 2.** (builds on #10)

### 21. VMAF Quality Analysis Tool
Shutter Encoder ships VMAF analysis as a built-in function. UCX already has Format Inspector. Add a VMAF comparison workspace: reference + distorted → per-frame VMAF score chart + mean/harmonic-mean summary. Uses `ffmpeg -vf libvmaf`. Surfaces quality budget signal for the compressor. **Impact 3 / Effort 3.** [R-11]

### 22. Scene Detection + Auto-Split
Add `ffmpeg -vf select='gt(scene\,0.3)'` scene change detection to the editor toolbox. Output: timestamped chapter list or batch-split files. Silence detection (`silencedetect` filter) as companion feature. Both map to existing SmartTrimmer stub. **Impact 4 / Effort 2.** [R-3]

### 23. Editor: Timeline Waveform + Thumbnail Strip
ClipForge UI needs a visual waveform + keyframe thumbnail strip below the seek bar before feature expansion beyond trim. Without this, crop/filter/split UX is unusable. Use FFmpeg to pre-extract thumbnails at 1 fps and waveform via `showwavespic`. **Impact 5 / Effort 3.** [R-3]

### 24. Chapter Marks Editor (MKV/MP4)
Edit embedded chapter markers in MKV and MP4 files via FFmpeg metadata. Expose as a toolbox workspace. LosslessCut ships this — high usage for long-form video/podcast audiences. **Impact 3 / Effort 2.** [R-3]

### 25. Rewrap Without Re-encode (Container Swap)
`ffmpeg -c copy` container remux — MKV↔MP4↔MOV↔TS without quality loss. 10–100× faster than transcoding. Expose as a "Rewrap" option in Converter and Toolbox (MetadataEditor stub is adjacent). **Impact 4 / Effort 1.** [R-3]

### 26. Multi-track Stream Management
Add/remove audio, subtitle, and data tracks from a video container without re-encoding. LosslessCut's most-requested feature class. Expose as a track manager panel in the editor. **Impact 4 / Effort 3.** [R-3]

### 27. Watch Folder Automation
Monitor a folder; apply a user-defined conversion profile to any new file. Unmanic and Tdarr prove this pattern has sustained user demand. Windows integration: `FileSystemWatcher` in the host process or as a background service. Queue fed into existing conversion pipeline. **Impact 4 / Effort 3.** [R-9, R-10]

### 28. Whisper Auto-Subtitle + Translation
Extend whisper.cpp sidecar (item 11) to auto-generate SRT/VTT subtitle files. Add optional DeepL/LibreTranslate post-processing pass for multilingual output. Wires to AiSubtitlePage stub. **Impact 5 / Effort 2.** (builds on #11)

### 29. Text-to-Speech sidecar
TextToSpeechPage stub exists. Use `edge-tts` (Microsoft Edge Neural TTS, free Python package, no API key, no network dependency beyond first use — voices cached locally) for high-quality voices in 100+ languages. Expose: voice selection, speed, pitch, output format (MP3/WAV/OGG). **Impact 4 / Effort 2.** [R-12, S-7]

### 30. PowerShell Module (`ucx.psm1`)
Expose conversion pipeline via `Convert-MediaFile`, `Compress-MediaFile`, `Get-MediaInfo`, `Watch-Folder` cmdlets. Each cmdlet wraps `ucx` CLI with typed parameters and progress-bar output. Target: sysadmin batch-processing workflows. **Impact 3 / Effort 2.**

### 31. REST API Server Mode (local loopback)
Bind `ucx serve` to `127.0.0.1:PORT`. OpenAPI-documented endpoints: `POST /convert`, `GET /jobs/{id}`, `GET /tools`. Enables integration with n8n, PowerAutomate desktop, and custom scripts without shell subprocess. LosslessCut and Transmute both ship HTTP APIs for this reason. **Impact 3 / Effort 3.** [R-2, R-3]

### 32. Conversion History Dashboard
Persistent SQLite log of every conversion job (timestamp, source, target, engine, duration, size-before/after, exit code). Surfaces in a History page with search, filter, re-run, and "files saved" aggregate. File_Converter_Pro (SQLite gamification) and Tdarr (job reports) validate user demand for this data. **Impact 3 / Effort 2.** [R-13, R-10]

### 33. JPEG XL Encode/Decode
libjxl is already a planned UCX dependency. Surface JPEG XL as a conversion target in the native Converter with a quality slider and metadata strip control. Shutter Encoder ships this as a named output option. **Impact 3 / Effort 1.** [R-11]

### 34. FFV1 Archival Codec Preset
Add an "Archive (FFV1 + FLAC in MKV)" preset to VideoCrush. FFV1 is lossless, bit-exact, checksummed. Target audience: digital archivists who currently convert from Shutter Encoder. FFmpeg 8.1 shipped Vulkan-based FFV1 encode/decode. **Impact 3 / Effort 1.** [R-3, R-11]

### 35. Accessibility: Windows Narrator + Keyboard Nav
HandBrake 1.11.0 shipped screen reader fixes as a named release feature — this is now user-visible parity work. Audit all WinUI 3 pages for: `AutomationProperties.Name` on unlabeled controls, tab-stop order, focus ring visibility, progress bar accessible names. **Impact 4 / Effort 3.** [R-1]

---

## LATER (v3.x)

### 36. Gyroflow Video Stabilization
Gyroflow uses embedded gyroscope data from cameras (GoPro, Sony, DJI, Insta360, Canon, Blackmagic, RED) for precision digital stabilization. It ships as a portable `.exe` with GPU rendering. Integration: spawn as sidecar, expose camera model selection and smoothness slider. More accurate than optical-flow-only stabilizers. **Impact 4 / Effort 4.** [R-14]

### 37. GPU-Accelerated Whisper (whisper.cpp Vulkan/CUDA)
whisper.cpp supports Vulkan and CUDA GPU inference. Enables real-time or faster-than-realtime transcription on consumer hardware. Build or bundle GPU-enabled whisper.cpp binary as an optional upgrade to the CPU-only sidecar from #11. **Impact 4 / Effort 3.** [R-8]

### 38. Conditional Transcode Rules (Plugin Stack)
Tdarr's plugin stack model: user builds a conditional chain (e.g., "only transcode if not H.265", "remove subs", "add stereo AAC if absent"). Each rule is a composable unit. For UCX: implement as a Watch Folder extension — a rule editor that maps file properties → conversion actions. **Impact 4 / Effort 5.** [R-10]

### 39. OCR: Image/PDF → Searchable PDF / TXT
Tesseract OCR wrapper. Input: image files or scanned PDFs. Output: searchable PDF (hOCR overlay) or plain TXT. Use existing PDF backend infrastructure. **Impact 3 / Effort 3.**

### 40. DICOM → PNG/JPG/NIfTI
`dcmtk` wrapper for radiology/medical imaging workflows. Native use case given the developer's PACS domain. DICOM frames → PNG sequence or NIfTI volume. **Impact 2 / Effort 3.**

### 41. Font Conversion (TTF ↔ OTF ↔ WOFF ↔ WOFF2)
`fonttools` Python wrapper. Existing planned item. **Impact 2 / Effort 2.**

### 42. i18n / Localization Framework
FileConverter ships 25+ languages via `.resx` resource files. UCX has no localization layer. Add `Resources.resw` per-language files, switch WinUI 3 text bindings to resource lookups. Priority languages: English (done), French, German, Spanish, Chinese Simplified, Japanese. **Impact 4 / Effort 4.** [R-15]

### 43. H.266 / VVC Encoding
Shutter Encoder already ships H.266 output. VVC offers 50% bitrate reduction vs H.265 at equivalent quality. FFmpeg integration via `libvvenc`. Encoding is CPU-heavy (no GPU path yet); position as "archive/archival streaming" tier. **Impact 2 / Effort 3.** [R-11]

### 44. ProRes RAW Decode + Encode
FFmpeg 8.0 shipped ProRes RAW decode (Vulkan). Encode is in review for 8.1.x. Target: professional camera workflows (Sony FX series, Canon Cinema). **Impact 2 / Effort 3.** [S-3]

### 45. FunASR / SenseVoice Streaming STT
SenseVoice supports 31 languages and real-time streaming transcription. Alternative to Whisper for non-English-primary users. Consider as a configurable backend selector in the STT page alongside whisper.cpp. **Impact 3 / Effort 4.** [R-16]

### 46. MV-HEVC / Stereoscopic Output
FFmpeg 7.1 added MV-HEVC decode for VR headsets (Apple Vision Pro, Quest). Future-leaning: expose MV-HEVC muxing for side-by-side stereoscopic input. VR Converter stub exists in Toolbox. **Impact 2 / Effort 4.** [S-3]

### 47. IAMF Spatial Audio Support
FFmpeg 8.1 added IAMF Ambisonic Audio muxing/demuxing. Spatial audio for next-gen streaming/VR. Low immediate demand but zero competition in the Windows desktop converter space. **Impact 2 / Effort 3.** [S-3]

### 48. Winget / MSIX Distribution
Publish UCX to Windows Package Manager (`winget install UCX`) and optionally Microsoft Store. WinAppSDK 2.0 ships an improved `IPackageValidator` framework. Chocolatey/Scoop packages as complementary distribution. **Impact 3 / Effort 3.** [S-5]

### 49. .NET 10 LTS Migration
.NET 8 LTS support ends 2026-11-10. .NET 10 LTS targets late 2025 with support until 2027. HandBrake is already migrating from .NET 4.8 to .NET 10. Target this for UCX v3.0 alongside WinAppSDK 2.x compatibility audit. **Impact 3 / Effort 3.** [R-1]

### 50. Integration Test Suite
Add automated end-to-end tests for conversion pipelines: reference input → expected output format detection + spot-check on output validity (FFprobe metadata roundtrip). No UI tests — CLI + sidecar contract only. Target: CI gatekeeping for backend regressions. **Impact 3 / Effort 3.**

### 51. User Documentation / Wiki
In-app help overlay or GitHub Wiki covering: quick-start per module, supported format matrix, sidecar requirements, CLI reference, common workflows. Currently zero user docs beyond README. **Impact 3 / Effort 2.**

---

## UNDER CONSIDERATION

### A. Pandoc Document Converter Integration
Pandoc 3.9 converts 50+ markup formats (DOCX, ODT, LaTeX, Markdown, EPUB, PPTX, HTML, etc.). Would fill the non-image, non-AV document gap in UCX's format matrix. Complexity: Pandoc requires Haskell runtime or a ~100 MB self-contained binary. Already listed as a native backend candidate. Validate demand via user feedback before committing. [S-6]

### B. Calibre Ebook Pipeline (EPUB ↔ MOBI ↔ AZW3)
`ebook-convert` CLI. Adds a format category UCX currently lacks. Calibre binary is 300 MB. Demand signal unclear for this user base. [S-6]

### C. 3D Format Conversion (glTF / OBJ / STL)
Via Assimp + Blender headless. Already listed in original roadmap. Very niche. Validate before v3.x work begins.

### D. Library Statistics Dashboard
File count, codec distribution, total space saved, conversion trends over time — visualized (Matplotlib in a WebView2 pane or WinUI 3 charts). Tdarr and File_Converter_Pro validate the UX. Prerequisite: History dashboard (#32) must be live first. [R-10, R-13]

### E. Windows AI / Phi Silica Integration
WinAppSDK 2.0 ships `AICapabilities.HasAICapability` to detect Copilot+ PCs with NPU hardware. If hardware is present, Phi Silica (on-device LLM) could power Video Summarizer, caption polish, and intelligent preset selection. This is a leapfrog opportunity — no competitor does this. Prerequisite: WinAppSDK 2.0 upgrade (#17). [S-5]

### F. Gyroflow NLE Plugins
Gyroflow ships plugins for Adobe Premiere, DaVinci Resolve, and Final Cut Pro. A UCX-to-Gyroflow handoff (export `.gcsv` metadata, launch Gyroflow) would be lower effort than full stabilization integration. Assess before committing to #36.

---

## REJECTED

| Item | Reason |
|------|---------|
| Cloud file processing (upload to Cloudconvert/Convertio/etc.) | Contradicts core philosophy: local processing, no telemetry, no third-party access to files |
| OIDC / SSO multi-user server | Desktop-local product; server/multi-user mode contradicts scope |
| Mobile (Android / iOS) | Windows-only by design; WinUI 3 has no mobile target; not on the table for any version |
| CD optical ripping | Optical drive ownership is rare in 2026; `cdrtools` GPL-2 license conflict; low demand |
| Blu-ray rip | CSS/AACS/BDMV circumvention is legally prohibited in most jurisdictions (DMCA §1201, EU Directive) |
| DRM circumvention of any kind | Legal liability; explicitly refused with error dialog if DRM is detected |
| Cryptocurrency / blockchain metadata | Irrelevant to domain |
| Autonomous cloud AI inference (Replicate/Huggingface API calls) | Requires outbound network, API keys, and sends user media to third parties |

---

## Architecture Notes

**Offline / resilience:** UCX is 100% offline by design. No network calls are made during conversion. Model downloads and yt-dlp update checks are the only network operations, both opt-in and skippable. All AI inference runs locally via ONNX Runtime or whisper.cpp.

**Sidecar contract (NDJSON):** All Python AI sidecars communicate via stdout NDJSON lines. Events: `progress` (0–100%), `log` (informational), `complete` (with output path), `error` (with message). SidecarRunner.cs is the C# orchestrator; new sidecars must conform to this contract.

**Binary discovery:** `SidecarRunner` walks from `AppContext.BaseDirectory` upward looking for `tools/<name>/<name>.exe`, then falls back to `%LocalAppData%\UniversalConverterX\tools\`. All sidecars are PyInstaller-frozen Windows executables.

**Model cache:** `tools/_models/` is the shared ONNX model directory. Sidecars receive a `--model-dir` CLI argument pointing to this path. Models are downloaded on first use and verified by SHA-256.

**Platform ceiling:** .NET 8 LTS until 2026-11-10. Target .NET 10 LTS (ships late 2025, mainstream support until 2027) for v3.0. WinAppSDK 1.5 → 2.0 migration is a v2.3+ target.

**Engine versions (current):** FFmpeg static build (tracked in `tools/README.md`), yt-dlp (pin ≥ 2026.02.21 for CVE-2026-26331), ONNX Runtime (upgrade to 1.25.x), ImageMagick 7.1.2-21+, WinAppSDK 1.5.x → target 2.0.1.

---

## Security Posture

| Component | Current Risk | Remediation |
|-----------|-------------|-------------|
| yt-dlp (StreamKeep) | **CVE-2026-26331** command injection via `--netrc-cmd` | Pin ≥ 2026.02.21 (NOW) |
| ONNX Runtime (all ONNX sidecars) | Heap OOB, integer overflow in CPU kernels | Upgrade to 1.25.x (NOW) |
| NDJSON IPC contract | Path traversal via `output_path` field | Validate all output paths are under designated output dir (NOW) |
| FFmpeg (VideoCrush, ClipForge, RecordCast) | Regular CVE cadence; static build | Pin to vetted stable build; track FFmpeg security advisories |
| ImageMagick (native Converter) | CVE-active project; frequent memory safety issues | Pin to 7.1.2-21+; do not process untrusted remote input |
| Process isolation | Sidecars run in-process with user privileges | Evaluate job-object-based sandbox for sidecar processes in v2.3 |

---

## Appendix: Sources

### OSS Competitors
- [R-1] https://github.com/HandBrake/HandBrake/releases — HandBrake v1.11.0 (DNxHR, ProRes, AV1 AMD 10-bit, PCM, MOV, screen reader accessibility)
- [R-2] https://github.com/transmute-app/transmute — Transmute: self-hosted Docker converter, REST API, OIDC, 7 themes
- [R-3] https://github.com/mifi/lossless-cut — LosslessCut: lossless trim, smart cut, multi-track, chapter editor, HTTP API, scene detection
- [R-4] https://github.com/C4illin/ConvertX — ConvertX: self-hosted TS, VTracer, Markitdown, Dasel, dvisvgm, msgconvert
- [R-5] https://github.com/xinntao/Real-ESRGAN — Real-ESRGAN: 4x photo + anime upscaler, ncnn-Vulkan portable exe
- [R-5b] https://github.com/TencentARC/GFPGAN — GFPGAN v1.4: blind face restoration, Apache 2.0
- [R-6] https://github.com/facebookresearch/demucs — Demucs v4 (htdemucs): 4/6-stem music separation, 9.0 dB SDR, MIT license
- [R-7] https://github.com/openai/whisper — Whisper: multilingual ASR, 6 model sizes (75 MB–2.9 GB), turbo model 8× speed
- [R-8] https://github.com/ggml-org/whisper.cpp — whisper.cpp: C++ ASR inference, Vulkan/CUDA GPU support, zero-dependency binary
- [R-9] https://github.com/Unmanic/unmanic — Unmanic: watch-folder library optimiser, FFmpeg plugin system
- [R-10] https://github.com/HaveAGitGat/Tdarr — Tdarr: distributed conditional transcode, plugin stack, library stats, job reports
- [R-11] https://www.shutterencoder.com/en/ — Shutter Encoder: VMAF, loudness analysis, H.266, FFV1, JPEG XL, ProRes, AI functions list
- [R-12] https://github.com/staxrip/staxrip — StaxRip: AviSynth/VapourSynth scripting GUI for advanced encoding
- [R-13] https://github.com/Hyacinthe-primus/File_Converter_Pro — File_Converter_Pro: SQLite gamification/stats, i18n .lang JSON, project files
- [R-14] https://github.com/gyroflow/gyroflow — Gyroflow: gyro-based video stabilization, GPU rendering, 40+ camera sources
- [R-15] https://github.com/Tichau/FileConverter — FileConverter: 20k+ stars, 25+ languages, SharpShell context menu
- [R-16] https://github.com/alibaba-damo-academy/FunASR — FunASR/SenseVoice: 31-language ASR, VAD, speaker diarization
- [R-17] https://github.com/ozmartian/vidcutter — VidCutter: PyQt5 trim/cut tool, cross-platform

### Platform / Framework
- [S-1] https://github.com/yt-dlp/yt-dlp/releases — CVE-2026-26331 in 2026.02.21; browser impersonation, extractor fixes in 2026.03.17
- [S-2] https://github.com/microsoft/onnxruntime/releases — ORT 1.25.0: CUDA minimum → 12.0, CUDA Plugin EP, 15+ security fixes; ORT 1.25.1 patch
- [S-3] https://ffmpeg.org/index.html#news — FFmpeg 8.0 "Huffman" (ProRes RAW, Vulkan FFv1, D3D12, Whisper filter); FFmpeg 8.1 "Hoare" (D3D12 H.264/AV1 encode, EXIF, IAMF, Vulkan ProRes)
- [S-4] https://github.com/ImageMagick/ImageMagick/releases — ImageMagick 7.1.2-21 (latest stable, active security fixes)
- [S-5] https://github.com/microsoft/WindowsAppSDK/releases — WinAppSDK 2.0.1: SystemBackdropElement, Storage Pickers 2.0, Windows ML refactor, ORT 1.24.5 bundled, MSIX validator
- [S-6] https://github.com/jgm/pandoc/releases — Pandoc 3.9.0.2: DOCX/ODT/Typst/EPUB/Markdown/HTML/LaTeX universal converter
- [S-7] https://github.com/rany2/edge-tts — edge-tts: Python client for Microsoft Edge Neural TTS, 100+ voices, MIT license

### Community Signal
- https://github.com/topics/file-converter — GitHub topic: OSS landscape survey
- https://github.com/topics/video-converter?l=c%23 — C# video converter topic
- https://handbrake.fr/features.php — HandBrake feature reference (queue metaphor, RF slider, HW accel)
