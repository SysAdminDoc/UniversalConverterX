# Changelog

All notable changes to UniversalConverterX will be documented in this file.

## [Unreleased]

### Added

- Runtime UI smoke gate (`build.ps1 -Target UiSmoke`, `tests/ui_smoke/Invoke-UiSmoke.ps1`). The real x64 shell is launched and driven through all 54 registered routes in light, dark, and a 640-DIP narrow reflow pass — 162 navigations — asserting each page constructs, lays out to a non-empty rect, and exposes a reachable focus target. Failures capture a PNG of the shell and are reported per route/theme with the exception; unhandled XAML and AppDomain exceptions are recorded rather than killing the sweep, so one broken page no longer hides the rest. Verified by fault injection: a thrown constructor is reported on all three passes with screenshots.

### Changed

- Release artifacts now report sidecar readiness truthfully instead of implying every advertised engine ships. `tools/release/sidecar_readiness.py` stages only artifacts named in one authenticated clean build report, re-verifies every byte against it, and writes an architecture-scoped `sidecar-readiness.json` covering all 212 engines as bundled, on-demand, or unavailable with a reason. Untracked payload under `tools/` fails the stage. The MSI payload is generated from the clean staged tree (`installer/New-WixPayload.ps1`) rather than hand-listed in `Product.wxs`, so packaged content can no longer drift from what was published. `installer/Test-ReleaseArtifacts.ps1` extracts a fresh portable ZIP and MSI and runs a real FFmpeg-generated fixture through the packaged `ucx` CLI, probing the output. Toolbox tiles in a packaged build resolve their badge from the shipped catalog, so a workflow whose engine is absent reads Unavailable with an actionable reason instead of Ready.

### Fixed

- Explorer, MSIX file/protocol/startup activation, Jump Lists, and completion notifications now converge on one AppLifecycle router. Every selected path is queued in the existing Converter window, secondary launches redirect to the primary instance, `ucx:` routes reach the requested page, and the invalid COM toast declaration was removed.

### Added

- UltraHDR gain-map workflows can explicitly encode and decode-check 10-bit and 12-bit AVIF base/gain-map pairs; the headless runtime smoke also accepts an ISO 21496-1 JPEG fixture to verify metadata-preserving JPEG round-trips and JPEG-to-AVIF conversion.
- Sidecar builds now have a connected preparation/offline consumption pipeline: independent per-tool resolutions record authenticated wheel URLs, sizes, and SHA-256 values; clean builds recreate isolated environments and install only the hash-locked wheel set with indexes disabled. Installer staging now emits a separately publishable and bundled CycloneDX 1.7 SBOM covering exact staged files, NuGet and Python dependencies, native tools and runtimes, sidecars, and governed model packs.

### Security

- Python build tooling is exactly pinned, undeclared inline dependencies fail the 212-sidecar manifest audit, extra or modified wheelhouse content fails closed, and resolutions containing Torch older than 2.6.0 are rejected for GHSA-53q9-r3pm-6pq6. Twenty-one previously inline-only sidecar dependency sets now have auditable requirements manifests.
- Background-removal inference no longer trusts mutable Hugging Face cache state. BiRefNet and RMBG packs now install only through an explicit licence-gated action from full commit revisions and allowlisted files, verify exact sizes and cryptographic digests before atomic promotion, reject modified or additional code at every load, and isolate Transformers' dynamic-module cache. The frozen sidecar also carries the required CPU ONNX and BiRefNet dependencies and is smoke-tested with a real offline BiRefNet conversion.
- Corrected the libvips security policy for CVE-2026-3281: the official 8.18.3 Windows bundle is now the approved, exact-size/SHA-256-pinned UltraHDR runtime, while the known-affected 8.19.0 build is explicitly blocked instead of being accepted as the minimum safe version. CLI, Settings, sidecar health, and conversion-gate diagnostics now distinguish an explicitly rejected build from an older release.

## [2.33.0] - 2026-07-21

### Added

- **VVC / H.266 decode support (decode-only).** Raw VVC bitstreams (`.vvc`, `.h266`, `.266`) are now recognized as video, categorized correctly, and transcodable to common containers via FFmpeg's native `vvc` decoder (FFmpeg 8.1+; `vvc_qsv` hardware decode is also available where present). VVC is intentionally not offered as an output/encode target — decode-only, per the format's still-thin encode ecosystem. Covered by CanConvert tests.
- **Batch-queue search & non-destructive clone primitives.** `BatchQueueOperations.Search` filters queued jobs by a free-text query across source/output path, engine, action, preset, status, and error message; `CloneAsNew` clones a job into a fresh re-queueable one (new id, `Queued` status, cleared error, deep-copied args) without mutating the original. Both are unit-tested.
- **Encode-history replay accessors.** `HistoryStore.GetRerunRequestAsync(id)` reconstructs the saved `ConversionRerunRequest` for a specific history row ("Apply settings"), and `GetLastUsedRerunAsync()` returns the most recent row that still carries valid re-run parameters ("Apply last used settings"), skipping rows without them. Both are covered by tests over a real SQLite store.
- **Hardware video encoder detection beyond NVENC.** New `FfmpegEncoderProbe` parses `ffmpeg -encoders` and classifies the available hardware encoders by vendor (NVIDIA NVENC, AMD AMF, Intel Quick Sync, VAAPI, VideoToolbox, Vulkan) and codec. Exposed as `ucx encoders`, which lists what the local FFmpeg build actually supports — on this machine it detects AMD AMF AV1, Intel QSV AV1/HEVC, and NVENC alongside the previously-only-assumed NVENC. Parsing is unit-tested with fixture output; the live probe is cached per FFmpeg binary.
- **Per-track audio/subtitle stream selection.** `ConversionOptions.AudioTrackSelection` and `SubtitleTrackSelection` drive explicit FFmpeg `-map` directives: `null` keeps every track of that kind, an empty list drops it, and a list of zero-based indices keeps exactly those streams (all video streams are always kept). Works for both re-encode and remux (`-c copy`) paths. Exposed on the CLI as `ucx convert --audio-tracks 0,2` / `--subtitle-tracks none`. Covered by command-builder tests.

## [2.32.0] - 2026-07-20

### Added

- **Completed the outcome-named "Production" preset family.** Added `Video/Production` curated presets for the remaining professional tiers — ProRes 422 HQ, ProRes 422 Proxy, ProRes 4444, DNxHR SQ, DNxHR HQX — alongside the existing ProRes 422 / DNxHR HQ entries, giving a full HandBrake-style editing-mezzanine family (all routing through the videocrush sidecar). The `Video/Preservation` FFV1+FLAC lossless-archival preset is unchanged. Extended the family regression test to lock in every tier.
- **Offline "best format for target" recommender.** New `FormatRecommender` maps a source file's media category and a delivery target (`Web`, `Apple`, `Android`, `Discord`, `Email`, `Archive`, `Editing`) to a concrete container/codec choice with a one-line rationale — fully deterministic, zero network calls (unlike the cloud "AI recommend" features rivals paywall). Exposed on the CLI as `ucx recommend <file> --target <target>`. Unit-tested rule table across video/audio/image and the extension-classifier overload.
- **Remux / stream-copy ("change container, no re-encode").** New `ConversionOptions.StreamCopy` makes `FFmpegConverter` emit `-map 0 -c copy` (video containers) or `-map 0:a? -c:a copy -vn` (audio containers) instead of re-encoding, so a container swap (e.g. MKV→MP4) is near-instant and lossless when the source codecs are allowed in the target container. Exposed on the CLI as `ucx convert <file> -o <ext> --copy` (alias `--remux`). Incompatible codec/container pairs surface as a normal failed conversion with FFmpeg's error. Two-pass planning is skipped when stream-copy is set.
- **Cross-instance-safe batch queue claiming.** `IBatchQueueStore` gains `TryClaimJob(queueKey, jobId)`, which atomically transitions a job from `Queued` to `Running` and persists it, returning `false` when the job is missing or already claimed. `JsonBatchQueueStore` now serializes every read/write/claim behind a per-directory named mutex (`Local\ucx-batch-queue-<hash>`, with abandoned-mutex recovery) layered over its in-process lock, so a second running instance watching the same queue directory can no longer double-claim and re-process the same file. Writes were already atomic (temp + rename); a concurrency test proves exactly one of many contending claims wins.

### Fixed

- **JPEG XL lossless-JPEG recompression is now correct.** `LibJxlConverter` previously emitted `--lossless_jpeg=1` for *any* Lossless input (including PNG/PPM, where it is invalid) and combined it with `--progressive` (which conflicts with JPEG recompression). It now applies `--lossless_jpeg=1` only when the input is a JPEG — producing a byte-for-byte reconstructable JXL — and drops the incompatible distance/effort/progressive/responsive flags in that mode. Lossless non-JPEG inputs correctly encode mathematically lossless pixels via `-d 0`.
- **Native FFmpeg two-pass encoding now actually runs two passes** instead of silently falling back to single-pass. Previously `VideoOptions.TwoPass = true` only wrote a debug warning and encoded once, so callers who requested average-bitrate two-pass got single-pass output reported as success. `FFmpegConverter` now overrides `ConvertAsync` to run a real analysis pass (to the OS null sink, audio disabled) followed by the encode pass, sharing a `-passlogfile` prefix that is cleaned up afterward. Two-pass engages only when it is meaningful — an explicit target bitrate with no CRF override on a video output; CRF-mode/audio-only/raw-command-override jobs fall through to the unchanged single-pass path. Added unit coverage for the pass-1/pass-2 argument planning and the engagement gate.

### Security

- **The security version floor is now enforced at conversion time, not just surfaced as a warning.** `ConversionOrchestrator` probes the CLI tool backing the selected converter (via the new `IToolVersionProbe`/`ProcessToolVersionProbe`, cached per executable + mtime) and refuses the job with a clear message when the tool is *positively identified* as below its floor (`ToolVersionGate.IsBlocked`). Unknown/unparseable versions (custom or nightly builds) and missing executables never block — the gate only stops known-old, vulnerable binaries. Added `IConverterStrategy.ResolveExecutablePath()` so the probe reuses each strategy's own executable resolution. Regression tests cover the blocked path (converter never invoked) and the pass-through path.
- Extended the `ToolVersionPolicy` security floor to four previously-ungated external parsers that read untrusted files: **libheif ≥ 1.22.0** (CVE-2026-32740/-32741/-32814 — grid-tile heap OOB write on the default HEIF/AVIF decode path, CVSS 8.8), **libjxl ≥ 0.11.2** (CVE-2026-1837 decoder UAF), **libvips ≥ 8.19.0** (CVE-2026-3281), and **Ghostscript ≥ 10.07.1** (PostScript/PDF parser hardening). Added canonical aliases (`libvips`→`vips`, `gswin64c`/`gswin32c`/`gs`→`ghostscript`, `cjxl`/`djxl`→`libjxl`, `heif-enc`/`heif-dec`→`libheif`) so `SidecarHealthService`, Settings, and `ucx tools` all surface an out-of-date warning for these engines.

