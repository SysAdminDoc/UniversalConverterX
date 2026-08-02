# UniversalConverterX — Product Roadmap

**Status:** v2.34.0 · 212 sidecar engines · 459 preset files · 53 UI pages
**Last updated:** 2026-07-29

Blocked items live in [`Roadmap_Blocked.md`](Roadmap_Blocked.md).
Shipped work is recorded in [`CHANGELOG.md`](CHANGELOG.md).

**Design charter:** Offline-first. No cloud fallback. No accounts. No telemetry. Windows 10 21H2+. Preserve user files and metadata; expose the same trusted engine behavior through UI, CLI, REST, and PowerShell.

---

## Legend

| Tier | Meaning |
|------|---------|
| **P0 / Now** | Release-blocking security, data-safety, activation, or artifact-integrity work |
| **P1 / Next** | Next reliability, accessibility, testing, and workflow-foundation work |
| **P2 / Later** | Product depth, performance, compatibility, and upgrade work after P1 foundations |
| **P3 / Later** | Lower-urgency specialist capability or consolidation |
| **UC** | Under Consideration; evidence or upstream capability is not yet sufficient |

---

## Under Consideration

- [ ] UC — Item 134 — Prove Opus 1.6 HD interoperability before exposing 96 kHz
  Why: libopus 1.6 ships experimental 96 kHz Opus HD, but UCX's bundled FFmpeg/libopus path reports at most 48 kHz and the scalable-quality extension remains an Internet-Draft.
  Evidence: Opus 1.6 official release/demo; `draft-valin-opus-scalable-quality-extension-02`; `FFmpegConverter`.
  Touches: FFmpeg capability probe, audio fixtures, `AudioConverterPage`.
  Acceptance: a pinned build demonstrates encode/decode/remux interoperability at 96 kHz across UCX, FFmpeg, and at least two independent players before any user-facing option is enabled.
  Complexity: M

---

## Research-Driven Additions

_2026-07-29 research pass. Existing incomplete IDs are preserved; new IDs continue at Item 147. Evidence is in [`RESEARCH.md`](RESEARCH.md)._

### P1 — Reliability, trust, accessibility, and test foundations

- [ ] P1 — Item 155 — Add a media metadata and output-fidelity regression corpus
  Why: competitors repeatedly regress language labels, track names, attachments, color data, and fallback selection; UCX's broad claims need fixture proof.
  Evidence: Shutter issue 228; LosslessCut 3.69.0; VidCoder 12.23; MKVToolNix v100; Netflix VMAF; C2PA security considerations.
  Touches: `FFmpegConverter`, native converters, representative sidecars, `ffprobe` comparator, staged-artifact tests.
  Acceptance: fixed fixtures round-trip named/language-tagged audio/subtitles, dispositions, chapters, attachments, rotation, HDR/color, cover art, C2PA/UltraHDR metadata, malformed inputs, cancellation, and output duration/streams without mutating sources.
  Complexity: M

- [ ] P1 — Item 156 — Introduce a durable app-scoped job coordinator and job center
  Why: dozens of pages own cancellation/process state and only Converter persists its queue, so navigation, restart recovery, retry, and preflight behavior vary by workflow.
  Evidence: page-level `CancellationTokenSource` usage; `ConverterPage`/`BatchQueueStore`; Adobe Media Encoder, Apple Compressor, UniConverter, and Topaz queue behavior.
  Touches: new UI/Core job coordinator, queue store schema/migration, pages, navigation shell, history.
  Acceptance: jobs survive page navigation; queued jobs restore after restart and formerly running jobs return as interrupted/retryable; cancel/retry/skip work from one job center; preflight separates blocking errors from warnings for tool/model/input/output/free-space/capability checks.
  Complexity: XL

- [ ] P1 — Item 158 — Route Console and Shell preset parsing through Core `PresetDocument`
  Why: three XML readers enforce different validation and path semantics, creating a security/compatibility drift point.
  Evidence: `Core/Utilities/PresetDocument.cs`; `Console/Presets/ConversionPreset.cs`; `ShellExtension/Presets/PresetReader.cs`.
  Touches: Core adapter model, Console and Shell preset readers, shared fixture tests.
  Acceptance: UI, CLI, REST, PowerShell, and Explorer accept/reject the same valid, future-schema, XXE, traversal, invocation-mode, and output-template fixtures with one diagnostic vocabulary.
  Complexity: M

