# UniversalConverterX — Product Roadmap

**Status:** v2.20.1 · 176 sidecar engines · 274+ presets · 45 UI pages
**Last updated:** 2026-05-01 (Phase 5 audit reconciliation)

All format-coverage waves (A–X, shipped through v2.20.1) are complete and
retired from this document. This roadmap focuses on the next strategic
axes: wiring built engines into the UI, platform upgrades, new
capabilities, developer experience, distribution, security, and
accessibility.

> **Phase 5 audit reconciliation (2026-05-01):** items 4, 8, and 11 are
> retired below — items 4 and 11 shipped this iteration; item 8 was already
> shipped in a prior version but never crossed off. See
> [`docs/research/iter-1-audit.md`](docs/research/iter-1-audit.md) for the
> full audit (seven dimensions, cross-family signal). Item 6 (Conversion
> History) is flagged for verification next iteration.

**Design charter (unchanged):** Offline-first. No cloud. No accounts. No
telemetry. Windows 10 21H2+. Beat every competitor on: format coverage,
batch UX, programmability (CLI + REST + PS module), and AI depth.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| **Now** | Ship next (v2.21–v2.22). High certainty, well-scoped. |
| **Next** | v2.23–v2.27 window. Design complete or dependencies blocked on Now items. |
| **Later** | v2.27+. Higher effort, lower urgency, or needs community signal. |
| **UC** | Under Consideration — needs more investigation before placement. |
| **Rejected** | Will not ship. Reason stated. |
| **Impact** | User value 1 (niche) – 5 (universal). |
| **Effort** | Engineering cost 1 (hours) – 5 (weeks of cross-cutting work). |
| **Type** | `parity` = catch-up to table-stakes competitor feature; `leapfrog` = ahead of the field; `platform` = infra/framework upgrade; `dx` = dev/maintainer experience. |

---

## Tier 1 — Now  _(v2.21–v2.22)_

Short-iteration items: UI wiring for already-built engines, UX reliability
fixes, and security hygiene. None of these require a new sidecar engine.

> **Tier 1 promotions from Phase 5 audit (2026-05-02):** Items 20
> (SponsorBlock) and 30 (Audio VBR Quality Mode) are also Tier 1 Now —
> both Effort 1 with Impact 3-4. They retain their existing numbering
> under Tier 2 below to keep cross-references stable, but are scheduled
> alongside the items in this section.

### 1. AiLab UI Wiring — ⚠️ PARTIALLY SHIPPED (narrow scope)

Phase 5 audit (2026-05-01) found three of the four "Future" tiles already
wired to live pages — only Voice Changer remains.

| Tile | Status | Evidence |
|------|--------|----------|
| Text-to-Speech | ✅ shipped | `TextToSpeechPage.xaml.cs` exists; routed in `MainWindow.xaml.cs:152` |
| Speech-to-Text | ✅ shipped | `SpeechToTextPage.xaml.cs` exists; routed in `MainWindow.xaml.cs:153` |
| Old Photo Restoration | ✅ shipped | `PhotoRestorationPage.xaml.cs` exists; routed in `MainWindow.xaml.cs:154` |
| AI Voice Changer | ❌ engine TBD | `VoiceChangerPage.xaml` exists but is a placeholder; no RVC/so-vits-svc sidecar yet |

**Remaining work** (narrowed):

- Voice Changer engine selection — needs sidecar choice (RVC, so-vits-svc, or other), then UI wiring.

Impact: 3 · Effort: 3 · Type: leapfrog
Sources: [S3], [S4], [S10]

---

### 2. AudioTools — Audio Compressor standalone page

`audio-compressor` sidecar already exists. Wire it to a `AudioCompressorPage.xaml`
matching the same pattern as existing AudioTools pages: threshold, ratio,
attack/release sliders, preview waveform (optional Phase 2 enhancement).

Impact: 4 · Effort: 1 · Type: parity
Source: [S5] (ToolboxPage.xaml.cs stub)

---

### 3. OtherTools — Batch Rename