## [2.31.5] - 2026-07-19

### Changed

- Every bounded (blocking, output-buffered) `subprocess.run` call across the 212 sidecars now enforces a wall-clock timeout (600s, matching the C# host's silence watchdog). Previously ~85 calls omitted `timeout=`, so a wedged external tool hung the job forever under CLI/test invocations that run without the host watchdog. Added a shared `ucx_sidecar.run()` helper (with `DEFAULT_SUBPROCESS_TIMEOUT` and a `SubprocessTimeout` error) plus unit tests, and documented the required pattern. Streaming encoders that report progress remain governed by that progress via `run_ffmpeg`.

### Fixed

- LibreOffice output relocation now reconciles the filter's native extension. `--convert-to` writes the filter's own extension (requesting `.jpeg` yields `.jpg`, `.text` yields `.txt`), so the exact-extension relocation added earlier could still miss the produced file and report a successful conversion as failed. The validator now also relocates a known-alias output (`jpeg`↔`jpg`, `tif`↔`tiff`, `htm`↔`html`, `text`→`txt`), guarded to only pick a file freshly written during the conversion — never the input or a stale same-stem file.
- `PathSafety.SanitizeFileNameComponent` now neutralizes Windows reserved device names (`CON`/`NUL`/`PRN`/`AUX`/`COM1`–`COM9`/`LPT1`–`LPT9`, with or without an extension) by prefixing an underscore, and strips trailing dots/spaces that Windows silently removes. Untrusted metadata (EXIF/ID3/probe titles) resolving a stem to one of these previously produced a name the downstream file create would reject.
- Vips no longer discards image quality/compression/strip/metadata settings when a resize dimension is set. Previously, specifying a width or height rebuilt a bare `thumbnail in out <size>` command that dropped every selected `Q=`/`compression=`/`lossless=`/`effort=`/`strip=` option, so any resized output silently reverted to default quality with metadata intact. The save options now ride in the vips output-filename suffix (`out.jpg[Q=55,strip=true]`), which is how `thumbnail` accepts saver options. Also extends `strip=true` honoring to PNG/WebP/AVIF/HEIF/JXL/TIFF outputs (was JPEG-only).

### Security

- Cap tool downloads at a per-tool size ceiling (default 1 GiB; 256 MiB for the non-checksum-required image tools resvg/vips/libjxl/libheif/imagemagick/potrace). A response whose declared `Content-Length` exceeds the cap is rejected before any byte is written, and the copy loop aborts (deleting the partial file) if a chunked/under-declaring body streams past the cap — a compromised or mis-pinned asset can no longer fill the disk ahead of the post-download checksum.

## [2.31.4] - 2026-07-17

### Security

- Guard sidecar `tarfile.extractall` and the Godot `.pck` extractor against path traversal (tar-slip): a malicious `.cbt` comic archive, Joplin `.jex` export, or crafted `.pck` could write outside the extraction directory or plant symlinks. Added shared `safe_tar_extractall`/`safe_extract_path` helpers. (zip extraction was already safe — CPython strips `..`.)
- Neutralize CSV formula injection in exported conversion reports: fields beginning with `= + - @` (from filenames or tool output) are prefixed with an apostrophe so they aren't executed as formulas in Excel/LibreOffice, while genuine negative numbers are left intact.
- Escape user-controlled values in `ucx` CLI markup output so a `[` in a config key/value, path, format, tool name, or action no longer throws inside Spectre and returns exit code -1 instead of the intended 0/1.

### Fixed

- Fix a fatal crash when opening several tool pages from the Toolbox (and Home / AI Lab). Nine pages — Image Converter, Image Enhancer, Video Enhancer, Photo Restoration, Noise Remover, GIF Maker, PDF Tools, Batch Rename, and Auto Reframe — wired a `SelectionChanged`/`Changed` handler that fires while `InitializeComponent()` is still constructing the page, before the controls it reads exist. The existing `if (RunButton is null) return;` guard checked a control created too early, so the handler ran and threw `NullReferenceException`, fail-fasting the app. Added an `_isReady` flag set immediately after `InitializeComponent()` and guarded the affected handlers on it. Verified by navigating to all 40 tool routes with zero crashes.
- Fix a cluster of clipped/overflowing layouts introduced by the density pass:
  - **Converter queue** — the 7-column table forced a 720px min-width into a ~520px panel, clipping the Size/Status columns and crushing the filename. Rebuilt as a 6-column table (the estimated output is now stacked under Size), fitting the panel with readable headers and filenames.
  - **Downloader** — the Quality/Container combos and three option checkboxes shared one non-wrapping row that ran off the right edge (hiding "Skip sponsor segments"). Split into two rows and widened the Quality combo so "Highest available (video + audio)" fits.
  - **AI Lab tiles** — 148px tiles clipped the second description line with no ellipsis; raised to 168px so descriptions show in full.
  - **Home** — workflow cards were too short (148px) to render their descriptions at all; raised to 176px, and the AI-feature tiles now ellipsize overflow instead of hard-cutting.
- Fix clipped, unreadable Toolbox tiles. The "tighten workspace density" pass shrank tile height to 116px, but each tile renders a 40px icon block, title, two-line description, and a status row — needing ~170px. Title and description were squeezed to an unreadable sliver. Restored the tile to 216×172 (padding 14) so all tile content is fully visible.
- Fix a fatal launch crash: `MainWindow`, `SettingsWindow`, and `ProgressWindow` each carried an `x:Uid` on the `Window` root. A WinUI 3 `Window` is not a `FrameworkElement`, so `x:Uid`-driven resource application throws `XamlParseException` ("Failed to assign to property Window.Title") during `InitializeComponent`. `MainWindow` crashed the app on startup; the other two would crash when Settings or a progress window opened. Removed the `x:Uid`/literal `Title` from all three roots and set the (localized) title in code-behind, matching the existing pattern.
- Format and parse all external-tool numbers with `InvariantCulture`. On comma-decimal locales (de/fr, which ship as resources) converters emitted args like `-r 29,97` that FFmpeg rejects, and `double.Parse` of period-decimal tool output threw, breaking FFmpeg/Calibre/JXL progress and resvg SVG sizing. Covers FFmpeg, potrace, cjxl, resvg, Calibre.
- Do not fail an otherwise-successful conversion when Mark-of-the-Web can't be copied under the default Keep action (output on FAT32/exFAT/SMB or an over-cap zone). Surface it as a warning instead of a hard failure.
- Relocate LibreOffice output to the requested filename: `--convert-to` writes `<sourceStem>.<ext>` and ignored collision-avoidance suffixes and filename templates, so a successful conversion was reported as failed and left a mis-named file.
- Harden `SidecarHealthService` (a concurrently-used DI singleton) against manifest-cache corruption by switching to `ConcurrentDictionary`.
- `ReleaseCompatibilityPolicy.ParseManifest` no longer throws `NullReferenceException` on a remote manifest with `"product": null`; bad input returns null as documented.
- Harden `AutoHighlightWorkflowViewModel.ParseHighlight` against malformed sidecar JSON (wrong value kinds) so a bad event degrades to defaults instead of throwing in the event callback.
- Stamp only the schema version actually reached on a settings-migration gap, preventing a false "fully migrated" stamp from becoming permanent.

## [2.31.3] - 2026-07-17

### Changed

- Continued approved-mockup parity in the Converter workspace with real row and select-all checkboxes, persistent manual ordering, move-up/down actions, remove-selected confirmation, a compact bottom queue toolbar, and flat finished-result rows.
- Consolidated shortcuts and FFmpeg controls inside the existing output inspector, moved conversion feedback into a quiet bottom status line, and removed duplicate high-emphasis queue actions from the page footer.
- Reduced the permanent shell navigation to Converter, Downloader, Compressor, Editor, Universal Convert, DVD Rip, and Toolbox; specialized workflows remain discoverable through Toolbox and direct routes, while Settings and a functional About dialog anchor the footer.
- Extended the visual contract to lock the simplified shell, selectable queue, unified inspector, and functional batch-action wiring; all six localization catalogs remain synchronized.

## [2.31.2] - 2026-07-17

### Changed

- Brought the primary Converter workspace into closer parity with the approved desktop mockup: the shell now opens on Converter, core navigation is ordered around the main workflows, file intake uses one split action, and queued files sit in a flat, divider-led table instead of separate rounded cards.
- Replaced the stacked output and shortcut cards with one scrollable output inspector. Format, quality preset, resolution, frame rate, audio, destination, same-source, and open-after-conversion controls are grouped in conversion order; quality, video, and audio selections now feed real `ConversionOptions` and persist with an interrupted queue.
- Regenerated all six localization catalogs and added a source-level visual contract for the flatter queue, unified inspector, and functional output-profile wiring.

## [2.31.1] - 2026-07-17

### Changed

- Completed a second density pass across the WinUI workspace: 38 queue and drop surfaces no longer reserve oversized empty-state height, 46 large placeholder illustrations are compact, Converter leads with Format and Save controls, and Home, Toolbox, and Settings shed hidden dashboard scaffolding and redundant header copy. Visual contracts now enforce readable shared descriptions, compact empty states, and control-first ordering; concise copy remains localized across all six catalogs.

## [2.31.0] - 2026-07-17

### Changed

- Rebuilt the WinUI visual system across all 53 pages around a compact 28 px page-title scale, readable 15 px body copy, shorter descriptions, tighter section rhythm, and restrained blue/emerald accents. Removed explicit card outlines, tiny 9–11 px labels, decorative status pills, hero gradients, and glass-backed AI tiles in favor of tonal grouping and sparse structural separators.
- Reworked the application shell, Home, Converter, AI Lab, Toolbox, Settings, and progress surfaces to keep primary controls higher in the viewport. Converter now exposes its main action beside file intake, the shell uses the shipped UniversalConverter X mark, and high-traffic discovery tiles are denser with bounded descriptions.
- Synchronized the complete WinUI localization catalog after the page-wide copy and hierarchy pass; localized catalogs retain matching keys and placeholder contracts.

## [2.30.0] - 2026-07-17

### Added

- Replaced the legacy folder-and-wordmark artwork with a transparent, text-free UniversalConverter X mark built from interlocking blue/emerald conversion ribbons and a faceted format core. The same source now drives the executable ICO, README branding, and all generated MSIX tile, Store, and file-type icon sizes, with a silhouette verified from 16 through 310 pixels on light and dark surfaces.
- Disc Burner now authors a single video title as Blu-ray BDMV, creates a UDF 2.50 ISO, or writes the same image through the existing Windows IMAPI2 boundary. Managed FFmpeg normalizes the title to a conservative H.264 High@4.1 and AC-3 profile; the optional Apache-2.0 tsMuxeR 2.7.0 runtime comes only from a versioned release archive whose exact size and SHA-256 are verified after explicit license acceptance. UCX validates the index, movie object, playlist, clip-info, backup, and M2TS signatures before atomically preserving the inspectable BDMV folder, even when a later image/write step fails.
- Added local, non-destructive commercial detection through a frozen Comskip wrapper, shared preset, and Toolbox entry. It accepts an explicitly supplied Comskip executable, writes bounded JSON, EDL, and FFmetadata chapter reports atomically, leaves the source untouched, and can optionally export only the detected keep ranges through managed FFmpeg. UCX downloads no runtime at execution time; maintainers can instead prepare or build the GPL-2.0 backend from pinned source, FFmpeg, and argtable2 inputs whose sizes and SHA-256 hashes are verified before extraction.
- Added a SysAdminDoc-operated, versioned community preset catalog and machine-readable governance policy covering review, SPDX license provenance, immutable release publication, SHA-256 metadata, incident response, takedown/revocation, and a strict ban on mutable branch feeds and installed-preset auto-updates. The new offline `ucx community-presets` client lists entries, previews the exact validated engine and argument vector, rejects tampering/path traversal/revoked digests, and requires the displayed SHA-256 before an atomic install into the user's preset directory.
- Added a repeatable `win-arm64` cross-publish for the CLI, WinUI app, Explorer shell extension COM host, and FFmpeg command proxy. The publish gate reads PE headers to require ARM64 primary apphosts and emits an architecture inventory for installed sidecar executables, explicitly routing x64-only engines to Windows emulation or a native rebuild rather than claiming compatibility from filenames. `ucx tools qnn --json` now performs a local-only, fail-closed ARM64 Python/ONNX Runtime provider probe and succeeds only when `QNNExecutionProvider` is actually exposed; no runtime or model is installed or downloaded.
- Compressor can now run a guarded FFmpeg 8.1 D3D12VA zero-copy chain from hardware decode through optional `deinterlace_d3d12`, `scale_d3d12`, and H.264/H.265/AV1 hardware encode. A one-frame runtime probe verifies the exact input, filters, driver, and encoder before the real job; any failure automatically preserves the request through software BWDIF/scaling and the original software codec. The WinUI surface exposes D3D12 deinterlacing explicitly, and D3D12 quality targets use QVBR instead of unsupported CRF arguments.

## [2.29.0] - 2026-07-17

### Fixed

- Restored valid Python syntax in the FrameSnap, HEICShift, and LipSight legacy GUI sources after malformed icon-import injection, and added a repository-wide tracked-Python parser contract to prevent recurrence.
- Unsigned installer packaging now discovers either repository-local or globally installed WiX 4+ tools and references the current `UniversalConverterX.exe` publish outputs instead of obsolete `UniversalConverterX.UI.*` filenames.

### Security

- Dia2 and Chatterbox inference is process-offline and accepts only complete local model bundles from immutable Hugging Face revisions with exact byte counts and SHA-256 hashes. Model acquisition is explicit-consent only and stages every file before promotion. Dia2's vendored runtime disables remote tokenizer code and localizes Mimi loading; Chatterbox voice cloning requires an explicit consent flag and preserves the upstream PerTh watermark.
- Sidecar model and runtime acquisition now follows one repository-wide contract: network access requires explicit licence consent, immutable HTTPS metadata, exact byte-count and SHA-256 verification in private staging, and atomic promotion. Super-resolution, GFPGAN, and AlphaCut provide pinned download commands; Whisper.cpp and Real-ESRGAN packagers use the same consent and integrity gates. ML inference is process-offline, runtime pip installs and mutable Git clones are prohibited, Hugging Face loaders are local-only, and a contract test classifies every remaining direct network path so new implicit downloads fail CI.

### Changed

- Preset discovery now uses a shared dependency-free semantic ranker instead of requiring a Qdrant service or embedding model. Core builds bounded sparse TF-IDF vectors from preset names, categories, engines, formats, and extensions, expands media-domain aliases, prioritizes candidates that cover every query concept, and applies deterministic cosine ranking. The Presets UI returns its top 100 matches and `ucx convert-preset --list --search` exposes the top 50 through the same offline implementation.
- The searchable output library now builds on UCX's existing bounded SQLite History store instead of adding a Meilisearch server. Space-separated terms can match across engine, action, source/output paths, preset, error code, and error text; every term must match somewhere, `%`/`_` remain literal user input, Unicode paths are preserved, and filtered rows and summary metrics share the same query definition.
- The legacy Spleeter-specific proposal is superseded by the shipped Stem Separator workflow, which covers two-, four-, and six-stem separation through newer MelBand/BS-RoFormer, Demucs, MDX-Net, and VR Arch models without adding a second TensorFlow runtime. Its 262 MB frozen package now retains `audio-separator` metadata correctly and returns the curated offline model catalogue even when optional upstream catalogue data is not installed, rather than crashing or attempting an implicit download.
- Preset invocation modes now share one Core definition across the editor, WinUI executor, and Console runner. The previously exposed-but-downgraded `batch-input-list` mode now performs one input-only batch invocation without prompting for or inventing outputs; metadata presets use it, Opus presets use their required output-directory mode, and the ab-av1 search-only preset runs per file and atomically writes its promised recommendation report.
- NVDEC frame decoding now extends beyond Auto Highlight to LipSight speech segmentation and Vertigo smart tracking, with automatic OpenCV fallback and no duplicate frames if hardware decoding fails mid-stream. Pixel-producing ClipForge face blur and Colorize video workflows expose hardware decode only through an explicit `--hw-decode` opt-in. All four frozen engines pin and bundle PyAV 17, while a fully GPU-resident path remains deferred until a CuPy/Torch-class frame consumer exists.
- ClipForge's 2,322-line sidecar entrypoint is now split into focused metadata/filter, track, analysis/proxy, and face-privacy operation modules. The entrypoint retains its complete CLI and import surface while focusing on parser wiring and orchestration, PyInstaller includes and exercises the package, and the static NDJSON contract audit now follows extracted `*_ops` modules.
- Video Summarizer, Auto Highlight, Colorize, Background Remover, and Compressor now delegate their non-visual workflow state, sidecar argument construction, output planning, and error mapping to tested CommunityToolkit.Mvvm ViewModels in Core. The WinUI code-behind is limited to picker, dispatcher, and view-service work, with focused xUnit coverage for transcript/video branching, selected highlight serialization, model readiness, AlphaCut options, target-size headroom, and VMAF encoder presets.

### Added

- Added two isolated offline neural-speech engines and shared presets. Dia2 1B generates English `[S1]`/`[S2]` dialogue through a pinned PyTorch 2.8/CUDA 12.8 stack; its 107 KB Apache-2.0 runtime is vendored at an immutable revision because the upstream wheel omits subpackages, with narrow Windows cuDNN and local-only loader fixes. Chatterbox Turbo uses its separate pinned PyTorch 2.6/CUDA 12.4 stack to clone one explicitly consented local reference voice, emits the built-in PerTh watermark, and never sends audio or text off-device. The optional model sets are 4.69 GB and 2.99 GB; the corresponding 4.37 GiB and 4.00 GiB CUDA runtimes use fast-starting `onedir` packages and are not bundled in the default install.
- Added a reviewed local ComfyUI workflow bridge through a 9.4 MB standard-library frozen sidecar and shared preset. API-format graphs are submitted only to a validated HTTP loopback server after explicit acknowledgment; UCX refuses redirects, non-loopback hosts, embedded remote URLs/credential fields, and known network/cloud node classes, supports up to 100 existing-input JSON overrides, polls the exact prompt ID, and atomically exports bounded final artifacts plus a result manifest. It never installs ComfyUI, models, or custom nodes and does not support Comfy Cloud; separately managed custom nodes remain executable Python that users must review, and ComfyUI should be started with `--disable-api-nodes`.
- Added offline AI video metadata tagging through a 77.8 MB frozen `videotag` sidecar and a preset shared by the UI, CLI, REST, and PowerShell catalogues. It samples bounded local image/video frames, detects 80 COCO object classes with MediaPipe EfficientDet-Lite0 int8, and atomically writes per-frame scores/boxes plus aggregate first/last-seen tags without changing the source. UCX uses standalone LiteRT instead of the metrics-reporting MediaPipe Tasks SDK, disables process network access during inference, and downloads the immutable Apache-2.0 model only after explicit consent with exact 4,602,795-byte and SHA-256 verification.
- Added bundled-FFmpeg IAMF immersive-audio workflows. Ordinary stereo audio can become a 48 kHz Opus IAMF master; normal six-channel sources are split into the four-substream scalable stereo + 5.1 representation defined by FFmpeg's IAMF contract. Both stream groups can be stream-copied into MP4, while the base layer or UCX scalable profile can be rendered to verified 48 kHz stereo/5.1 WAV or FLAC. Every output is staged, probed for its promised groups/layers/channels, and atomically promoted.
- Added a read-only offline C2PA Content Credentials inspector using optional prebuilt `c2patool` 0.27+. Embedded manifests can be validated and exported as bounded JSON, info, tree, or certificate reports; local `.c2pa` sidecars can be supplied explicitly. UCX forces remote-manifest and OCSP fetching off, clears inherited trust-list locations, permits no network hosts, exposes no signing surface, and atomically promotes reports.
- Added a confined offline Pkl 0.32+ preset compiler. Local `.pkl` descriptions are evaluated with file modules rooted to the source directory, only Pkl's built-in output-format property permitted while file/environment/network resources are denied, projects/cache/user settings disabled, and strict time/source/output/diagnostic bounds. Only a versioned allowlisted schema can become namespaced UCX preset XML; duplicate JSON keys, unknown fields, traversal, unsafe identifiers, and invalid invocation modes are rejected before atomic output promotion. Pkl remains an optional external tool and UCX never downloads it.
- Added dependency-free Prometheus 0.0.4 metrics to the loopback `ucx serve` API. `/metrics` exposes build/start/uptime gauges plus cumulative per-engine started/completed counters and live running/retained gauges with LF termination, correct Prometheus 3 content type, deterministic ordering, and escaped untrusted labels. An optional local scrape configuration and importable five-panel Grafana dashboard are included; UCX installs no monitoring service and sends no telemetry.
- Added an explicit-trust VapourSynth scripting bridge for local `.vpy` workflows. VSPipe R76+ can inspect output metadata, export simple or full DOT filter graphs, and pipe selected frame ranges/output indexes to FFmpeg for H.264, HEVC, AV1, ProRes, or FFV1 rendering with optional source-audio remuxing. Script arguments are validated `key=value` entries, child processes never use a shell, diagnostics stay bounded, and graph/video outputs are atomically promoted. Because `.vpy` files are executable Python, every operation requires a reviewed local script and an explicit acknowledgment; UCX never downloads scripts or plugins.
- Added an offline Av1an bridge and SVT-AV1 preset for resumable per-scene parallel encoding. The wrapper follows Av1an 0.5.2's current CLI, supports automatic or fixed workers, reusable scene JSON, FFmpeg or plugin-backed chunking, encoder/audio parameter strings, and optional VMAF/SSIMULACRA2/Butteraugli/XPSNR target quality. Outputs are staged beside the destination and atomically promoted only after success; readiness reports Av1an, FFmpeg, VapourSynth/vspipe, and each supported external encoder without downloading any runtime.
- Added a safe offline Conditional Rules Engine for batch automation. Versioned JSON rules can match extension, size, duration, dimensions, video/audio codecs, channels, HDR, and subtitle presence, then select presets, skip files, add filename suffixes, tags, or notes. Evaluation writes an atomic, deterministic plan and is available through the shared CLI/REST/PowerShell engine surface; the schema rejects unknown conditions, duplicate names, path traversal, arbitrary command fields, oversized files, and more than 1,000 rules.
- Added Unified OCR Batch for mixed images and PDFs. The new offline `ocrkit` engine routes images to Tesseract and scanned PDFs to OCRmyPDF in one invocation, shares language settings, defaults PDF output to deskewed/auto-rotated PDF/A-2 with existing-text skipping, scales child progress into one NDJSON stream, and reports child readiness only when the frozen wrappers plus Tesseract and Ghostscript are all available. Existing Surya text/layout and bitmap-subtitle OCR remain separate specialist paths rather than being overstated as unimplemented table/math operations.
- Added an offline Spatial Audio engine and preset collection for first-order ACN/SN3D Ambisonics to binaural stereo, 5.1, or 7.1, plus stereo surround upmix. Surround-to-binaural rendering uses FFmpeg's SOFAlizer only when the user supplies a local SOFA HRTF file; UCX does not bundle or download impulse-response data. The engine validates channel layouts, preserves 48 kHz multichannel output, and exposes FFmpeg pan/surround/SOFA readiness through its probe contract.
- Added general-purpose automatic deinterlacing through ClipForge and a Video/Repair preset. The workflow inspects FFprobe field order, stream-copies already-progressive sources when the container is unchanged, and defaults interlaced material to BWDIF one-frame-per-field output so 25i becomes 50p and 29.97i becomes 59.94p; YADIF and single-rate output remain explicit alternatives. Audio, subtitles, data, chapters, and metadata are preserved without re-encoding.
- Track Manager now provides an independent -600000 to +600000 ms timestamp offset for every audio stream. Positive values delay a track and negative values advance it; removals and offsets are applied together in one FFmpeg stream-copy remux with chapters and metadata preserved, so synchronization fixes do not re-encode media. The sidecar validates stream types and bounds, exposes the same `track-edit --delays stream=milliseconds` operation to automation, and reports applied offsets in its completion event.
- Added the bundled FFmpeg 8.1 native `whisper` filter as a third offline transcription backend in Speech-to-Text and AI Subtitle. The 8.6 MB frozen wrapper reuses installed whisper.cpp GGUF models, probes filter availability, supports CPU/GPU selection and optional local VAD models, emits SRT/text/JSON, converts SRT cues to WebVTT locally, and never downloads a model. A matching preset exposes the backend to CLI, REST, and PowerShell automation through the shared engine catalogue.
- Video Timelines now has verified CMX 3600 EDL and FCPXML import paths. The preset-backed `vidpost` engine converts multi-event EDL files to structured CSV, probes FCPXML assets, formats, projects, sequences, and clips, and retains optional OpenTimelineIO conversion through `otioconvert`; focused fixtures and frozen-executable smokes protect both interchange formats.
- Added a native whisper.cpp speech-to-text path alongside faster-whisper. The frozen 9.9 MB NDJSON wrapper discovers local GGUF models and compiled Vulkan/CUDA/VAD capabilities, converts media to the required 16 kHz mono input through managed FFmpeg, and is selectable from both Speech-to-Text and AI Subtitle with a matching preset. The separately pinned upstream runtime remains an explicit-consent, SHA-256-verified install so the default package does not silently acquire models or binaries.
- Added one shared engine catalogue across WinUI, Console, the loopback REST API, and the PowerShell module. `ucx engines --json`, `GET /engines`, and `Get-UcxEngine` expose the same native converter plus all source and installed sidecars; `ucx invoke-engine`, the existing REST job endpoint, and `Invoke-UcxEngine` can execute any installed specialized engine. REST now routes the native `converter` engine through the canonical CLI, and repository contracts fail when a UI/preset engine falls outside the shared catalogue or an automation surface loses generic discovery/invocation.
- Added a local sidecar verification harness covering all 198 engines. It enforces one valid health manifest and PyInstaller entry point per sidecar, imports each source in an isolated process, checks responsive `--help` and statically discovered operation surfaces, offers an opt-in full freeze plus frozen-help mode, and runs a five-engine fast subset in the pytest contract suite. Missing build entry points for Disc Burner, SVT-AV1-HDR, and Vship Metrics are now supplied and verified through real frozen executables.
- Added pinned, opt-in ISO 21496-1 gain-map tooling. UltraHDR JPEGs can be round-tripped through libvips 8.18.2 without dropping gain-map metadata or converted to AVIF through a reproducible static libavif 1.4.2 build; SDR/HDR image pairs can also synthesize new AVIF gain maps. Downloads require explicit license acceptance and exact size/SHA-256 verification, outputs are re-inspected before atomic promotion, and a generated-fixture headless smoke covers the writer.
- Video Enhancer now offers Anime4K v4.0.1 as an optional local 2× GLSL backend alongside Real-ESRGAN. Modes A, B, and C run through mpv with isolated configuration, preserve audio, and expose CRF control; the pinned MIT shader pack requires explicit consent and SHA-256 verification. A matching preset, readiness status, focused archive/command tests, and a headless 640×360 to 1280×720 render proof are included.
- Navigation, AI Lab cards, and the Settings panel now use element-scoped Mica or Acrylic through Windows App SDK `SystemBackdropElement`. Each material is guarded by runtime API/controller capability checks and layered over the existing solid theme surface, so unsupported GPUs, remote sessions, elevated launches, and disabled transparency keep the previous legible appearance.
- Release packaging now produces a directly runnable unsigned portable ZIP, an explicitly unsigned MSIX, correctly sized generated package assets, and a post-package SHA-256 release inventory. The portable ZIP is exercised through its real `ucx.exe`, and versioned WinGet 1.12 manifests install its UI and CLI aliases without relying on a signing certificate.
- Added a **Disc Burner** page and `discburn` sidecar. Data CD/DVD images and physical writes use the inbox Windows IMAPI2 APIs with no third-party burner; DVD-Video mode transcodes one or more titles with managed FFmpeg, authors `VIDEO_TS` through optional `dvdauthor`, and creates or writes a UDF 1.02 image through the same IMAPI path. Source trees containing reparse points are rejected, ISO promotion is atomic, recorder/media support is checked before writes, and Blu-ray is intentionally excluded while its authoring backend remains unresolved.

## [2.28.0] - 2026-07-17

### Changed

- Long-form video analysis now decodes on the GPU's NVDEC engine when a CUDA device is present. A new shared `tools/_lib/hw_decode.py` helper decodes frames with PyAV v17 (`*_cuvid`), offloading the expensive decode from the CPU on HD/4K footage, and the Auto Highlight motion-energy pass is the first consumer. It degrades transparently to OpenCV software decode when PyAV or a CUDA device is absent, produces identical motion results either way, and honours a `UCX_HWDECODE=0` kill switch.

## [2.27.0] - 2026-07-17

### Added

- Shipped the **Video Summarizer** (previously a "Planned" placeholder): turn a long recording into a written summary, timestamped chapters, and an optional condensed highlight cut — all offline. A new `videosummary` sidecar transcribes audio/video with the existing Whisper engine, then runs a pure-standard-library **extractive TextRank** summarizer that needs no model download, no GPU, and no network. It picks the most central sentences (Brief / Standard / Detailed / Executive lengths), detects chapters and titles them from their top keywords, and can render a speech-driven highlight reel by concatenating the highest-ranked segments with FFmpeg. Output as plain text, Markdown, YouTube-style chapter descriptions (first chapter pinned to 00:00 with auto hashtags), or a bare chapters list; transcripts (SRT / VTT / JSON / TXT) can be summarized directly, and you can bring your own transcript alongside a video to cut a reel without re-transcribing. An optional local-LLM path via Ollama is used only when a server is reachable, otherwise it transparently falls back to the offline extractive engine.

## [2.26.0] - 2026-07-16

### Fixed

- Video background removal now honours the chosen output format. The Background Remover passed short format tags (webm / mp4 / mov / png_sequence) that the AlphaCut sidecar validated against display-name keys, so every export silently fell back to the first format and failed; the sidecar now maps those tags to AlphaCut's real format codes and validates against them. PNG-sequence output (a directory of frames) is also no longer misreported as a missing file. WebM/VP9 transparency, ProRes-alpha MOV, MP4, and PNG sequences now all export correctly.

### Added

- Added an offline **Colorize** tool that adds colour to black-and-white photos and video entirely on the CPU (no GPU or PyTorch), backed by a new `colorize` sidecar using OpenCV's DNN colourisation model. The ~123 MB BSD-2-Clause model is downloaded once behind an explicit licence-consent dialog and SHA-256 verified; colourisation itself never downloads. Images preview instantly; video is colourised frame-by-frame and remuxed with its original audio in a single lossless-intermediate h264 encode. Reachable from search and the AI tool set.

## [2.25.0] - 2026-07-16

### Added

- VMAF Quality Analysis can now run a fast proxy pass: a new clipforge `proxy` op generates a 480p preview proxy of both the reference and distorted clips, and a "Fast proxy pass" toggle scores those proxies for a quick approximate VMAF before committing to a full-resolution run.
- Subtitle Converter now handles broadcast closed captions via a new `ccextract` FFmpeg sidecar: it decodes Scenarist SCC to SRT/VTT/ASS, extracts an embedded caption track from a video file (MP4/MKV/MOV/TS and more), and falls back to CEA/EIA-608 carried in the video bitstream when no container track is present. The page accepts video and SCC inputs alongside the existing subtitle formats and routes each source to the right engine.

## [2.24.0] - 2026-07-16

### Added

- Added a dedicated **Lossless Cut** page: a keyframe-accurate visual trimmer that stream-copies a clip with no re-encode. It loads a thumbnail-strip timeline (clipforge `timeline`) and the video keyframe list (new clipforge `keyframes` op), lets you scrub, set In/Out points that snap to the nearest keyframe in lossless mode, and export the cut. A re-encode toggle is available for frame-exact cuts. Reachable from the navigation pane and search.
- Added a **DVD Rip** page and `dvdrip` sidecar for unprotected VIDEO_TS discs. It scans a VIDEO_TS folder (or a mounted ISO / disc drive), lists the ripable titles with duration and part counts, and rips a chosen title to H.264/H.265 MP4 or a stream-copy MKV. Commercial CSS-encrypted discs are never decrypted, and the UI documents the non-commercial scope.
- Opus encoding can now target higher-order ambisonics. The Audio Converter's Opus panel gains a channel-layout selector (Standard or ACN/SN3D ambisonics), and the audiopro sidecar maps it to libopus mapping family 2, validating that the source has a full-sphere channel count (4, 9, 16, and so on) before encoding.

## [2.23.0] - 2026-07-16

### Security

- FFmpeg now ships from a pinned BtbN 8.1.2 build instead of a mutable latest channel. Windows and Linux downloads have platform-specific SHA-256 pins, the installer stages verified FFmpeg/FFprobe/FFplay binaries, BtbN version banners are parsed against the 8.1.2 floor, and every sidecar that can fail on missing FFmpeg now declares the managed dependency.
- Whisper STT and HEICShift sidecars no longer invoke pip or escalate package installation at conversion time. Missing dependencies now fail closed with actionable managed-environment guidance, while packaged builds require dependencies to be bundled during the trusted build step.
- DPAPI protection now uses current-user scope plus application-specific entropy and reports failures instead of returning or storing plaintext. StreamKeep cookies, account credentials, and config secrets share a versioned DPAPI2 format, retain legacy read compatibility, migrate cookie stores safely, and preserve existing data when protection fails.
- Successful conversions now preserve a source file's Windows Mark-of-the-Web on derived outputs, including the default keep-source flow. Archive extraction now runs in a private staging tree, rejects links and reparse points, applies the archive's Zone.Identifier to every regular extracted file, and promotes files only after 7-Zip succeeds.
- ImageMagick conversions now force a shipped policy that blocks MVG, MSL, internal MSVG, and remote URL coders while bounding CPU, memory, disk, dimensions, and sequence length. Calibre sidecar jobs now use isolated config/cache/temp roots with custom plugins and Python templates disabled, stage copied inputs and outputs in a private job directory, and atomically promote only non-empty regular outputs.
- Raised all Pillow sidecar floors to 12.3.0 and yt-dlp to 2026.07.04, with the sidecar contract gate enforcing both floors.
- Added shared minimum-version policy checks for FFmpeg 8.1.2, ImageMagick 7.1.2-15, Calibre 9.10, 7-Zip 26.01, and LibreOffice 26.2.4. The CLI, Settings tool inventory, and preset health surface now warn when an installed parser is outdated or cannot be verified.
- Audited ONNX Runtime 1.27 across every direct consumer: the CPU-only RapidOCR path advances to 1.27, CUDA-capable AlphaCut, StemKit, and TranslateKit remain on the validated 1.26/CUDA 12 line, and preset health warns before an unvalidated CUDA 13 migration.
- Installer publishing now refuses to build on .NET runtimes older than 10.0.9 and resolves the latest installed servicing patch.

### Added

- Audio Converter and Speech-to-Text now show a live waveform preview of the most recently added file. A new `mediathumb waveform` operation renders the trace offline through FFmpeg's `showwavespic` filter (trace colour is sanitised to a hex value before it reaches the filter graph), and the preview degrades silently to a hidden card when FFmpeg or the sidecar is unavailable.
- The full WinUI shell is now localizable. Every page's user-visible strings carry `x:Uid` keys backed by compiled `Resources.resw` catalogs for English, German, French, Spanish, Polish, and Simplified Chinese, and Core conversion messages resolve through a host-provided resolver with English fallbacks. A Settings language selector overrides the Windows UI language per user, and `tools/localization/` ships the extraction and machine-translation tooling plus a contract test that keeps every locale key-complete.
- Chapter Editor now imports and exports exact chapter JSON, Matroska XML, and simple chapter text; preserves untouched integer PTS/time bases; supports delete-all; and verifies every title and timestamp before atomically promoting a stream-copy remux. MKV writes require and enforce MKVToolNix 97+ (including TrueHD-in-MP4 input support), while MP4/MOV use FFmpeg without replacing global metadata.
- Added a fully local Auto Highlight workflow that combines PySceneDetect transition strength with sampled motion energy, lets users review and exclude ranked clip windows, renders an audio-preserving H.264 reel, and exports frame-accurate CMX 3600 EDL or OpenTimelineIO timelines. PySceneDetect is pinned to 0.6.7.1 and a ready-to-run five-clip preset is included.
- Video Enhancer now offers SeedVR2 3B FP8 as an opt-in CUDA restoration engine with 540p, 720p, and 1080p targets. The approximately 3.9 GB Apache-2.0 model/runtime pack requires explicit consent, immutable revision and SHA-256 verification, and at least 10 GB VRAM; inference is forced offline and uses streaming, BlockSwap, CPU offload, and tiled VAE processing. A matching 720p preset and clean missing-model/no-CUDA errors are included.
- Added default-deny third-party sidecar plugins under the local app-data plugin directory. Manifests and preset paths are validated, links/reparse points are rejected, every plugin file is covered by one SHA-256 approval, changed plugins are re-quarantined before launch, and Settings can trust or revoke plugins that then surface in Presets and Toolbox.
- Video Enhancer now reports the local Windows App SDK 2.2 VideoScaler readiness state without downloading AI components, keeps Real-ESRGAN as the portable export backend, and includes a headless frame benchmark smoke that runs only on supported hardware.
- Speech-to-Text now offers NVIDIA Parakeet TDT 0.6B v3 as a CUDA-only engine for 25 European languages, with word-timestamp subtitle generation and SRT/VTT/TXT/JSON parity. Its pinned CC-BY-4.0 model snapshot requires an explicit in-app license confirmation and download; transcription is offline-only and cleanly blocks when the exact model pack or CUDA runtime is absent.
- Sidecars now share one dependency-free protocol/runtime module for NDJSON events, managed FFmpeg and FFprobe discovery, media probing, bounded FFmpeg diagnostics, and normalized progress. All standard sidecars and frozen PyInstaller builds consume the common module, with contract tests preventing helper drift.
- Vocal Remover and StemKit now default vocal work to MelBand-RoFormer and six-stem work to the supported BS-RoFormer SW model, with legacy Viperx, Demucs, and MDX choices retained. A new BS-RoFormer six-stem preset accompanies the refreshed model catalog, while four-stem selections continue to use fine-tuned Demucs.
- Converter now presents queued files as a sortable preflight table with cached asynchronous 48 px thumbnails, current and estimated output sizes, and per-file warning badges. Missing sources, empty files, and unsupported routes block conversion before work starts; restored queues receive the same estimates and review checks.
- Added an offline face-blur privacy filter to ClipForge and Toolbox. OpenCV scans every frame, expands and strongly blurs/pixelates each detected face, preserves source audio through FFmpeg, and refuses to write a privacy-labelled output when no face is detected.
- Image Converter now applies batch-safe brightness, contrast, saturation, sharpness, blur, hue, grayscale, sepia, invert, vignette, grain, tint, and border edits, plus vivid/muted/B&amp;W/vintage/cold/warm looks. Compatible PNG, WebP, and TIFF outputs preserve alpha, and WebP/TIFF edits process every input frame.
- Image Converter can now binary-search lossy quality for a target file size, while HEICShift also exposes PSNR and local Vship SSIMULACRA2 score targets. Results report the chosen quality and warn when a requested target is outside the encoder's achievable range; a 500 KB web JPEG preset is included.
- Converter, Compressor, and Downloader queues now share configurable completion actions: notification, sleep, delayed shutdown, or a hidden PowerShell hook. Power actions are refused unless every item succeeds; scripts run for any outcome and receive an atomic per-item JSON summary path.
- Converter now records every per-file result in History with a versioned, validated re-run payload. Re-run restores the source, output format/location, conversion options, post-source action, forced engine, and advanced FFmpeg template; SQLite upgrades existing history databases in place and legacy rows receive a safe best-effort prefill.
- Conversion batches can now emit structured JSON or RFC 4180 CSV reports with per-file status, source/output sizes, byte delta, duration, engine, profile, warnings, and errors. `ucx convert --report` writes live results, while the History page exports its current filtered view through the same Core report writer.
- Editor and ClipForge now support lossless display-crop metadata for H.264/H.265 and container-only display aspect overrides. Crop metadata rewrites only SPS display edges while preserving coded picture samples; aspect overrides stream-copy compressed packets unchanged. A 16:9 lossless metadata preset is included.
- Added curated Preservation and Production video families: lossless FFV1+FLAC/MKV archival, ProRes 422/MOV, and DNxHR HQ/MOV. The Presets page now has dedicated Preservation and Production filters, and the lossless VideoCrush path is covered by decoded-frame and PCM verification.
- Added APV camera-master support backed by the bundled FFmpeg 8.1.2 codec: Format Inspector recognizes RFC 9924 raw bitstreams, and presets convert APV to H.265 10-bit, ProRes 422 HQ, or compatible H.264. Raw streams without container duration now run with indeterminate progress instead of failing, and professional/lossless VideoCrush presets correctly bypass lossy CRF validation.
- Subtitle Studio now runs a complete local Whisper-to-caption workflow with optional Helsinki OPUS-MT translation through ONNX Runtime, editable text and cue timing preview, SRT/VTT/ASS export, and post-preview video burn-in. The AI Lab and Home tiles now open the ready workflow.
- Converter now exposes batch-safe FFmpeg command templates with required `{input}` and `{output}` placeholders. An off-by-default Advanced setting enables shell-free argument editing for direct conversions and exact per-invocation command review for FFmpeg calls made inside sidecars; edited vectors reject shell metacharacters before dispatch.
- Audio Converter is now a complete batch workflow in Toolbox with MP3, AAC, FDK-AAC, Opus, Ogg Vorbis, FLAC, WAV, ALAC, WavPack, AC-3, E-AC-3, and WMA targets. Codec-aware VBR quality (0–9), fixed bitrate, sample-rate/channel overrides, Opus application/frame controls, FDK-AAC cutoff/afterburner/profile controls, and Vorbis managed mode are wired to AudioPro; existing outputs receive unique names instead of being overwritten.
- Conversion history persistence now lives in a headless Core store with CI coverage for CRUD, search, summaries, row/age retention, and concurrent writers. Explorer preset launches now use a tested argument-vector builder with safe quote/Unicode handling and automatic list-file fallback, and the test suite executes a real preset through its sidecar.
- Every one of the 190 sidecars now carries a schema-validated `ucx.sidecar.json` health manifest. Model, GPU, external-tool, managed-tool, optional-tool, and argument-conditional requirements are resolved from manifest data; CI rejects missing or mismatched manifests and prevents reintroduction of hard-coded engine fallback tables.
- Application update checks now consume each release's preset/queue compatibility contract, compare it with user-defined preset schemas, saved queue schemas, and referenced engines, and show actionable pre-update warnings on Home and in Settings. Legacy saved queues default safely to schema v1, while incompatible or unverifiable release metadata fails visibly instead of implying compatibility.
- Release packaging now publishes a versioned JSON manifest after packaging with SHA-256 and size metadata for each MSI/MSIX artifact plus a non-executing inventory of bundled tools and sidecars. Requested package types must exist and be non-empty before the manifest can be emitted.
- Presets now have a full custom editor for creating, editing, and duplicating workflows without hand-editing XML. The editor covers input matching, output templates, invocation modes, sidecar arguments, and optional extra-input prompts; built-ins remain read-only while custom presets are schema-validated, atomically saved under the user profile, and available after restart.
- Compressor smart-quality mode now targets a user-selected VMAF score with AV1, H.265, or H.264 through ab-av1. It preflights the wrapper, upstream binary, and FFmpeg; performs sampled CRF search plus encoding; runs a full-reference VMAF verification; and reports the achieved score and selected CRF with each result.
- Compressor now offers cap-safe Discord 10/25/50 MB and Email 25 MB profiles plus a custom maximum-size mode. Size-targeted jobs reserve 5% container overhead and use deterministic CPU two-pass encoding; matching presets are available outside the Compressor page.
- Added managed, SHA-256-verified yt-dlp and Deno release channels with exact platform asset selection, staged version validation, atomic promotion, and rollback backups. Downloader health now explains missing or outdated runtimes and can install both; StreamKeep prefers the managed yt-dlp binary, reports active Deno/EJS status on probes, and ignores external yt-dlp configuration.

### Fixed

- The WinUI service container now loads the persisted `ConverterXOptions` instance at startup, so saved general, queue-action, tool, quality, and advanced settings survive application restarts instead of silently reverting in memory.
- ClipForge now drains FFmpeg diagnostics and progress from one combined pipe with a bounded error tail, preventing long FFmpeg banners or error output from deadlocking any editor operation.
- Added a platform regression gate that requires the WinUI project to remain on Microsoft Windows App SDK 2.x or newer with the supported Windows target and self-contained runtime configuration.
- Sidecar processes now force UTF-8 at the Python producer boundary, preventing Unicode file paths from failing when NDJSON output is redirected on legacy Windows code pages.
- StreamKeep download completion now trusts yt-dlp's reported regular file or selects only files created or modified by the current run. The fallback ignores directories, symlinks, unchanged downloads, partial artifacts, and ranks subtitle/metadata companions behind primary media instead of returning an unrelated path.
- Converter cancellation now records queued, in-flight, and orchestrator-returned cancellations separately from failures, persists each cancelled job as retryable, and always renders the cancelled batch summary even when no cancellation exception escapes the parallel task set.
- Update checks now compare normalized dotted numeric versions instead of string inequality. Prefixes, tool output labels, missing components, prereleases, date-style versions, and newer nightly builds are ordered correctly; rolling tags such as `latest` or autobuild dates are treated as non-comparable instead of producing false update prompts.
- Watch folders now wait for two identical size/timestamp observations plus an exclusive-open probe, react to create/change/rename arrivals, suppress concurrent and unchanged duplicate notifications with bounded caches, and exclude their own planned outputs to prevent recursive conversion loops. The page now surfaces active, settling/running, and remembered-file counts.
- Resolved the ab-av1 wrapper/upstream executable name collision across WinUI, CLI preset, and local API sidecar discovery; frozen wrappers now consistently use `ab-av1-sidecar.exe` while launching upstream `ab-av1.exe`.
- VideoCrush NDJSON is now safe on legacy Windows console code pages, and FFmpeg output is consumed without a redirected-stderr deadlock during long two-pass encodes.
- The canonical build script now uses the .NET 10 SDK for full x64 WinUI solution builds and publishing instead of an older Visual Studio MSBuild that could not resolve SDK-style projects. Repaired ten malformed Explorer `/select` invocations that blocked C# compilation and removed the remaining build warning.

## [2.22.1] - 2026-07-01

### Security

- DPAPI scope narrowed from `LocalMachine` to `CurrentUser` so other accounts on the same machine cannot decrypt stored credentials.
- ToolDownloader: enforced HTTPS-only downloads; relaxed RequireChecksum default (was true but no checksums configured, blocking all downloads).
- Clipforge subtitle burn-in: sanitize font names and validate hex color args to prevent FFmpeg filter-graph injection. Also escape `[`, `]`, `;` in path arguments.
- HttpClient UserAgent set once in constructor to prevent thread-unsafe mutation of DefaultRequestHeaders.

### Fixed

- **P1**: ConverterPage finally block now dispatches UI property access to the dispatcher thread, preventing COM exception crash when conversion completes on a thread-pool thread.
- **P2**: OpenContainingFolder now quotes folder paths in explorer.exe /select invocation across 21 pages so paths with spaces open correctly.
- **P2**: PersistQueue removed from per-progress-tick callback — was causing disk thrashing with dozens of JSON writes per second during conversion.
- **P2**: WatchFolderService _watchers and _profileCts switched from Dictionary to ConcurrentDictionary to prevent data race between FSW callback and UI threads.
- **P2**: PostConversionHandler refuses to delete/move source when output file is zero bytes (prevents data loss on corrupt conversions).
- **P2**: Clipforge op_speed and op_reverse now probe input streams and build filters conditionally for video-only, audio-only, or A+V inputs instead of crashing.
- **P2**: Videocrush two-pass log prefix now includes PID + stem to prevent concurrent job corruption.
- **P2**: Stabilize .trf file now written to output directory instead of next to source (which fails on read-only input paths).

## [2.22.0] - 2026-07-01

### Security

- Normalized sidecar dependency security floors: Pillow>=12.2.0 across 19 sidecars (GHSA-pwv6-vv43-88gr), onnxruntime>=1.25.1 in stemkit (15+ ORT CVEs), opencv-python>=4.10.0 in videosubtitleremover. Added automated security-floor enforcement to the sidecar contract test.

### Added

- Extended UIA gate with icon-only button accessible-name semantic check to prevent screen-reader regressions.
- Created `ucx.sidecar.json` manifests for 50 sidecars declaring tool, model, and GPU requirements. SidecarHealthService now reads manifests with hard-coded fallback.
- Added orjson fast-path to all 188 sidecar emit functions for ~3-5x NDJSON serialization speedup when orjson is installed.
- Wired OutputSizeEstimator into ConverterPage queue — queued files now show estimated output size with tooltip caveat.
- Added lock toggles for crop and quality values in EditorPage that persist across operation/preset switches.
- Added VOBSUB/PGS OCR subtitle extraction presets for the existing subocr sidecar.
- Added shared Pydantic validation layer (`tools/_lib/ucx_validate.py`) for structured input validation in sidecars.

### Changed

- Normalized ROADMAP.md from ~2600 lines to ~300 lines of actionable open work. Moved 4 blocked items to Roadmap_Blocked.md.
- Updated README project planning links to reference active planning surfaces only.

## [2.21.9] - 2026-06-28

### Fixed - Native Output Validation

- Native converter wrappers now fail successful process exits when the expected output file is missing or zero bytes.
- Added an explicit converter opt-out for intentional stdout/no-file outputs and preserved command/output metadata on validation failures.
- Moved process-exit success apart from final artifact validation so multi-stage converters can validate intermediate and final outputs correctly.

### Fixed - Package Graph and Version Truth

- Repaired solution restore after the test project pinned lower `Microsoft.Extensions.*` versions than Core.
- Moved active app/version metadata back to root `Directory.Build.props` and made `src/Directory.Build.props` import it instead of duplicating release values.
- Synced installer manifests, UI version labels, and CLI assembly version output to `2.21.9`.
- Updated compatible NuGet pins, documented intentional test-package holds, and adapted CLI command overrides to the current Spectre.Console.Cli API.
- Added a version consistency test that fails when active release surfaces drift.

### Added — Post-Conversion Source File Management (ROADMAP Item 59)

- New `PostConversionAction` enum (Keep/Move/Delete) replaces the limited `DeleteSourceOnSuccess` bool
- `PostConversionHandler` utility with output-file verification, in-place conversion safety, and archive folder collision resolution
- Core conversion orchestration now applies Keep/Move/Delete only after successful output creation, so CLI, UI, and batch conversion share the same guardrails
- `ucx convert` now supports `--source-action keep|move|delete` plus `--source-archive <PATH>` for archive moves
- Settings now exposes explicit source-file action choices and an archive-folder picker instead of the deprecated delete toggle
- Settings schema v3 migration: `DeleteSourceOnSuccess=true` automatically upgrades to `PostConversionAction=Delete`
- Relative archive folder paths resolve from the source file's parent directory
- 15 new unit tests covering keep/move/delete actions, safety guards, and edge cases
- 4 new migration tests for v2→v3 schema upgrade

## [2.21.0] - 2026-05-03

### Added — Parallel Job Limit Enforcement with SemaphoreSlim (ROADMAP Item 99)

- Refactored `ConverterPage.xaml.cs` ConvertButton_Click to use Task.WhenAll with semaphore gating
- Read MaxParallelConversions from ConverterXOptions (default: CPU count / 2, range 1–16)
- Wrap job execution in SemaphoreSlim to prevent exceeding configured limit
- Use Interlocked counters to safely track completed/failed jobs across parallel tasks
- Dispatch all UI updates via DispatcherQueue to prevent cross-thread issues
- Graceful cancellation support with CancellationToken propagation
- Enables true parallel conversion (up to N jobs simultaneously) instead of sequential processing

### Added — DPAPI Cookie Encryption Infrastructure (ROADMAP Item 100)

- New `Core/Security/DpapiProvider.cs` — cross-platform encryption/decryption wrapper
- Encrypt() and Decrypt() methods for sensitive configuration at rest
- Windows-only DPAPI (DataProtectionScope.LocalMachine); graceful no-op on macOS/Linux
- Used by future config encryption for credentials, tokens, webhooks
- Complements existing streamkeep sidecar DPAPI cookie encryption (streamkeep/dpapi.py)
- IsAvailable() check for platform detection

### Added — Premium UI Polish Pass (23/45 XAML Pages)

- Refined visual hierarchy: spacing (14→16px), typography (explicit line-heights), component consistency
- Applied EyebrowTextStyle header pattern consistently across all refined pages
- Improved empty states: icon size (80→88–120px), supporting text hierarchy
- Standardized button padding (20,10), GhostButton color (gray→blue), spacing rhythm (8/12/16/20/32px)
- Established consistent RowSpacing (4–12px depending on density) and ColumnSpacing (16px)
- Typography: explicit line-height (16–18px) for description text, monospace font stack for logs
- Pages refined: HomePage, ToolboxPage, AiLabPage, PresetsPage, ConverterPage, HistoryPage, WatchFoldersPage, ImageConverterPage, DocumentConverterPage, EbookConverterPage, SubtitleConverterPage, FontConverterPage, VideoEnhancerPage, SpeechToTextPage, OcrPage, ImageEnhancerPage, TextToSpeechPage, NoiseRemoverPage, AudioCompressorPage (+ 4 from prior sessions)

### Build Status

- Release build: 0 errors, 2 warnings (existing).
- All version strings synced (Directory.Build.props, ROADMAP, CHANGELOG).

## [Unreleased]

### Changed - platform and NuGet package refresh

- Updated Windows App SDK to 2.2.0, Microsoft.Windows.SDK.BuildTools to 10.0.28000.2270, Microsoft.Extensions packages to 10.0.9, Microsoft.Data.Sqlite.Core to 10.0.9, SQLitePCLRaw.provider.winsqlite3 to 3.0.3, CommunityToolkit.Mvvm to 8.4.2, Spectre.Console to 0.57.1, Spectre.Console.Cli to 0.55.0, Microsoft.Windows.CsWin32 to 0.3.298, System.Drawing.Common to 10.0.9, and test tooling to current stable releases.
- Adapted Spectre.Console.Cli command overrides to the newer cancellation-token API and preserved CLI cancellation propagation.
- Kept FluentAssertions at 6.12.0 because v8+ changed licensing terms and needs an explicit project license decision before adoption.
- Synced project version strings to `2.21.8`.

### Added - sidecar capability preflight and health panel

- Added a shared sidecar health service that evaluates preset engines for missing frozen sidecars, known external CLIs, model-cache warnings, and GPU runtime warnings.
- Presets page now shows a health panel, marks each preset card with readiness, disables blocked Run buttons, and re-checks dependencies immediately before launch.
- User-initiated diagnostics bundles now include `sidecar-health.json` with the same engine health table.
- Synced project version strings to `2.21.7`.

### Added - converter batch queue persistence

- Added a reusable JSON batch queue store for incomplete work with corrupt-file preservation.
- Converter page now restores queued, failed, cancelled, and interrupted jobs after restart with original input, output path, target format, and retry arguments.
- Successful conversions are removed from persisted queue state so completed jobs are not duplicated on restart.
- Synced project version strings to `2.21.6`.

### Changed - shipped workflow discoverability

- Promoted shipped preset-backed Toolbox workflows from Future/Planned to Ready and routed them to runnable preset filters: metadata editing, auto-crop, intro/outro, lens correction, VR conversion, and subtitle removal.
- Corrected existing Ready tiles for screen recording and stream downloading so they open the live Recorder/Downloader pages instead of nonexistent preset engines.
- Added regression coverage that fails if a Future/Planned tile points at an existing preset engine or if a Ready preset tile points at a missing engine.
- Synced project version strings to `2.21.5`.

### Security - verified tool updater

- Enabled Settings/CLI tool downloads through the real `ToolDownloader` path instead of the previous unavailable/manual-only flow.
- Require SHA-256 verification from configured hashes or GitHub release asset digests before installing downloaded tool archives.
- Install downloads through a staging directory, retain replaced binaries under `tools/rollback/<tool>/`, and restore previous binaries automatically if promotion fails.
- Synced project version strings to `2.21.4`.

### Security - SQLite bundled library advisory

- Replaced the WinUI app's `Microsoft.Data.Sqlite` package path with `Microsoft.Data.Sqlite.Core` plus `SQLitePCLRaw.provider.winsqlite3`, removing the vulnerable transitive `SQLitePCLRaw.lib.e_sqlite3` 2.1.11 package.
- Initialized the Windows `winsqlite3` provider before history database connections are opened.
- Synced project version strings to `2.21.3`.

### Added - AI video denoise/enhance presets (ROADMAP Item 16)

- Added `tools/video-face-enhance/`, a stdlib FFmpeg sidecar that extracts video frames, delegates frame batches to the existing `facerestore` CodeFormer/GFPGAN sidecar, and re-encodes the restored frames with source audio passthrough.
- Added AI/Video presets for Real-ESRGAN video cleanup, anime-focused sharpening, and CodeFormer video face enhancement.
- Fixed existing Real-ESRGAN/GFPGAN per-file presets whose sidecars require single `--input`/`--output` arguments.
- Marked Video Enhancer and Image Enhancer as Ready on AI Lab/Home surfaces and exposed the new video enhancement presets through search and Toolbox.
- Synced project version strings to `2.21.2`.

### Added - Slideshow Maker workflow (ROADMAP Item 15)

- Added `tools/slideshow/` as a stdlib-only FFmpeg sidecar for image-folder-to-video rendering with Ken Burns motion, fade/wipe/zoom/cut transitions, overlay text, optional background music, MP4/MOV/WebM output, and `presets` discovery.
- Added `SlideshowPage.xaml` with drag/drop image intake, folder import, output folder selection, duration/fps/resolution/fit controls, transition and motion controls, optional music picker, progress overlay, cancellation, and output-folder access.
- Wired the Slideshow Maker Toolbox tile and global navigation route as Ready.
- Synced project version strings to `2.21.1`.

### Changed - faster-whisper UI wiring (ROADMAP Item 61 closeout)

- Speech-to-Text and Auto Subtitle now expose faster-whisper batch size and pass `--batch-size` to `whisper-stt`.
- VAD is no longer labeled or routed as whisper.cpp-only; both STT surfaces pass `--vad` when enabled.
- Auto Subtitle gained the `large-v3-turbo` and `distil-large-v3` model choices already supported by the sidecar.

### Added - Voice Changer workflow (ROADMAP Item 1)

- Replaced the disabled Voice Changer placeholder with a sidecar-backed WinUI workflow: drag/drop queue, folder intake, output folder selection, progress overlay, cancellation, five voice styles, pitch shift, timbre intensity, audio export, and video remux mode.
- Added `tools/voice-changer/` as a stdlib-only FFmpeg sidecar with `transform` and `presets` ops, PyInstaller build script, NDJSON progress/log/complete/error events, and local smoke coverage for audio plus video remux.
- Flipped the Voice Changer tiles in Toolbox and AI Lab from Future to Ready.

### Changed - UIA AutomationId baseline drained (ROADMAP Item 10-b)

- Added stable `AutomationProperties.AutomationId` values to every currently scanned interactive WinUI control across 45 XAML files.
- Tightened the UIA scanner so XAML property elements such as `AutoSuggestBox.ItemTemplate` are not treated as controls.
- Regenerated `tests/uia_contract/baseline.txt` to an empty allowlist; future missing IDs fail the gate immediately.

### Changed — planning consolidation

- Consolidated project planning docs into root `ROADMAP.md`, `COMPLETED.md`, and `RESEARCH_REPORT.md`.
- Archived phase-3 and iter-8 root planning artifacts under `docs/archive/`.

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

### Added — Anime upscale sidecar (Real-ESRGAN ncnn-vulkan) (ROADMAP Item 95 partial)

- New `tools/anime-upscale/` sidecar wraps the Real-ESRGAN
  ncnn-vulkan binary with `image` / `video` / `models` / `probe` ops.
  Defaults to `realesr-animevideov3` for video and
  `realesrgan-x4plus-anime` for stills.
- `video` op extracts frames via FFmpeg, batch-upscales with
  Real-ESRGAN, then re-muxes with the source audio at the original
  framerate (CRF + codec configurable).
- Vulkan-based — runs on Intel Arc / AMD / Nvidia / iGPU without
  CUDA. Binary not bundled (download from upstream); sidecar
  discovers it next to itself or under tools/_bin/.
- Two presets ship: `anime-upscale-still-4x` (4x stills) and
  `anime-upscale-video-2x` (2x video). Anime4K GLSL backend deferred.
- Sidecar count: 181 (was 180).

### Added — Metadata Editor (EXIF / XMP / IPTC) sidecar (ROADMAP Item 12)

- New `tools/exiftool-meta/` sidecar wraps Phil Harvey's exiftool CLI
  with five NDJSON ops: `read` (full tag dictionary as JSON), `write`
  (repeatable `--set TAG=value` with optional group prefix), `clear`
  (all metadata or a specific group), `template` (apply a JSON
  metadata template across a folder for batch-stamping), and
  `rotate-orient` (rewrite EXIF Orientation 1..8 without re-encoding
  pixels). `probe` op reports availability + version.
- exiftool binary not bundled (Windows portable build from
  exiftool.org); sidecar discovers it next to itself, under
  tools/_bin/, on PATH, or via `EXIFTOOL_PATH`.
- Three presets ship: `exif-read` (JSON dump for any image / video /
  RAW), `exif-clear-all` (privacy scrub), `exif-strip-gps`
  (location-only strip).
- New `metadata_record` event registered in `KNOWN_EVENTS`.
- Sidecar count: 180 (was 179).

### Added — Audio encoder advanced parameters (ROADMAP Item 58 partial)

- `audiopro convert` exposes five new encoder-specific flags (silently
  ignored on non-matching codecs so a single "Advanced audio" preset
  ships across formats):
  - `--fdk-cutoff <Hz>` (libfdk_aac low-pass cap),
  - `--fdk-afterburner true|false` (libfdk_aac quality knob),
  - `--fdk-profile {aac_low|aac_he|aac_he_v2|aac_ld|aac_eld}`
    (profile selector for LC / HE-AAC v1+v2 / LD / ELD),
  - `--vorbis-managed` (libvorbis ABR-bounded managed bitrate; sets
    minrate/maxrate to bracket --bitrate).
- The libopus application + frame-duration controls already shipped
  under Item 90 also belong to this umbrella.
- "Advanced audio…" expansion panel in AudioConverterPage deferred
  until Item 2's broader page lands.

### Added — ab-av1 VMAF / XPSNR-guided CRF auto-search (ROADMAP Item 67)

- New `tools/ab-av1/` sidecar wraps the upstream ab-av1 Rust binary
  with four NDJSON ops:
  - `auto-encode` — search + produce the final encode at the smallest
    CRF that hits the target VMAF.
  - `crf-search` — search-only mode; emit the recommended CRF without
    encoding (useful for capturing into a preset).
  - `sample-encode` — encode a single sample at an explicit CRF and
    report VMAF (verification before committing to a full encode).
  - `probe` — report ab-av1 availability and version.
- Encoder aliasing accepts `av1`/`svtav1` -> `libsvtav1`,
  `h265`/`hevc` -> `libx265`, `h264` -> `libx264`. Search output
  parsed for final CRF + VMAF; surfaced on the `complete` payload.
- ab-av1 binary not bundled (single download from
  github.com/alexheretic/ab-av1/releases); sidecar discovers it next
  to the sidecar or under tools/_bin/.
- Three presets ship: `ab-av1-target-vmaf-93` (SVT-AV1 archival),
  `ab-av1-target-vmaf-95-x265` (x265 high-quality),
  `ab-av1-crf-search-only` (recommendation only).
- Sidecar count: 179 (was 178).

### Reconciled — Speaker Diarization + Background Noise Reduction (ROADMAP Items 21, 22)

- Item 21 (Speaker Diarization in STT Output) marked SHIPPED — the
  whisper-stt sidecar already implements `--diarize` via pyannote
  3.1 (`pyannote/speaker-diarization-3.1`) gated on the `HF_TOKEN`
  env var. ONNX-converted offline variant remains as future work.
- Item 22 (Background Audio Noise Reduction) marked SHIPPED — UCX
  ships two sidecars covering both ends of the requested capability:
  `tools/speechenhance/` runs DeepFilterNet3 with `--atten` strength
  control, and `tools/rnnoise/` covers Mozilla RNNoise for clean
  broadband noise. NoiseRemoverPage already wires the DFN3 path.

### Added — Auto-edit silence/motion removal sidecar (ROADMAP Item 73)

- New `tools/auto-edit/` sidecar wraps the auto-editor CLI (>=27.0.0)
  with three NDJSON ops: `silence-remove` (audio threshold + margin),
  `motion-edit` (audio + motion thresholds combined via auto-editor's
  DSL), `speedup-quiet` (keep silent regions but render high-speed),
  plus a `probe` op that reports availability + version.
- stderr percent-progress parsed into NDJSON `progress` events; full
  PyInstaller frozen-guard so the sidecar can be bundled without the
  Python runtime.
- Two presets ship: `auto-edit-silence-remove` (0.04 threshold + 0.2
  sec margin — talk-head trimming) and `auto-edit-motion-cut`
  (combined audio + motion 0.02 threshold — tutorials / lectures).
- Sidecar count: 178 (was 177).

### Added — AVIF tuning controls + HDR / lossless presets (ROADMAP Item 89)

- `heicshift convert` op gains three AVIF flags: `--avif-speed 0..10`
  (encoder effort), `--avif-subsampling {4:0:0|4:2:0|4:2:2|4:4:4}`
  (chroma sampling — 4:4:4 best for HDR / gradients),
  `--avif-lossless` (overrides --quality).
- ICC + EXIF pass-through (already shipping) preserves cICP / colour
  metadata for HDR-tagged sources.
- Two new presets: `to-avif-hdr` (Q92 / 4:4:4 / speed 4) and
  `to-avif-lossless` (4:4:4 / speed 2 / archival).
- Remaining: Apple-style gain-map writing waits for pillow-avif-plugin
  to expose libavif 1.4.x's gain-map API.

### Added — Opus 1.5 application + frame_duration controls (ROADMAP Item 90)

- `audiopro convert` exposes Opus-specific tuning flags:
  `--opus-application {voip|audio|lowdelay}` and
  `--opus-frame-duration {2.5|5|10|20|40|60}` ms. Both ignored
  silently for non-Opus targets.
- Three Opus presets ship: `to-opus-voice-32k` (voip / 32 kbps / 20
  ms — podcast-grade), `to-opus-music-128k` (audio / 128 kbps / 20 ms
  — transparent stereo), `to-opus-rtc-lowdelay` (lowdelay / 64 kbps /
  5 ms — RTC tuning).
- DRED in libopus 1.5+ inherited from the bundled FFmpeg; higher-order
  ambisonics channel-layout selector deferred.

### Added — Audio metadata auto-populate from filename (ROADMAP Item 78)

- `audiotag` sidecar gains an `auto-populate` op. Each input filename
  is matched against a list of regex patterns; named capture groups
  feed mutagen's `easy=True` tag keys (title / artist / album /
  albumartist / tracknumber / discnumber / date / year / genre /
  composer / comment / lyrics).
