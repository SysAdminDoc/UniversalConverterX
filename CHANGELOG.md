# Changelog

All notable changes to UniversalConverterX will be documented in this file.

## [Unreleased]

### Added — Local crash bundle + structured app log (ROADMAP Item 51)

- New `Services/StructuredLogger.cs` (`IStructuredLogger`) — NDJSON
  daily-rotated app log with 500-entry in-memory ring buffer, 30-day
  retention prune, and Debug/Info/Warning/Error/Crash levels. Verbose
  off skips disk writes for Debug+Info but still populates the ring
  buffer so a crash bundle has meaningful tail context.
- New `Services/CrashBundle.cs` — captures a zip containing
  `system-info.txt` (OS / runtime / app version / CPU / working set),
  `exception.txt` (recursive InnerException walk + stack trace),
  `log-tail.ndjson` (ring buffer snapshot), and `log-today.ndjson`
  (the day's full file when present) into
  `%LocalAppData%/UniversalConverterX/crashes/crash_<utc>.zip`.
- `App.xaml.cs` registers the logger as a singleton, eagerly resolves
  it in `OnLaunched`, and routes `UnhandledException`,
  `AppDomain.CurrentDomain.UnhandledException`, and
  `TaskScheduler.UnobservedTaskException` through both the logger and
  the bundle capture.
- `HomePage` Diagnostics card with "Open log folder" + "Export crash
  bundle" buttons (status-text feedback on success/failure).
- Local-only by charter: nothing leaves the user's disk unless they
  manually attach the resulting zip to a bug report.

### Added — Subtitle burn-in / HDR-to-SDR / Auto-crop / Stabilize (ROADMAP Items 14, 17, 19, 23)

- `clipforge` sidecar gains four new ops:
  - `subtitle-burn`: FFmpeg `subtitles=` + libass `force_style` —
    font / size / colour / outline / shadow / 9-point position grid.
  - `hdr-to-sdr` extended with `--operator {hable|reinhard|mobius|
    clip|linear|gamma}` + `--desat` + `--peak-nits` + `--crf`.
  - `auto-crop`: cropdetect sample pass picks the most-frequent
    rectangle, then re-encode applies it. `--detect-only` reports the
    detected box without producing output.
  - `stabilize`: two-pass vidstabdetect -> vidstabtransform with
    shakiness / smoothing / border (keep|black|crop) controls and a
    final unsharp recovery pass.
- Six new presets: `subtitle-burn`, `hdr-to-sdr-{hable,reinhard,mobius}`,
  `auto-crop`, `stabilize`. Contract test still 177 sidecars conforming.

### Added — Audio loudness preset library expansion (ROADMAP Item 18)

- New `presets/loudnorm-broadcast.preset.xml` — EBU R128 / ATSC A/85
  broadcast deliverable target (-23 LUFS, -2 dBTP). Reuses the existing
  `audiomastering loudnorm` two-pass FFmpeg engine.
- New `presets/loudnorm-podcast.preset.xml` — Apple Podcasts / Spotify
  streaming-safe target (-16 LUFS, -1.5 dBTP).
- The existing `loudnorm-streaming.preset.xml` (-14 LUFS) remains for
  YouTube/Netflix-style platforms; all three presets use distinct output
  suffixes (`_loudnorm`, `_r128`, `_pod16`) so a side-by-side render of
  the same source produces three independent files.
- Item 18 closed (preset library gap, not a missing engine — sidecar
  already implemented `--lufs` / `--tp` / `--lra` two-pass loudnorm).

### Added — Home dashboard update banner (ROADMAP Item 7 Phase 2)

- `HomePage.xaml` gains a top-of-page `InfoBar` (`UpdateBanner`),
  collapsed by default and only opened when
  `IUpdateCheckService.GetCachedResults()` reports at least one tracked
  tool with a newer GitHub release than the locally cached version file.
- Banner message lists each pending tool with its latest version
  (e.g. "New release available for: yt-dlp 2026.05.01, ffmpeg n8.1.").
- "Open release notes" action button shells out to the first tool's
  `ReleaseUrl` via `ProcessStartInfo { UseShellExecute = true }` so it
  honours the user's default browser without bundling an HTTP renderer.
- Reads cache only — never triggers a network probe from the page; the
  startup-side `UpdateCheckService.CheckAsync` remains the only probe
  caller and continues to honour the `CheckForUpdates` opt-out toggle.
- All exceptions are swallowed: a missing service, malformed cache, or
  shell-launch failure can never block the dashboard from rendering.
- Item 7 closed end-to-end (Phase 1 service + Phase 2 UI).

### Changed — faster-whisper sidecar refresh (ROADMAP Item 61, partial)

- Bumped pin: `faster-whisper>=1.0.0` -> `>=1.1.0` in the sidecar
  bootstrap install (`tools/whisper-stt/sidecar.py`).
- New `--batch-size` CLI arg (default `8`). When >1 and the installed
  `faster-whisper` exposes `BatchedInferencePipeline`, transcription runs
  through the batched pipeline (~4x throughput on long-form GPU audio).
  Older installs and CPU-only builds fall through to the existing
  sequential streaming path with a warning log; one TypeError on rejected
  kwargs also retries sequentially.
- `SpeechToTextPage` model combo gains `large-v3-turbo` (fast + accurate
  multilingual) and `distil-large-v3` (~6x faster, English-mostly).
- Deferred: Purfview Whisper-XXL VAD models (`silero_v6`, `nemo_v2`,
  `ten`) — those live in a fork, not upstream. Tracked separately rather
  than vendoring a fork.

### Added — Batch Rename utility (ROADMAP Item 3)

- New `Views/Pages/BatchRenamePage.xaml{,.cs}` under Toolbox · OtherTools.
  Pure-C# rename engine — no sidecar — backed by `System.IO.File.Move`.
- Drag-drop file list, "Add Files" / "Add Folder" / "Clear" controls.
- Find/Replace with literal or regex toggle; output-template box that
  overrides Find/Replace when set; case transform (none / lower / upper /
  title); configurable counter start + step.
- Token engine: `{n}`, `{n:N}` (zero-padded width), `{stem}`, `{ext}`,
  `{parent}`, `{date}`, `{date:format}`. Unknown tokens render literally
  so users can fix typos.
- Live preview table with per-row status icons: pending / unchanged /
  on-disk conflict / in-batch conflict / regex error. Apply button
  disables until conflicts clear.
- Two-pass apply with per-row try/catch — one EACCES never aborts the run.
- Toolbox tile flipped Future→Ready (UCX engine) with updated description.
  Routed through `MainWindow` nav switch + selection-tag grouping.
- ExifTool tokens (`{exif:*}`) deferred to Next-tier per original scope.

### Added — Dependency update checker service (ROADMAP Item 7, Phase 1)

- New `Services/UpdateCheckService.cs` (UI project): fire-and-forget
  background probe of GitHub Releases for yt-dlp, BtbN/FFmpeg-Builds,
  ggerganov/whisper.cpp, and microsoft/onnxruntime.
- 24 h throttle window enforced through the cache `LastCheckUtc` field.
  Honours `ConverterXOptions.CheckForUpdates` opt-out (returns cached
  results without hitting the network when off).
- Atomic JSON cache write to `%LocalAppData%/UniversalConverterX/update-cache.json`
  (sibling-tmp + Move pattern, mirrors `SettingsService`). Best-effort
  installed-version probe via per-tool `<engine>.version` files under
  `ToolsBasePath`.
- DI singleton registration in `App.xaml.cs`; fires after main window
  activation. Probe failures are swallowed.
- Phase 2 (dashboard InfoBar + one-click update) deferred to follow-up.

### Changed — UX polish (ROADMAP Items 54, 60)

- AiLab tile statuses for Text-to-Speech, Speech-to-Text, and Old Photo
  Restoration flipped from stale `Future` to `Ready` with engine
  attributions (Kokoro/Piper, Whisper, Real-ESRGAN/GFPGAN). Pages have
  been wired and shipped for releases — the chip now matches reality.
- Batch queue auto-scrolls to the active job in long queues.
  `QueueList.ScrollIntoView(job)` invoked at the top of the per-job
  loop in `DownloaderPage`, `RecorderPage`, and `FrameSnapshotPage`
  (the three `QueueList`-bearing pages). Try/catch absorbs the rare
  virtualization race when a container hasn't realized yet.

### Added — Audio Compressor sidecar + standalone page (ROADMAP Item 2)

- New `tools/audio-compressor/sidecar.py` — stdlib-only FFmpeg
  `acompressor` wrapper. Three operations: `compress` (explicit
  threshold/ratio/attack/release/makeup), `preset` (named DRC profile),
  `presets` (NDJSON enumeration of built-in presets).
- Five tested DRC presets: `light` (gentle, mastering bus), `medium`
  (default, all-purpose), `heavy` (obvious, loud sources), `podcast`
  (spoken word), `broadcast` (heavy with fast attack).
- Audio-only inputs preserve the original codec; video containers
  re-mux video and re-encode only the audio. Optional `--encode
  {mp3|aac|opus|flac|wav}` flag transcodes output for size-conscious
  workflows.
- Range-validated parameters: threshold −60..0 dB, ratio 1..20:1,
  attack 0.01..2000 ms, release 0.01..9000 ms, makeup 0..24 dB.
- New `audio_compressed` event registered in `KNOWN_EVENTS`; 177
  sidecars conform.
- New `Views/Pages/AudioCompressorPage.xaml` + `.xaml.cs` follows
  `CompressorPage` layout: drag-drop queue, preset combo with Custom
  mode revealing five sliders, encode-output combo, output-folder
  picker, progress overlay; every interactive control carries
  `AutomationProperties.AutomationId`.
- `ToolboxPage` `audio-compressor` tile flipped from `Future` /
  `null` engine to `Ready` / `FFmpeg acompressor`. `MainWindow` nav
  routes `audio-compressor` to the new page.

### Added — DownloaderPage cookie auth surface (ROADMAP Item 9-UI)

- Closes ROADMAP Item 9 — the DPAPI at-rest cookie encryption layer
  shipped iter-3 (commit `b8058de`) is now reachable from the C# UI.
- `streamkeep/sidecar.py` gains three ops: `cookies-status`,
  `cookies-import` (`--browser <chrome|firefox|edge|brave|chromium|
  vivaldi|opera|librewolf|safari>` | `--file <path>`), `cookies-clear`.
  All three emit a unified `cookie_status` NDJSON event reporting
  presence, encryption state, staleness in seconds, last action, and
  user-visible message.
- `cookie_status` event registered in `KNOWN_EVENTS`.
- `DownloaderPage.xaml` inserts a Cookie Authentication card between
  the URL options card and the Activity card. Browser combo, Import
  button, "Import from file..." picker for manual cookies.txt files,
  Clear button (gated on actual cookie presence). Status text auto-
  refreshes on page activation: e.g. "Cookies imported · encrypted
  at rest (DPAPI) · 5m ago".

### Added — UIA AutomationId contract gate + DownloaderPage cleanup (ROADMAP Item 10)

- Ships parts (a) and (c) of ROADMAP Item 10's three-part
  accessibility plan: a CI lint that prevents regression of
  AutomationId coverage on new interactive controls, plus an opening
  shrink of the baseline covering the most-clicked DownloaderPage
  chrome.
- `tests/uia_contract/check_uia.py` — stdlib-only XAML scanner over
  every `src/UniversalConverterX.UI/Views/**/*.xaml`. Flags 18
  interactive control element types (Button / ComboBox / Slider /
  ToggleSwitch / CheckBox / RadioButton / ToggleButton /
  MenuFlyoutItem / NumberBox / TextBox / PasswordBox / AutoSuggestBox
  / DropDownButton / SplitButton / HyperlinkButton / RepeatButton /
  AppBar*Button / ColorPicker / DatePicker / TimePicker / PivotItem)
  lacking `AutomationProperties.AutomationId`.
- Skips `DataTemplate` / `ControlTemplate` / `ItemsPanelTemplate` /
  `Style.Setters` scopes (templates can't carry an instance ID).
- Line-independent baseline keys: named controls keyed by `x:Name`,
  anonymous controls keyed by per-(file, element) document-order
  index `UNNAMED#N`. Unrelated edits don't trip the lint; only adding
  a new control without an ID does.
- `tests/uia_contract/baseline.txt` snapshots the current 470-entry
  deficit. CI passes when current violations are a subset; cleanups
  that shrink it are silently accepted. Regenerate with
  `--write-baseline`.
- `.github/workflows/build.yml` adds a `uia-contract` job; build job
  now `needs: [sidecar-contract, uia-contract]`.
- `DownloaderPage.xaml`: 11 high-traffic controls annotated
  (UrlBox, PasteButton, AddUrlButton, QualityCombo, OutputFormatCombo,
  AudioOnlyCheck, SubtitlesCheck, SponsorBlockCheck, ClearQueueButton,
  DownloadButton, CancelButton) — first cleanup against the baseline.

### Added — DPAPI at-rest encryption for StreamKeep cookies (ROADMAP Item 9 partial)

- New `tools/streamkeep/streamkeep/dpapi.py` — stdlib-only `ctypes`
  wrapper around `Crypt32.dll` (`CRYPTPROTECT_LOCAL_MACHINE` scope).
  `encrypt`, `decrypt`, `is_encrypted`, `available` helpers with a
  self-describing `DPAPI1\n` magic header so callers can detect format
  on read. `DpapiUnavailable` raised on non-Windows / GPO-locked hosts.
- `cookies.py` rewired:
  - `import_from_browser` / `import_from_file` writes encrypted at-rest
    when DPAPI is available; plaintext fallback otherwise.
  - `cookies_file_path()` transparently decrypts to a per-process
    temp file under `%TEMP%` and registers an `atexit` cleanup; yt-dlp
    / curl never see the encrypted form.
  - New `is_storage_encrypted()` accessor for any future settings UI.
- Round-trip verified end-to-end: import → encrypted on-disk →
  decrypted-on-read → matches input → cleared.
- Drive-by: `presets/to-mp3-192.preset.xml` migrated from a broken
  videocrush invocation (referenced a non-existent `--audio-only`
  flag) to the audiopro engine like the iter-2 VBR presets.

### Added — settings.json schema versioning + migration table (ROADMAP Item 53)

- `ConverterXOptions` gains a `SchemaVersion` field (`CurrentSchemaVersion = 2`)
  plus a public `LoadFromJson(json, persistMigrated)` entry point.
- New `SettingsMigrations` class holds an ordered list of
  `Action<JsonObject>` migrations. Index N transforms v(N+1) → v(N+2).
  Migrate iterates the table, stamps the target version, surfaces a
  `didMigrate` flag, and bails on gaps without looping.
- Legacy JSON without `SchemaVersion` treated as v1 and upgraded.
  Future-version JSON loads what it understands and clamps `SchemaVersion`
  back to current on its way out — older binaries don't silently downgrade.
- Console (`ucx config`) routes through `LoadFromJson` too without
  persisting (CLI may inspect read-only files).
- 7 new xUnit tests; `InternalsVisibleTo` on Core for test access.
- Foundation work for the next default-flip / field-rename — adding a
  migration is now a one-liner table addition rather than a refactor.

### Added — Output filename template DSL (ROADMAP Item 5)

- New `Core/Utilities/OutputFilenameTemplate` static class — single
  source of truth for output filename rendering.
- Token catalogue per the ROADMAP spec:
  - Built-in path: `{stem}` `{dir}` `{ext}` `{preset}`
  - Built-in time: `{date}` `{year}`
  - Caller-supplied media: `{title}` `{artist}` `{resolution}` `{fps}`
    `{bitrate}` `{codec}` `{duration}` `{n}`
- Path-separator-aware sanitization on every caller-supplied value
  (untrusted EXIF / ID3 / yt-dlp probes can't escape the directory).
  `{dir}` is intentionally NOT sanitised (it's a directory path).
- yt-dlp-compatible `{{` / `}}` brace escaping for literal braces.
- Unknown tokens render to empty (NOT left as `{foo}`) so half-resolved
  templates can't surface in user-visible paths. Strict mode opt-in via
  `GetSupportedTokens()`.
- Token names are case-insensitive.
- `ConversionPreset.ResolveOutputPath` delegates to the new utility and
  gains an optional `mediaTokens` parameter so future orchestrator
  metadata probing can plumb FFprobe data through.
- 13 new xUnit tests; full Core suite at 181 passing.

### Added — SponsorBlock integration in StreamKeep + DownloaderPage (ROADMAP Item 20)

- New `--sponsorblock {mark,remove}` flag in `tools/streamkeep/sidecar.py`
  plus `--sponsorblock-categories` (default `sponsor,selfpromo,interaction`).
  When set, populates yt-dlp's `sponsorblock_remove` / `sponsorblock_mark`
  ydl_opts. Backwards-compatible: omitting the flag is byte-for-byte
  identical to prior behaviour.
- DownloaderPage gains a "Skip sponsor segments (SponsorBlock)" checkbox
  alongside the existing Audio-only / Subtitles cluster. Job summary
  chip shows "+ sponsor-skip" when active. Tooltip documents the
  network behaviour (api.sponsor.ajay.app via yt-dlp's postprocessor).

### Added — Audio VBR quality mode in audiopro + videocrush (ROADMAP Item 30)

- Unified `--vbr-quality 0..9` (audiopro) / `--audio-vbr-quality 0..9`
  (videocrush) flag with codec-specific remapping:
  - libmp3lame → `-q:a 0..9` directly
  - libvorbis → `-q:a 9..0` (scale inverted)
  - libfdk_aac → `-vbr 5..1`
  - aac (native) → `-q:a 2.0..0.1` interpolated
  - libopus → `-b:a 192..32` kbps + `-vbr on`
  - unknown codec → warn + fall back to CBR / format defaults
- `videocrush` audio command-build refactored into a new `audio_args()`
  helper. The four inline cmd-build sites (intermediate codec branch,
  CRF mode, AV1 size-targeted, H.264/265 two-pass) now share one source
  of truth — eliminates copy-paste behaviour. Behaviour-preserving when
  `--audio-vbr-quality` is omitted.
- New presets:
  - `to-mp3-vbr-q2.preset.xml` — VBR V2 (~190 kbps avg, transparent)
  - `to-mp3-vbr-q4.preset.xml` — VBR V4 (~165 kbps avg, smaller files)
  - `to-aac-vbr-q3.preset.xml` — AAC VBR Q3 m4a output

### Added — Subtitle track export (ROADMAP Item 13 narrowed)

- `tools/clipforge/sidecar.py` gains `track-extract` op + argparse
  subcommand. Auto-picks FFmpeg subtitle codec from output extension
  (.srt → subrip / .vtt → webvtt / .ass → ass / .ssa → ssa / .lrc → lrc).
  PGS / DVD bitmap streams stream-copied to `.sup` only; bitmap-to-text
  OCR is correctly delegated to `subocr` / `subkit` sidecars.
- `TrackManagerPage` row template adds a per-row "Export..." button on
  subtitle rows (`IsSubtitle` + `ExportButtonVisibility` helpers on
  `TrackRow`). FileSavePicker scopes choices by source codec class
  (text vs bitmap) so users can't pick a transcoding combination the
  sidecar would refuse.

### Changed — ROADMAP.md (Phase 5 audit follow-through)

- Items 20 and 30 promoted to Tier 1 priority (still numbered under Tier 2
  for stable cross-references; flagged in the Tier 1 header).
- Items 7, 45, 48 carry inline Charter notes documenting why each
  user-initiated network operation aligns with the offline-first charter
  + which guardrails each must honour.
- Item 10 (Accessibility UIA) rewritten as "continue an in-progress
  audit" with the verified state (22 `Name` occurrences across 10 of
  45+ pages; zero `AutomationId` in `src`) and three concrete remaining
  steps including a CI lint to prevent regressions.
- Three new items (51 Observability, 52 Plugin Manifest, 53 Settings
  Schema Migration) added in a new "Audit-Surfaced Coverage Gaps" section.
  Total ROADMAP item count: 50 → 53.

### Added — orchestrator-level output filename collision protection (ROADMAP Item 4)

- **`UniversalConverterX.Core/Utilities/UniqueOutputPath`** — new utility:
  `Resolve(string desiredPath, int maxSuffix = 9999)` returns the input
  path unchanged if free, or `"stem (1).ext"`, `"stem (2).ext"`, …
  otherwise. Preserves the final extension only — `archive.tar.gz` becomes
  `archive.tar (1).gz`. `TryResolve` companion never throws.
- **`ConversionOrchestrator`** now applies `OverwriteBehavior` at the
  orchestrator boundary so every converter strategy and CLI/UI caller
  benefits from the same policy in one place. `Skip` returns a new
  `ConversionResult.Skipped` (`WasSkipped` flag, `ConversionStatus.Skipped`),
  distinct from cancellation.
- **`OverwriteBehavior` default flipped to `Never`** for fresh installs
  (auto-rename). Persisted `Ask`/`Always` settings continue to be honoured
  for upgraders. `Ask` falls through to legacy behaviour in Core (UI layers
  can prompt and set `OverwriteExisting=true` per job).
- **11 new xUnit tests** in `UniqueOutputPathTests` (single-collision /
  multi-collision / dual-extension / no-extension / directory-collision /
  saturation / TryResolve cases). Full Core suite: 161/161 passing.
- **`ProgressWindow`** unified its legacy `stem_N.ext` pre-render with the
  new utility so the UI preview and orchestrator policy match.

### Added — CI sidecar contract test gate (ROADMAP Item 11)

- **`.github/workflows/build.yml`** gains a new `sidecar-contract` job on
  ubuntu-latest that runs `tests/sidecar_contract/check_contract.py` on
  every push to `main` and every pull request. Stdlib-only — no install
  step required. The Windows build job now `needs: sidecar-contract`,
  failing fast on contract drift before burning Windows runner time.
- Local verification: 176 sidecars conforming, exit 0.

### Changed — ROADMAP.md reconciliation (Phase 5 audit)

Cross-family Phase 5 audit (master Claude Opus 4.7 + codex-direct gpt-5.4)
landed `docs/research/iter-1-audit.md`. ROADMAP.md updated:
- Items 4, 6, 8, 11, 34, 35 marked SHIPPED with closing-commit / evidence.
- Items 1 and 13 narrowed to PARTIALLY SHIPPED with remaining-scope notes.
- Item 10 (UIA) marked IN PROGRESS — `Name` partial, zero `AutomationId`.
- Header authoring date corrected (was future-dated).

## [v2.20.1] - 2026-05-01

### Fixed — Universal-converter audit cleanup

Comprehensive structural audit (sidecars × Toolbox tiles × presets cross-reference) revealed orphan engines that existed on disk but weren't surfaced through the UI. This release closes those gaps so every shipping sidecar is reachable from both the Toolbox grid and the preset browser.

### Added

- **`tools/framesnap/sidecar.py`** — NDJSON wrapper around the existing FrameSnap GUI for headless batch frame extraction. Ops: `every-n-seconds`, `every-n-frames`, `at-time`, `scene-cuts`. Emits `frame` events per extracted image.
- **31 new presets** linking previously-orphan engines into the preset browser: `bg-remove-video`, `audiotag-read`, `audiotag-strip`, `chaptermark-read`, `codeformat`, `coordfmt-convert`, `demucs-stems`, `ebookconvert-epub`, `edge-tts-speak`, `fontconvert`, `gfpgan-restore`, `gisconvert-vector`, `gisconvert-raster`, `lipsight-transcribe`, `mailbox-mbox-to-maildir`, `mailbox-mbox-split`, `ocr-recognize`, `pdfocr-recognize`, `pdftools-merge`, `pdftools-compress`, `pdftools-split`, `realesrgan-upscale`, `rnnoise-denoise`, `scenedetect-detect`, `timefmt-convert`, `vertigo-9x16`, `videosubtitleremover`, `wallet-bip39-check`, `wallet-keystore`, `whisper-cpp-transcribe`, `whisper-stt-transcribe`, `framesnap-every-n-seconds`.
- **33 new Toolbox tiles** for previously-orphan engines: `alphacut`, `archive`, `audiotag`, `chaptermark`, `codeformat`, `coordfmt`, `demucs`, `docconvert`, `ebookconvert`, `edge-tts`, `fontconvert`, `framesnap`, `gfpgan`, `gifstudio`, `gisconvert`, `heicshift`, `lipsight`, `mailbox`, `ocr`, `pdfocr`, `pdftools`, `realesrgan`, `recordcast`, `rnnoise`, `scenedetect`, `streamkeep`, `subconvert`, `timefmt`, `vertigo`, `videocrush`, `videosubtitleremover`, `whisper-cpp`, `whisper-stt`.
- KNOWN_EVENTS gains `frame` for the new framesnap sidecar.

### Changed

- Sidecar count: 175 → **176** (added framesnap).
- Toolbox tile coverage: 150 → **176 unique engines** — every shipping sidecar now has a tile.
- Preset coverage: 148 → **174 unique engines** — every shipping conversion sidecar has at least one preset. The two remaining preset-less sidecars (`recordcast` for live screen recording, `streamkeep` for URL-input downloads) are intentional: they take device handles or URLs, not files, so the preset model doesn't apply.
- Contract test: 175 → **176 sidecars conforming**, 0 broken tile refs, 0 broken preset refs.
- Version 2.20.0 → 2.20.1 across all manifests.

## [v2.20.0] - 2026-05-01

### Added — 13 new pure-format conversion sidecars (AI/ML + Forensics + Notes + DAW + Video post + PCB + BI + Reg + LMS + Med + IoT + Social + Dev)

- **mlmodel** — ML model interchange probes: HuggingFace `.safetensors` JSON header (read 8-byte length-prefix + JSON metadata without loading tensors), GGUF v2/v3 llama.cpp header + KV metadata walker (handles all 13 type IDs + array recursion), ONNX graph summary via `onnx` lib (input/output shapes + op-counts + opset imports), PyTorch `.pt`/`.pth`/`.bin` magic-byte heuristic detection, TFLite / CoreML / TF SavedModel format detection.
- **forensics** — Digital forensics artifact decoders: NTFS `$MFT` 1024-byte record parser with attribute walking + Windows FILETIME -> ISO-8601 timestamps, Windows `.reg` UTF-16 export -> JSON tree, Windows Prefetch `.pf` SCCA header (executable / path-hash decode), Chrome+Firefox+Edge browser history SQLite -> CSV with proper Chromium 1601-epoch + Firefox 1970-microsecond timestamps, EnCase `.E01` EWF probe via `ewfinfo` shellout.
- **notetaking** — Knowledge management exports: Evernote `.enex` XML walker with HTML-to-Markdown crude transform + per-note frontmatter, Notion workspace ZIP -> Markdown vault with manifest CSV, Obsidian vault crawler with tag/backlink extraction, Joplin `.jex` tar extraction, Day One JSON journal -> per-entry Markdown, Roam Research recursive block-tree -> Markdown bullet outline.
- **dawproject** — DAW project probes: Ableton Live `.als` gunzip + XML walk (tracks + plugins), REAPER `.rpp` text parser, Audacity `.aup` XML + `.aup3` SQLite probes, FL Studio `.flp` chunk-header reader, LMMS `.mmp`/`.mmpz` XML, DAWproject open-standard ZIP probe.
- **vidpost** — Video post-production timelines: FCPXML probe (formats + assets + sequences), `otioconvert` shellout for FCPXML <-> OpenTimelineIO, Premiere Pro `.prproj` gunzip + regex-based version/sequence/bin/clip count, CMX 3600 EDL parser with timecode regex -> CSV.
- **pcbcad** — Electronics CAD: Gerber RS-274X aperture catalog + command-count probe, Excellon NC drill (T-tool definitions + X/Y hole coordinates), KiCad `.kicad_pro` JSON + `.kicad_pcb` S-expression regex (footprints/tracks/vias/zones), Eagle XML probe, IPC-D-356 fixed-width netlist parser.
- **bireport** — BI / reporting projects: Tableau `.twb` XML / `.twbx` ZIP probe, Power BI `.pbix` UTF-16-LE DataModelSchema decode (tables + measures + data sources + culture), SSRS `.rdl` XML probe, Looker LookML directory regex, dbt project directory walker.
- **sdmx** — Regulatory data interchange: XBRL document parser with context + unit + concept resolution -> per-fact CSV, iXBRL inline-XBRL HTML extraction, SDMX-ML 2.1 generic data series + observation walker, SDMX codelist code/name extraction, DDI 2.5 codebook variable list.
- **lmskit** — Learning Management System: SCORM 1.2 / 2004 `imsmanifest.xml` probe, Common Cartridge `.imscc` ZIP probe, QTI assessment item walker, xAPI Tin Can statement JSON + NDJSON normalization, LTI 1.3 launch JWT decoder (no signature check), Moodle `.mbz` gzipped tar with `moodle_backup.xml` walker.
- **medkitex** — Healthcare extras: DICOM Structured Report content-sequence recursive walker with concept codes + measured values, DICOM Waveform per-channel CSV with proper sample-rate timing, HL7 CDA R2 / CCD / CCDA section walker, IHE XDS ExtrinsicObject metadata -> CSV, NCPDP SCRIPT e-prescribing -> JSON.
- **iotbus** — Industrial IoT: OPC UA NodeSet XML node-type counts + namespace + sample listing, Modbus register map JSON -> CSV, KNX ETS `.knxproj` ZIP probe, EDS DeviceNet/EtherNet-IP INI-style sections.
- **socialarchives** — Social-media exports: Twitter / X archive ZIP `.js`-prefixed JSON tweet decoder -> CSV, Mastodon `.tar`/`.tar.gz` outbox.json ActivityPub walker -> CSV, Reddit data export ZIP CSV bundle extraction, auto-detection of Twitter/Mastodon/Reddit/Discord/Bluesky archive types.
- **devbuild** — Developer build manifests: npm `package-lock.json` v1+v2 dependency tree -> CSV with depth, Cargo.lock TOML block parser, composer.lock packages + packages-dev, go.sum module/version/hash, Maven pom.xml dependency walker, .NET `.csproj` PackageReferences, auto-detect manifest format.

### Added — 33 new presets

`safetensors-header`, `gguf-header`, `onnx-info`, `mft-to-csv`, `reg-to-json`, `browser-history`, `enex-to-md`, `notion-zip`, `joplin-jex`, `als-info`, `flp-info`, `rpp-info`, `fcpxml-to-otio`, `edl-to-csv`, `gerber-info`, `drill-to-csv`, `kicad-pro`, `twb-info`, `pbix-info`, `rdl-info`, `xbrl-facts-csv`, `sdmx-data-csv`, `scorm-info`, `xapi-to-csv`, `dicom-sr-json`, `ccd-to-json`, `opcua-nodeset-info`, `twitter-tweets-csv`, `mastodon-outbox-csv`, `package-lock-csv`, `cargo-lock-csv`, `pom-deps-csv`, `manifest-info`.

### Changed

- KNOWN_EVENTS extended with 13 new event types: `ml_model`, `forensic_doc`, `note_doc`, `daw_doc`, `vidpost_doc`, `pcb_doc`, `bi_doc`, `regulatory_doc`, `lms_doc`, `medkitex_doc`, `iot_doc`, `social_archive`, `dev_doc`. Contract test: 175 sidecars conforming.
- 13 new Toolbox tiles route through `presets:engine` deep-link convention.
- Version 2.19.0 → 2.20.0 across all manifests.

## [v2.19.0] - 2026-05-01

### Added — 12 new pure-format conversion sidecars (Lab + Scope + Retro + Test reports + DB exports + Splat + ArcGIS + Thumbs)

- **labkit** — Lab + Windows-trace data: LabVIEW .lvm text Measurement file with `***End_of_Header***` sentinel parsing -> CSV, LabVIEW .tdms binary via npTDMS -> per-group CSV, Sysinternals Procmon .pml -> CSV via `Procmon.exe /OpenLog`, Windows ETW .etl -> CSV via `tracerpt`, Performance Monitor .blg -> CSV via `relog`.
- **scope** — Oscilloscope vendor formats: Tektronix .isf (curve-array ASCII headers + binary curve data with YMULT/YOFF/YZERO scaling) -> CSV, Tektronix .wfm v3+ binary -> CSV, LeCroy .trc with WAVEDESC descriptor -> CSV, Keysight / Agilent .bin (AG1000/AG1100 magic) -> CSV. Pure stdlib struct unpacking.
- **retroimg** — Retrocomputing graphics decoders: Atari ST DEGAS (.PI1/.PI2/.PI3/.NEO) with proper interleaved-bitplane unpacking, ZX Spectrum SCR (256x192 with bizarre line-address scrambling + attribute bytes), WBMP (Wireless Bitmap) for OMA mobile, Apple II HGR (8192-byte hi-res with vertical scrambling), all -> PNG via Pillow.
- **retrodisks** — Retrocomputing disk images: Apple II DOS 3.3 catalog walker (track 17 sector 15) for .dsk/.do/.po (143KB), Commodore 64 D64 catalog (track 18 sector 1) with 5-type file table (DEL/SEQ/PRG/USR/REL), Atari ATR magic header probe, ZX Spectrum .tap block walker (header + data block decoder).
- **legacydocs** — DOS / early-Windows word processors: WordStar 8th-bit-stripping decoder for .ws/.wsd, Microsoft Write .wri body extraction (after 256-byte OLE header), Lotus Word Pro .lwp last-resort string scrape, format detection by magic-byte heuristics.
- **testreports** — Test-runner result formats: JUnit XML (Jest/Vitest/Mocha/pytest/Maven/Gradle/MSTest) -> normalized CSV / standalone Catppuccin-themed HTML report, TAP (Test Anything Protocol) line parser, Allure JSON cases, Cucumber JSON (one row per scenario step), format auto-detection.
- **dbexport** — Database vendor exports: IBM DB2 IXF (record-oriented binary with H/T/C/D/A type prefixes) column metadata + data row decoder, SQL Server BCP character format -> CSV, MySQL .sql dump regex-extraction of `INSERT INTO table VALUES (...)` -> per-table CSV (handles escaped strings + NULL + numeric literals), Oracle SQL*Loader .ctl probe.
- **demosound** — Demoscene chip-music: Atari ST .YM file probe (YM2/3/4/5/6 magic + LeOnArD! tag check), .YM -> WAV via sc68 / sndh-converter, ZX Spectrum .ay -> WAV via zxtune123, Atari 8-bit SAP -> WAV via asap.
- **vidlegacy** — Legacy / proprietary video: RealVideo .rm/.rmvb, Bink .bik/.bk2 (RAD), Smacker .smk, OGG Media .ogm, DivX, MS Video 1, Cinepak, Indeo — all -> MP4 H.264 via FFmpeg with explicit codec hints, plus ffprobe-style legacy probe.
- **gsplat** — 3D Gaussian Splatting: Antimatter15 .splat (32-byte records: position + scales + RGBA + quaternion) <-> 3DGS .ply round-trip with proper PLY binary header emission and ASCII/binary input handling, splat header probe.
- **arcgis** — ArcGIS file geodatabase via GDAL: .gdb / .gpkg layer enumeration via ogrinfo, per-layer extraction via ogr2ogr to GeoJSON / Shapefile / GeoPackage / FlatGeobuf / GML / KML, extract-all walks every layer, ArcGIS Pro .aprx project ZIP probe.
- **mediathumb** — Universal media thumbnail extractor: video frame at N seconds via FFmpeg, PDF first page via pdftoppm, audio cover art (ID3 APIC + FLAC/Vorbis embedded picture) via mutagen, EPUB/CBZ/DOCX first image via zipfile, image resize via Pillow. Single `thumb` op auto-detects input type. `bulk-thumb` walks a directory tree preserving structure.

### Added — 23 new presets

`lvm-to-csv`, `tdms-to-csv`, `etl-to-csv`, `blg-to-csv`, `wfm-to-csv`, `isf-to-csv`, `trc-to-csv`, `retro-img-to-png`, `retrodisk-list`, `wordstar-to-text`, `wri-to-text`, `junit-to-csv`, `junit-to-html`, `tap-to-csv`, `ixf-to-csv`, `mysql-dump-csv`, `ym-to-wav`, `ay-to-wav`, `realvideo-to-mp4`, `splat-to-ply`, `ply-to-splat`, `arcgis-list-layers`, `mediathumb`.

### Changed

- KNOWN_EVENTS extended with 12 new event types: `lab_doc`, `scope_doc`, `retro_image`, `retro_disk`, `test_report`, `dbexport_doc`, `demo_audio`, `legacy_video`, `gsplat_doc`, `arcgis_doc`, `thumb_doc` (+ `legacy_doc` reused for legacydocs). Contract test: 162 sidecars conforming.
- 12 new Toolbox tiles route through `presets:engine` deep-link convention.
- Version 2.18.0 → 2.19.0 across all manifests.

## [v2.18.0] - 2026-05-01

### Added — 12 new pure-format conversion sidecars (Source Xform + DICOM-RT + niche eBooks + Auto + Airline + Tax)

- **srctranspile** — Cross-language source code transpilation: Python 2 -> Python 3 via stdlib lib2to3 (no install required), CoffeeScript -> JS via npm `coffee` CLI, Vue 2 SFC -> Vue 3 via `vue-codemod`, JS -> TypeScript bootstrap via `tsc --allowJs --declaration`, Flow-annotated JS -> TypeScript via `flow-to-ts`.
- **dicomrt** — DICOM-RT (radiation therapy) decoder extending `dicomkit`/`medkit`: RTSTRUCT structure-set ROI table -> CSV/JSON with full contour data, RTPLAN beam + control point + fraction sequence -> JSON, RTDOSE 3D dose grid -> NIfTI (.nii.gz) with proper spacing/origin via SimpleITK, dose-statistics probe (max/mean/Dx/Vx/p95/p99).
- **ebookmore** — Niche / legacy ebook formats: FictionBook 2 (.fb2 Russian/Slavic ecosystem) -> HTML / plain text via stdlib XML walker, PalmDoc TEXt/REAd PDB -> plain text via custom LZ77-style decompressor, .pdb header probe distinguishing PalmDoc / iSilo / Mobi6, Calibre `ebook-convert` fallback for LRF/TPZ/PRC.
- **bus** — Automotive / industrial bus database: DBC (Vector CAN) parser handling BO_/SG_/VAL_ keywords -> JSON / per-signal CSV (no cantools required), AUTOSAR ARXML quick probe (package + ECU count), SocketCAN candump trace -> CSV (timestamp/iface/id/len/payload), built-in OBD-II PID reference dictionary.
- **iata** — IATA airline messaging: NDC v17.2/v21.3 (AirShoppingRQ/RS, OfferPriceRQ/RS, OrderCreateRQ/RS, OrderViewRS, ItinReshopRQ/RS, ServiceListRS, SeatAvailabilityRQ/RS) XML -> structured JSON via stdlib XML walker, NDC type/version detection, legacy line-based PNR -> JSON, built-in IATA airport (39 codes) + airline (34 codes) reference data.
- **mobilephotos** — Mobile photo-library exports: Google Takeout Photos directory walker pairs each image with its sidecar `*.json` -> CSV manifest + selective EXIF/mtime re-injection, Apple `.photoslibrary` SQLite probe (handles ZASSET / ZGENERICASSET schema variations), Android MediaStore `.db` SQLite -> CSV (auto-detects images/media table), iOS `.ips` diagnostic archive (header JSON + body JSON) -> JSON.
- **taxkit** — Tax / accounting interchange: Swedish SIE 4 (BAS chart of accounts via `#KONTO` + voucher `#VER` / `#TRANS` lines, latin-1 encoded) -> CSV / JSON, DATEV German accounting CP1252 CSV with semicolon separator -> normalized UTF-8 CSV, IFX (Interactive Financial Exchange) XML -> JSON via generic walker, ELSTER tax filing XML probe (Verfahren / DatenArt / tax period detection).
- **datakitmore** — Niche data formats (extends `datakit`): EDN (Clojure's Extensible Data Notation), KDL (Cuddly Data Language) line-oriented parser, JSON5 (relaxed JSON with comments + trailing commas) via regex strip-down fallback when `json5` lib missing, HJSON (Human JSON), RON (Rusty Object Notation) regex transform, NestedText round-trip with JSON.
- **diagrammore** — Niche diagrams (extends `diagram`): GraphML (yEd / Cytoscape) -> JSON nodes+edges + SVG via Graphviz `dot` shellout, Freemind .mm mind maps -> Markdown bullet outline / OPML, Lucidchart `.lcc` bundle extract.
- **bgpkit** — BGP / RPKI routing telemetry: MRT TABLE_DUMP_V2 RIB (RFC 6396) via `mrtparse` -> CSV (prefix/next_hop/AS_PATH/origin/MED/local_pref/community) / JSON, BIRD `birdc show route` text output -> CSV, RPKI ROA dump normalization (handles RIPE / Cloudflare / NLnet column variants).
- **sdrkit** — Software-Defined Radio IQ format conversion: RTL-SDR `.cu8` (unsigned 8-bit) -> HackRF `.cs16` (signed 16-bit) -> GNU Radio `.cf32` (32-bit float) round-trip via stdlib struct + 1 MiB chunked I/O (no OOM on multi-GB captures), IQ-stream statistics (mean/min/max/RMS for I and Q), SigMF `.sigmf-meta` probe.
- **comicmeta** — Comic Rack ComicInfo.xml metadata for CBZ libraries: bulk read across CBZ collection -> CSV manifest with all 32 ComicInfo fields, inject ComicInfo.xml into existing CBZ files (preserves all other contents), CSV-driven bulk-edit (read manifest, edit, write back), scrub strips ComicInfo.xml + ComicBookInfo JSON.

### Added — 28 new presets

`py2-to-py3`, `coffee-to-js`, `js-to-ts`, `rtstruct-to-csv`, `rtdose-to-nifti`, `rtplan-to-json`, `fb2-to-html`, `fb2-to-text`, `palmdoc-to-text`, `dbc-to-json`, `dbc-to-csv`, `candump-to-csv`, `ndc-to-json`, `takeout-list`, `sie-to-csv`, `datev-to-csv`, `edn-to-json`, `kdl-to-json`, `json5-to-json`, `graphml-to-svg`, `graphml-to-json`, `freemind-to-md`, `mrt-rib-to-csv`, `rpki-roa-fix`, `cu8-to-cs16`, `cs16-to-cf32`, `comicinfo-read`, `comicinfo-scrub`.

### Changed

- KNOWN_EVENTS extended with 14 new event types: `source_xform`, `rt_struct`, `rt_plan`, `rt_dose`, `ebook_extra`, `bus_doc`, `airline_doc`, `photolib_doc`, `tax_doc`, `data_extra`, `diagram_extra`, `bgp_doc`, `sdr_iq`, `comic_meta`. Contract test: 150 sidecars conforming.
- 12 new Toolbox tiles route through `presets:engine` deep-link convention.
- Version 2.17.0 → 2.18.0 across all manifests.

## [v2.17.0] - 2026-05-01

### Added — 10 new pure-format conversion sidecars (Specialty Engineering + Wire / Network / Music / Sci)

- **wells** — Oil & gas well-log conversion: LAS 2.0/3.0 (CWLS Log ASCII Standard) parser handles section headers (~V/~W/~C/~P/~A) without lasio, plus DLIS binary read via dlisio. Outputs CSV (curves + units row) / JSON (full sections) / LAS round-trip from CSV.
- **datawire** — Schema-driven binary wire format conversion (extends `wirefmt`): Protocol Buffers binary <-> text-format via protoc CLI shellout, Apache Avro Object Container Format <-> JSON via fastavro, Apache Thrift IDL symbol introspection, FlatBuffers .fbs schema introspection.
- **wirelesskit** — NMEA 0183 GPS sentences (GGA/RMC/GLL/VTG/GSA/GSV) -> JSON / CSV / KML LineString track / GPX trkpt track. Plus AIS marine tracking (!AIVDM/!AIVDO) decode via pyais. Pure stdlib NMEA parser with checksum validation.
- **iac** — Infrastructure-as-Code translation: Docker Compose v1 -> v3 (links to depends_on, volumes_from drop, log_driver to logging.driver), CloudFormation YAML <-> JSON (intrinsic-function aware !Ref/!Sub/!GetAtt), Terraform plan JSON -> create/update/delete/replace/no-op summary, Helm template + Kustomize build shellouts.
- **bed** — Genome interval format conversion: BED3/BED6/BED12 + ENCODE narrowPeak/broadPeak/gappedPeak round-trip + GFF3/GTF -> BED6 (1-based -> 0-based coordinate translation, gene_id/transcript_id pulled from attributes) + bigBed <-> BED via UCSC bigBedToBed/bedToBigBed CLI.
- **swiftmx** — SWIFT MX (ISO 20022 XML banking) message decoder. Handles pacs.* / pain.* / camt.* / setr.* / remt.* families. Detects family + version from xmlns. Pure stdlib XML walk -> JSON. SEPA pain.001 Credit Transfer -> CSV (EndToEndId/Amount/Currency/Creditor/IBAN/BIC/RemittanceInfo). camt.053 statement entries -> CSV (BookingDate/ValueDate/Amount/CdtDbtInd/BankRef).
- **musicmore** — Notation conversion (extends `music`): LilyPond .ly -> PDF/SVG/MIDI via lilypond CLI, MusicXML -> LilyPond via musicxml2ly, LilyPond -> MusicXML via MIDI roundtrip + music21, MuseScore .mscz -> MIDI/PDF via mscore CLI.
- **playlistmore** — Playlist format extras (extends `playlist`): iTunes Library.xml plist -> M3U (whole library + per-playlist subset) + normalized JSON with track metadata + Spotify export JSON/CSV (exportify-style) -> M3U (with #EXTINF) + normalized CSV.
- **netflowkit** — Network flow telemetry decoder: NetFlow v5 fixed-width PDU parser (24-byte header + 48-byte records), NetFlow v9 + IPFIX (v10) template-aware parser maintaining template cache across flowsets, IPv4/IPv6 address decoding via ipaddress module, IANA IPFIX field names. Pure stdlib.
- **proteomics** — Mass-spectrometry / proteomics format conversion: mzML (HUPO-PSI XML standard) -> JSON / CSV with base64-encoded m/z + intensity arrays decoded via struct (32/64-bit float, optional zlib compression), mzXML (older ISB format), MGF (Mascot Generic Format) line-based parser. Pure stdlib (xml.etree).

### Added — 28 new presets

`las-to-csv`, `las-to-json`, `dlis-to-csv`, `avro-to-json`, `thrift-list-types`, `fbs-list-types`, `nmea-to-gpx`, `nmea-to-kml`, `ais-to-json`, `compose-upgrade`, `cfn-yaml-to-json`, `cfn-json-to-yaml`, `tf-plan-summary`, `bed-to-csv`, `gff-to-bed`, `gtf-to-bed`, `bigbed-to-bed`, `swift-mx-to-json`, `sepa-pain-to-csv`, `camt-statement-to-csv`, `lilypond-to-pdf`, `lilypond-to-midi`, `musicxml-to-lilypond`, `itunes-library-to-m3u`, `itunes-library-to-json`, `spotify-to-m3u`, `netflow-v5-to-json`, `ipfix-to-json`, `mzml-to-csv`, `mzml-to-json`, `mgf-to-json`.

### Changed

- KNOWN_EVENTS extended with 12 new event types: `well_log`, `datawire_blob`, `datawire_schema`, `nmea_msg`, `iac_doc`, `iac_plan`, `genome_interval`, `swift_mx`, `score_extra`, `playlist_extra`, `netflow_doc`, `massspec_doc`. Contract test: 138 sidecars conforming.
- 10 new Toolbox tiles route through `presets:engine` deep-link convention.
- Version 2.16.0 → 2.17.0 across all manifests.

## [v2.16.0] - 2026-05-01

### Added — 12 new pure-format conversion sidecars (Email + Messaging + Calendar + Subtitles + Specialty Enterprise)

- **emailpro** — Specialty email format conversion (extends `mailbox`): Outlook .msg via extract-msg → .eml or HTML, Apple Mail .emlx (length-prefix stripping) → .eml, and `thread-mbox` to bundle a directory of .eml files into a single .mbox.
- **messaging** — Chat / messenger export normalization: Telegram JSON, Discord JSON, Slack workspace ZIP, iMessage chat.db SQLite, WhatsApp text export. Normalized `Message` dataclass per platform → CSV / JSON / browseable HTML.
- **calmore** — Calendar + address-book extras (extends `calconvert`): Apple `.icbu` calendar-backup unpack, Google Takeout calendar JSON → ICS via icalendar lib, LDIF address books → vCard 3.0, Outlook CSV contacts → vCard 3.0.
- **subextra** — Subtitle format extras (extends `subkit` / `subocr`): CEA-608 / 708 closed captions via ccextractor CLI shellout, Apple iTunes Timed Text (.itt) → SRT / VTT, ASS karaoke → LRC lyrics (strips `\kNN` tags).
- **edi** — EDI X12 (US healthcare / supply chain / banking) and EDIFACT (international supply chain) → hierarchical JSON / per-segment CSV. Pure stdlib parser handles ISA / UNA delimiter declarations and EDIFACT release-character escaping.
- **swift** — SWIFT MT (banking) message decoder: parses {1:...}{2:...}{3:...}{4:...}{5:...} block envelope, extracts message type from block 2, walks block-4 fields by `:TAG:` boundaries → JSON / per-field CSV.
- **asn1** — ASN.1 BER / DER / PEM converter: structural TLV walk produces JSON tree (handles X.509 / PKCS#7 / CMS / SNMP / Kerberos blobs), human-readable universal tag names, OID dotted-decimal decoding, PEM ↔ DER round-trip.
- **mobile** — Mobile-device backup decoder: iTunes / Finder iOS backup inventory via Manifest.db SQLite + selective extract by relativePath substring; Android adb backup (.ab) → plain tar via DEFLATE strip.
- **dbsql** — SQL dialect translation via `sqlglot`: MySQL / Postgres / SQL Server / Oracle / SQLite / BigQuery / Snowflake / DuckDB / ClickHouse / Spark / Hive / Redshift / Databricks / Presto / Trino round-trip + format + AST dump.
- **spreadsheet** — Legacy spreadsheet conversion via LibreOffice headless: Lotus 1-2-3 (.wk1/.wk3/.wk4/.123), Quattro Pro (.wq1/.wq2/.qpw), Gnumeric, StarOffice .sxc, AppleWorks .cwk → XLSX / ODS / CSV.
- **colorfmt** — Color-format converter: hex (#RRGGBB[AA]) ↔ RGB ↔ HSL ↔ HSV ↔ CMYK ↔ CIE Lab (D65) ↔ CSS named (147 colors). Outputs CSV / JSON / CSS custom-property block. Pure stdlib (sRGB↔linear↔XYZ↔Lab math inline).
- **gameasset** — Game-engine asset container reader: Quake .pak (id Software), Doom .wad (IWAD/PWAD), Valve VPK v1/v2 (Source / GoldSrc), Godot .pck, ZIP-style .pk3 / .pk4 / .bsa. List manifest → JSON, extract → directory tree.

### Added — 22 new presets

`msg-to-eml`, `msg-to-html`, `emlx-to-eml`, `messaging-to-csv`, `messaging-to-json`, `messaging-to-html`, `icbu-extract`, `google-takeout-to-ics`, `ldif-to-vcard`, `outlook-csv-to-vcard`, `cea608-to-srt`, `itt-to-srt`, `itt-to-vtt`, `ass-to-lrc`, `edi-x12-to-json`, `edi-x12-to-csv`, `swift-mt-to-json`, `swift-mt-to-csv`, `asn1-to-json`, `ab-to-tar`, `sql-mysql-to-postgres`, `sql-postgres-to-bigquery`, `sql-tsql-to-snowflake`, `lotus-to-xlsx`, `lotus-to-ods`, `colors-expand`, `colors-to-css`, `game-asset-list`, `game-asset-extract`.

### Changed

- KNOWN_EVENTS extended with 12 new event types: `email_extra`, `chat_doc`, `calmore_doc`, `subtitle_extra`, `edi_doc`, `swift_mt`, `asn1_doc`, `mobile_doc`, `sql_doc`, `spreadsheet_legacy`, `color_doc`, `game_asset`. Contract test: 128 sidecars conforming.
- 12 new Toolbox tiles route through `presets:engine` deep-link convention.
- Version 2.15.0 → 2.16.0 across all manifests.

## [v2.15.0] - 2026-05-01

### Added — 7 new pure-format conversion sidecars (Healthcare + Finance + Engineering + Wire)

- **hl7** — HL7 healthcare messaging conversion. `v2-to-json` parses HL7 v2 pipe-delimited messages into structured JSON honouring all five delimiters (field / component / repetition / escape / subcomponent). `json-to-v2` re-emits cleanly. `fhir-to-xml` and `fhir-to-json` round-trip FHIR R4 / R5 resources. All pure stdlib (no fhir.resources / hl7apy dependency).
- **finance** — Personal finance / accounting interchange: OFX / QFX (Quicken / banks) via ofxparse, QIF (Quicken Interchange) via custom parser, IIF (QuickBooks Desktop) tab-delimited, MT940 / MT942 (European banking) via mt-940. Normalized Transaction record (date / amount / payee / memo / category / account / type / fitid). Outputs CSV / JSON / QIF.
- **cadmore** — 3D-printing / additive-manufacturing CAD: STL / OBJ / PLY / GLB / GLTF / DAE / OFF mutual conversion + 3MF (3D Manufacturing Format ZIP-based) + AMF (Additive Manufacturing Format XML). Custom 3MF emitter writes `[Content_Types].xml` + `_rels/.rels` + `3D/3dmodel.model`. `gcode-info` op probes G-code line / layer count + extrusion / travel mm + max Z height.
- **genome** — Genomics binary formats: VCF <-> BCF round-trip via pysam, BGZF (block-gzip) compress / decompress, tabix .tbi index generation for VCF / GFF / BED / SAM, ENCODE narrowPeak / broadPeak / gappedPeak -> BED6.
- **gistiles** — GIS raster + tile-pyramid conversion: GeoTIFF -> Cloud Optimized GeoTIFF via `gdal_translate -of COG`, KMZ -> KML + assets (zip extract), KML -> KMZ (zip), MBTiles SQLite metadata probe, PMTiles header probe.
- **imgmore** — Niche image conversion (extends `rasterimg`): JBIG2 (.jb2) via jbig2dec, Mac PICT / Amiga IFF / Atari Degas via ImageMagick, Adobe layered TIFF preserved via tifffile (one PNG per IFD page).
- **wirefmt** — Binary wire-format conversion: CBOR (RFC 8949) / MessagePack / BSON (MongoDB) / Apache Ion <-> JSON. Decodes from any of the four to JSON, encodes JSON to any of the four. Handles bytes / dates safely through round-trip.

### Added — 14 new presets

`hl7-v2-to-json`, `fhir-json-to-xml`, `ofx-to-csv`, `finance-to-qif`, `stl-to-3mf`, `stl-to-amf`, `vcf-to-bcf`, `bcf-to-vcf`, `geotiff-to-cog`, `kmz-to-kml`, `jbig2-to-png`, `cbor-to-json`, `msgpack-to-json`, `bson-to-json`, `json-to-cbor`.

### Changed

- KNOWN_EVENTS extended with 10 new event types: `hl7_message`, `fhir_doc`, `finance_doc`, `cad_more`, `cad_more_info`, `genome_doc`, `gistile`, `gistile_info`, `imgmore`, `wire_blob`. Contract test: 116 sidecars conforming.
- 7 new Toolbox tiles route through `presets:engine` deep-link convention.
- Version 2.14.0 → 2.15.0 across all manifests.

## [v2.14.0] - 2026-05-01

### Added — 7 new pure-format conversion sidecars (Streaming + Crypto + Niche A/V)

- **videopro** — Specialty video container conversion: DVD VOB / EVO / Blu-ray MTS / M2TS / TS / DV / DIF / 3GP / 3G2 / F4V / SWF / Y4M / IVF + AVS / AVS2. `extract-bitstream` op pulls raw H.264 / H.265 / AV1 / VP9 elementary streams from any container.
- **streaming** — Adaptive streaming manifests: MP4 → HLS (.m3u8 + .ts) and MP4 → DASH (.mpd + .m4s) via FFmpeg or shaka-packager. `to-mp4` op assembles a single MP4 from any HLS / DASH manifest.
- **imageseq** — VFX image-sequence ↔ video conversion. `encode` takes a DPX / Cineon / OpenEXR / PNG / TIFF / JPEG sequence and produces ProRes 422 / 422 HQ / 4444 / DNxHR HQ / SQ / H.264 / H.265 / AV1 / FFV1 / raw video. `decode` extracts frames from any video as PNG / JPG / TIFF / EXR / DPX with optional FPS override.
- **chiptune** — Retro game-music renderer: NSF / NSFE (NES), SPC (SNES), VGM / VGZ (multi-system), GBS (Game Boy), HES (PCEngine), KSS (MSX), GYM (Genesis), AY (ZX Spectrum), SID (C64). Backed by `game-music-emu` Python binding + `sidplayfp` for SID. Renders to WAV / FLAC / MP3 / OGG / Opus.
- **audiomore** — Long-tail audio codec conversion (extends `audiopro`): AIFF / AIFC / IFF-8SVX / Apple CAF / G.711 ulaw / alaw / DTS / DTS-HD MA / Dolby TrueHD / MLP / HE-AAC v2 / xHE-AAC.
- **gpgkit** — OpenPGP / GnuPG armor codec. `armor` op wraps any binary `.gpg`/`.pgp` blob in RFC 4880 ASCII armor with proper CRC-24, `dearmor` op reverses it. `key-info` op shells out to `gpg` to probe fingerprints + user IDs.
- **wallet** — Read-only crypto wallet metadata. `bip39-check` validates a BIP39 mnemonic phrase + checksum. `keystore-info` decodes Ethereum keystore JSON v3 header (cipher / KDF / address) without ever exposing the private key. `descriptor` parses Bitcoin output descriptors (`wpkh(...)`, `tr(...)`, `multi(...)`). `psbt-decode` heuristically counts inputs / outputs of a Partially Signed Bitcoin Transaction. **Never** decodes private keys, never signs.

### Added — 12 new presets

`vob-to-mp4`, `extract-h264`, `mp4-to-hls`, `mp4-to-dash`, `hls-to-mp4`, `seq-to-prores`, `video-to-png-seq`, `nsf-to-flac`, `aiff-to-flac`, `to-aiff`, `gpg-armor`, `gpg-dearmor`.

### Changed

- KNOWN_EVENTS extended with 11 new event types: `video_specialty`, `stream_manifest`, `image_seq`, `chiptune_audio`, `audio_long_tail`, `pgp_blob`, `pgp_key`, `wallet_bip39`, `wallet_keystore`, `wallet_descriptor`, `wallet_psbt`. Contract test: 109 sidecars conforming.
- 7 new Toolbox tiles route through `presets:engine` deep-link convention.
- Version 2.13.0 → 2.14.0 across all manifests.

## [v2.13.0] - 2026-05-01

### Added — 14 new pure-format conversion sidecars (Office + Diagrams + Sysadmin)

- **legacyoffice** — WordPerfect (.wpd/.wpt/.wpg) / AmiPro (.sam) / Microsoft Works (.wps) / Microsoft Publisher (.pub) / StarOffice 1-5 (.sxw/.sxc/.sxi) / KOffice (.kwd) / AbiWord (.abw) / AppleWorks (.cwk) / MacWrite (.mw) -> PDF / DOCX / ODT / RTF / HTML / TXT via LibreOffice CLI.
- **applepro** — Apple Pages / Numbers / Keynote (.pages/.numbers/.key) -> DOCX / XLSX / PPTX / PDF / ODT / RTF / HTML / TXT. LibreOffice path for older iWork; embedded `Preview.pdf` extraction fallback for modern (post-2013) bundles.
- **hwpkit** — Korean Hangul HWP / HWPX -> PDF / DOCX / ODT / RTF / HTML / TXT. LibreOffice primary path; pyhwp text/HTML extraction fallback.
- **diagram** — Render text-based and binary diagrams: Mermaid (.mmd) via mmdc, PlantUML (.puml) via plantuml.jar, Graphviz (.dot) via dot, Visio (.vsd/.vsdx) via LibreOffice + libvisio, draw.io (.drawio) via drawio CLI, Excalidraw (.excalidraw) via excalidraw-cli. Outputs SVG / PNG / PDF / HTML.
- **playlist** — M3U / M3U8 / PLS / XSPF / WPL / ASX / B4S / iTunes Library .xml mutual conversion. Normalizes track metadata (path/title/artist/album/length) through a unified intermediate; CSV + JSON output also supported.
- **comic** — CBZ / CBR / CBT / CB7 mutual re-pack + CBZ-to-PDF (img2pdf) + CBZ-to-EPUB (EbookLib). RAR support via the rarfile package + unrar binary.
- **notebooks** — Jupyter ipynb <-> py / md / Rmd / qmd / html / pdf / tex / rst / slides via nbconvert and jupytext. `execute` op runs notebook + saves outputs.
- **helpkit** — Compiled HTML Help (.chm): `extract` op cracks open the bundle to a directory of HTML, `to-pdf` stitches the pages into a single PDF via weasyprint.
- **tlskit** — X.509 certificate + key conversion: PEM <-> DER <-> PKCS#7 (.p7b) cert conversion, PKCS#12 (.p12 / .pfx) bundle extract + create, private key PEM <-> DER. `cert-info` op probes subject/issuer/validity/SAN/SHA-256+SHA-1 fingerprints.
- **sshkit** — SSH key format conversion: OpenSSH <-> PKCS#8 PEM, PEM/OpenSSH <-> PuTTY .ppk (via puttygen), OpenSSH .pub -> RFC 4716 wrapped public key. Encrypted output supported via `--out-password`.
- **timefmt** — Timestamp conversion: ISO 8601 / RFC 822 / Unix epoch (s + ms) / Excel serial date / Apple Cocoa epoch / Microsoft FILETIME / HFS+ / mainframe Julian / .NET ticks. `cron-explain` op shows next N runs + human-readable description for any cron expression.
- **coordfmt** — Geographic coordinate conversion: DD <-> DMS <-> DDM <-> UTM <-> MGRS <-> Geohash <-> Plus Codes (Open Location Code). CSV bulk transform appends all representations as columns.
- **config** — DevOps configuration formats: HCL (Terraform .tf / .hcl) / HOCON (Typesafe .conf) / Java .properties / INI (.ini/.cfg) / systemd unit files <-> JSON / YAML / TOML / properties / INI. Round-trips through normalized JSON middle representation.
- **dnskit** — DNS zone file conversion: BIND zone (.zone/.db) <-> JSON / YAML / CSV via dnspython. `validate` op reports findings (missing SOA, missing NS, etc.). `emit` op rebuilds a BIND zone from JSON/YAML/CSV.

### Added — 25+ new presets

`wpd-to-pdf`, `pages-to-docx`, `numbers-to-xlsx`, `keynote-to-pptx`, `hwp-to-pdf`, `mermaid-to-svg`, `diagram-to-png`, `visio-to-pdf`, `playlist-to-m3u`, `playlist-to-xspf`, `comic-to-pdf`, `comic-to-epub`, `comic-to-cbz`, `ipynb-to-html`, `ipynb-to-md`, `py-to-ipynb`, `chm-extract`, `chm-to-pdf`, `cert-pem-to-der`, `cert-der-to-pem`, `pfx-extract`, `ssh-to-pem`, `ssh-to-ppk`, `hcl-to-json`, `properties-to-yaml`, `zone-to-json`.

### Changed

- KNOWN_EVENTS extended with 17 new event types: `legacy_doc`, `iwork_doc`, `hwp_doc`, `diagram_doc`, `diagram_tool_status`, `playlist_doc`, `comic_book`, `notebook_doc`, `help_doc`, `tls_cert`, `ssh_key`, `time_value`, `cron_explain`, `coord`, `coord_csv`, `config_doc`, `dns_record`, `dns_zone_check`. Contract test: 102 sidecars conforming.
- 14 new Toolbox tiles route through `presets:engine` deep-link convention.
- Version 2.12.0 → 2.13.0 across all manifests.

## [v2.12.0] - 2026-05-01

### Added — 10 new domain-specific raw-conversion sidecars

- **chemkit** — Chemistry / cheminformatics: SMILES, MOL, SDF, MOL2, PDB, XYZ, CIF, InChI mutual conversion via RDKit; falls back to Open Babel CLI for the broader format pool. `info` op probes molecular formula, MW, SMILES, InChI, ring count, heavy-atom count.
- **biokit** — Bioinformatics: FASTA / FASTQ / GenBank / EMBL / Newick / Stockholm / Clustal / PHYLIP / NEXUS sequence + alignment conversion via Biopython. `fastq-stats` op for QC (read count, GC %, mean Phred Q, length distribution). `vcf-to-tsv` flattens VCF to tab-delimited. `bam-to-fastq` extracts reads from BAM/CRAM via pysam.
- **medkit** — 3D medical / scientific imaging: NIfTI 1/2 (.nii, .nii.gz), Analyze 7.5, MetaImage (.mha/.mhd), NRRD, MINC, GIPL, VTK ImageData mutual conversion via SimpleITK. `to-png-stack` op renders every Z slice as a normalized PNG. `info` op reports dim / spacing / origin / dtype.
- **netcap** — Network capture conversion: PCAP <-> PCAPNG via scapy. `to-csv` op flattens each packet into a CSV row (time / src / dst / protocol / port / summary).
- **logkit** — Log file -> structured JSONL: Apache CLF / Combined / Nginx, syslog (RFC 3164 + RFC 5424), Windows Event Log .evtx (via python-evtx + xmltodict).
- **rasterimg** — Niche raster image conversion: PCX, Truevision TGA, Cineon, DPX, SGI/RGB, Sun Raster, Wireless Bitmap (.wbmp), Photo CD (.pcd), Netpbm (.pbm/.pgm/.ppm), APNG, MNG (read), FLI/FLC (read), X PixMap (.xpm), XBM, Palm Pixmap. Handled via Pillow with smart mode coercion (auto-drop alpha for formats that lack it).
- **morearchive** — Long-tail archive / package extraction: SIT/SITX (StuffIt via unar), LHA/LZH, ARJ, ZOO/HA/ARC (legacy DOS via unar), DEB/IPK (Debian), RPM (Red Hat via 7z + cpio), DMG (macOS, read-only via 7z), IPA (iOS), APK/XAPK/APKS (Android), MSIX/APPX (Windows modern app), NUPKG (NuGet). `info` op probes APK/IPA/MSIX manifests.
- **bookmark** — Cross-browser bookmark conversion: Chromium (Chrome/Edge/Brave/Opera) JSON `Bookmarks` file, Firefox bookmark backup JSON, Safari .plist (binary), Opera classic .adr, Netscape HTML (de-facto export format), CSV / Pinboard / Diigo / Raindrop. Outputs Netscape HTML, CSV, or normalized JSON.
- **engcad** — Engineering CAD: STEP (ISO 10303), IGES, BREP, STL, OBJ via pythonocc-core (Open CASCADE Technology BREP solid modeling kernel). Falls back to trimesh for mesh-only paths when pythonocc isn't available.
- **animkit** — 3D animation / scene description: BVH (Biovision Hierarchy motion capture), Alembic (.abc), USD / USDA / USDC / USDZ (Pixar Universal Scene Description), FBX, glTF / GLB, VRM (VRoid), Collada (.dae). USD path via usd-core; FBX/Collada/Alembic via assimp CLI shellout.

### Added — 19 new presets

`smiles-to-sdf`, `mol-to-pdb`, `fasta-to-genbank`, `fastq-to-fasta`, `bam-to-fastq`, `nifti-to-png-stack`, `analyze-to-nifti`, `pcap-to-pcapng`, `pcap-to-csv`, `apache-log-to-jsonl`, `evtx-to-jsonl`, `tga-to-png`, `extract-niche-archive`, `bookmarks-to-html`, `bookmarks-to-csv`, `step-to-stl`, `step-to-iges`, `fbx-to-glb`, `usd-to-usdz`.

### Changed

- KNOWN_EVENTS extended with 15 new event types: `molecule`, `molecule_info`, `bio_seq`, `bio_stats`, `medical_volume`, `medical_volume_info`, `net_capture`, `log_record`, `raster_image`, `archive_extra`, `archive_extra_entry`, `archive_extra_info`, `bookmark_doc`, `eng_cad`, `anim_scene`. Contract test: 88 sidecars conforming.
- 10 new Toolbox tiles route through `presets:engine` deep-link convention.
- Version 2.11.0 → 2.12.0 across all manifests.

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