New `batchrename` sidecar (or pure-C# implementation): regex/pattern-based
file rename with live preview. Tokens: `{n}` (1-based counter), `{date}`,
`{exif:date}`, `{parent}`, `{ext}`, regex replace, case transform.
Ship a `BatchRenamePage.xaml` with live preview table.

No sidecar strictly needed — `System.IO.File.Move` in the UI project is
sufficient for a first pass. ExifTool integration for `{exif:*}` tokens is
a Next-tier enhancement.

Impact: 4 · Effort: 2 · Type: parity
Sources: [S5] (ToolboxPage stub), [S6] (competitor feature)

---

### 4. Output Filename Collision Protection — ✅ SHIPPED 2026-05-01

When an output file already exists: auto-append ` (1)`, ` (2)` etc. instead
of silently overwriting or erroring. Apply across all sidecars via the Core
orchestrator — one fix, universal effect.

Impact: 5 · Effort: 1 · Type: parity
Sources: [S11] (HandBrake #7848), [S12] (LosslessCut overwrite issue #2667)
**Closing commit:** `80932bd` — `Core/Utilities/UniqueOutputPath` + orchestrator
switch on `OverwriteBehavior`, 11 new xUnit tests, 161/161 Core suite passing.

---

### 5. Output Filename Template DSL

User-configurable output filename pattern: `{title}_{date}_{resolution}.{ext}`.
Supported tokens for video/audio: `{title}`, `{artist}`, `{date}`, `{year}`,
`{resolution}`, `{fps}`, `{bitrate}`, `{codec}`, `{duration}`, `{n}` (counter).
Store as a per-preset optional `<OutputTemplate>` element in preset XML.
Fallback to existing stem-based naming when unset.

Impact: 4 · Effort: 2 · Type: leapfrog
Sources: [S13] (yt-dlp `%(title)s` pattern system), [S14] (general UX pattern)

---

### 6. Conversion History / Activity Log — ✅ SHIPPED (already)

Persist every completed job to a SQLite database: timestamp, engine, input
file, output file, duration, file sizes, exit code, log snippet. Surface as
a `HistoryPage.xaml` with filter/search, re-run action, and "open output
folder" shortcut. Log is local-only — consistent with offline-first charter.

Impact: 4 · Effort: 2 · Type: parity
Source: [S14] (common request across all media converter communities)

**Already shipped (verified 2026-05-01 audit):**
`HistoryService.cs` (414 LOC, SQLite-backed `HistoryRecord` schema with
timestamp/engine/action/source/output/bytes/duration/error fields).
`HistoryPage.xaml.cs` (138 LOC) with search, refresh, clear, open-output,
re-run wired. `ConverterXOptions.{EnableHistory=true, MaxHistoryEntries=1000,
HistoryRetentionDays=30}` for retention policy.

---

### 7. Dependency Update Checker

Background check (on app start, at most once per 24 h) against GitHub Releases
for yt-dlp, whisper-cpp, ffmpeg-builds, and onnxruntime. Show a non-blocking
toast with one-click update. This directly addresses the CVE triage workflow
(v2.2.0 pinned yt-dlp for CVE-2026-26331 and onnxruntime for heap OOB
manually — automate the detection step).

Impact: 4 · Effort: 2 · Type: dx + security
Sources: [S1] (CHANGELOG v2.2.0 CVE pins), [S15] (YoutubeDownloader auto-update env var)

**Charter note (Phase 5 audit, 2026-05-02):** This item makes outbound
network requests to GitHub Releases. Charter-aligned because (a) the
request is one-way (no telemetry sent), (b) it polls only release
manifests (no user data), (c) it must be opt-out-able via a Settings
toggle (`CheckForUpdates`, already exists in `ConverterXOptions`).
Implementation must respect the toggle + show clear network indicator
in the UI.

---

### 8. Parallel Job Limit Setting — ✅ SHIPPED (already)

Expose the max-concurrent-jobs cap as a user setting (default: CPU count / 2,
range 1–16). Adds a single `<Slider>` in
`SettingsPage.xaml` and one property in `AppSettings`.

Impact: 3 · Effort: 1 · Type: parity
Source: [S14] (common user request in HandBrake / FFmpeg GUI communities)

**Already shipped (verified 2026-05-01 audit):**
`SettingsWindow.xaml:178-200` ParallelSlider (Min=1, Max=16, default Value=4).
`ConverterXOptions.cs:61` `MaxParallelConversions = ProcessorCount / 2`.
`ConversionOrchestrator.cs:235` runtime clamp. `ConfigCommand.cs:64,111`
`--max-parallel` CLI flag.

---

### 9. yt-dlp Cookie Credential Encryption

Encrypt stored yt-dlp cookies at rest using Windows DPAPI
(`System.Security.Cryptography.ProtectedData`), machine-scoped. Mirrors the
approach shipped in YoutubeDownloader v1.14+. Prevents credential leakage if
the UCX app data folder is exfiltrated.

Impact: 3 · Effort: 1 · Type: security
Source: [S15] (YoutubeDownloader DPAPI cookie encryption, v1.14 changelog)

---

### 10. Accessibility — Continue UIA Automation Properties Pass — ⚠️ IN PROGRESS

**This is the continuation of an audit-in-progress, not a fresh start.**
22 of 45+ pages already carry `AutomationProperties.Name` annotations.
Zero pages carry `AutomationProperties.AutomationId`. The remaining work
is concrete and verifiable:

- (a) Extend `AutomationProperties.Name` to the ~35 unannotated pages
  for screen-reader coverage parity with the 10 already-annotated pages.
- (b) Introduce `AutomationProperties.AutomationId` for every interactive
  control across ALL 45+ pages so UI automation tests (Playwright /
  Appium / WinAppDriver) can target controls reliably.
- (c) Land a CI lint that fails the `sidecar-contract` job (or a sibling
  job) when a new `<Button>` / `<Slider>` / `<ComboBox>` / `<ToggleSwitch>`
  ships without an `AutomationId`. Prevents regression after the pass.

Impact: 3 · Effort: 2 · Type: accessibility
Source: [S16] (WinUI 3 accessibility docs — UIA peer requirement)

**Verified state (Phase 5 audit, 2026-05-02):**
- `AutomationProperties.Name` — 22 occurrences across 10 of 45+ pages.
- `AutomationProperties.AutomationId` — 0 occurrences anywhere in `src/`.

---

### 11. CI — Sidecar Contract Test Gate — ✅ SHIPPED 2026-05-01

Add a GitHub Actions job that runs `tests/sidecar_contract/check_contract.py`
against all 176 sidecars on every PR. Failing contract tests block merge.
This catches NDJSON schema regressions before they hit users.

Impact: 3 · Effort: 1 · Type: dx
Source: [S17] (tools/README.md contract checklist), repo CI gap observation
**Closing commit:** `2f2864c` — `.github/workflows/build.yml` adds
`sidecar-contract` job on ubuntu-latest, gated on push/PR/tag triggers,
build job now `needs: sidecar-contract`. 176 sidecars conforming locally.

---

## Tier 2 — Next  _(v2.23–v2.27)_

Medium-effort items. Some require new sidecars; most build on existing
engines. Ordered roughly by impact within each category.

### 12. ToolboxPage — Metadata Editor (EXIF / XMP / IPTC)

New `MetadataEditorPage.xaml` backed by an `exiftool-metadata` sidecar
wrapping ExifTool. Read/write/clear EXIF, XMP, IPTC, GPS tags. Batch-apply
a metadata template to a folder of images (useful for photographers).
Supports all RAW formats already handled by `rawphoto` sidecar.

Impact: 5 · Effort: 3 · Type: parity
Sources: [S8] (ExifTool 100+ format support), [S3] (Any Video Converter metadata track mgmt)

---

### 13. Subtitle Track Management — ✅ SHIPPED 2026-05-02

Add/remove/export subtitle tracks in MKV/MP4 without full re-encode. New
preset + sidecar wrapping `mkvmerge` or `ffmpeg -map` for track operations.
Surface in `VideoToolsPage`: "Add Subtitles", "Extract Subtitles", "Remove
Track". Complements existing `subconvert` and `subkit` sidecars.

Impact: 4 · Effort: 2 · Type: parity
Sources: [S3] (Any Video Converter track add/remove/export, v9.1.8), [S26] (SubtitleEdit v5.0.0 format breadth)

**Closing commits:**
- track-add and track-remove shipped pre-v2.20.1 (caught by 2026-05-01 audit).
- track-extract shipped 2026-05-02 in commit `11b7829` — `clipforge`
  sidecar gains `op_track_extract` (auto-picks codec from output extension:
  `.srt`/`.vtt`/`.ass`/`.ssa`/`.lrc`/`.sup`); `TrackManagerPage` row
  template gains a per-row Export button on subtitle rows.

---

### 14. Subtitle Burn-in Preset

New preset using `videocrush` or a dedicated `hardsub` sidecar: burn
SRT/ASS/VTT into video with configurable font, size, color, position, stroke,
and background. FFmpeg `subtitles` filter chain. Frequently requested;
every commercial converter ships it.

Impact: 4 · Effort: 2 · Type: parity
Source: [S3] (Any Video Converter subtitle customization — stroke/outline/background, v9.2.0)

---

### 15. Slideshow Maker

New `slideshow` sidecar: image folder → video with Ken Burns effect,
configurable duration per slide, transition type (fade / wipe / zoom),
overlay text, background music. FFmpeg zoompan + overlay filter chain.
Wire to `SlideshowPage.xaml`.

Impact: 4 · Effort: 3 · Type: parity
Source: [S5] (ToolboxPage.xaml.cs stub), [S7] (OpenShot animation features)

---

### 16. AI Video Denoise / Enhance Presets

New presets under AiLab using Real-ESRGAN or ESRGAN sidecar variants for
video: per-frame upscale/denoise, anime-style sharpening, face enhancement
on video frames (not just stills). Wrap inference via existing
`real-esrgan` tooling pattern.

Impact: 4 · Effort: 3 · Type: leapfrog
Source: [S3] (Any Video Converter AI Denoise / Anime / Face Enhancement presets, v9.2.0)

---

### 17. HDR → SDR Tone Mapping Preset

New preset in VideoTools: HDR10 / HLG → SDR conversion using FFmpeg
`zscale` + `tonemap` filter chain. Include Hable, Reinhard, and Mobius
operator options. Currently `clipforge` has a stub 3D-LUT path but no
first-class HDR→SDR workflow.

Impact: 4 · Effort: 2 · Type: parity
Source: [S9] (FFmpeg 8.1 — libavcodec 62.x new tone-mapping capabilities)

---

### 18. Audio Loudness Normalization (EBU R128 / LUFS)

New `audioloudness` sidecar or preset: two-pass FFmpeg `loudnorm` to
target broadcast loudness (e.g., -16 LUFS for streaming, -23 LUFS for
broadcast). Expose target LUFS, true-peak ceiling, and LRA controls.

Impact: 4 · Effort: 2 · Type: parity
Source: [S14] (EBU R128 — table-stakes in any professional audio conversion tool)

---

### 19. Video Stabilization Preset

Wrap FFmpeg `vidstab` (two-pass: `vidstabdetect` → `vidstabtransform`).
New `VideoStabilizePage.xaml` or preset under VideoTools. Controls: shakiness
detection threshold, smoothing, border crop/black-fill mode.

Impact: 3 · Effort: 2 · Type: parity
Source: [S14] (standard professional video conversion feature)

---

### 20. SponsorBlock Integration (StreamKeep / yt-dlp) — ✅ SHIPPED 2026-05-02

Pass `--sponsorblock-remove` (or `--sponsorblock-mark`) flags through to
the yt-dlp sidecar. Expose as a checkbox in `StreamKeepPage.xaml`:
"Skip sponsor segments (SponsorBlock)". yt-dlp already supports this
natively — it's a config-surface task.

Impact: 4 · Effort: 1 · Type: leapfrog
Source: [S13] (yt-dlp SponsorBlock flags in latest releases)
**Closing commit:** `c338af1` — `streamkeep` sidecar gains
`--sponsorblock {mark,remove}` and `--sponsorblock-categories`;
`DownloaderPage` adds a "Skip sponsor segments" checkbox alongside the
existing Audio-only / Subtitles cluster; job summary chip shows
"+ sponsor-skip" when active.

---

### 21. Speaker Diarization in STT Output

Extend the `whisper-stt` / `whisper-cpp` sidecar with `pyannote.audio`
(onnx variant to stay offline): identify speaker segments and label them
`[Speaker 1]`, `[Speaker 2]` in SRT/VTT/TXT output. Expose as a checkbox
"Identify speakers" in `SttPage.xaml`.

Impact: 3 · Effort: 3 · Type: leapfrog
Source: [S10] (Purfview whisper-standalone-win — pyannote_v3/onnx VAD + diarization)

---

### 22. Background Audio Noise Reduction

New `audionoise` sidecar wrapping `rnnoise` (Mozilla) or `deepFilterNet`
(ONNX model): remove background noise from speech recordings, interview
audio, or video audio track. Include a denoise strength control.

Impact: 3 · Effort: 3 · Type: parity
Source: [S14] (common request in audio processing communities)

---

### 23. Auto Crop — Content-Aware Crop

New `autocrop` preset using FFmpeg `cropdetect` filter: analyze a video clip
for black borders, suggest crop rectangle, apply. Wire to `AutoCropPage.xaml`
or as a VideoTools option.

Impact: 3 · Effort: 2 · Type: parity
Source: [S5] (ToolboxPage.xaml.cs stub)

---

### 24. Lens Correction

New `lenscorrect` preset using FFmpeg `lenscorrection` filter: correct barrel
/ pincushion distortion with k1/k2 coefficients, or use `vf_lensfun`
(LensFun lens database). Useful for action cam footage (GoPro) and wide-angle
photography.

Impact: 3 · Effort: 2 · Type: parity
Source: [S5] (ToolboxPage.xaml.cs stub)

---

### 25. MSIX Packaging + WinGet Submission

Build a `.msixbundle` in the CI release workflow using the Windows Application
Packaging Project or `makeappx.exe`. Submit a manifest to
`microsoft/winget-pkgs` so users can install via `winget install MavenImaging.UniversalConverterX`.
Requires a code-signing certificate. Track as a separate GitHub release asset.

Impact: 4 · Effort: 3 · Type: distribution
Source: [S18] (winget-pkgs CONTRIBUTING.md — manifest schema v1.6)

---

### 26. WinAppSDK 2.0 Migration

Upgrade from WinAppSDK 1.x to 2.0 (released 2026-04-29). Key gains:

- `SystemBackdropElement` — place Mica/Acrylic inside any layout panel
  (replaces current window-level backdrop hack).
- `Microsoft.Windows.Storage.Pickers` — file type grouping, suggested start
  folder, persistent picker IDs (better multi-folder batch UX).
- `Microsoft.Windows.AI.MachineLearning` 2.0 + ONNX Runtime 1.24.5 — faster
  ONNX inference on Copilot+ PCs. **Caveat:** WinAppSDK 2.0 bundles ONNX RT
  1.24.5, which is below UCX's sidecar security floor of ≥1.25.1 ([S36]).
  Python sidecars must continue pinning `onnxruntime>=1.25.1` in their own
  `requirements.txt` regardless of what WinAppSDK bundles.
- `IXamlCondition` — parse-time feature flags for capability-gated UI.

Breaking changes: review `DispatcherQueue` API surface and any
`AppWindow` interop. Test on clean Win10 21H2 before shipping.

Impact: 3 · Effort: 3 · Type: platform
Source: [S19] (Windows App SDK 2.0 release notes, 2026-04-29)

---

### 27. AI Portrait — Still Image Enhancement

Wire the `AI Portrait` ToolboxPage stub to a dedicated `AiPortraitPage.xaml`.
Pipeline: `real-esrgan` (face-oriented model) or `codeformer` sidecar for
portrait upscale + restoration. Batch-capable. Separate from Old Photo
Restoration (which targets degraded/aged prints).

Impact: 3 · Effort: 2 · Type: parity (wiring) + leapfrog (depth)
Source: [S5] (ToolboxPage stub)

---

### 28. FFmpeg 8.x Sidecar Refresh

Audit all sidecars that bundle or call an FFmpeg binary. BtbN/FFmpeg-Builds
provides daily Windows auto-builds of FFmpeg 7.x–8.x. Pin all ffmpeg-dependent
sidecars to ≥7.1 (current stable shipped with UCX) and test against 8.1
("Hoare", 2026-03-16). Notable 8.x additions: libavcodec 62.x new codec
support, libvmaf AVX-512 improvements. Carry a pinned FFmpeg build in
`tools/ffmpeg/` rather than relying on PATH.

Impact: 3 · Effort: 2 · Type: platform + security
Source: [S9] (FFmpeg 8.1 changelog), [S20] (BtbN FFmpeg auto-builds)

---

### 29. Manual FFmpeg Command Override (Advanced Mode)

Expose the FFmpeg command generated by each sidecar in a read-only "Advanced"
panel at the bottom of every conversion page. Add an opt-in "Edit before run"
toggle (power-user mode) that lets the user modify the argument string before
dispatch. Implementation: sidecars already emit structured log events; surface
the effective FFmpeg argv in a `ScrollableTextBlock` with a copy button. The
edit path re-injects the modified string via a `--raw-args` sidecar flag.
Input sanitized: disallow shell injection characters (`|`, `;`, `&`, `>`).
Disabled by default; enabled via Settings toggle. No new sidecar required —
pure C# UI + sidecar contract extension.

Impact: 4 · Effort: 3 · Type: leapfrog
Sources: [S31] (VCT README — stated #1 goal: "manually edit any command option
of ffmpeg"), [S38] (Videomass advanced FFmpeg panel UX reference)

---

### 30. Audio VBR Quality Mode — ⚠️ PARTIALLY SHIPPED 2026-05-02

Add a "Quality (VBR)" encoding mode toggle alongside the existing fixed-bitrate
mode in audio conversion presets. libmp3lame: `-q:a 0–9` (0 = highest quality);
libfdk_aac: `-vbr 1–5`; libopus: `-compression_level 0–10`. Present as a
labeled quality slider that replaces the bitrate field when VBR is selected.
Preset XML extension: `<BitrateMode>vbr</BitrateMode>` +
`<VbrQuality>2</VbrQuality>`. Pure preset + `AudioConverterPage.xaml` change;
no new sidecar required.

Impact: 3 · Effort: 1 · Type: parity
Source: [S29] (66HEX/frame v0.28.0 — audio VBR MP3/AAC quality preset)

**Closing commits:**
- Sidecar + presets shipped 2026-05-02 in commit `0fdfad5` —
  `tools/audiopro/sidecar.py` and `tools/videocrush/sidecar.py` both
  gain a unified 0..9 VBR quality flag with codec-specific remapping
  (libmp3lame / libvorbis / libfdk_aac / aac native / libopus). Three
  new presets (mp3 V2, mp3 V4, AAC Q3). The `videocrush` audio cmd-build
  was refactored into a reusable `audio_args()` helper at the same time.
- **Remaining work**: `AudioConverterPage.xaml` UI surface deferred —
  the page itself doesn't yet exist (covered by ROADMAP Item 2). When
  Item 2 lands, surface the VBR controls there. The slider/toggle the
  ROADMAP describes can land alongside.

---

### 31. Image / Video Watermark Overlay

New `watermark` sidecar preset: stamp a PNG/JPEG logo or watermark onto video
or image batches. Controls: position (9-point grid: TL/TC/TR/ML/MC/MR/BL/BC/BR),
opacity (0–100%), and scale (% of frame width). Video: FFmpeg `overlay` filter
chain. Images: Pillow `Image.paste()` with alpha compositing. Wire to
`WatermarkPage.xaml` with a live thumbnail preview of the positioned overlay.

Impact: 3 · Effort: 2 · Type: parity
Sources: [S29] (66HEX/frame v0.29.0 image overlay pipeline), [S28] (Shutter
Encoder logo overlay)

---

### 32. Subtitle Auto-Sync

New `subtitle-sync` sidecar: correct subtitle timing drift by comparing FFT
audio fingerprints of speech segments against subtitle timestamps. Backend:
`subsync` (Python, audio-based dynamic time-warping alignment). No video
re-encode; outputs a re-timed `.srt` file. Wire to a "Subtitle Sync" entry in
VideoToolsPage: input video + misaligned SRT → corrected SRT. Complements the
existing `subconvert` / `subkit` sidecars (format conversion, not timing).

Impact: 4 · Effort: 3 · Type: parity
Source: [S32] (smacke/subsync — FFT audio fingerprint subtitle synchronization)

---

### 33. Media Inspector (Technical Stream Analysis)

New `mediainspect` sidecar wrapping `pymediainfo` (Python MediaInfo bindings):
surface full technical metadata for any A/V file — container format, all
video/audio/subtitle stream details (codec, profile, bit depth, colour space,
HDR metadata, audio channel layout, stream delay, language tags, container
atoms). Present as `MediaInspectorPage.xaml` with collapsible per-stream
sections and a "Copy as JSON" export button. Distinct from the EXIF metadata
editor (Item 12): read-only technical analysis of A/V streams, not tag editing.

Impact: 3 · Effort: 2 · Type: parity
Sources: [S37] (MediaArea/MediaInfo — technical A/V stream analysis),
[S35] (krzemienski/awesome-video: sbraz/pymediainfo wrapper)

---

## Tier 3 — Later  _(v2.28+)_

Higher effort, lower urgency, or dependent on Tier 1/2 completion.

### 34. Watch Folder Automation — ✅ SHIPPED (already)

Background service that monitors one or more folders for new files and
auto-dispatches them through a configured preset. Surface in
`WatchFolderPage.xaml`. Implementation options: FileSystemWatcher (in-process)
or a lightweight Windows Service (`ucx-watchd`).

Impact: 5 · Effort: 4 · Type: parity
Source: [S14] (HandBrake batch queue, AVC watch folder — universal commercial feature)

**Already shipped (verified 2026-05-01 audit):**
`src/UniversalConverterX.UI/Views/Pages/WatchFoldersPage.xaml{,.cs}` and
`src/UniversalConverterX.UI/Services/WatchFolderService.cs`. Listed as
"Tier 3 Later" but actually shipped pre-v2.20.1.

---

### 35. REST API / Local HTTP Service (`ucx serve`) — ✅ SHIPPED (already)

Extend the existing `ucx` CLI with a `ucx serve` subcommand: local HTTP API
for headless/programmatic conversion. Enables scripting and integration with
other tools.

Impact: 3 · Effort: 4 · Type: dx
Source: [S5] (old ROADMAP.md "Out of Scope" call-out — reconsidered)

**Already shipped (verified 2026-05-01 audit):**
`src/UniversalConverterX.Console/Commands/ServeCommand.cs` (505 LOC).
Listed as "Tier 3 Later" but shipped in v2.4. ROADMAP entry survived a
version cycle without being crossed off.

---

### 36. Intro & Outro Editor

Attach a pre-clip and post-clip to any batch conversion job: each output file
gets the intro prepended and outro appended via FFmpeg `concat` demuxer.
Configure per-preset. Wire to `IntroOutroPage.xaml`.

Impact: 3 · Effort: 3 · Type: parity
Source: [S5] (ToolboxPage.xaml.cs stub)

---

### 37. Auto Highlight — Scene Detection + Clip Extraction

Analyze a video for scene-change peaks and motion energy; auto-extract a
highlight reel at user-specified duration. Backend: FFmpeg `select=scene`
filter + optional PySceneDetect sidecar. Wire to `AutoHighlightPage.xaml`.
Additionally export the detected scene list as EDL (CMX 3600) or OTIO for
direct import into DaVinci Resolve, Premiere Pro, or any OTIO-compatible NLE.

Impact: 3 · Effort: 4 · Type: leapfrog
Sources: [S5] (ToolboxPage.xaml.cs stub), [S33] (PySceneDetect v0.6.6 EDL/OTIO output)

---

### 38. VR / 360° Video Conversion

Convert equirectangular (360° video) to cubemap, fisheye, or rectilinear
projection. FFmpeg `v360` filter. Wire to `VrConverterPage.xaml`. Niche but
no-OSS-GUI exists for it on Windows.

Impact: 2 · Effort: 2 · Type: leapfrog (niche gap)
Source: [S5] (ToolboxPage.xaml.cs stub)

---

### 39. Color Grading LUT Application

A dedicated `lut-apply` preset (distinct from existing `lutgen`) that takes
an input `.cube` or `.3dl` LUT file and applies it to a video or image batch.
FFmpeg `lut3d` filter or HALDCLUT for images. Target colorists and
photographers exporting from DaVinci Resolve or Lightroom.

Impact: 3 · Effort: 2 · Type: parity
Source: [S7] (OpenShot 3D-LUT support), [S5] (clipforge stub)

---

### 40. Chapter Editor (MKV / MP4)

Add, edit, delete, and import/export chapter markers in MKV or MP4 containers
without re-encoding. Backend: `mkvmerge --chapters` for MKV; `mp4box -chap`
or FFmpeg for MP4. Wire to `ChapterEditorPage.xaml`.

Impact: 3 · Effort: 3 · Type: parity
Source: [S6] (LosslessCut chapter editor), [S14] (standard pro video feature)

---

### 41. Localization (i18n / l10n)

Extract all user-visible strings into `Resources.resw` per-language files.
Set up a Crowdin project for community translation. Auto-detect Windows
display language on first run. Priority target locales (by UCX GitHub
issue geography): DE, FR, ES, PL, ZH-Hans.

This is a large cross-cutting change (all 45 XAML pages + Core messages).
Prerequisite: complete UIA pass (Item 10) since accessible names are also
localizable strings.

Impact: 4 · Effort: 5 · Type: i18n
Source: [S15] (YoutubeDownloader shipped EN/UK/DE/FR/ES + system language auto-detect)
Source: [S21] (ImageGlass Crowdin i18n workflow)

---

### 42. Lossless Trim / Cut (No Re-encode)

New `losslesscut` preset: trim video clip by start/end timestamps without
re-encoding. FFmpeg `-ss` + `-to` with `-c copy`. Surface in
`LosslessCutPage.xaml` with a simple timeline scrubber showing keyframe
positions (I-frames only for true lossless trim). Competes directly with
LosslessCut (Electron app, ~13k stars).

Impact: 4 · Effort: 3 · Type: parity
Source: [S6] (LosslessCut — primary OSS competitor for this workflow)

---

### 43. DVD Rip / Copy (Non-DRM Discs Only)

Read unprotected DVD VIDEO_TS structure → MP4/MKV via `libdvdread` + FFmpeg.
Scope: menu-free ISOs, non-commercial home videos. Clearly document the
DRM exclusion in the UI (CSS-encrypted commercial discs unsupported by charter).
Addresses the disc-import use case from Any Video Converter's feature set.

Impact: 3 · Effort: 4 · Type: parity
Source: [S3] (Any Video Converter DVD import, v9.2.0)

---

### 44. DVD Burn / CD Burner (Disc Tools)

Write video files to DVD-Video structure or data files to a CD/DVD using
`growisofs` / `cdrecord` / Windows `IDiscRecorder2` COM API. Wire to existing
`DiscTools` category stubs in ToolboxPage.

Impact: 2 · Effort: 4 · Type: parity
Source: [S5] (ToolboxPage.xaml.cs DiscTools stubs)

---

### 45. Preset Import / Export / Share

Export a preset XML (or preset bundle ZIP including sidecar model weights) to
a shareable file. Import from file or URL. Prerequisite for a community preset
repository. Wire to a "Share Preset" menu action in `PresetsPage.xaml`.

Impact: 3 · Effort: 2 · Type: dx
Source: [S14] (HandBrake preset import/export — table-stakes in converter UX)

**Charter note (Phase 5 audit, 2026-05-02):** "Import from URL" is a
user-initiated outbound network request. Charter-aligned because (a) the
user typed/pasted the URL, (b) the import is to local disk (no cloud
storage), (c) imported XML must pass a strict allow-list schema validator
before any sidecar reference is resolved (mitigates malicious-preset
attack surface). Implementation must show the URL clearly + a "this will
download from the internet" confirmation step before fetching.

---

### 46. Audio Waveform Preview

Show a waveform thumbnail in `AudioConverterPage` and `SttPage` after file
selection. Backend: FFmpeg `showwavespic` filter (one-shot PNG). Improves
the "confirm before convert" UX loop, especially for STT and noise reduction.

Impact: 3 · Effort: 3 · Type: UX
Source: [S6] (LosslessCut waveform display)

---

### 47. Qualcomm NPU / ARM64 Native Build

Publish a native ARM64 build of UCX targeting Snapdragon X Elite / X Plus
devices. Requires ARM64 .NET 10 publish, ARM64 WinUI 3 validation, and
verifying all Python sidecars run under ARM64 Python or x64-under-emulation.
FFmpeg ARM64 build available from BtbN. HandBrake has an open ARM64/Qualcomm
encoder request.

Impact: 2 · Effort: 4 · Type: platform
Source: [S22] (HandBrake #7822 Qualcomm VCE/ARM64 encoder request)

---

### 48. AI Video Colorization (B&W → Color)

New `colorize-video` sidecar: per-frame colorization of grayscale or archival
footage using DeOldify or DDeoldify (Stable Diffusion-guided variant). Requires
PyTorch + ~1.5 GB model download (one-time, auto-fetched on first use). Expected
throughput: ~1–3 FPS at 720p on an RTX 3080; CPU path is unusably slow — sidecar
must gate on GPU presence and show a clear warning otherwise. Wire to
`ColorizeVideoPage.xaml` with a single-frame preview before committing to full
encode. Complements the existing Old Photo Restoration tile.

Impact: 3 · Effort: 4 · Type: leapfrog
Sources: [S28] (Shutter Encoder DeOldify integration), [S35] (awesome-video AI
section — DeOldify, DDeoldify)

**Charter note (Phase 5 audit, 2026-05-02):** The "auto-fetched on first
use" model download is a user-initiated outbound request (the user must
have launched the colorization feature). Charter-aligned because (a) the
download is one-time and cached locally, (b) inference runs entirely
locally after the fetch, (c) the user must see a clear "this will
download ~1.5 GB from HuggingFace" confirmation before the fetch starts.
Implementation must NOT auto-download silently on app start — only on
explicit feature first-use. Apply the same pattern to any other large-
model sidecar that lazy-fetches weights.

---

### 49. AI Video Background Removal

New `bgremove-video` sidecar: segment and remove or replace the video background
using BRIA-RMBG 2.0 or MODNet (both ONNX-exportable). Output options: VP9/WebM
with transparency channel, PNG image sequence, or chroma-key solid-colour fill.
Expected throughput: ~5–15 FPS at 1080p on RTX 3080. GPU check required; display
estimated processing time per minute of input before the job starts. Wire to
`BgRemovePage.xaml`.

Impact: 3 · Effort: 4 · Type: leapfrog
Sources: [S28] (Shutter Encoder BackgroundRemover integration), [S35] (awesome-video
AI/ML section)

---

### 50. CEA-608/708 Closed Caption Extraction

New `ccextract` sidecar wrapping CCExtractor: extract embedded closed captions
(CEA-608/708 for ATSC, MPEG-2, and MPEG-TS broadcast recordings) to SRT, WebVTT,
or plain text. Wire to the subtitle section of VideoToolsPage alongside the
existing subtitle track management tools (Item 13). Primary use case: users with
OTA/cable DVR recordings saved as raw MPEG-TS or MPEG-2 PS files who need to
extract the captions as a text track.

Impact: 2 · Effort: 3 · Type: parity
Sources: [S34] (CCExtractor — open-source broadcast closed-caption extractor),
[S35] (awesome-video subtitle / caption section)

---

## Audit-Surfaced Coverage Gaps  _(added 2026-05-02 from `iter-1-audit.md`)_

The Phase 5 audit found three categories under-served by the original
ROADMAP. These items were not in the Round 2 research output because the
research focused on competitor-feature parity rather than internal
quality / extensibility / migration concerns. Tier placement reflects
audit recommendation, not pure user-facing impact.

### 51. Observability — Local Crash Bundle + Structured App Log _(Tier 2)_

A user-toggleable structured log panel inside the app (Catppuccin debug
console) that streams to `%LocalAppData%/UniversalConverterX/logs/` on
disk with daily rotation + 30-day retention. On unhandled exception,
write a crash bundle (last-N-log-lines + system info + active job state
+ stack trace) to a clearly-flagged `crashes/` folder. Surface a
"Open log folder" / "Export crash bundle for support" UI hook. Gated
behind the existing `ConverterXOptions.VerboseLogging` flag — silent
when off, zero-cost. No telemetry — local-only by charter.

Closes the audit's observability gap: today, when a sidecar fails or
the app crashes, there is no actionable evidence pack the user can hand
back to a maintainer. History (Item 6) records job outcomes, but not
the structured log that produced them.

Impact: 3 · Effort: 2 · Type: dx + observability
Source: standard desktop-app pattern; surfaced by Phase 5 audit.

---

### 52. Plugin — Third-Party Sidecar Manifest _(Tier 3)_

UCX hard-codes 176 sidecars under `tools/<name>/`. The NDJSON contract
test (Item 11, just shipped) is permissive enough that any sidecar
following the contract works — but there is no formal extension point.
Add `tools/<name>/manifest.json` schema (declares input/output formats,
event types, op list) + a "Discover plugins" sweep at app start that
indexes any `manifest.json` under `tools/` *or* a user-configurable
plugin directory (default `%LocalAppData%/UniversalConverterX/plugins/`).
Plugins surface in PresetsPage and ToolboxPage automatically.

Charter alignment: the user installs plugins by dropping a directory —
no app store, no remote fetch. Identical to how OSS GUI tools (HandBrake,
OBS, Audacity) handle local plugin folders.

Impact: 3 · Effort: 4 · Type: leapfrog
Source: charter emphasizes programmability; surfaced by Phase 5 audit.

---

### 53. Migration — settings.json Schema Versioning _(Tier 2)_

Add a `SchemaVersion` integer to `ConverterXOptions`. Implement a
migration table keyed by version-pair (e.g. `1 → 2: rename
"OverwriteBehavior=Ask" to "Prompt"`). On `Load`, if the on-disk
schema is older than current, run migrations in order, write back the
upgraded JSON, and emit a one-line log entry. On corrupt read, the
existing fallback (backup file with `.corrupt.<timestamp>` suffix)
already exists in `ConverterXOptions.Load()` — keep that path.

Audit motivation: the iter-1 wave flipped `OverwriteBehavior` default
from `Ask` to `Never` for fresh installs, while preserving persisted
user preferences. That worked because the deserializer kept the value
verbatim. But the next time a field is renamed or an enum value is
removed, that approach silently breaks. A schema migration table is
the cheap insurance.

Impact: 2 · Effort: 1 · Type: dx + migration
Source: surfaced by Phase 5 audit's migration coverage gap.

---

## Under Consideration

These need more investigation or community signal before placement.

| Item | Question blocking placement |
|------|-----------------------------|
| **OCR full pipeline** (image → structured text, not just searchable PDF) | Already have `pdfocr`; would a dedicated `ocrkit` sidecar add incremental value? Survey user requests. |
| **VMAF quality reporting** _(✅ shipped — `VmafAnalysisPage.xaml` exists; retire from UC list next iteration)_ | Expose `libvmaf` score as a post-conversion metric. Useful for production workflows; adds ~10% to encode time. |
| **Spatial audio conversion** (Ambisonics ↔ binaural ↔ 5.1 ↔ 7.1) | FFmpeg has partial support; full Ambisonics requires specialized libraries. Assess demand. |
| **Community preset repository** | GitHub-hosted index of contributed presets. Requires governance model, security review of contributed XML, and moderation bandwidth. Assess when preset count warrants it. |
| **EDL / XML timeline import** | Bulk-convert based on an edit decision list (CMX 3600 EDL, Final Cut XML). Niche; assess against demand. |
| **Copilot+ PC / NPU acceleration** | `AICapabilities.HasAICapability` (WinAppSDK 1.8) can gate ONNX inference to NPU. Measure actual throughput gain vs. CUDA GPU before committing. [S27] |
| **Deinterlace framerate auto-doubling** | For Bwdif+Bob deinterlace, automatically double the output framerate (e.g. 25i → 50p). FFmpeg supports this; needs UX decision about when to auto-enable. [S23] |
| **Per-track audio delay control** | Fine-grain delay offset per audio track during conversion (e.g. fix lip-sync issues). `ffmpeg -itsoffset` or `adelay` filter. Common request; needs UI design. [S24] |
| **C2PA Content Credentials embedding** | Embed a `c2pa:actions` assertion in output files recording that UCX processed them. C2PA Spec 2.0 is fully published; Adobe, Microsoft, Google, and Sony are all shipping support. Requires `c2pa-python` (Rust-backed FFI sidecar dependency). Question: is the UCX audience large enough to justify a Rust compile dependency in the sidecar chain? [S30] |
| **IAMF immersive audio pass-through** | Remux IAMF (Immersive Audio Model and Formats, AOMedia) audio streams into MP4/ISOBMFF without transcoding. FFmpeg 7.0+ supports IAMF via `libiamf`. Question: identify at least three concrete user workflows before committing. [S37] |
| **Commercial / ad detection (Comskip)** | Detect and optionally remove commercial breaks in OTA/DVR recordings using Comskip. Relevant only to users with ATSC tuner or MPEG-TS recordings. Question: is this a UCX use case or a dedicated DVR-management tool problem? Needs community signal. [S35] |

---

## Out of Scope — Will Not Ship

| Item | Reason |
|------|--------|
| Cloud-based AI services (remote render, API-backed models) | Violates offline-first charter. |
| Live stream publishing (RTMP/SRT egress, restreaming) | Stream publishing, not conversion. Separate problem domain. |
| DRM-bound format decryption (CSS DVDs, AAX audiobooks, KFX, FairPlay) | Legal grey area. Intentional exclusion from day one. |
| Mobile apps (iOS / Android UCX client) | Windows-only by charter. |
| Accounts, login, subscription management, cloud sync | Anti-charter. |
| Anonymous / opt-out telemetry collection | Anti-charter. UCX will never phone home. |
| AI model training or fine-tuning | Cloud compute dependency. |
| Web scraping beyond yt-dlp / streamkeeper scope | Legal risk, maintenance burden beyond engine scope. |
| Phone / tablet wireless push (AirPlay, MTP over Wi-Fi) | Out of conversion scope. |
| Real-time / live video encoding pipeline | Architecture mismatch with current sidecar model. |

---

## Definition of Done (Sidecar Checklist)

Before any new sidecar or preset is merged:

1. NDJSON contract: emits `progress`, `log`, `complete`, `error` events and
   at least one domain-specific event listed in `KNOWN_EVENTS`.
2. Frozen-PyInstaller guard (if sidecar calls `pip install` at runtime).
3. Standard argument shape: `--input`, `--output`, `--output-dir`.
4. At least one preset XML so the feature surfaces in the right-click menu
   and `PresetsPage`.
5. A Toolbox tile via `presets:<engine>` deep-link convention (where applicable).
6. A `build.ps1` from the standard PyInstaller template.
7. A `requirements.txt` (even if just a comment) for reproducible builds.
8. Contract test in `tests/sidecar_contract/check_contract.py` passes.

---

## Appendix: Sources

| ID | URL | Used for |
|----|-----|----------|
| S1 | Repo CHANGELOG.md (v2.1–v2.20.1) | What's already shipped; CVE pin context |
| S2 | Repo ToolboxPage.xaml.cs + AiLabPage.xaml.cs | "Future" tile inventory |
| S3 | https://www.any-video-converter.com/en/features.php | Commercial competitor features: AI models, track mgmt, subtitle burn-in, DVD rip |
| S4 | https://github.com/Purfview/whisper-standalone-win | Speaker diarization, VAD methods, batch recursive STT |
| S5 | Repo source (ToolboxPage.xaml.cs, AiLabPage.xaml.cs stubs) | 14 Future tile inventory |
| S6 | https://github.com/mifi/lossless-cut/issues | Overwrite collision #2667, relative segment time #2730, waveform/chapter features |
| S7 | https://github.com/OpenShot/openshot-qt | Hardware encoding (VA-API/NVDEC/D3D11), EDL/XML, keyframe animation |
| S8 | https://exiftool.org/ | ExifTool 100+ format EXIF/XMP/IPTC/GPS r/w/c |
| S9 | https://ffmpeg.org/index.html | FFmpeg 8.1 "Hoare" (2026-03-16), libavcodec 62.x, libvmaf |
| S10 | https://github.com/Purfview/whisper-standalone-win | GPU CUDA, VAD methods, speaker diarization, vocal extraction |
| S11 | https://github.com/HandBrake/HandBrake/issues/7848 | Auto-increment output filename collision |
| S12 | https://github.com/mifi/lossless-cut/issues/2667 | Overwrite conflict / auto-rename handling |
| S13 | https://github.com/yt-dlp/yt-dlp | yt-dlp output template DSL, SponsorBlock flags |
| S14 | General competitive survey (HandBrake, AVC, community threads) | Table-stakes features: watch folder, loudnorm, parallel jobs, etc. |
| S15 | https://github.com/Tyrrrz/YoutubeDownloader/releases | Localization (EN/UK/DE/FR/ES), DPAPI cookie encryption, FFmpeg auto-download |
| S16 | https://learn.microsoft.com/windows/apps/design/accessibility/accessibility-overview | WinUI 3 UIA peer requirements |
| S17 | Repo tools/README.md | NDJSON sidecar contract definition + 8-requirement checklist |
| S18 | https://github.com/microsoft/winget-pkgs/blob/master/CONTRIBUTING.md | WinGet manifest schema v1.6 submission requirements |
| S19 | https://github.com/microsoft/WindowsAppSDK/releases/tag/v2.0.0 | WinAppSDK 2.0 — SystemBackdropElement, StoragePickers, Windows ML / ONNX 1.24.5 |
| S20 | https://github.com/BtbN/FFmpeg-Builds/releases | BtbN FFmpeg daily builds — Windows x64 + ARM64, FFmpeg 7.x / 8.x |
| S21 | https://github.com/d2phap/ImageGlass | ImageGlass Crowdin localization workflow, 90+ format support |
| S22 | https://github.com/HandBrake/HandBrake/issues/7822 | Qualcomm VCE / Snapdragon X ARM64 encoder request |
| S23 | https://github.com/HandBrake/HandBrake/issues/7729 | Deinterlace Bwdif+Bob framerate doubling |
| S24 | https://github.com/HandBrake/HandBrake/issues/7472 | Audio delay offset control |
| S25 | _(removed — 404)_ | — |
| S26 | https://github.com/SubtitleEdit/subtitleedit/releases | SubtitleEdit v5.0.0 active beta releases (subtitle format breadth) |
| S27 | https://github.com/microsoft/WindowsAppSDK/releases | WinAppSDK 1.8.7 — AICapabilities.HasAICapability, NPU detection |
| S28 | https://github.com/paulpacifico/shutter-encoder | Shutter Encoder — DeOldify colorization, BackgroundRemover, LibRaw RAW, MediaInfo integration, logo overlay, tsMuxeR Blu-ray |
| S29 | https://github.com/66HEX/frame/releases | 66HEX/frame releases — v0.27 subtitle burn-in styles, v0.28 audio VBR, v0.29 image overlay pipeline |
| S30 | https://c2pa.org/specifications/specifications/2.0/ | C2PA Content Credentials spec v2.0 — provenance assertion standard |
| S31 | https://github.com/zbabac/VCT | VCT (Video Conversion Tool) — stated goal #1: manual FFmpeg command override |
| S32 | https://github.com/smacke/subsync | subsync — FFT audio-fingerprint subtitle auto-synchronization |
| S33 | https://github.com/Breakthrough/PySceneDetect/releases | PySceneDetect v0.6.6 — EDL (CMX 3600) and OTIO export for NLE import |
| S34 | https://github.com/CCExtractor/ccextractor | CCExtractor — CEA-608/708 broadcast closed caption extraction |
| S35 | https://github.com/krzemienski/awesome-video | awesome-video — comprehensive OSS video tools catalog |
| S36 | https://github.com/microsoft/onnxruntime/releases | ONNX Runtime v1.25.0/1.25.1 — 10+ security fixes (heap OOB, integer overflows); UCX Python sidecars must pin ≥1.25.1 |
| S37 | https://github.com/MediaArea/MediaInfo/releases | MediaInfo 26.01 — C2PA parsing, IAMF audio, Spherical Video 2, Gain Map HDR metadata |
| S38 | https://github.com/jeanslack/Videomass/releases | Videomass v6.1.18 — advanced FFmpeg panel UX reference, waveform display, subtitle stream indexing |