- Default patterns cover `NN - Artist - Title`, `Artist - Album - NN -
  Title`, `Artist - Title`, and `Title`-only fallbacks.
- Repeatable `--pattern` overrides + `--set key=value` static
  overrides; `--overwrite` flag controls whether existing tag values
  are replaced (default preserves).
- New `presets/audiotag-auto-populate.preset.xml` exposes the default
  flow as a one-click batch preset.
- Charter-aligned: offline-first, file-local, no cloud metadata service.

### Added — Intro / outro editor (ROADMAP Item 36)

- New `intro-outro` op on `clipforge`. Thin wrapper over the existing
  `op_concat`: builds the `[intro?, primary, outro?]` list and
  delegates to the same stream-copy / filter_complex machinery so
  re-encode only fires when codecs differ. Args: `--input` (primary
  single file), `--intro` / `--outro` (both optional), `--reencode`.
- New `presets/intro-outro.preset.xml` ships with
  `RequiresExtraInput` so the executor prompts for the intro file at
  run time.

### Added — Cross-encoder capped-CRF harmonization (ROADMAP Item 91)

- `videocrush` sidecar gains a canonical `--max-bitrate <kbps>` flag
  that pairs with `--crf <quality>` and translates per-encoder:
  libx264 / libx265 / `*_nvenc` / `*_amf` / `*_qsv` -> `-maxrate Nk
  -bufsize 2Nk`; libsvtav1 -> `-svtav1-params crf=Q:mbr=N`; libvpx-vp9
  -> `-maxrate / -bufsize`. Honoured only in CRF mode.