- [ ] P1 — Item 160 — Localize imperative runtime copy and add pseudo-localization
  Why: XAML resource parity is strong, but 54 C# files contain 493 direct user-visible assignments and only four `AppLocalizer` calls.
  Evidence: `src/UniversalConverterX.UI/Views/**/*.xaml.cs`; Microsoft globalization guidance; File Converter/Shutter localization history.
  Touches: `.resw` files, `AppLocalizer`, code-string extraction/formatting contract, locale tests.
  Acceptance: no user-visible status/error/dialog literal remains in code outside a narrow documented allowlist; formatted/plural values use resources; pseudo-locale UI automation finds clipping, missing keys, or fallback English.
  Complexity: L

- [ ] P1 — Item 161 — Establish accessible status, keyboard, contrast, and reflow primitives
  Why: the UI has three live regions, no accelerator/access-key infrastructure, no adaptive states or high-contrast resources, 54 wide fixed widths, and subtle text below 4.5:1 contrast.
  Evidence: `App.xaml`; `Views/**/*.xaml`; Microsoft accessibility checklist/text/layout guidance; WCAG 2.2 status messages.
  Touches: shared XAML resources/components, shell/pages, Item 124 runtime tests.
  Acceptance: progress/success/error changes are announced without focus theft; core actions have documented accelerators; all pages pass keyboard, Narrator, high-contrast, 4.5:1 text, 225% scale, and narrow-window reflow checks.
  Complexity: XL

- [ ] P1 — Item 162 — Implement or remove every persisted setting
  Why: accent, minimize-to-tray, start-minimized, and completion-sound values are loaded/saved but have no runtime consumers, undermining settings trust.
  Evidence: `SettingsWindow.xaml.cs`; `ConverterXOptions.cs`; repository-wide consumer scan.
  Touches: app/window lifecycle, notification service, theme resources, settings schema/migrations/tests.
  Acceptance: each visible setting has an observable tested effect immediately or after clearly stated restart; unused options are removed through a versioned migration and no-op settings fail a contract test.
  Complexity: M

- [ ] P1 — Item 157 — Replace duplicated discovery lists with one stable workflow catalog
  Why: Main, Home, Toolbox, Presets, and Universal Convert diverge, and Toolbox deduplication by route removes distinct tasks sharing the same destination.
  Evidence: `MainWindow.xaml.cs`; `HomePage.xaml.cs`; `ToolboxPage.DedupeTiles`; Adobe/Apple/Topaz preset browsers.
  Touches: new catalog model/service, all discovery/search surfaces, sidecar health, resources.
  Acceptance: every task has a stable ID independent of route, localized title/search metadata, input/output capabilities, readiness, favorite/recent state, and local/one-time-download/network disclosure; all surfaces consume the same catalog and no ClipForge task disappears.
  Complexity: M

- [ ] P1 — Item 126b — Wire history replay into the UI
  Why: Core replay accessors are shipped and tested; users still lack History “Apply settings” and page-level “Apply last used” affordances.
  Evidence: `HistoryStore.GetRerunRequestAsync`; `GetLastUsedRerunAsync`; `ConversionRerunRequest`.
  Touches: History, Converter, and Compressor pages.
  Acceptance: a history row or latest replayable job pre-fills the destination page without starting work; ViewModel tests cover missing presets/tools.
  Complexity: S

- [ ] P1 — Item 128b — Surface per-track keep/drop controls in Converter preflight
  Why: Core and CLI stream selection shipped, but the preflight UI cannot control it.
  Evidence: `FFmpegConverter.BuildStreamMapArgs`; `ConversionOptions.AudioTrackSelection`/`SubtitleTrackSelection`; Shutter issue 228.
  Touches: Converter preflight table and job snapshot.
  Acceptance: named/language-tagged streams show keep/drop controls, default to preserve all, persist into the job snapshot, and pass Item 155 fixtures.
  Complexity: S

### P2 — Product depth, performance, and compatibility

- [ ] P2 — Item 130b — Offer capability-gated hardware encoders and safe fallback
  Why: runtime detection exists, but UI selection must show why a device/preset is unavailable and snapshot the actual encoder/fallback used.
  Evidence: `FfmpegEncoderProbe`; HandBrake preset gating; FileFlows fallback; VidCoder 12.23; FFmpeg 8.1 D3D12/Vulkan capabilities.
  Touches: Converter/Compressor encoder UI, job preflight/provenance, diagnostics.
  Acceptance: only probed encoders appear enabled; disabled choices explain driver/tool/VRAM requirements; a tested per-job software fallback preserves requested scale/deinterlace and is recorded in history.
  Complexity: S