- Three new presets exercise the flag end-to-end:
  `to-h264-capped-crf-23` (8 Mbps cap), `to-h265-capped-crf-25` (6 Mbps
  cap), `to-av1-capped-crf-30` (4 Mbps cap). Same "Quality with bitrate
  cap" concept renders to three different argv shapes — the preset
  portability moat in action.

### Added — Output size estimator utility (ROADMAP Item 68)

- New `Core/Utilities/OutputSizeEstimator.cs` exposes
  `ForLosslessCopy`, `ForConstantBitrate`, and `ForVariableBitrate`
  estimators returning typed `OutputSizeEstimate(Kind, Bytes,
  DisplayLabel, Caveat)`. Lossless / CBR labels are exact; VBR
  prefixes with `~` and tags with a ±25% caveat. Scene-complexity
  multiplier clamped to 0.5..1.8 so unrealistic factors don't blow up.
- 14 new xUnit tests (195/195 Core suite passing). Queue ListView
  wiring deferred to land alongside the next queue UX pass.

### Added — AI Portrait wiring (ROADMAP Item 27)

- ToolboxPage tile flipped Future -> Ready (CodeFormer / GFPGAN).
- `MainWindow.NavigateTo("ai-portrait")` routes to `PresetsPage` with
  the `facerestore` engine filter so users see both
  `restore-face-codeformer` (fidelity slider) and `gfpgan-restore`
  (blind face restoration) presets side-by-side.