- [ ] P2 — Item 132b — Wire queue search and clone into queue/History UI
  Why: tested Core primitives exist, while professional queues make warnings, prior jobs, and copied settings searchable.
  Evidence: `BatchQueueOperations.Search`/`CloneAsNew`; MKVToolNix v100.
  Touches: queue and History UI.
  Acceptance: search filters filename/engine/status/error, and “open copy as new settings” creates a fresh job without mutating the original.
  Complexity: S

- [ ] P2 — Item 133 — Preserve MP4/MOV `udta` track names on remux
  Why: named-track fidelity remains incomplete and MKVToolNix v100 now imports these names.
  Evidence: MKVToolNix v100; Item 155 fixture matrix.
  Touches: probe/remux layer and `FFmpegConverter`.
  Acceptance: MP4/MOV remux preserves `udta` audio/subtitle track names verified by independent probe.
  Complexity: S

- [ ] P2 — Item 136 — Add KEPUB interchange and a governed KCC comic pipeline
  Why: KFX input already exists; remaining value is EPUB↔KEPUB plus device-profiled comic output with explicit protected-input rejection.
  Evidence: `CalibreConverter.cs`; `tools/ebookconvert/sidecar.py`; Calibre/KCC documentation.
  Touches: ebook/comic sidecars, presets, readiness catalog.
  Acceptance: EPUB↔KEPUB and CBZ/CBR→device-profiled EPUB/MOBI pass fixtures; protected KFX/Kindle inputs fail with a clear no-DeDRM message.
  Complexity: M

- [ ] P2 — Item 137 — Promote existing ClipForge RIFE into the managed workflow contract
  Why: `rife-ncnn-vulkan` already works in legacy ClipForge, but it is not governed by the main catalog, queue, artifact, and fallback contracts.
  Evidence: `tools/clipforge/clipforge.py:163-164,935-1010`; Video2X/RIFE precedent.
  Touches: managed sidecar operation/preset, workflow catalog, artifact manifest, Video Enhancer UI.
  Acceptance: a catalog-visible job interpolates to a target FPS through the app-scoped queue with a pinned runtime, GPU readiness reason, cancel/retry, and source-preserving output validation.
  Complexity: M

- [ ] P2 — Item 163 — Virtualize Toolbox, Presets, and History
  Why: nested grids and fully materialized lists scale poorly at 459 presets and the retained-history ceiling.
  Evidence: `ToolboxPage.xaml`; `PresetsPage.xaml`; `HistoryPage.xaml`.
  Touches: list/repeater layouts, incremental data sources, search debounce, performance tests.
  Acceptance: only visible containers are realized; scrolling/filtering 459 presets and 500 history rows remains responsive; cold-navigation and memory budgets are recorded in tests.
  Complexity: M

- [ ] P2 — Item 164 — Add representative sample render and synchronized comparison
  Why: users need evidence before committing to expensive compression/restoration settings, and UCX already computes VMAF.
  Evidence: Movavi sample conversion; Topaz/Apple preview; StaxRip issue 702; `VmafAnalysisPage`.
  Touches: Compressor/Enhancer job builder, preview cache, `VmafAnalysisPage`.
  Acceptance: users render a bounded representative segment, compare source/output with linked seek or split view, see estimated size/time plus VMAF summary, and promote the exact settings into a full job.
  Complexity: M

- [ ] P2 — Item 165 — Version plugin and sidecar host-compatibility manifests
  Why: plugin schema validates trust but not minimum/maximum host or capability contracts, while built-in sidecar manifests omit schema and engine versions.
  Evidence: `PluginTrustService.CurrentSchemaVersion`; `tools/*/ucx.sidecar.json`; FileFlows plugin/server compatibility.
  Touches: plugin and sidecar schemas, discovery/readiness service, CLI diagnostics, compatibility tests.
  Acceptance: manifests declare schema, engine version, min/max host, capabilities, architecture, tools/models, and migration behavior; incompatible extensions are quarantined with an actionable reason before execution.
  Complexity: M

- [ ] P2 — Item 166 — Enforce documentation and supported-platform truth
  Why: README links missing CONTRIBUTING guidance and conflicts with project/MSIX/WiX/runtime floors; stale changelog/roadmap state has repeatedly survived releases.
  Evidence: `README.md:112-113,258-259,441`; `src/UniversalConverterX.UI/UniversalConverterX.UI.csproj`; `installer/msix/Package.appxmanifest`; `installer/wix/Product.wxs`; version-consistency tests.
  Touches: README contribution/platform sections, manifests, installer checks, changelog/roadmap validation.
  Acceptance: one tested matrix states OS, architecture, package type, runtime, sidecar availability, migration, and unsigned-install behavior; the missing CONTRIBUTING link is removed or replaced in README, and broken local links, duplicate Unreleased headings, completed roadmap rows, and conflicting version/floor claims fail the release gate.
  Complexity: S