- Nav search adds an "AI Portrait" suggestion alongside "Photo
  Restoration"; PhotoRestorationPage stays focused on GFPGAN-only
  blind face restoration.

### Added — Post-encode output duration validation (ROADMAP Item 72)

- New `Core/Utilities/OutputDurationValidator.cs` — probes input +
  output via FFprobe and returns a typed `DurationValidationResult`
  with `IsValid` / `DeltaSeconds` / `StatusTag`. Threshold is
  `min(MinDurationDeltaSeconds, 1% of input)`.
- `SidecarRunner.RunAsync` success path now invokes the validator when
  `ConverterXOptions.ValidateOutputDuration` is on (default true) and
  both input + output look like media files. Truncation surfaces as a
  `warn`-level log entry ("PARTIAL / TRUNCATED — Δ delta s > threshold s")
  while the job itself stays Successful because the sidecar already
  reported complete; History / toasts can pick up the warn line.
- Probe failures silently no-op so the validator never falsely flags
  a job when ffprobe is missing or the file is non-media.
- Two new `ConverterXOptions` fields: `ValidateOutputDuration` (bool,
  default true) and `MinDurationDeltaSeconds` (double, default 2.0).

### Hardened — libjxl security floor pin to 0.11.2 (ROADMAP Item 88)