- [ ] P2 — Item 168 — Migrate the Core test suite from xunit 2.x to xunit.v3
  Why: NuGet marks xunit 2.9.3 and its four transitive packages Legacy because xunit.v3 supersedes them; the deprecation is currently suppressed in `tools/gates/allowlist.json` and that suppression expires 2027-01-29.
  Evidence: `dotnet list package --deprecated` via `tools/gates/dependency_gate.py`; `tests/UniversalConverterX.Core.Tests/UniversalConverterX.Core.Tests.csproj`; xunit v3 migration guidance.
  Touches: Core test project references, runner/test-platform wiring, `tools/gates/Invoke-Gates.ps1` if the invocation changes, allowlist removal.
  Acceptance: the Core suite runs on xunit.v3 with the same 2400+ tests green under `build.ps1 -Target Test`, and the five xunit allowlist entries are deleted rather than extended.
  Complexity: M

- [ ] P2 — Item 167 — Service .NET packages and validate Windows App SDK 2.3.1
  Why: UCX repeats Microsoft 10.0.9 versions across projects while .NET 10.0.10 is a security servicing release, and Windows App SDK 2.3.1 supersedes the 2.2.0 UI/runtime smoke dependency.
  Evidence: project package references; .NET 10.0.10 release notes; Windows App SDK downloads; live 2026-07-29 outdated-package audit.
  Touches: central package-version props, Core/Console/UI/Shell/tests, installer runtime checks, Items 124 and 152.
  Acceptance: Microsoft 10.0.x packages resolve centrally to 10.0.10; UI and VideoScaler use 2.3.1; restore/build/Core tests/runtime page smoke/publish/portable/MSI/MSIX checks pass with no unsupported-OS or activation regression.
  Complexity: M

### P2/P3 — Governed local AI capability

- [ ] P3 — Item 141 — Finish governed offline speaker diarization output
  Why: `whisper-stt --diarize` assigns speakers in memory but depends on an HF token/cache and does not provide a pinned offline pack, complete writers, or first-class UI.
  Evidence: `tools/whisper-stt/sidecar.py:332,381-405`; pyannote offline guidance; Shutter 20.2.
  Touches: whisper sidecar, model-pack manifest/downloader, TXT/SRT/VTT/JSON writers, transcription UI.
  Acceptance: after explicit model terms/consent, a revision/hash-pinned local pack works air-gapped; every selected writer preserves speaker labels; toggle is off by default and no telemetry/network call occurs during inference.
  Complexity: L

- [ ] P3 — Item 143 — Add DDColor/ColorMNet temporal colorization tier
  Why: the existing Zhang CPU model is fast but temporally weaker; these local models offer a quality tier without removing the portable fallback.
  Evidence: `tools/colorize`; `vs-deoldify`.
  Touches: colorize sidecar, pinned model packs, capability UI, temporal fixtures.
  Acceptance: DDColor/ColorMNet is consented, revision/hash pinned, kill-switchable, and measurably reduces frame-to-frame color flicker while retaining the portable CPU default/fallback.
  Complexity: L

### P3 — Specialist capability and consolidation

- [ ] P3 — Item 144 — Support bounded live/dynamic DASH recording
  Why: Streamkeep logs dynamic MPD as unsupported, so live downloads fail without recording semantics.
  Evidence: `tools/streamkeep/streamkeep/dash.py:55`.
  Touches: DASH parser/downloader, CLI/UI recording controls, fixtures.
  Acceptance: a dynamic MPD records a user-bounded duration/segment window with discontinuity recovery, or fails before writing with a precise unsupported-feature reason.
  Complexity: M

- [ ] P3 — Item 146 — Complete shared sidecar discovery and emit consolidation
  Why: the shared protocol/runtime exists, but local `find_ffmpeg` and emit implementations still create drift across 212 engines.
  Evidence: `tools/_lib/ucx_sidecar.py`; remaining per-sidecar helper definitions.
  Touches: `tools/_lib/`, per-sidecar entry points, contract checker.
  Acceptance: all sidecars import the shared discovery/emit helpers unless an allowlisted engine proves a distinct contract; all 212 contract fixtures remain green.
  Complexity: L