- `tools/heicshift/build.ps1` bumps `pillow-jxl-plugin` install pin
  from `>=1.3.0` to `>=1.3.4` (first wrapper release that bundles
  libjxl 0.11.x with CVE-2025-12474 + CVE-2026-1837 fixes) and adds a
  `--security-pin`-style guard that fails the build if the installed
  wrapper is below 1.3.4.
- `tools/heicshift/sidecar.py._try_register_jxl()` introspects the
  installed wrapper version and emits a `warn`-level `log` event when
  it's below the security floor — audible signal even when no
  malformed JXL is hit.
- `heicshift.py`'s auto-bootstrap dependency map gets the same pin
  so dev-mode launches pull the upgraded wrapper.

### Added — VR / 360° video reprojection (ROADMAP Item 38)

- New `v360` op on `clipforge` exposes FFmpeg's `v360` filter with
  input/output projection switching (equirect / 3x2 cubemap / 6x1 /
  1x6 / fisheye / flat / dfisheye / barrel) plus yaw/pitch/roll, fov
  overrides, and explicit output dimensions.
- Three new presets: `v360-equirect-to-flat` (rectilinear viewport at
  90°×60° FOV), `v360-equirect-to-cubemap` (3x2 layout for
  game-engine import), `v360-fisheye-to-equirect` (insta360 / GoPro
  Max raw -> equirectangular).

### Added — Lens correction / Watermark overlay / LUT apply / Lossless trim / ProRes+DNxHR (ROADMAP Items 24, 31, 39, 42, 57)

- `clipforge` sidecar gains two new ops: `lens-correct` (FFmpeg
  `lenscorrection` filter, --k1/--k2/--cx/--cy controls for action-cam
  fisheye correction), and `watermark` (FFmpeg `scale2ref` -> `overlay`
  filter chain with 9-point position grid, --opacity 0..1, --scale as
  percent of frame width, --margin in pixels). Watermark pre-multiplies
  alpha so users can dial transparency without baking it into the PNG.
- New presets routing through clipforge: `lens-correct-actioncam`
  (default action-cam k1=-0.2), `watermark-overlay` (RequiresExtraInput
  for the overlay path), `lut-apply` (RequiresExtraInput for the .cube
  LUT path; runs the existing clipforge.lut3d op), `lossless-trim`
  (clipforge.trim --lossless, keyframe-bounded stream-copy).
- New ProRes/DNxHR videocrush presets (Item 57): `to-prores-422-proxy`,
  `to-prores-4444`, `to-dnxhr-sq`, `to-dnxhr-hq`, `to-dnxhr-hqx`. The
  underlying videocrush PRESETS dict already maps each to the right
  prores_ks profile or dnxhr_<tier> flag — this item closes the
  preset-library gap.

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
