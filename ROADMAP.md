# UniversalConverterX — Product Roadmap

**Status:** v2.20.1 · 176 sidecar engines · 274+ presets · 45 UI pages
**Last updated:** 2026-05-02 (iter-7 wave 5 + Phase 5 self-audit — 98 items, 165 sources)

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

> **iter-5 external research refresh (2026-05-03):** 45+ sources surveyed
> (HandBrake 1.11 + open issues, faster-whisper 1.1–1.2, PySceneDetect 0.6.7,
> ONNX Runtime 1.25, CCExtractor 0.96.x, WinAppSDK 2.0, 66HEX/frame,
> MediaInfo 26.01, OpenShot 3.5.1, SubtitleEdit 5-betas, C2PA Spec 2.0,
> RVC/voice-changer ecosystem). Net additions: Items 54–65. Updated: Items 1,
> 21, 28, 33, 40, 43, 47, 50. New appendix sources: S39–S48.

> **iter-6 external research refresh (2026-05-10):** 67+ sources surveyed
> (FFmpeg 8.1 "Hoare" D3D12/Vulkan pipeline, DeepFilterNet3 MVDR model,
> whisper.cpp v1.8.4 Silero VAD v6.2 + iGPU speedup, MKVToolNix v91–v98,
> LosslessCut v3.67–v3.68, Dia-1.6B/Dia2 TTS, Chatterbox voice clone,
> ab-av1 VMAF CRF search, tsMuxeR archived April 2025, yt-dlp CVE-2026-26331,
> SubtitleEdit v5 beta20, HandBrake VAAPI PR #7467). Net additions: Items 66–68,
> UC table extended. Updated: Items 22, 28, 37, 40, 44, UC (VMAF retired,
> IAMF updated, estimated-size promoted). New appendix sources: S49–S67.
>
> **iter-7 external research refresh (2026-05-02):** 80+ sources surveyed
> (SVT-AV1-HDR (successor to ended PSY, April 2025) tuning presets + community
> builds, Vship GPU-accelerated SSIMULACRA2/Butteraugli/CVVDP metrics in NVEncC
> 9.15–9.16, QSVEncC 8.11 deinterlace updates, VCEEnc 9.05 AMF 1.5.0 + AV1,
> Purfview Whisper-XXL Pro r3.256.1 (4 new VAD models, RTX 50xx CUDA 12.8 support),
> DeepFilterNet v0.5.6, HandBrake SVT-AV1-HDR community builds, issue #7828 silent
> video truncation, #7467 VAAPI H.264/AV1 encoder, WinAppSDK 2.0.1 SystemBackdropElement,
> Uranite HandBrake-SVT-AV1-HDR nightly builds, eac3to v3.36 tsMuxeR replacement).
> Net additions: Items 69–72 (69 is SVT-AV1-HDR rewrite of iter-6 PSY item).
> Updated: Items 22, 26, 28, 47. New appendix sources: S68–S83.
>
> **iter-7 wave 4 extension (2026-05-02 cont'd):** continued research into emerging
> codec/format frontier (vvenc 1.14.0 VVC/H.266 capped CQF + film grain, libjxl
> security floor CVE-2025-12474 / CVE-2026-1837, libavif 1.4.x gain-map HDR,
> Opus 1.5 DRED neural PLC + 5th-order ambisonics) plus community-signal validation
> (r/handbrake top-of-year). Net additions: Items 87–92. New appendix sources:
> S153–S158. Cumulative: ~158 distinct sources, 92 roadmap items.
>
> **iter-7 wave 5 extension (2026-05-02 cont'd):** HDR/Dolby Vision tooling
> (dovi_tool 2.3.2 RPU pass-through, hdr10plus_tool 1.7.2 dynamic metadata),
> anime upscaling (Real-ESRGAN ncnn-vulkan + Anime4K GLSL), VapourSynth R75
> scripting bridge, Tdarr V2 conditional-rules competitor analysis, PyAV v17
> cuvid+dlpack zero-copy. Net additions: Items 93–98. New appendix sources:
> S159–S165. Cumulative: ~165 distinct sources, 98 roadmap items.
>
> **iter-7 Phase 5 self-audit (2026-05-02):** Full end-to-end review completed.
> Findings + corrections applied in-place:
> 1. **Cross-ref bug fixed (4×):** Items 87/89/93/94 referenced "Item 71 (HDR10
>    metadata)" — Item 71 is actually Av1an Per-Scene Parallel Encoding. Re-pointed
>    to **Item 69 (SVT-AV1-HDR Tuning Presets)** which is the canonical HDR-encoding
>    item.
> 2. **Duplicate item collapsed:** Item 85 ("Vector Database for Preset Search") was
>    a redundant restatement of Item 80 ("Vector Semantic Search for Presets") —
>    both propose Qdrant + embeddings. Item 85 retained as a stub with audit note;
>    canonical entry is Item 80. Item numbers preserved for cross-reference stability.
> 3. **Source-table integrity:** 169 rows, ~165 unique URLs (a few duplicates from
>    append-with-collision: S87/S92 = auto-editor, S88/S93 = OpenShot proxy,
>    S100/S150 = SRS, S94/S151 = Spleeter, S96/S152 = TagStudio). Not renumbered to
>    keep [S{n}] cross-refs in items stable; flagged here for future iter cleanup.
> 4. **Category coverage check:** all required categories represented —
>    security (Items 9, 88, 56), accessibility (Item 10), i18n/l10n (Item 41 + 81),
>    observability/telemetry (Items 51, 81, 86), testing (Item 11 ✓ shipped),
>    docs (CHANGELOG/Roadmap), distribution/packaging (Items 25, 26, 47),
>    plugin ecosystem (Item 52), mobile (out-of-scope, charter), offline/resilience
>    (charter foundation), multi-user/collab (out-of-scope), migration (Item 53 ✓
>    shipped + Item 26 schema), upgrade strategy (Item 7).
> 5. **Tier integrity:** no items appear in two tiers; no resurrected rejects;
>    every Now/Next item maps to at least one Appendix source.
> 6. **Adversarial review:** intentionally retained — Items 75/76/96/97 are speculative;
>    UC tier flags this honestly. Items 92 (community signal) and 85 (audit-stub) are
>    explicitly non-build entries. Effort estimates are sketches not commitments;
>    every item with Effort ≥ 4 has a stated risk paragraph.
> 7. **Charter conflicts:** zero. Items 86 (Prometheus) and 97 (Tdarr-rules) are
>    explicitly opt-in / advanced-user, not default behavior — no telemetry, no cloud.
> 8. **ROADMAP.md verified on disk** (98 items, ~169 source rows, ~2350 lines).

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

- Voice Changer engine selection — the original RVC project is unmaintained
  (last release: 2023) [S47]. Current viable engines: **w-okada/voice-changer**
  (active real-time RVC fork, ONNX-exportable) or **CosyVoice** / **OpenVoice v2**
  (zero-shot voice style transfer, no training data required). Evaluate and
  select engine before sidecar work begins.

Impact: 3 · Effort: 3 · Type: leapfrog
Sources: [S3], [S4], [S10]

---

### 2. AudioTools — Audio Compressor standalone page — ✅ SHIPPED 2026-05-02

Built the `audio-compressor` sidecar (the iter-3 LR notes incorrectly
claimed it already existed — Phase 5 audit found it as `Future` /
`null` in `ToolboxPage.xaml.cs:100`) AND wired the `AudioCompressorPage`
in one pass. FFmpeg `acompressor` filter wrapper with five tested DRC
presets (light/medium/heavy/podcast/broadcast) plus Custom mode that
exposes threshold/ratio/attack/release/makeup sliders.

Impact: 4 · Effort: 1 · Type: parity
Source: [S5] (ToolboxPage.xaml.cs stub)
**Closing commit:** `0cab7d0` — `tools/audio-compressor/{sidecar.py,
build.ps1,requirements.txt}` (stdlib-only Python; FFmpeg via
subprocess), `Views/Pages/AudioCompressorPage.xaml{,.cs}` (drag-drop
queue + preset combo + custom-params card + encode combo + output dir
picker + progress overlay), `audio_compressed` event registered,
`ToolboxPage` tile flipped to Ready, `MainWindow` nav routes the key.
Phase 2 enhancements (preview waveform) deferred — base feature is
useful without it.

---

### 3. OtherTools — Batch Rename — ✅ SHIPPED 2026-05-02

New `batchrename` sidecar (or pure-C# implementation): regex/pattern-based
file rename with live preview. Tokens: `{n}` (1-based counter), `{date}`,
`{exif:date}`, `{parent}`, `{ext}`, regex replace, case transform.
Ship a `BatchRenamePage.xaml` with live preview table.

No sidecar strictly needed — `System.IO.File.Move` in the UI project is
sufficient for a first pass. ExifTool integration for `{exif:*}` tokens is
a Next-tier enhancement.

Impact: 4 · Effort: 2 · Type: parity
Sources: [S5] (ToolboxPage stub), [S6] (competitor feature)
**Closing commit:** new `BatchRenamePage` (XAML + code-behind) — drag-drop
file list, regex toggle, case transform, counter start/step, output
template (`{n}`, `{n:03}`, `{stem}`, `{ext}`, `{parent}`, `{date}`,
`{date:fmt}`), live preview with conflict detection (in-batch + on-disk),
two-pass `File.Move` apply with per-row error capture. Toolbox tile
flipped Future→Ready (UCX engine). ExifTool tokens (`{exif:*}`) deferred
to Next-tier per original scope note.

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

### 5. Output Filename Template DSL — ✅ SHIPPED 2026-05-02

User-configurable output filename pattern: `{title}_{date}_{resolution}.{ext}`.
Supported tokens for video/audio: `{title}`, `{artist}`, `{date}`, `{year}`,
`{resolution}`, `{fps}`, `{bitrate}`, `{codec}`, `{duration}`, `{n}` (counter).
Store as a per-preset optional `<OutputTemplate>` element in preset XML.
Fallback to existing stem-based naming when unset.

Impact: 4 · Effort: 2 · Type: leapfrog
Sources: [S13] (yt-dlp `%(title)s` pattern system), [S14] (general UX pattern)

**Closing commit:** `3ed8f0d` — new
`Core/Utilities/OutputFilenameTemplate` static class is the single
source of truth for filename rendering across CLI presets, the
orchestrator, and (eventually) the Watch Folder service. Full token
catalogue per the spec above plus built-ins ({stem}, {dir}, {ext},
{preset}, {date}, {year}). Path-separator-aware sanitization on
caller-supplied tokens. Yt-dlp-compatible `{{` `}}` brace escaping.
Unknown tokens render to empty so half-resolved templates can't leak.
13 new xUnit tests (181/181 passing). `ConversionPreset.ResolveOutputPath`
gains an optional `mediaTokens` parameter so future orchestrator
metadata probing can plumb FFprobe data through.

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

### 7. Dependency Update Checker — ✅ SHIPPED 2026-05-02 (service + UI banner)

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

**Phase 1 shipped 2026-05-02 — service + cache + DI + opt-out:**
- New `Services/UpdateCheckService.cs` — polls GitHub Releases for the
  four tracked tools (yt-dlp, BtbN/FFmpeg-Builds, ggerganov/whisper.cpp,
  microsoft/onnxruntime). Best-effort installed-version probe via per-tool
  `<engine>.version` files under `ToolsBasePath`.
- 24 h throttle window enforced via `LastCheckUtc` field of the cache.
- Honours `ConverterXOptions.CheckForUpdates` opt-out (returns cached
  results without hitting the network when toggled off).
- Atomic JSON cache write to `%LocalAppData%/UniversalConverterX/update-cache.json`
  (sibling-tmp + Move pattern, mirrors `SettingsService`).
- `HttpClient` is static + 15 s timeout; `User-Agent: UniversalConverterX-UpdateCheck/1.0`
  (GitHub API requires a UA header).
- Registered as singleton in `App.xaml.cs`; fired fire-and-forget on
  `OnLaunched` after main window activation. Probe failures are swallowed
  so they can never crash the app.
- Build verified Release.

**Phase 2 shipped 2026-05-02 — Home dashboard banner:**
- `HomePage.xaml` gains a top-of-page `InfoBar` (`UpdateBanner`), collapsed
  by default and only opened when `IUpdateCheckService.GetCachedResults()`
  reports at least one tool with `UpdateAvailable=true`.
- Banner message lists each pending tool with its latest version
  (e.g. "New release available for: yt-dlp 2026.05.01, ffmpeg n8.1.").
- "Open release notes" action button shells out to the first tool's
  `ReleaseUrl` via `ProcessStartInfo { UseShellExecute = true }` so it
  honours the user's default browser without bundling an HTTP renderer.
- Reads cache only — never triggers a network probe from the page; that
  stays the App-startup path's responsibility.
- All exceptions are swallowed: a missing service, malformed cache, or
  shell-launch failure can never block the dashboard from rendering.
- Build verified Release.

**Closing commit:** Item 7 Phase 2 — Home dashboard InfoBar surfacing UpdateCheckService cached results.

**Phase 2 (deferred):** dashboard `InfoBar` surface, "Open release notes"
links per tool, optional one-click update action (requires per-tool
download + replace logic; substantial — separate roadmap item).

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

### 9. yt-dlp Cookie Credential Encryption — ✅ SHIPPED 2026-05-02 (UI completed)

Encrypt stored yt-dlp cookies at rest using Windows DPAPI
(`System.Security.Cryptography.ProtectedData`), machine-scoped. Mirrors the
approach shipped in YoutubeDownloader v1.14+. Prevents credential leakage if
the UCX app data folder is exfiltrated.

Impact: 3 · Effort: 1 · Type: security
Source: [S15] (YoutubeDownloader DPAPI cookie encryption, v1.14 changelog)

**Closing commit (Python at-rest layer):** `b8058de` — new
`tools/streamkeep/streamkeep/dpapi.py` module wraps Crypt32.dll via
`ctypes` (stdlib-only). `cookies.py` writes are encrypted at-rest with a
`DPAPI1\n` magic header for self-describing format detection. Reads
detect encrypted blobs and decrypt to a process-private temp file under
`%TEMP%`, registered for `atexit` cleanup. yt-dlp / curl never see the
encrypted form. Round-trip verified.

**Closing commit (UI surface):** `fe699e3` — streamkeep sidecar gains
`cookies-status` / `cookies-import` (`--browser <name>` |
`--file <path>`) / `cookies-clear` ops, all emitting a unified
`cookie_status` NDJSON event. DownloaderPage gets a Cookie
Authentication card between the URL options and Activity cards:
browser combo (chrome/firefox/edge/brave/chromium/vivaldi/opera/
librewolf/safari), Import button, Import-from-file picker, Clear
button gated on cookie presence. Status text auto-refreshes on page
activation and shows encryption state ("encrypted at rest (DPAPI)"
vs "plaintext (legacy)") plus staleness ("5m ago").

---

### 10. Accessibility — Continue UIA Automation Properties Pass — ⚠️ IN PROGRESS (parts a+c shipped, b incremental)

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

**Verified state (Phase 5 audit, 2026-05-02 + iter-4 closure):**
- `AutomationProperties.Name` — 40 of 44 pages (was 22; iter-4 work
  surfaced control-level annotations across newly-shipped pages).
- `AutomationProperties.AutomationId` — 22 occurrences across 2 pages
  (AudioCompressorPage all controls + DownloaderPage cookie chrome +
  11 high-traffic existing controls). Baseline locks the remaining
  470-entry deficit.

**Closing commit for parts (a) + (c):** `40edbce` — new
`tests/uia_contract/check_uia.py` (stdlib-only XAML scanner +
DataTemplate/ControlTemplate/ItemsPanelTemplate/Style.Setters scope
skip + line-independent x:Name / UNNAMED#N keys), CI workflow gates
on `uia-contract` job, baseline at `tests/uia_contract/baseline.txt`,
DownloaderPage 11 controls cleanup proves shrink-baseline path.

**Remaining work for part (b):** add AutomationId to the remaining
~459 controls across the other 42 pages. Now safe to incremental-drain
across iterations because the gate prevents new violations from sneaking
in. Each cleanup commit shrinks the baseline.

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

### 54. AiLabPage — Fix Stale "Future" Status Labels — ✅ SHIPPED 2026-05-02

Three AiLab tiles (`TextToSpeech`, `SpeechToText`, `OldPhotoRestoration`)
still display a `"Future"` status chip in `AiLabPage.xaml.cs` (lines 35–38)
despite all three pages being fully wired and shipped (verified in Item 1,
Phase 5 audit). The stale label greys out tiles and suppresses the live
call-to-action. Fix: change `TileStatus.Future` → `TileStatus.Ready` for
the three shipped tiles. One-line change per tile; no sidecar involved.

Shipped: `AiLabPage.xaml.cs` lines 36–38 — TTS/STT/OldPhoto chips now
`Ready` with workflow-available subtitles and engine attributions
(Kokoro/Piper, Whisper, Real-ESRGAN/GFPGAN). Build verified Release.

Impact: 2 · Effort: 1 · Type: UX
Source: [S2] (AiLabPage.xaml.cs stale status inspection, Phase 0 recon)

---

### 60. Batch Queue — Auto-scroll to Active Job — ✅ SHIPPED 2026-05-02

When the batch queue begins processing a job, the queue `ListView` should
auto-scroll to keep the active row visible. In deep queues (50+ items) the
processing row scrolls off-screen and users lose track of progress.
Implementation: call `ListView.ScrollIntoView(activeItem)` when the
orchestrator fires `ActiveJobChanged`. WinUI 3 `ListView` supports this
natively — no custom scroll code required; no sidecar change.

Shipped: `QueueList.ScrollIntoView(job)` invoked at top of the per-job
loop in the three `QueueList`-bearing pages (`DownloaderPage`,
`RecorderPage`, `FrameSnapshotPage`). Wrapped in try/catch to absorb
the rare virtualization race where a container hasn't realized yet.
Other pages use `QueuePivot` only and are unaffected. Build verified Release.

Impact: 3 · Effort: 1 · Type: UX
Source: [S40] (HandBrake #7813 — auto-scroll queue to active job)

---

### 61. faster-whisper Sidecar Refresh (Batched Inference + New Models) — ⚠️ PARTIAL 2026-05-02

Update the `whisper-stt` sidecar to `faster-whisper>=1.1.0`:

- **Batched inference:** 4× throughput on long-form audio by processing in
  overlapping chunks (`--batch_size 8` default for GPU; sequential fallback
  on CPU).
- **large-v3-turbo model:** Distilled Whisper; quality close to `large-v3`
  at ~3× the speed. Add as a UI model selection option in `SttPage.xaml`.
- **New VAD models:** `silero_v6_fw`, `silero_v6`, `nemo_v2`, `ten` —
  improved silence detection on noisy/music-heavy audio. Update VAD dropdown.
- **3× faster CPU VAD:** significant benefit for CPU-only installs.

Update `requirements.txt`: pin `faster-whisper>=1.1.0`. No NDJSON contract
change — only sidecar CLI arg extension and model-list update.

Impact: 4 · Effort: 2 · Type: platform + performance
Sources: [S44] (faster-whisper v1.1.0/v1.2.1 — batched inference 4×, large-v3-turbo),
[S48] (Purfview Whisper-XXL Pro r3.256.1 — silero_v6/nemo_v2/ten VAD models)
**Closing commit:** sidecar pin bumped to `faster-whisper>=1.1.0`; new
`--batch-size` arg (default 8) opportunistically uses
`BatchedInferencePipeline` when available with graceful fallback to the
streaming path on older installs / CPU-only builds. SttPage model combo
gains `large-v3-turbo` and `distil-large-v3` entries. **Deferred:** new
VAD models (`silero_v6`, `nemo_v2`, `ten`) — those live in Purfview's
Whisper-XXL fork, not upstream `faster-whisper`. Tracked as a follow-up
item rather than vendoring a fork.

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

### 14. Subtitle Burn-in Preset — ✅ SHIPPED 2026-05-02

New preset using `videocrush` or a dedicated `hardsub` sidecar: burn
SRT/ASS/VTT into video with configurable font, size, color, position, stroke,
and background. FFmpeg `subtitles` filter chain. Frequently requested;
every commercial converter ships it.

Impact: 4 · Effort: 2 · Type: parity
Source: [S3] (Any Video Converter subtitle customization — stroke/outline/background, v9.2.0)

**Closing commit:** new `subtitle-burn` op on `clipforge` (FFmpeg
`subtitles=` filter + libass `force_style` overrides). Args cover font /
size / primary colour / outline colour / shadow colour / border style /
outline thickness / shadow offset / vertical margin / 9-point position
grid (tl/tc/tr/ml/mc/mr/bl/bc/br) / bold / italic. Path escape helper
handles Windows drive-colon double-escaping for the inner filter parser.
New `presets/subtitle-burn.preset.xml` with sensible defaults (Arial 24,
bottom-centre, white-on-black outline). Honours
`<RequiresExtraInput>true</RequiresExtraInput>` so the executor prompts
for the subtitle file at run time rather than baking a path into the
preset. Contract test: 177 sidecars conforming.

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

### 17. HDR → SDR Tone Mapping Preset — ✅ SHIPPED 2026-05-02

New preset in VideoTools: HDR10 / HLG → SDR conversion using FFmpeg
`zscale` + `tonemap` filter chain. Include Hable, Reinhard, and Mobius
operator options. Currently `clipforge` has a stub 3D-LUT path but no
first-class HDR→SDR workflow.

Impact: 4 · Effort: 2 · Type: parity
Source: [S9] (FFmpeg 8.1 — libavcodec 62.x new tone-mapping capabilities)

**Closing commit:** existing `op_hdr_to_sdr` extended with
`--operator {hable|reinhard|mobius|clip|linear|gamma}` + `--desat` +
`--peak-nits` + `--crf` flags. Three new presets: `hdr-to-sdr-hable`
(safest default), `hdr-to-sdr-reinhard` (saturation-faithful),
`hdr-to-sdr-mobius` (highlight-rolling). Output naming distinguishes
the three operators (`_sdr-hable` / `_sdr-reinhard` / `_sdr-mobius`)
so a side-by-side render produces three files instead of overwriting.

---

### 18. Audio Loudness Normalization (EBU R128 / LUFS) — ✅ SHIPPED 2026-05-02

New `audioloudness` sidecar or preset: two-pass FFmpeg `loudnorm` to
target broadcast loudness (e.g., -16 LUFS for streaming, -23 LUFS for
broadcast). Expose target LUFS, true-peak ceiling, and LRA controls.

Impact: 4 · Effort: 2 · Type: parity
Source: [S14] (EBU R128 — table-stakes in any professional audio conversion tool)

**Shipped 2026-05-02:**
- Existing `audiomastering` sidecar already implements two-pass
  `loudnorm` with `--lufs`, `--tp`, `--lra` arguments — feature surface
  was a preset library gap, not a missing engine.
- Existing `loudnorm-streaming.preset.xml` covered -14 LUFS streaming.
- New `presets/loudnorm-broadcast.preset.xml` — -23 LUFS / -2 dBTP, the
  EBU R128 / ATSC A/85 broadcast deliverable target.
- New `presets/loudnorm-podcast.preset.xml` — -16 LUFS / -1.5 dBTP, the
  Apple Podcasts / Spotify-safe streaming target. (-14 streaming preset
  remains for YouTube/Netflix-style platforms that re-normalize to that
  ceiling.)
- All three presets use distinct output suffixes (`_loudnorm`, `_r128`,
  `_pod16`) so a side-by-side render of the same source produces three
  files instead of overwriting.
- Build verified Release (preset XMLs are XCOPY'd by build.ps1).

**Closing commit:** Item 18 — Add EBU R128 broadcast (-23 LUFS) and podcast (-16 LUFS) loudnorm presets.

---

### 19. Video Stabilization Preset — ✅ SHIPPED 2026-05-02

Wrap FFmpeg `vidstab` (two-pass: `vidstabdetect` → `vidstabtransform`).
New `VideoStabilizePage.xaml` or preset under VideoTools. Controls: shakiness
detection threshold, smoothing, border crop/black-fill mode.

Impact: 3 · Effort: 2 · Type: parity
Source: [S14] (standard professional video conversion feature)

**Closing commit:** new `stabilize` op on `clipforge` runs the
`vidstabdetect` -> `vidstabtransform` two-pass FFmpeg pipeline with the
detection `.trf` written to a temp file beside the input and unlinked
on success. Args: `--shakiness 1..10` / `--smoothing 1..60` /
`--border {keep|black|crop}` plus standard codec/crf/preset overrides.
Output passes through an `unsharp` second-pass filter to recover edge
detail lost to the warp. Reports `vidstab_missing` error code when the
local FFmpeg lacks `--enable-libvidstab` (BtbN's gpl builds include
it). New `presets/stabilize.preset.xml` ships with shakiness 5 /
smoothing 15 / keep-borders defaults.

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

**Engine note (iter-5, 2026-05-03):** faster-whisper 1.1.0 [S44] ships
batched inference (4× throughput) and the `large-v3-turbo` distilled model.
The STT sidecar refresh (Item 61) should land before this item to avoid
double-integrating on an older inference path.

Impact: 3 · Effort: 3 · Type: leapfrog
Sources: [S10] (Purfview whisper-standalone-win — pyannote_v3/onnx VAD + diarization),
[S44] (faster-whisper v1.1.0 — batched inference, large-v3-turbo)

---

### 22. Background Audio Noise Reduction

New `audionoise` sidecar wrapping `rnnoise` (Mozilla) or `deepFilterNet`
(ONNX model): remove background noise from speech recordings, interview
audio, or video audio track. Include a denoise strength control.

**DeepFilterNet3 (iter-6, 2026-05-10):** DeepFilterNet v0.5.0+ [S53]
ships DeepFilterNet3 — a higher-quality noise-suppression model with
Multi-Frame Filtering (MVDR/Wiener) that improves suppression in
reverberant environments. The Rust ONNX backend remains; Python bindings
updated. v0.5.3 adds attenuation limiting to prevent speech removal artefacts.
Prefer DeepFilterNet3 over RNNoise as the default model; expose model selection
(`dfn2` / `dfn3`) in the UI for CPU-constrained users.

**DeepFilterNet v0.5.6 (iter-7, 2026-05-02):** Latest stable release [S79]
continues MVDR/Wiener multi-frame architecture; no breaking changes, all prior
tuning parameters preserved. v0.5.4 added Python 3.11 + macOS aarch64 + Linux
aarch64 wheels for broader platform coverage.

Impact: 3 · Effort: 3 · Type: parity
Sources: [S14] (common request in audio processing communities),
[S53] (DeepFilterNet v0.5.0/v0.5.3 — DeepFilterNet3, MVDR, attenuation limit),
[S79] (DeepFilterNet v0.5.6 latest stable)

---

### 23. Auto Crop — Content-Aware Crop — ✅ SHIPPED 2026-05-02

New `autocrop` preset using FFmpeg `cropdetect` filter: analyze a video clip
for black borders, suggest crop rectangle, apply. Wire to `AutoCropPage.xaml`
or as a VideoTools option.

Impact: 3 · Effort: 2 · Type: parity
Source: [S5] (ToolboxPage.xaml.cs stub)

**Closing commit:** new `auto-crop` op on `clipforge`. Sample-pass runs
`cropdetect=<threshold>:16:0` over the first `--sample-seconds` (default
10) of the input, parses the rectangles emitted to stderr, and picks the
most-frequently observed. The rectangle is then re-injected into a
single-pass re-encode. `--detect-only` skips the encode and emits the
detected coordinates as a `complete.detected` payload (for UI preview).
Errors as `crop_undetected` when no rectangle was reported (suggest
raising `--threshold` and lengthening the sample window). New
`presets/auto-crop.preset.xml` with threshold 24 / sample 10 / CRF 20.

---

### 24. Lens Correction — ✅ SHIPPED 2026-05-02

New `lenscorrect` preset using FFmpeg `lenscorrection` filter: correct barrel
/ pincushion distortion with k1/k2 coefficients, or use `vf_lensfun`
(LensFun lens database). Useful for action cam footage (GoPro) and wide-angle
photography.

Impact: 3 · Effort: 2 · Type: parity
Source: [S5] (ToolboxPage.xaml.cs stub)

**Closing commit:** new `lens-correct` op on `clipforge` exposes
FFmpeg's `lenscorrection` filter with `--k1` / `--k2` (quadratic +
quartic) and `--cx` / `--cy` (optical centre) controls. Default
preset (`lens-correct-actioncam`) ships with `k1=-0.2 k2=0` — a
reasonable starting point for action-cam fisheye correction; fine
tuning is exposed via the args. LensFun database integration deferred
to a follow-up: requires shipping the database and the lensfun model
selector UI; the bare lenscorrection filter covers the common case.

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
  (replaces current window-level backdrop hack). **Enables in-app acrylic
  panels** like the Mica/Acrylic theming roadmap item (WinAppSDK 2.0.1 adds
  `CornerRadius` support [S74]).
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
Sources: [S19] (Windows App SDK 2.0 release notes, 2026-04-29),
[S74] (WinAppSDK 2.0.1 SystemBackdropElement + CornerRadius)

---

### 27. AI Portrait — Still Image Enhancement — ✅ SHIPPED 2026-05-02

Wire the `AI Portrait` ToolboxPage stub to a dedicated `AiPortraitPage.xaml`.
Pipeline: `real-esrgan` (face-oriented model) or `codeformer` sidecar for
portrait upscale + restoration. Batch-capable. Separate from Old Photo
Restoration (which targets degraded/aged prints).

Impact: 3 · Effort: 2 · Type: parity (wiring) + leapfrog (depth)
Source: [S5] (ToolboxPage stub)

**Closing commit:** the `facerestore` sidecar already shipped both
CodeFormer (`--w` fidelity slider, `--upscale`, `--face-upsample`,
`--bg-enhance`) and GFPGAN ops in v2.10. The remaining wiring was UI
discoverability: ToolboxPage tile flipped Future → Ready (CodeFormer /
GFPGAN), `MainWindow.NavigateTo` routes `ai-portrait` to `PresetsPage`
with the `facerestore` engine filter, and the nav search adds
"AI Portrait" alongside "Photo Restoration" so both flows are
findable. PhotoRestorationPage stays focused on GFPGAN blind face
restoration; AI Portrait surfaces both engines via the `restore-face-codeformer`
and `gfpgan-restore` presets so users pick the fidelity-vs-restoration
trade-off explicitly. Dedicated `AiPortraitPage.xaml` is feasible as
follow-up if the preset UX proves insufficient.

---

### 28. FFmpeg 8.x Sidecar Refresh

Audit all sidecars that bundle or call an FFmpeg binary. BtbN/FFmpeg-Builds
provides daily Windows auto-builds of FFmpeg 7.x–8.x. Pin all ffmpeg-dependent
sidecars to ≥7.1 (current stable shipped with UCX) and test against 8.1
("Hoare", 2026-03-16). Notable 8.x additions: libavcodec 62.x new codec
support, libvmaf AVX-512 improvements. Carry a pinned FFmpeg build in
`tools/ffmpeg/` rather than relying on PATH.

**CUDA / ONNX floor (iter-5, 2026-05-03):** ONNX Runtime 1.25.0 [S36] dropped
CUDA 11.x support — UCX AI sidecars must pin `onnxruntime-gpu>=1.25.1` and
document `CUDA ≥12.0` as the GPU runtime floor. RTX 50xx (Blackwell, CUDA 12.8)
is tested by Purfview r3.256.1 [S48]; no sidecar change needed as 12.0 ≤ 12.8.
**ArmNN EP removed in ORT 1.25.0** — Qualcomm NPU work (Item 47) must target
QNN EP only.

**FFmpeg 8.1 D3D12 pipeline (iter-6, 2026-05-10):** FFmpeg 8.1 "Hoare"
[S52] adds `scale_d3d12`, `deinterlace_d3d12`, and `mestimate_d3d12` filters
plus D3D12 H.264/AV1 hardware encoding. This unlocks GPU-accelerated encode
and filter chains on any DirectX 12 GPU (Intel Arc, AMD RDNA2/3, Nvidia
Pascal+) without a CUDA driver requirement. Also ships Vulkan ProRes
encode/decode and the native `whisper` filtergraph filter. The dedicated
D3D12 pipeline item is tracked as Item 66.

**Hardware encoder updates (iter-7, 2026-05-02):** NVEncC 9.15–9.16 [S69]
adds Vship GPU-accelerated quality metrics (SSIMULACRA2, Butteraugli, CVVDP)
for post-encode analysis. QSVEncC 8.11 [S70] adds `--vpp-ivtc` + `--vpp-bwdif`
deinterlace presets. VCEEnc 9.05 [S71] updates to AMF 1.5.0 (requires AMD
Adrenalin 25.10.2+) and adds Dolby Vision output + parallel multi-GPU encoding.

Impact: 3 · Effort: 2 · Type: platform + security
Sources: [S9] (FFmpeg 8.1 changelog), [S20] (BtbN FFmpeg auto-builds),
[S36] (ONNX Runtime 1.25.0 — CUDA 12.0 minimum, ArmNN EP removal),
[S52] (FFmpeg 8.1 "Hoare" — D3D12 encode/filter, Vulkan ProRes, whisper filter),
[S69] (NVEncC 9.15–9.16 Vship metrics), [S70] (QSVEncC 8.11 deinterlace),
[S71] (VCEEnc 9.05 AMF 1.5.0)

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

### 31. Image / Video Watermark Overlay — ✅ SHIPPED 2026-05-02 (video path)

New `watermark` sidecar preset: stamp a PNG/JPEG logo or watermark onto video
or image batches. Controls: position (9-point grid: TL/TC/TR/ML/MC/MR/BL/BC/BR),
opacity (0–100%), and scale (% of frame width). Video: FFmpeg `overlay` filter
chain. Images: Pillow `Image.paste()` with alpha compositing. Wire to
`WatermarkPage.xaml` with a live thumbnail preview of the positioned overlay.

Impact: 3 · Effort: 2 · Type: parity
Sources: [S29] (66HEX/frame v0.29.0 image overlay pipeline), [S28] (Shutter
Encoder logo overlay)

**Closing commit:** new `watermark` op on `clipforge` runs the FFmpeg
`scale2ref` -> `overlay` filter chain. Args: `--overlay <png|jpg>` /
`--position` (9-point grid tl/tc/tr/ml/mc/mr/bl/bc/br) / `--opacity 0..1`
/ `--scale <% of frame width>` / `--margin <pixels>`. Pre-multiplies
opacity via `format=rgba,colorchannelmixer=aa=<opacity>` so users can
dial transparency without baking it into the source PNG. New
`presets/watermark-overlay.preset.xml` with `RequiresExtraInput` so
the executor prompts for the overlay file at run time. Image-batch
path (Pillow paste) deferred — for stills there is already an
imagemagick-style preset path covering common sizes; full image-batch
op land if explicit demand surfaces.

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

### 33. Media Inspector (Technical Stream Analysis) — ✅ SHIPPED (already, via FormatInspectorPage)

New `mediainspect` sidecar wrapping `pymediainfo` (Python MediaInfo bindings):
surface full technical metadata for any A/V file — container format, all
video/audio/subtitle stream details (codec, profile, bit depth, colour space,
HDR metadata, audio channel layout, stream delay, language tags, container
atoms). Present as `MediaInspectorPage.xaml` with collapsible per-stream
sections and a "Copy as JSON" export button. Distinct from the EXIF metadata
editor (Item 12): read-only technical analysis of A/V streams, not tag editing.

**MediaInfo 26.01 scope note (iter-5, 2026-05-03):** MediaInfo 26.01 [S37]
adds C2PA assertion parsing for MPEG-4 containers. The `mediainspect` sidecar
should surface the C2PA `actions` assertion list (author, creation tool,
processing steps) when present — providing read-only content-provenance display
without requiring the full C2PA embedding pipeline (UC table entry).

Impact: 3 · Effort: 2 · Type: parity
Sources: [S37] (MediaArea/MediaInfo — technical A/V stream analysis, C2PA parsing),
[S35] (krzemienski/awesome-video: sbraz/pymediainfo wrapper)

**Already shipped (verified 2026-05-02 audit):**
`Views/Pages/FormatInspectorPage.xaml{,.cs}` (560 LOC) ships native
file-signature detection plus FFprobe-driven stream analysis,
collapsible per-stream sections, and JSON export. The pymediainfo
backend isn't strictly required since FFprobe surfaces the same
codec / profile / bit-depth / colorspace / HDR / channel-layout /
language-tag fields. The C2PA assertion follow-up remains as a UC
deferment until `MediaInfo` (or an equivalent C2PA-aware probe) is
introduced as a parallel inspector backend.

---

### 56. AI Subtitle & Translation Full Pipeline

Extend the existing STT workflow into a complete subtitle production pipeline:
transcribe → translate → edit → burn-in → export. Stages:

1. **Transcribe:** Whisper (existing `whisper-stt` sidecar) → raw SRT.
2. **Translate:** Machine-translate the SRT to a target language using a local
   model (e.g. `Helsinki-NLP/opus-mt-*` ONNX weights via `ctranslate2`) —
   no external API, charter-aligned.
3. **Edit (light):** Surface the SRT in a read-only preview panel with a
   "copy to clipboard / open in Notepad" escape hatch. Full subtitle editing
   is out of scope for this item.
4. **Burn-in or export:** Pass the output SRT to the existing subtitle burn-in
   preset (Item 14) or export as SRT/VTT/ASS.

Wire to an expanded `SttPage.xaml` pipeline view or a new
`SubtitleStudioPage.xaml`. The AI Subtitle tile in `AiLabPage.xaml.cs` is
currently `"Planned"` — this item ships it.

Impact: 4 · Effort: 3 · Type: leapfrog
Source: [S2] (AiLabPage.xaml.cs "Planned" tile inspection, Phase 0)

---

### 57. ProRes & DNxHR Encoder Presets — ✅ SHIPPED 2026-05-02

HandBrake 1.11.0 ships Apple ProRes (all variants: 422 Proxy/LT/422/HQ,
4444, 4444 XQ) and Avid DNxHR (SQ, HQX, 444, LB) encoders via FFmpeg,
confirming production-readiness for intermediate-format workflows.

Add presets for:

- `ProRes 422 HQ` — standard production deliverable (MOV container)
- `ProRes 4444` — effects/compositing with alpha channel support
- `DNxHR SQ` — Avid Media Composer project-ready intermediate (MXF/MOV)
- `DNxHR HQX` — 10-bit intermediate for color work

UCX's existing `videocrush` sidecar already exposes FFmpeg codec flags;
extending it for ProRes/DNxHR is a preset-XML addition + minor sidecar
validation of `prores_ks` / `dnxhd` codec availability at runtime.

Impact: 3 · Effort: 2 · Type: parity
Source: [S39] (HandBrake 1.11.0 release — ProRes + DNxHR encoder support)

**Closing commit:** the `videocrush` sidecar already implements the
underlying preset profiles (`prores-422-proxy`, `prores-422-lt`,
`prores-422`, `prores-422-hq`, `prores-4444`, `dnxhr-sq`, `dnxhr-hq`,
`dnxhr-hqx`, `dnxhr-444`) and selects the correct pixel format /
profile flags. The existing `to-prores-422-hq` preset XML covered HQ
only — this item adds five more user-facing presets (Proxy, 4444, DNxHR
SQ, DNxHR HQ, DNxHR HQX). Each preset routes to the matching videocrush
profile and ships with the standard `_proresproxy` / `_prores4444` /
`_dnxhrsq` / `_dnxhrhq` / `_dnxhrhqx` output suffixes so a side-by-side
render produces distinct deliverables.

---

### 58. Audio Encoder Advanced Parameters

Expose per-encoder advanced options beyond bitrate and sample rate. Most
professional converters expose these; UCX sidecars support the FFmpeg flags
but the UI surfaces no controls:

- **FDK-AAC:** cutoff frequency (`-cutoff`), afterburner (`-afterburner`).
- **libopus:** bitrate mode (CVBR/CBR), application profile (voip / audio /
  lowdelay), frame duration.
- **libvorbis:** managed bitrate mode toggle.
- **MP3 (libmp3lame):** psychoacoustic tuning preset (complements the VBR
  mode already covered by Item 30).

Implementation: add an "Advanced audio…" expansion panel in
`AudioConverterPage` (when Item 30 VBR surface lands) exposing these as
optional override fields. Store in preset XML as `<AudioAdvanced>` child
elements; sidecar parses and maps to FFmpeg flags.

Impact: 3 · Effort: 2 · Type: parity
Source: [S43] (HandBrake #7336 — audio encoder advanced parameter exposure)

---

### 59. Post-Conversion Source File Management

After a successful conversion, optionally: move the source file to a configured
archive folder, delete it, or do nothing (default). Surface as a per-preset
option: "After successful conversion: [Keep / Move to / Delete]".

Implementation:

- Add `PostConversionAction` enum (`Keep`, `Move`, `Delete`) to
  `ConversionPreset`.
- The orchestrator executes the action after the `complete` event and
  verification of output file presence.
- "Move to" shows a folder picker; resolves relative paths from source parent
  if the configured path is relative.
- Delete requires explicit user opt-in (checked setting in the preset editor)
  and logs the deletion to History (Item 6) before executing.

Impact: 3 · Effort: 2 · Type: UX
Source: [S41] (HandBrake #7400 — auto-move source files after successful encode)

---

### 62. Lock Preset Dimensions Across Switches

When a user adjusts the crop / resolution / aspect ratio settings in the
conversion UI and then switches to a different preset, the dimension fields
currently reset to preset defaults — discarding manual settings. Add a
per-field lock toggle (lock icon beside each dimension control) that pins
the value and prevents preset-switch from overwriting it. Pinned fields
persist until the user explicitly unlocks or resets.

Implementation: `LockedFields` bitmask on the UI ViewModel; preset-apply
logic skips fields whose bit is set. No preset XML change — purely a
ViewModel-layer UX pattern.

Impact: 3 · Effort: 2 · Type: UX
Source: [S42] (HandBrake #7423 — lock crop/resolution settings across preset changes)

---

### 63. VOBSUB + OCR Subtitle Extraction (Standalone Tool)

Wire a dedicated toolbox entry for VOBSUB/PGS image-subtitle → SRT
conversion. Primary use case: users ripping home-video DVDs whose subtitle
tracks are stored as VOBSUB image streams rather than text.

Implementation: CCExtractor 0.96.3 [S34] supports VOBSUB OCR output for
MP4/MKV. Extend the `ccextract` sidecar with:

- `--input-format vobsub` mode
- OCR output to SRT/VTT
- Language selection (`--ocr-lang <iso>` passed to Tesseract backend)

Wire to a "VOBSUB → Text Subtitles" entry in VideoToolsPage or the DiscTools
section alongside DVD Rip (Item 43). Latin-script OCR quality is good; CJK
degrades — document in UI tooltip.

Impact: 2 · Effort: 2 · Type: parity
Source: [S34] (CCExtractor 0.96.3 VOBSUB OCR support for MP4/MKV)

---

### 68. Per-Job Estimated Output File Size _(promoted from UC — iter-6)_ — ⚠️ PARTIALLY SHIPPED 2026-05-02

Show a pre-encode size estimate for each job in the batch queue: target
bitrate × source duration + container overhead. Surfaces in the queue metadata
column and in the per-job detail panel.

**Precedent:** LosslessCut v3.67.2 [S56] shipped "Show estimated segment file
size in segment list" (#2630), proving the UX pattern is feasible and
user-valued. Their implementation uses a simple `bitrate × duration` model for
lossless copy (known-exact because no transcode). UCX's transcode path is
inherently approximate (VBR, scene complexity) — show as "~X MB" with a
"±25%" caveat for VBR presets and an exact value for CBR or lossless-copy jobs.

**Implementation:** Pure C# UI change. No sidecar required.
1. `ConversionJob` gains a `EstimatedOutputBytes` computed property that
   reads `TargetBitrate` × `SourceDuration` from the probed media info.
2. Queue `ListView` gains an "Est. Size" column (sortable, hidden by default).
3. For lossless-copy presets (`-c copy`), show exact = source bytes with a
   tiny container-overhead delta.
4. For VBR presets, show the estimate with a `~` prefix and tooltip explaining
   the approximation.

Impact: 3 · Effort: 1 · Type: UX
Sources: [S56] (LosslessCut v3.67.2 — segment size estimate in segment list, #2630)

**Closing commit (utility layer):** new
`Core/Utilities/OutputSizeEstimator.cs` exposes three estimators:
`ForLosslessCopy(inputBytes)` (input + ~0.5% rewrap overhead, exact
prefix), `ForConstantBitrate(videoBps, audioBps, durationSec)` (CBR
target × duration + 1% container overhead, exact prefix),
`ForVariableBitrate(targetAvgBps, audioBps, duration, sceneComplexity?)`
(VBR with `~` prefix and ±25% caveat; complexity factor clamped to
0.5..1.8 so unrealistic values don't blow the estimate up). Returns
typed `OutputSizeEstimate(Kind, Bytes, DisplayLabel, Caveat)` so the
UI can colour-code lossless vs CBR vs VBR and surface the caveat as a
tooltip. 14 new xUnit tests (195/195 passing). **Remaining work:**
wire the estimator into the queue ListView's "Est. Size" column —
deferred so it can land alongside the broader queue UX pass.

---

### 69. SVT-AV1-HDR Tuning Presets _(replaces SVT-AV1-PSY from iter-6)_

**Context (iter-7 research, 2026-05-02):** The SVT-AV1-PSY project ended
development in April 2025 [S68]; maintainer Gianni Rosato announced the project
would wind down in favour of merging features into mainline SVT-AV1. The **official
successor is SVT-AV1-HDR** [S83], a community fork by Julio (PSY's former lead
developer) now maintained by the codec team. HDR is not a second "PSY alternative"
— it is the canonical continuation. Community builds (nightly) available via
Uranite's HandBrake patch [S83] and FFmpeg-Builds.

**SVT-AV1-HDR feature set:**
- `--tune 0` (VQ): Prioritize detail retention over artifact prevention.
- `--tune 5` (Film Grain): Optimize for film-grain preservation, temporal consistency.
- `--tune 3` (IQ): Still-image coding preset for AVIF or lossless-capable video.
- `--cdef-scaling` (1–30): Control CDEF filter strength (lower = sharper, ringier; 10–12 recommended).
- `--noise` (0–200): Generate and inject film-grain noise. ~50 ≈ `--film-grain 50`.
- `--noise-chroma` (−1–200): Independent chroma noise strength.
- `--variance-boost-strength` (1–4): Merged to mainline; adaptive AQ control.
- `--variance-octile` (1–8): Selectivity of variance-based superblock boosting.
- `PQ-optimized variance boost curve` (--variance-boost-curve 3): Tuned for HDR with Perceptual Quantizer transfer.

**UCX integration:** Add preset family `SVT-AV1-HDR` alongside the existing `SVT-AV1`:
1. Bundle community-build `svtav1.exe` from Uranite or FFmpeg-Builds in `tools/svtav1-hdr/`.
2. Expose tuning mode selector in the sidecar UI: VQ (detail), Film Grain, IQ (still), Custom.
3. For Custom mode, expose sliders for cdef-scaling, noise, and noise-chroma.
4. Presets XML: add `<SvtAv1HdrTuning>VQ|FilmGrain|IQ|Custom</SvtAv1HdrTuning>` element.

**Effort note:** This is a **parallel sidecar**, not a replacement for the existing `svtav1` 
(mainline AVX-512 codepath). Users get both options; presets default to mainline for stability,
with HDR as an opt-in "experimental" preset tier.

Impact: 3 · Effort: 2 · Type: leapfrog
Sources: [S68] (SVT-AV1-PSY project end announcement), [S83] (SVT-AV1-HDR fork + Uranite
HandBrake-SVT-AV1-HDR community builds)

---

### 70. SSIMULACRA2 / Butteraugli Quality Metrics _(promote from UC)_

`libvmaf` was the sole quality metric in the VMAF Analysis page (Item 40, shipped).
But VMAF is optimized for motion video; for still frames, texture, and perceptual
accuracy, **SSIMULACRA2** and **Butteraugli** outperform VMAF [S75]. Both are
GPU-accelerated via the **Vship** library (Codeberg, Line-fr/Vship) [S75].

**Precedent:** NVEncC 9.15+ [S69] already ships Vship integration:
`--vship-ssimulacra2`, `--vship-butteraugli`, `--vship-cvvdp` output.

**UCX integration:**
1. Extend the existing `VmafAnalysisPage` to offer a metric selector: VMAF (motion-video),
   SSIMULACRA2 (still/texture), Butteraugli (Google libjxl metric), or all three in parallel.
2. Call the Vship CLI (or bundle it) to compute scores post-encode.
3. Display results in the same chart as VMAF for comparison.
4. Store metric preference in `ConverterXOptions`.

**Technical sketch:** `mediainspect` / `vmafanalyze` sidecar gains `--metrics ssimulacra2,butteraugli`
flag; emits NDJSON with per-frame scores. Plotted alongside VMAF in the UI.

Impact: 3 · Effort: 2 · Type: leapfrog
Sources: [S75] (Vship — SSIMULACRA2/Butteraugli/CVVDP GPU metrics),
[S69] (NVEncC 9.15 Vship integration)

---

### 71. Per-Scene Parallel Encoding (Av1an) _(remains UC)_

`Av1an` [S76] is a Rust CLI that performs:
1. Scene detection (FFmpeg `scenedetect` or VapourSynth).
2. Split video into chunks at scene boundaries.
3. Encode each chunk independently at a per-scene CRF target (constant VMAF mode).
4. Concatenate results.

**Advantages:** Consistent perceptual quality throughout the video (no quality dips at scene changes);
natural parallelization (all chunks encode in parallel); better VMAF targeting than global CRF.
Av1an v0.5.2 [S76] supports SVT-AV1, x265, x264, VP9 with per-scene VMAF/XPSNR targeting.

**Technical blocker:** VapourSynth dependency is significant (Rust toolchain, conditional build).
Also requires `PySceneDetect` integration. **Effort: 5.**

**Decision:** Keep in UC. This is a leapfrog (no competing Windows converter does per-scene
parallel encoding), but the dependency footprint is large. Assess demand before committing.

Impact: 4 · Effort: 5 · Type: leapfrog
Sources: [S76] (Av1an v0.5.2 — scene-split, per-scene CRF, parallel encoding)

---

### 72. Post-Encode Output Duration Validation _(new Tier 2)_ — ✅ SHIPPED 2026-05-02

**Problem (HandBrake #7828, iter-7):** HandBrake sometimes reports successful
conversion when the video track prematurely ends. Example: input audio 1:37,
output video 0:43 — **silent truncation**. The user doesn't discover the loss
until playback.

**UCX solution:** After every job completes successfully, run a post-encode check:
1. Probe output file duration with `ffprobe`.
2. Compare against input duration from the original probe.
3. If delta > user-configurable threshold (default 2 seconds or 1%, whichever is smaller):
   - Mark job as `PARTIAL / TRUNCATED` in History (Item 6).
   - Show a toast alert: "⚠️ Output duration 0:43 but input was 1:37. Check for truncation."
   - Optionally quarantine the output file (rename with `_truncated` suffix).

**Implementation:** Pure C# logic in `ConversionOrchestrator.FinalizeJob()`. Calls existing
`ffprobe` sidecar. No new sidecar required. Settings entry: `ValidateOutputDuration` (toggle)
and `MinDurationDeltaSeconds` (default 2).

**Charter alignment:** This is **defensive reliability**, not a feature — UCX is offline-first
and local, so the check is instant and free.

Impact: 3 · Effort: 1 · Type: reliability
Sources: [S80] (HandBrake #7828 — silent video truncation bug)

**Closing commit:** new `Core/Utilities/OutputDurationValidator.cs`
(probes input + output via FFprobe, returns a typed
`DurationValidationResult` with `IsValid` + `DeltaSeconds` +
`StatusTag`). Threshold = `min(MinDurationDeltaSeconds, 1% of input)`.
Wired into `SidecarRunner.RunAsync` success path: only fires when
`ConverterXOptions.ValidateOutputDuration=true` (default), the input
+ output paths look like media files, and an FFprobe binary is
discoverable. Probe failures silently no-op so the validator never
falsely flags a job. Truncation surfaces as a `warn`-level log entry
("PARTIAL / TRUNCATED — output Xs vs. input Ys (Δ Zs > Ts threshold)")
that History/toasts can pick up, while the job itself stays Successful
because the sidecar already reported complete. Two new
`ConverterXOptions` fields: `ValidateOutputDuration` (bool, default
true) and `MinDurationDeltaSeconds` (double, default 2.0).

---

### 73. Automatic Silence Removal (auto-editor Integration) _(new Tier 3)_

**Context (iter-7 research, 2026-05-02):** `auto-editor` [S87] is a CLI tool written in Nim
that automatically cuts silence and low-motion segments from video using configurable thresholds
and a DSL. Supports `--edit audio:threshold=0.04 --edit motion:threshold=0.02` with per-track
settings.

**UCX integration:** Add a sidecar `auto-editor` wrapper + UI toggle in `AudioConverterPage`:
"Auto-remove silence (experimental)". Preset XML: `<AutoRemoveSilence>true</AutoRemoveSilence>`
+ threshold slider. Post-process step after primary encoding (can be done in parallel or as a
second pass for multi-track sources).

**Precedent:** OpenShot 3.5.1 [S88] added proxy editing for performance; auto-editor fills a
different niche (content optimization). Both address batch / long-form editing pain points.

Impact: 2 · Effort: 2 · Type: UX
Sources: [S87] (auto-editor — silence/motion cut CLI with DSL)

---

### 74. Proxy File Generation for Faster Preview _(new Tier 3)_

**Context (iter-7 research, 2026-05-02):** OpenShot 3.5.1 [S88] added "Optimize Video"
to generate proxy files (lower resolution / lower bitrate) for smoother playback during
editing and preview. Proxy files sit alongside originals and are auto-used during playback,
while the final export uses the original.

**UCX integration:** Add a preset option "Optimize for Preview" that auto-generates a
480p / 5 Mbps proxy file placed in a `_proxies/` subfolder next to the source. In
`VmafAnalysisPage` and `CompressorPage`, add a toggle to preview via proxy instead of
scanning full source (speeds up quality checking).

**Implementation:** New sidecar `generateProxy.exe` or extend existing `compress` sidecar.
Settings: `ProxyEnabled`, `ProxyResolution`, `ProxyBitrate`.

Impact: 2 · Effort: 3 · Type: UX + performance
Sources: [S88] (OpenShot 3.5.1 — proxy editing feature)

---

### 75. Music Source Separation (Spleeter) _(new UC / Lower Priority)_

**Context (iter-7 research, 2026-05-02):** `Spleeter` [S89] is Deezer's ML-based source
separation library (TensorFlow) that isolates vocals, drums, bass, and other instruments
from a mono or stereo mix. Multi-GPU optional; GPU-optional CPU path available. Python.

**Use case:** Music producers and streamers often need stems (isolated tracks) for remixing,
streaming overlays, or backing track creation. This is a niche but high-value workflow.

**UCX integration:** Add sidecar `source-separator` (Python wrapper around Spleeter).
UI: new `SeparatorPage` in the Converter sidebar. Preset XML:
`<SeparationMode>vocals|drums|bass|other</SeparationMode>` or `all` (outputs 5 files).
Output naming: `input_vocal.wav`, `input_drum.wav`, `input_bass.wav`, `input_other.wav`,
`input_accompaniment.wav` (all instrumental).

**Risk:** Model download size (~100 MB) is non-trivial; GPU inference 4× faster than CPU.
Justifies marking as UC pending community demand signal.

Impact: 2 · Effort: 4 · Type: leapfrog
Sources: [S89] (Spleeter — Deezer source separation)

---

### 76. AI Video Metadata Tagging (MediaPipe + Vision) _(new UC / Research Required)_

**Context (iter-7 research, 2026-05-02):** `MediaPipe` [S90] is Google's on-device ML library
offering vision tasks: object detection, pose estimation, hand detection, gesture recognition,
and more. Cross-platform (mobile, web, desktop). Supports batch processing.

**Concept (exploratory):** Automatically tag video metadata based on detected content:
- Frame count where faces/hands detected (for signing language videos)
- Scene keyframes (for thumbnail generation)
- Motion intensity (for auto-cut thresholds)
- Text in-frame OCR for searchability

**Charter concern:** This edges into "video understanding / AI inference", which UCX
currently doesn't do. MediaPipe is on-device (offline-first ✓), but the integration
complexity is unclear.

**Recommendation:** Keep in UC pending feasibility spike.

Impact: 1 · Effort: 5 · Type: leapfrog + AI/ML
Sources: [S90] (MediaPipe — Google on-device ML)

---

### 77. AV1 Film Grain Synthesis (av1-grain Crate) _(new Tier 3, Synergy with Item 69)_

**Context (iter-7 research, 2026-05-02):** The Rust-AV project's `av1-grain` crate [S91]
provides helpers for generating and parsing AV1 film grain data (photon noise tables). These
tables are compatible with SVT-AV1, aomenc, and rav1e.

**Integration with Item 69 (SVT-AV1-HDR):** SVT-AV1-HDR's `--noise` / `--noise-chroma` params
control noise strength, but don't control the underlying grain pattern. The `av1-grain` crate
allows per-ISO-setting photon noise generation (calibrated to camera ISO values), enabling
realistic film grain that varies by source characteristics.

**UCX implementation:** Extend the `generate-av1-config` sidecar to offer a "Film Grain"
preset section with sliders:
- ISO setting (100–6400, default 800)
- Chroma grain toggle
- Transfer function (BT.1886, PQ, HLG, etc.)

Generate `.tbl` noise table, pass to SVT-AV1-HDR via `--grain-table`. Output: artifact-free
HDR encodes with photorealistic grain.

Impact: 2 · Effort: 2 · Type: leapfrog
Sources: [S91] (av1-grain Rust crate — film grain synthesis for AV1)

---

### 78. Metadata Tag Auto-Population from Filename/Content _(new Tier 3)_ — ✅ SHIPPED 2026-05-02

**Context (iter-7 research, 2026-05-02):** `TagStudio` [S96] and `Mutagen` [S98] demonstrate
that file/audio metadata tagging is user-facing pain point. Currently, batch converters ignore
output metadata (artist, album, title, cover art, etc.).

**UCX enhancement:** After encoding audio, parse output filename (common patterns: `Artist - Title`
or ID3 tags from input if present) and auto-populate metadata:
- ID3v2 (MP3)
- Vorbis comments (FLAC/OGG/Opus)
- MP4 atoms (AAC/ALAC)
- WavPack / APE

Use Mutagen library (via Python sidecar) to write tags. Settings: toggle `PreserveMetadata`,
`AutoPopulateFromFilename` (regex pattern).

**Charter alignment:** Offline-first, file-local. No cloud metadata service.

Impact: 2 · Effort: 2 · Type: UX
Sources: [S98] (Mutagen — comprehensive audio metadata library)

**Closing commit:** the existing `audiotag` mutagen sidecar gains an
`auto-populate` op that runs each input filename through a list of
regex patterns; named capture groups feed straight into mutagen's
`easy=True` tag keys (title / artist / album / albumartist /
tracknumber / discnumber / date / year / genre / composer / comment /
lyrics — anything else is silently dropped so creative regex doesn't
fail the batch). Defaults ship four patterns covering
`NN - Artist - Title`, `Artist - Album - NN - Title`, `Artist - Title`,
and `Title`-only. Repeatable `--pattern` overrides; repeatable `--set
key=value` static overrides applied after the match; `--overwrite`
flag controls whether existing tag values are replaced (default
preserves them). Charter-aligned: offline-first, file-local, no cloud
metadata service. New `presets/audiotag-auto-populate.preset.xml`
exposes the default-pattern flow as a one-click batch preset.

---

### 79. Searchable Output Library (Meilisearch Integration) _(new UC / Research Required)_

**Context (iter-7 research, 2026-05-02):** `Meilisearch` [S97] is a full-text search engine
with AI-powered hybrid search. Users often lose track of where they saved converted files.

**Concept:** Index all historical conversions (from Item 6: Conversion History) with:
- Input filename
- Output filename
- Conversion presets used
- Metadata (resolution, bitrate, codec, date)
- Full-text search across all fields

Add a "Search History" UI pane in the app that queries a local Meilisearch instance.

**Risk:** Adds a heavyweight dependency (Meilisearch server process). Justifies UC pending
user demand signal.

Impact: 1 · Effort: 3 · Type: UX + convenience
Sources: [S97] (Meilisearch — lightning-fast search)

---

### 80. Vector Semantic Search for Presets (Qdrant) _(new UC / Exploratory)_

**Context (iter-7 research, 2026-05-02):** `Qdrant` [S99 (not yet added)] is a vector database
enabling semantic search. Combined with embedding models (e.g., Sentence Transformers), users
could ask "find presets for removing background noise" or "presets optimized for 4K movies"
and get results based on preset descriptions, not just keyword matching.

**Concept:** Embed preset descriptions into vectors using a small embedding model. Allow
users to query presets semantically: "noise reduction", "streaming-friendly encoding", etc.

**Charter concern:** Adds ML inference to preset search — potentially slow on first boot,
heavy model download. Feasibility unclear.

**Recommendation:** Keep in UC pending community signal and feasibility study.

Impact: 1 · Effort: 4 · Type: leapfrog + AI/ML
Sources: [S99-future] (Qdrant vector database)

Higher effort, lower urgency, or dependent on Tier 1/2 completion.

---

### 81. Structured Logging Framework + Crash Bundle (i18n/a11y/observability) _(new Tier 2)_

**Context (iter-7 research, 2026-05-02):** Phase 5 audit (Item 51 under Tier 2) identified
observability as table-stakes. Modern observability stacks (Prometheus/Grafana, Loki, SkyWalking)
use structured logging (JSON lines, OpenTelemetry). UCX currently has no systematic log export.

**Enhancement:** Integrate **Loguru** [S151] (Python) and **spdlog** [S149] (C++) for all
sidecar + UI logging. Log levels: DEBUG, INFO, WARNING, ERROR. Output: NDJSON to
`%LocalAppData%/UniversalConverterX/logs/` with rotation (7-day retention). On crash, bundle
last-100-logs + system info + job state into `crashes/<timestamp>_bundle.zip` for user support.

Gate behind `VerboseLogging` toggle (default off, zero-cost when disabled). No telemetry.

Impact: 3 · Effort: 2 · Type: observability/dx
Sources: [S149] (spdlog — high-performance C++ logging), [S151] (Loguru — Python logging)

---

### 82. Preset Configuration as Code (Pkl DSL) _(new UC / Research Required)_

**Context (iter-7 research, 2026-05-02):** Apple's **Pkl** [S141] is a configuration-as-code
language with rich validation. Unlike JSON/YAML, Pkl enforces type correctness and allows
reusable templates. Currently, UCX presets are hand-written XML; users cannot reason about
or compose presets programmatically.

**Concept:** Create a Pkl schema for `EncodingPreset` (codec, bitrate, filters, sidecar opts).
Allow power users to generate presets via Pkl scripts: `encode_preset(codec="av1", quality="hq")`.
Pkl compiler output → XML that UCX loads. Optional CLI: `ucx preset generate --pkl script.pkl`.

**Risk:** Adds Pkl compiler as a sidecar dependency. Justifies UC pending feasibility study.

Impact: 1 · Effort: 3 · Type: dx + leapfrog
Sources: [S141] (Apple Pkl — configuration as code language with validation)

---

### 83. Validation Layer + Pydantic Schemas _(new Tier 3)_

**Context (iter-7 research, 2026-05-02):** **Pydantic** [S140] (Python) provides runtime
validation of config/preset data using type hints. UCX sidecars receive JSON payloads from
the UI; currently there is no schema validation before sidecar invocation. Malformed presets
cause silent failures or crashes.

**Enhancement:** Define Pydantic models for each sidecar contract (e.g., `AV1EncodeRequest`,
`AudioFilterRequest`). Validate input JSON at the Python sidecar entry point before processing.
Output validation errors as structured warnings in the log bundle (Item 81). Improves reliability
and error messages.

**Side benefit:** Enables Instructor [S142] integration for LLM-guided preset generation (synergy
with Item 80, semantic preset search).

Impact: 2 · Effort: 2 · Type: reliability + dx
Sources: [S140] (Pydantic — data validation using Python type hints), [S142] (Instructor — structured outputs for LLMs)

---

### 84. Fast JSON Serialization (Orjson) _(new Tier 3)_

**Context (iter-7 research, 2026-05-02):** **Orjson** [S148] is a fast Python JSON library
with native support for dataclasses, datetimes, and numpy arrays. UCX currently uses the
standard library `json` module, which is slow for large preset/history batches.

**Enhancement:** Replace `json.dumps()` calls in Python sidecars with `orjson.dumps()`.
Expected speedup: ~3–5x for typical preset export/history serialization. Wire into the
sidecar contract layer (payload serialization on both input and output).

Impact: 1 · Effort: 1 · Type: performance/platform
Sources: [S148] (Orjson — fast Python JSON with dataclass/datetime support)

---

### 85. Vector Database for Preset Search (Qdrant) _(superseded by Item 80 — see audit note)_

**Phase 5 audit (2026-05-02):** This item is a duplicate of **Item 80** (Vector Semantic
Search for Presets) — both propose Qdrant + sentence-transformers for natural-language
preset search. Item 80 is the canonical entry; this slot retained as a placeholder so
existing item numbers stay stable (cross-reference invariant).

**Action:** Do not implement separately. Use Item 80. The Prometheus dashboard rationale
that originally lived here was elevated to **Item 86** during wave 3.

---

### 86. Batch Job Observability Dashboard (Prometheus + Grafana) _(new UC / Deployment)_

**Context (iter-7 research, 2026-05-02):** For distributed encoding workflows (Item 6 extended),
users need to monitor job queues, GPU utilization, and encode throughput. **Prometheus** [S115]
+ **Grafana** [S116] enable time-series metrics collection and visualization.

**Concept:** Expose a `/metrics` HTTP endpoint from UCX's REST API (Item 35). Metrics:
jobs queued/active/completed, average encode speed (FPS), GPU utilization, sidecar errors.
Users run a local Grafana container (docker-compose) pointed at the UCX metrics endpoint.
Optional: ship pre-built Grafana dashboard as JSON.

**Scope note:** This is optional telemetry for advanced users running large batch ops on
multiple machines. Not required for single-user local use. UC pending demand signal.

Impact: 2 · Effort: 3 · Type: observability + platform
Sources: [S115] (Prometheus — time-series monitoring), [S116] (Grafana — composable observability platform)

---

### 87. VVC / H.266 Encoding (vvenc 1.14.0) _(new T3 / Codec)_

**Context (iter-7 wave 4, 2026-05-02):** **vvenc 1.14.0** [S153] is Fraunhofer HHI's
production-grade VVC (Versatile Video Coding / H.266) encoder. v1.14.0 ships:
**capped constant-quality mode (CQF)**, **experimental film-grain analysis**, ARM SIMD/SVE
optimizations, GOP-adaptive QP cascade, and DASH-optimized decoder refresh (`idr_no_radl`).
VVC is the H.265 successor — **~30–50% bitrate savings vs. H.265 at equal quality** per
Fraunhofer benchmarks. Adoption is still nascent but tooling has matured enough that
prosumers archiving long-term assets will want it as a future-proofing path.

**Concept:** Wrap `vvencFFapp` (or `vvencapp`) as `vvc-encoder` sidecar. Expose presets
`faster | fast | medium | slow | slower` (matching x265 conventions) and CQF mode
("VVC Capped Quality 24"). Plays nicely with **Item 69** (SVT-AV1-HDR) since vvenc
honors VUI flags and color range. Decode path: ffmpeg has built-in `libvvdec` decoding
in 8.x for verification.

**Risks:** VVC playback support is sparse (VLC 4.0 beta, ffmpeg via libvvdec, no native
Windows codec). Surface this in the preset description so users don't ship VVC files to
relatives running Windows Media Player. Royalty/patent landscape is unsettled — present
as "experimental codec" UI tag.

Impact: 2 · Effort: 3 · Type: leapfrog + codec coverage
Sources: [S153] (vvenc 1.14.0 — capped CQF, film grain, ARM SVE, Jan 2026)

---

### 88. JPEG XL libjxl Security Floor — Update to v0.11.2 _(new T2 / Security)_ — ✅ SHIPPED 2026-05-02

**Context (iter-7 wave 4, 2026-05-02):** **libjxl 0.11.2** [S154] (Sep 2025) ships fixes
for **CVE-2025-12474** (tile dimension flaw in low-memory rendering pipeline) and
**CVE-2026-1837** (gray-to-gray color-transform channel-count error). Project Zero also
identified an integer overflow in `djxl` packed-representation size handling (no CVE,
fixed). All three are reachable from malicious untrusted JPEG XL inputs.

**Concept:** Audit the current bundled libjxl in any JXL-touching sidecar
(`heicshift`, image-conversion path), pin floor to **v0.11.2 minimum** in
`requirements.txt` / vcpkg manifest / sidecar build scripts. Add JXL fuzzing test
(see Item 56 fuzz harness) using small malformed JXL corpus. Add a `--security-pin`
guard to `build.ps1` that fails the build if a known-vulnerable libjxl version is
detected on the system.

**Why now:** UCX accepts arbitrary user input. Any image-pipeline CVE is a worst-case
threat surface (renders untrusted bytes from disk). This is exactly the hardening work
the charter calls for.

Impact: 4 · Effort: 1 · Type: security
Sources: [S154] (libjxl 0.11.2 — CVE-2025-12474, CVE-2026-1837)

**Closing commit:** `tools/heicshift/build.ps1` bumps the
`pillow-jxl-plugin` install pin from `>=1.3.0` to `>=1.3.4` (the
first wrapper release that bundles libjxl 0.11.x) and adds a
`--security-pin` guard that fails the build if the installed wrapper
is below 1.3.4 — fast feedback when a CI runner has a stale wheel
cached. `tools/heicshift/sidecar.py._try_register_jxl()` introspects
the installed wrapper version on import and emits a `warn`-level
`log` event when it's below the security floor (CVE-2025-12474 +
CVE-2026-1837 fixes), so users running an old dev install get an
audible signal even when no malformed JXL is hit. `heicshift.py`'s
auto-bootstrap dependency map gets the same pin so dev-mode launches
pull the upgraded wrapper.

---

### 89. AVIF Gain Map HDR (libavif 1.4.x) _(new T3 / Image)_

**Context (iter-7 wave 4, 2026-05-02):** **libavif 1.4.0–1.4.1** [S155] adds:
**Apple-style JPEG gain-map import** (HDR-from-SDR base layer + gain delta), **PNG cICP
chunk decode**, **Sample Transform 16-bit AVIF**, `--sato` decode flag, transformative
properties on alpha auxiliary items, and `AOM_TUNE_IQ` quality tuning by default for
non-RGB still images. Result: AVIF as a true HDR image format, not just an HEIC
substitute.

**Concept:** Add an `avif-hdr` preset path in the image conversion engine. Inputs:
HDR PNG (cICP-tagged) or HDR HEIC. Output: AVIF with gain map preserved (or generated).
Surface a "Preserve HDR" toggle on the image conversion page (next to existing AVIF
encode preset). Synergy with **Item 69** (SVT-AV1-HDR) — visually consistent HDR story
across UCX's still-image and video pipelines.

**Risks:** Many image viewers still treat AVIF as SDR-only and tone-map silently.
Add a UI hint and a verification toggle ("show with HDR-aware viewer recommendation").

Impact: 3 · Effort: 2 · Type: format coverage + HDR parity
Sources: [S155] (libavif 1.4.0–1.4.1 — gain map, Sample Transform, PNG cICP)

---

### 90. Opus 1.5 DRED + Higher-Order Ambisonics _(new T3 / Audio)_

**Context (iter-7 wave 4, 2026-05-02):** **Opus 1.5** [S156] introduces **Deep
Redundancy (DRED)** — neural in-band packet-loss recovery — plus **Deep PLC**, low
bitrate (6 kb/s wideband) speech improvements via ML, and **4th and 5th order
Ambisonics**. v1.5.2 (Sep 2025) is the stable release with AVX2 alignment fixes for
Windows.

**Concept:** Two sub-features:
(a) Audio engine bumps Opus floor to 1.5.2; expose DRED toggle in audio preset
("Opus DRED for transcripts/dialogue").
(b) Surface **3rd/4th/5th order ambisonics** as a metadata-aware audio channel layout
in the audio conversion page. Synergy with the UC entry "Spatial audio conversion"
(Ambisonics ↔ binaural ↔ 5.1 ↔ 7.1) — Opus 1.5 is the codec piece of that puzzle.

**Why T3, not T2:** DRED is mostly relevant for streaming/RTC, not file conversion.
Ambisonics is a small audience. But both are credible "we support modern codecs" wins.

Impact: 2 · Effort: 2 · Type: codec coverage + audio
Sources: [S156] (Opus 1.5/1.5.2 — DRED neural PLC, 5th order ambisonics)

---

### 91. Cross-Encoder Capped-CRF / Capped-Quality Harmonization _(new T2 / UX)_ — ✅ SHIPPED 2026-05-02

**Context (iter-7 wave 4, 2026-05-02):** Both **vvenc 1.14.0 (CQF)** [S153] and
**SVT-AV1-PSY/HDR** [S70] support a "capped constant-quality" mode — a CRF target with
a hard maximum bitrate ceiling. **x265** has it via `--crf-max` since 3.x. **NVEncC**
exposes it via `--vbr-quality`. Result: across UCX's encoder zoo, capped-CRF is
universally available but inconsistently labeled, breaking the preset-portability
promise.

**Concept:** Define a single canonical "Quality with Bitrate Cap" preset axis that all
five encoders (x264, x265, SVT-AV1, NVEncC, vvenc) honor identically. UI: a "Quality
target" slider + a "Don't exceed N Mbps" checkbox. Internally, each encoder driver
translates the abstract pair to its native flag pair. Eliminates the "why does CRF 23
look different on AV1 vs x265?" support load.

**Why this matters:** UCX's competitive moat is "preset portability across engines."
Capped-CRF is the next step of that promise. Zero new sidecars, pure orchestration.

Impact: 4 · Effort: 2 · Type: UX + parity
Sources: [S153] (vvenc CQF), [S70] (SVT-AV1 capped CRF)

**Closing commit:** the `videocrush` sidecar gains a single canonical
`--max-bitrate <kbps>` flag that the user pairs with `--crf <quality>`.
The sidecar translates per-encoder at dispatch time:
- libx264 / libx265 / h264_nvenc / hevc_nvenc / h264_amf / hevc_amf /
  h264_qsv / hevc_qsv → `-maxrate Nk -bufsize 2Nk`
- libsvtav1 → `-svtav1-params crf=Q:mbr=N`
- libvpx-vp9 → `-maxrate Nk -bufsize 2Nk`
The flag is silently ignored outside CRF mode (size-targeted two-pass
already has its own bitrate ceiling). Three new presets exercise the
flag end-to-end across the H.264 / H.265 / AV1 encoder family
(`to-h264-capped-crf-23`, `to-h265-capped-crf-25`, `to-av1-capped-crf-30`),
proving preset portability — the same UX-level concept ("Quality 23
with no more than 8 Mbps") renders to three different argv shapes
without the user thinking about it. **Remaining work:** UI surface
in `CompressorPage` (paired CRF slider + bitrate-cap checkbox);
deferred so it can land alongside the broader Compressor UX refresh.

---

### 92. r/handbrake & Community Signal — UCX Positioning Validation _(new — Reference, not a build item)_

**Context (iter-7 wave 4, 2026-05-02):** Reddit **r/handbrake top-of-year post**
[S157] ("Handbrake is the darling of my life", 192 upvotes, Dec 2025) confirms the
market gap UCX targets: users are not asking for *more* features, they are starving
for "something that just works." Common pain points across the year's threads:
preset confusion, queue fragility, lack of post-encode validation, inconsistent HDR.

**Action:** No new code. Use this signal to:
(a) Reorder Tier 1 to put **Items 26 (queue persistence)**, **72 (post-encode
validation)**, and **52 (preset clarity)** at the top of the next sprint.
(b) Pull at least 3 quotes from r/handbrake/r/ffmpeg threads into the README's
"Why UCX" section as social proof of the problem space.
(c) Periodic re-scan: harvest r/handbrake top posts every quarter; when a recurring
complaint appears 3+ times, escalate to a roadmap item without further research.

Impact: N/A · Effort: N/A · Type: positioning / reference
Sources: [S157] (r/handbrake top-of-year community signal)

---

### 93. Dolby Vision RPU Pass-Through (dovi_tool 2.3.2) _(new T2 / HDR)_

**Context (iter-7 wave 5, 2026-05-02):** **dovi_tool 2.3.2** [S159] (April 2025) is the
de-facto Dolby Vision metadata Swiss-army knife: `extract` / `inject-rpu` / `mux` /
`demux` / `editor` / `info` / `plot`. Critical fixes in 2.3.x: RPU now placed as last
NALU in access unit (corrects FFmpeg-based playback), `--remove-eos` flag, L8 trim
display fixes. Without RPU pass-through, transcoding a Dolby Vision source flattens it
to HDR10 and silently destroys per-shot grading.

**Concept:** Wrap dovi_tool as a `dovi-passthrough` sidecar. Default flow:
(a) on encode start, `dovi_tool extract-rpu` from input → `RPU.bin` sidecar file;
(b) re-encode video stream while preserving HEVC NALUs;
(c) `dovi_tool inject-rpu` to put RPU back into the encoded HEVC stream;
(d) `mux` step into MKV/MP4. Critical edge case: must detect Profile 5 (single-layer
IPT-PQ-C2) vs Profile 7 (dual-layer FEL/MEL) and refuse Profile 7 → Profile 5 conversion
(or expose an explicit `--convert-to-p8` flag with warning).

**Why T2:** Dolby Vision is the gold standard HDR for film archival. UCX's video
preset story is incomplete without this. Competitor pain: HandBrake silently strips
DV; FFmpeg has it but requires CLI choreography. UCX wraps the whole flow in a preset.
Synergy with **Item 69** (SVT-AV1-HDR) and **Item 89** (AVIF gain map).

Impact: 5 · Effort: 3 · Type: leapfrog + HDR
Sources: [S159] (dovi_tool 2.3.2 — RPU extract/inject/mux, Apr 2025)

---

### 94. HDR10+ Dynamic Metadata Pass-Through (hdr10plus_tool 1.7.2) _(new T2 / HDR)_

**Context (iter-7 wave 5, 2026-05-02):** **hdr10plus_tool 1.7.2** [S160] (Dec 2024)
extract / inject / edit / plot HDR10+ dynamic metadata (SMPTE ST 2094-40, Samsung-
backed competitor to Dolby Vision). v1.7.1 graduated MKV input out of experimental.
Same problem as DV: a transcode without explicit pass-through erases the dynamic
tone-mapping curve and reduces the file to static HDR10.

**Concept:** Symmetric to Item 93. `hdrplus-passthrough` sidecar:
(a) `hdr10plus_tool extract` from input HEVC → `metadata.json`;
(b) re-encode video;
(c) `hdr10plus_tool inject` JSON metadata back into the new HEVC bitstream;
(d) optional editor pass for trim/level fixups via `editor`. Synergy with **Item 69**
(HDR10 master metadata) — the static MaxCLL/MaxFALL go in the SEI, the dynamic curve
goes via this path.

**Why T2:** Less ubiquitous than DV but free of licensing constraints (open spec).
Many Samsung TVs, recent Apple TV firmware, and YouTube playback honor it. Together
with Item 93, completes the HDR-archival promise.

Impact: 4 · Effort: 3 · Type: leapfrog + HDR
Sources: [S160] (hdr10plus_tool 1.7.2 — extract/inject/edit/plot, Dec 2024)

---

### 95. Anime / Animation Upscale Sidecar (Real-ESRGAN + Anime4K) _(new T3 / AI)_

**Context (iter-7 wave 5, 2026-05-02):** Two complementary anime upscalers exist:
**Real-ESRGAN** [S161] ships an `realesr-animevideov3` model + portable
`realesrgan-ncnn-vulkan` Windows binary supporting Intel/AMD/Nvidia GPUs (no CUDA
dependency). **Anime4K** [S162] is a GLSL real-time shader chain optimized for
1080p H.264/H.265/VC-1 anime, used widely via mpv/Plex. Both target a workflow UCX
currently lacks: high-quality anime/animation upscaling distinct from photo content.

**Concept:** Add an `anime-upscale` sidecar with two backends:
(a) **Real-ESRGAN ncnn-vulkan** for batch offline 2× / 4× upscaling
(works on integrated GPUs, no Python dependency).
(b) **Anime4K (GLSL)** for a faster lower-quality preview pass via a small
embedded GLSL renderer (or an mpv-script bridge for users who already have mpv).
UI: AI Lab tile "Anime/Animation Upscale" with a mode selector and a preview frame
side-by-side. Synergy with **Item 64** (general video upscaling).

**Why T3:** Niche audience (anime/animation enthusiasts), but it's a clean win —
Real-ESRGAN ncnn binary is a single-file drop-in and Vulkan is universally available
on Windows 10 21H2+.

Impact: 3 · Effort: 3 · Type: AI + niche audience
Sources: [S161] (Real-ESRGAN — ncnn-vulkan portable Windows binary, anime models),
[S162] (Anime4K — GLSL shader chain for real-time anime upscale)

---

### 96. VapourSynth Scripting Bridge _(new UC / Power-user)_

**Context (iter-7 wave 5, 2026-05-02):** **VapourSynth R75** [S163] (Mar 2026) is the
modern AviSynth successor: Python-scripted frame-server for video filters, with
deep encoder-ecosystem support (x265, SVT-AV1, NVEncC consume `vspipe` output natively).
R75 highlights: portable Windows experience improvements, optimized plugin manifests
prevent recursive plugin load, `pip install vapoursynth` works on Windows/macOS/Linux.

**Concept:** Add a `vapoursynth-runner` sidecar that takes a user-provided `.vpy`
script + an input video and pipes the processed frame stream into UCX's encoder
zoo via `vspipe -c y4m | encoder --y4m -i -`. Surface a "VapourSynth script"
file picker on the encode page (advanced users only, off by default). This is a
power-user escape hatch: anyone with a custom VS script (TIVTC inverse-telecine,
QTGMC deinterlace, KNLMeansCL denoise, vs-mlrt with neural models) can route it
through UCX without leaving the app.

**Question blocking placement:** UCX's audience overlaps with mpv/encoder forums but
not as deeply as r/AV1. Survey demand. If positive, promote to T3.

Impact: 3 · Effort: 3 · Type: power-user / leapfrog
Sources: [S163] (VapourSynth R75 — frame-server scripting framework)

---

### 97. Conditional Rules Engine (Tdarr-style) _(new UC / Automation)_

**Context (iter-7 wave 5, 2026-05-02):** **Tdarr V2** [S164] is a direct adjacent
competitor: distributed transcoding system with a Server + Nodes architecture,
**conditional rule engine** ("if codec ≠ HEVC and audio ≠ AAC then transcode to
HEVC + AAC"), library health checking, and Plex/Sonarr/Radarr integration. UCX has
**Item 34 (Watch Folder)** but no rules layer — files matching a folder all run the
same preset, regardless of content.

**Concept:** Layer a rules engine on top of Watch Folders + Item 26 (queue):
(a) probe each new file with `mediainfo` / `ffprobe`;
(b) evaluate user-defined rules ("video codec is H.264 AND duration > 60 min →
transcode SVT-AV1 CRF 32; else skip");
(c) route matching files to the appropriate preset, mismatching files to "skipped"
or "needs review" buckets. Persisted as `Profiles/<name>.rules.xml`. Synergy with
**Item 6** (distributed encoding) — the rules engine is a natural prerequisite for
any multi-machine batch workflow.

**Why UC, not T2:** Rules engines are a deep design space. Tdarr's plugin model is
JS-based and unbounded — replicating that scope is a separate product. Start with a
simple declarative XML rules subset; promote to T2 only after we see real users
asking for it.

Impact: 4 · Effort: 4 · Type: automation + leapfrog
Sources: [S164] (Tdarr V2 — distributed conditional transcoding, plugin model)

---

### 98. PyAV v17 Hardware-Memory Zero-Copy Path _(new T3 / Performance)_

**Context (iter-7 wave 5, 2026-05-02):** **PyAV v17.0.0** [S165] (Mar 2026) introduces:
hardware-memory preservation during cuvid decoding (export/import via **dlpack**),
zero-copy `Packet` init from buffer, `OutputContainer.add_mux_stream()` for muxing
pre-encoded packets without re-encoding (a dedicated remux path), and exposed
`AVIndexEntry` for accurate seek metadata. Several UCX Python sidecars (PySceneDetect,
faster-whisper preprocessing, image extraction) currently round-trip frames through
NumPy CPU memory.

**Concept:** Audit Python sidecars that touch hardware-decoded video (SceneDetect,
preview-frame extraction in **Item 53**, the Whisper preprocessing path). Migrate
the hot loops to PyAV v17 with `AV_HWDEVICE_TYPE_CUDA` + dlpack export to
PyTorch/NumPy. Result: avoid CPU↔GPU copies on long-form video, measurable speedup
on RTX cards. Add a `--no-hwaccel` fallback CLI for users on integrated graphics.

**Trade-off:** PyAV v17 dropped libaom (use dav1d/svt-av1 alternatives) and 3.13t
free-threading wheels — no impact on UCX's Python 3.11/3.12 frozen sidecars.

Impact: 3 · Effort: 2 · Type: performance + dev-experience
Sources: [S165] (PyAV v17 — hardware memory zero-copy via cuvid + dlpack, Mar 2026)

---

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

### 36. Intro & Outro Editor — ✅ SHIPPED 2026-05-02

Attach a pre-clip and post-clip to any batch conversion job: each output file
gets the intro prepended and outro appended via FFmpeg `concat` demuxer.
Configure per-preset. Wire to `IntroOutroPage.xaml`.

Impact: 3 · Effort: 3 · Type: parity
Source: [S5] (ToolboxPage.xaml.cs stub)

**Closing commit:** new `intro-outro` op on `clipforge` is a thin
wrapper over the existing `op_concat`: builds the `[intro?, primary,
outro?]` list and delegates to the same stream-copy / filter_complex
machinery (re-encode only when codecs differ). Args: `--input`
(primary, single file), `--intro` / `--outro` (optional), `--reencode`.
Errors with `nothing_to_concat` if neither intro nor outro is supplied.
New `presets/intro-outro.preset.xml` ships with `RequiresExtraInput`
so the executor prompts for the intro file at run time. Dedicated
`IntroOutroPage.xaml` deferred — the preset path covers the common
workflow.

---

### 37. Auto Highlight — Scene Detection + Clip Extraction

Analyze a video for scene-change peaks and motion energy; auto-extract a
highlight reel at user-specified duration. Backend: FFmpeg `select=scene`
filter + optional PySceneDetect sidecar. Wire to `AutoHighlightPage.xaml`.
Additionally export the detected scene list as EDL (CMX 3600) or OTIO for
direct import into DaVinci Resolve, Premiere Pro, or any OTIO-compatible NLE.

**PySceneDetect 0.6.7 fix (iter-6, 2026-05-10):** v0.6.7 [S61] fixes the
EDL export end-timestamp being 1 frame short, which caused DaVinci Resolve to
import clips 1 frame too short. The `scenedetect` sidecar must pin
`PySceneDetect>=0.6.7` to get correct EDL output. FFmpeg 8.0 is now bundled
in the Windows PySceneDetect distribution.

Impact: 3 · Effort: 4 · Type: leapfrog
Sources: [S5] (ToolboxPage.xaml.cs stub), [S33] (PySceneDetect v0.6.6 EDL/OTIO output),
[S61] (PySceneDetect v0.6.7 — EDL end-timestamp fix for DaVinci Resolve)

---

### 38. VR / 360° Video Conversion — ✅ SHIPPED 2026-05-02

Convert equirectangular (360° video) to cubemap, fisheye, or rectilinear
projection. FFmpeg `v360` filter. Wire to `VrConverterPage.xaml`. Niche but
no-OSS-GUI exists for it on Windows.

Impact: 2 · Effort: 2 · Type: leapfrog (niche gap)
Source: [S5] (ToolboxPage.xaml.cs stub)

**Closing commit:** new `v360` op on `clipforge` exposes FFmpeg's
`v360` filter with input/output projection selection (equirect / cubemap
3x2 / 6x1 / 1x6 / fisheye / flat / dfisheye / barrel) plus yaw / pitch
/ roll / h_fov / v_fov / width / height controls. Three presets cover
the most common flows: `v360-equirect-to-flat` (rectilinear viewport,
90°×60° FOV), `v360-equirect-to-cubemap` (3x2 layout for game-engine
import), `v360-fisheye-to-equirect` (insta360 / GoPro Max raw -> equirect).
Dedicated `VrConverterPage.xaml` deferred — the `PresetsPage` already
surfaces all three flows via the `Video/360` folder grouping.

---

### 39. Color Grading LUT Application — ✅ SHIPPED 2026-05-02

A dedicated `lut-apply` preset (distinct from existing `lutgen`) that takes
an input `.cube` or `.3dl` LUT file and applies it to a video or image batch.
FFmpeg `lut3d` filter or HALDCLUT for images. Target colorists and
photographers exporting from DaVinci Resolve or Lightroom.

Impact: 3 · Effort: 2 · Type: parity
Source: [S7] (OpenShot 3D-LUT support), [S5] (clipforge stub)

**Closing commit:** clipforge's existing `lut3d` op (FFmpeg `lut3d`
filter) gets a first-class preset entry. `presets/lut-apply.preset.xml`
ships with `RequiresExtraInput=true` so the executor prompts for the
LUT path at run time, separate from the input video. Output names
suffix as `_graded`. The complementary `lutgen` sidecar (build LUTs
from before/after frames) shipped in v2.8.0; this item closes the
"apply LUT" half of the workflow.

---

### 40. Chapter Editor (MKV / MP4)

Add, edit, delete, and import/export chapter markers in MKV or MP4 containers
without re-encoding. Backend: `mkvmerge --chapters` for MKV; `mp4box -chap`
or FFmpeg for MP4. Wire to `ChapterEditorPage.xaml`.

**Precision note (iter-5, 2026-05-03):** HandBrake issue #7339 [S46]
documents a chapter timestamp offset bug when the source chapter file uses
non-zero start timestamps. The Chapter Editor must preserve exact PTS values
during import and must not silently renumber or offset them. Add a
timestamp-accuracy unit test to the sidecar contract suite.

**MKVToolNix v95–v98 notes (iter-6, 2026-05-10):**
- v95.0 [S55]: `mkvmerge` gains `--date` argument for explicit output date
  metadata control; MP4 display-matrix rotation is now translated to
  MKV roll/yaw values on remux.
- v97.0 [S55]: TrueHD audio in MP4 containers (FourCC `mlpa`) is now
  readable — fixes import of newer iPhone and studio MP4 sources.
- v98.0 [S55]: Chapter editor gains "apply modifications to all open tabs"
  option — useful for batch chapter normalization in the UCX workflow.
- v91.0 [S55]: mkvmerge auto-detects "commentary" and "original language"
  flags from filenames — the Chapter Editor / track manager UI can expose
  this via `--commentary-track-language` flag.

Pin `mkvmerge ≥ v97.0` for TrueHD-in-MP4 read support.

Impact: 3 · Effort: 3 · Type: parity
Sources: [S6] (LosslessCut chapter editor), [S14] (standard pro video feature),
[S46] (HandBrake #7339 — chapter timestamp offset on non-zero-start input),
[S55] (MKVToolNix v91–v98 NEWS.md — TrueHD MP4, --date, rotation, commentary auto-flag)

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

### 42. Lossless Trim / Cut (No Re-encode) — ⚠️ PARTIALLY SHIPPED 2026-05-02

New `losslesscut` preset: trim video clip by start/end timestamps without
re-encoding. FFmpeg `-ss` + `-to` with `-c copy`. Surface in
`LosslessCutPage.xaml` with a simple timeline scrubber showing keyframe
positions (I-frames only for true lossless trim). Competes directly with
LosslessCut (Electron app, ~13k stars).

Impact: 4 · Effort: 3 · Type: parity
Source: [S6] (LosslessCut — primary OSS competitor for this workflow)

**Sidecar layer shipped 2026-05-02:** clipforge's existing `trim` op
already supports `--lossless` (FFmpeg `-ss/-to` + `-c copy`,
keyframe-bounded). New `presets/lossless-trim.preset.xml` exposes it as
a one-click batch preset (start defaults to 0; the user adjusts via the
preset args panel or CLI). Full `LosslessCutPage` with a keyframe-aware
timeline scrubber is the remaining UI half — it builds on the trim op
plus the existing `clipforge timeline` thumbnail-strip path.

---

### 43. DVD Rip / Copy (Non-DRM Discs Only)

Read unprotected DVD VIDEO_TS structure → MP4/MKV via `libdvdread` + FFmpeg.
Scope: menu-free ISOs, non-commercial home videos. Clearly document the
DRM exclusion in the UI (CSS-encrypted commercial discs unsupported by charter).
Addresses the disc-import use case from Any Video Converter's feature set.

**VOBSUB subtitle scope (iter-5, 2026-05-03):** CCExtractor 0.96.3 [S34]
adds VOBSUB+OCR extraction (image subtitles → SRT) for MP4/MKV; 0.96.5
fixes MXF CEA-708 detection. The DVD rip pipeline can extend to converting
VOBSUB/PGS image subtitles to text-format SRT via the `ccextract` sidecar
(see also Item 63). Note: Tesseract OCR quality is acceptable for
Latin-script sources but degrades on CJK tracks — document in the UI.

Impact: 3 · Effort: 4 · Type: parity
Sources: [S3] (Any Video Converter DVD import, v9.2.0),
[S34] (CCExtractor 0.96.3 VOBSUB OCR support)

---

### 44. DVD Burn / CD Burner (Disc Tools)

Write video files to DVD-Video structure or data files to a CD/DVD using
`growisofs` / `cdrecord` / Windows `IDiscRecorder2` COM API. Wire to existing
`DiscTools` category stubs in ToolboxPage.

**tsMuxeR archived (iter-6, 2026-05-10):** tsMuxeR — which was the standard
Blu-ray TS muxer dependency for Blu-ray authoring — was archived by its
maintainer (justdan96) in April 2025 with development declared stopped [S57].
Blu-ray VIDEO_TS-level output (not data-disc burn) was being tracked as a
stretch goal of this item. That stretch goal must pivot to `eac3to` as the
TS muxing layer, or limit scope to data-DVD burns only and treat Blu-ray
authoring as out-of-scope. Document the dependency gap in the item spec before
implementation begins.

Impact: 2 · Effort: 4 · Type: parity
Sources: [S5] (ToolboxPage.xaml.cs DiscTools stubs),
[S57] (tsMuxeR archived April 2025 — Blu-ray TS muxer dependency gone)

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

**ORT 1.25.0 change (iter-5, 2026-05-03):** ONNX Runtime 1.25.0 [S36]
removed the ArmNN Execution Provider entirely. All Qualcomm NPU inference
must target the **QNN EP** (`onnxruntime.providers.qnn`). Verify QNN EP
availability on Snapdragon X Elite before committing the ARM64 AI path.

**Purfview Whisper-XXL Pro updates (iter-7, 2026-05-02):** r3.256.1 [S78]
adds 4 new VAD models (`silero_v6_fw`, `silero_v6` patched, `nemo_v2`, `ten`
with +0.2 threshold offset — now default). Updated torch 2.8.0+cu128 for
RTX 50xx (CUDA 12.8) support; ORT GPU 1.21.1 (cuDNN 9.x). Pin
`whisper_standalone>=r3.256.1` for RTX 50xx compatibility. Faster-Whisper-XXL
r245.4 adds distil-large-v3.5 model.

Impact: 2 · Effort: 4 · Type: platform
Sources: [S22] (HandBrake #7822 Qualcomm VCE/ARM64 encoder request),
[S36] (ONNX Runtime 1.25.0 — ArmNN EP removal, QNN EP as replacement),
[S78] (Purfview Whisper-XXL Pro r3.256.1 — 4 VAD models, CUDA 12.8)

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

**CCExtractor 0.96.x scope expansion (iter-5, 2026-05-03):** CCExtractor
0.96.3 [S34] adds VOBSUB+OCR for MP4/MKV (image subtitles → SRT); 0.96.5
fixes MXF persistent CEA-708 decoder context. Expand `ccextract` sidecar
scope: (a) VOBSUB/PGS image-format subtitle OCR in MKV/MP4, (b) MXF broadcast
container input, (c) SCC input format. The standalone VOBSUB OCR toolbox entry
is Item 63; this item focuses on broadcast caption extraction (MPEG-TS, MXF,
MPEG-2 PS streams).

Impact: 2 · Effort: 3 · Type: parity
Sources: [S34] (CCExtractor 0.96.3/0.96.5 — VOBSUB OCR, MXF CEA-708 fix),
[S35] (awesome-video subtitle / caption section)

---

### 55. Video Summarizer (AI Condensed Highlight) _(depends on Item 61)_

Ships the `"Planned"` Video Summarizer tile in `AiLabPage.xaml.cs`. The
pipeline:

1. **Transcribe:** Whisper (Item 61 sidecar, `large-v3-turbo` model) → full
   transcript with timestamps.
2. **Summarize:** Feed transcript to a local LLM. Two viable paths:
   - **Phi Silica** (Windows ML / WinAppSDK 2.0, Item 26) — zero additional
     sidecar if WinAppSDK 2.0 migration is complete.
   - **llama.cpp sidecar** with a GGUF-quantized Phi-3 Mini — broader
     compatibility, no WinAppSDK 2.0 gate.
3. **Identify highlight timestamps:** The summarization output contains
   key-event references; cross-reference with PySceneDetect (Item 37 or the
   scene-detect sidecar) to get segment boundaries.
4. **Produce highlight reel:** Extract + concatenate segments (FFmpeg
   `concat` demuxer). Output: new file `<source>_highlights.mp4`.

This is a 3-sidecar orchestration (whisper-stt → llm → videocrush). Scope
carefully and implement stages serially to validate intermediate quality
before full integration. Distinct from SponsorBlock (Item 20) and the
Manual Scene Selector (Item 37).

Impact: 3 · Effort: 4 · Type: leapfrog
Source: [S2] (AiLabPage.xaml.cs "Planned" tile — Video Summarizer)

---

### 64. SystemBackdropElement — In-App Mica / Acrylic Panels _(depends on Item 26)_

Post-WinAppSDK 2.0 migration (Item 26), apply `SystemBackdropElement`
to specific sub-areas of the UI: the navigation sidebar, the AiLab card
grid, and the Settings panel. This lets individual panels use Mica or
Acrylic translucency independently of the window-level backdrop already
set on `MainWindow`.

Gate behind a runtime capability check: fall back silently to solid fill
on Windows 10 or when running under WinAppSDK 1.x (item hard-depends
on Item 26). Surfaced as an optional "Glassmorphism panels" toggle in
Settings.

Impact: 2 · Effort: 1 · Type: UX post-migration polish
Source: [S19] (WinAppSDK 2.0 — SystemBackdropElement in-app panels)

---

### 66. FFmpeg 8.1 D3D12 Hardware Encode / Filter Pipeline _(iter-6)_

FFmpeg 8.1 "Hoare" [S52] ships a complete Direct3D 12 hardware pipeline:
`scale_d3d12`, `deinterlace_d3d12`, `mestimate_d3d12` filters, plus D3D12
H.264 and AV1 hardware encoding. This unlocks GPU-accelerated encode and
filter chains on any DirectX 12 GPU — Intel Arc, AMD RDNA2/3, and Nvidia —
without requiring the CUDA driver stack.

**Value over existing paths:**
- `h264_amf` (AMD) and `h264_nvenc` (Nvidia) already work; this adds **Intel
  Arc** encode support and a vendor-neutral D3D12 alternative.
- `scale_d3d12` runs on the GPU zero-copy for resize+deinterlace chains,
  eliminating the CPU round-trip that `scale_cuda` avoids but `scale` with
  `hwupload` does not.
- `deinterlace_d3d12` replaces `yadif` on D3D12 hardware for broadcast
  interlaced sources.

**Implementation sketch:** Upgrade bundled FFmpeg binary in `tools/ffmpeg/` to
≥8.1. Add `D3D12` encoder group to the encoder selection UI (alongside NVENC /
AMF / QuickSync). Gate on runtime D3D12 device enumeration: `d3d12_device_list`
sidecar helper (one-time probe at first launch, cached).

Also ships: **Vulkan ProRes** encode/decode — relevant to Item 57
(ProRes presets); the `whisper` native filter (transcription without a Python
sidecar, informational — see UC table).

**IAMF note:** FFmpeg 8.1 adds Ambisonic Audio Elements IAMF muxing, which
strengthens the IAMF UC entry below.

Impact: 3 · Effort: 2 · Type: platform + leapfrog
Sources: [S52] (FFmpeg 8.1 "Hoare" — D3D12 encode/filter, Vulkan ProRes, IAMF mux)

---

### 67. ab-av1 VMAF / XPSNR-Guided CRF Auto-Search _(iter-6)_

`ab-av1` [S54] is a Rust CLI tool that binary-searches over CRF values to find
the minimum CRF that achieves a user-specified target VMAF score (or XPSNR as a
compute-lighter alternative). Supports SVT-AV1, x265, and x264. Windows `.exe`
available as a prebuilt binary.

**Use case in UCX:** Users currently set CRF by guesswork or fixed presets. An
"Encode to quality target" mode — "achieve VMAF ≥ 93 at the smallest file size"
— is a leapfrog capability unavailable in any competing Windows converter.

**Implementation sketch:**
1. Bundle `ab-av1.exe` in `tools/ab-av1/`.
2. Add a new `quality-target` mode toggle in the AV1 / HEVC preset editor:
   "Target quality (VMAF)" with a slider 70–97 (default 93) and a
   "Use XPSNR instead (faster)" checkbox.
3. The sidecar runs `ab-av1 auto-encode --target-vmaf <score> ...`, streams
   progress via NDJSON. Estimated time: 5–10 sample encodes before final.
4. Show a "quality scan" progress indicator distinct from the normal progress
   bar so users understand the two-phase nature.

Quality-target encoding is already offered by commercial tools like Shutter
Encoder's VMAF feedback mode and is the dominant approach in the
r/DataHoarder / Handbrake communities for archival quality.

Impact: 3 · Effort: 3 · Type: leapfrog
Sources: [S54] (ab-av1 — VMAF/XPSNR CRF auto-search, SVT-AV1/x265/x264 support)

The Phase 5 audit found three categories under-served by the original
ROADMAP. These items were not in the Round 2 research output because the
research focused on competitor-feature parity rather than internal
quality / extensibility / migration concerns. Tier placement reflects
audit recommendation, not pure user-facing impact.

### 51. Observability — Local Crash Bundle + Structured App Log _(Tier 2)_ — ✅ SHIPPED 2026-05-02

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

**Closing commit:** new `Services/StructuredLogger.cs` (`IStructuredLogger`
interface + NDJSON-per-line writer + 500-entry ring buffer + 30-day
retention prune at startup) and `Services/CrashBundle.cs` (zip with
`system-info.txt`, `exception.txt`, `log-tail.ndjson` ring tail, plus
today's full NDJSON when present). `App.xaml.cs` registers the logger
as a singleton, eagerly resolves it in `OnLaunched`, and routes the
existing `UnhandledException` plus new `AppDomain.UnhandledException`
and `TaskScheduler.UnobservedTaskException` paths through both the
logger and the bundle capture. Daily files land at
`%LocalAppData%/UniversalConverterX/logs/ucx-YYYYMMDD.ndjson`; bundles
at `…/crashes/crash_YYYYMMDD-HHMMSS.zip`. HomePage gains a Diagnostics
card with "Open log folder" + "Export crash bundle" buttons (both
guarded with try/catch + status text fallback). Verbose-off behaviour:
Debug/Info entries skip disk writes but still populate the ring buffer
so a crash bundle has a meaningful tail; Warning/Error/Crash always
reach disk. Build verified Release.

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

### 53. Migration — settings.json Schema Versioning _(Tier 2)_ — ✅ SHIPPED 2026-05-02

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

**Closing commit:** `99015c2` — `ConverterXOptions` gains a
`SchemaVersion` property (default `CurrentSchemaVersion = 2`) and
`LoadFromJson(json, persistMigrated)` public entry point. New
`SettingsMigrations` static class holds an ordered list of
`Action<JsonObject>` migrations; index N transforms v(N+1) → v(N+2).
Legacy JSON without `SchemaVersion` is treated as v1 and upgraded
through the chain. Future-version JSON doesn't crash — older binaries
load what they understand and clamp `SchemaVersion` back to current
on the way out. CLI (`ucx config`) routes through `LoadFromJson` too
(without persisting back, since CLI may inspect read-only files).
7 new xUnit tests cover legacy / current / future / version stamping
/ no-op / fresh-instance / invalid-root paths. `InternalsVisibleTo`
added on Core for test access.

---

## Under Consideration

These need more investigation or community signal before placement.

| Item | Question blocking placement |
|------|-----------------------------|
| **OCR full pipeline** (image → structured text, not just searchable PDF) | Already have `pdfocr`; would a dedicated `ocrkit` sidecar add incremental value? Survey user requests. |
| **VMAF quality reporting** _(✅ shipped — `VmafAnalysisPage.xaml` exists; retired from UC list)_ | ~~Expose `libvmaf` score as a post-conversion metric.~~ Confirmed shipped. |
| **Spatial audio conversion** (Ambisonics ↔ binaural ↔ 5.1 ↔ 7.1) | FFmpeg has partial support; full Ambisonics requires specialized libraries. Assess demand. |
| **Community preset repository** | GitHub-hosted index of contributed presets. Requires governance model, security review of contributed XML, and moderation bandwidth. Assess when preset count warrants it. |
| **EDL / XML timeline import** | Bulk-convert based on an edit decision list (CMX 3600 EDL, Final Cut XML). Niche; assess against demand. |
| **Copilot+ PC / NPU acceleration** | `AICapabilities.HasAICapability` (WinAppSDK 1.8) can gate ONNX inference to NPU. Measure actual throughput gain vs. CUDA GPU before committing. [S27] |
| **Deinterlace framerate auto-doubling** | For Bwdif+Bob deinterlace, automatically double the output framerate (e.g. 25i → 50p). FFmpeg supports this; needs UX decision about when to auto-enable. [S23] |
| **Per-track audio delay control** | Fine-grain delay offset per audio track during conversion (e.g. fix lip-sync issues). `ffmpeg -itsoffset` or `adelay` filter. Common request; needs UI design. [S24] |
| **C2PA Content Credentials embedding** | Embed a `c2pa:actions` assertion in output files recording that UCX processed them. C2PA Spec 2.0 is fully published; Adobe, Microsoft, Google, and Sony are all shipping support. Requires `c2pa-python` (Rust-backed FFI sidecar dependency). Question: is the UCX audience large enough to justify a Rust compile dependency in the sidecar chain? [S30] |
| **IAMF immersive audio pass-through** | Remux IAMF (Immersive Audio Model and Formats, AOMedia) audio streams into MP4/ISOBMFF without transcoding. FFmpeg 8.1 [S52] now ships IAMF Ambisonic Audio Elements muxing, removing the "not yet in upstream FFmpeg" blocker. Question before promoting: identify at least three concrete user workflows. [S37][S52] |
| **Commercial / ad detection (Comskip)** | Detect and optionally remove commercial breaks in OTA/DVR recordings using Comskip. Relevant only to users with ATSC tuner or MPEG-TS recordings. Question: is this a UCX use case or a dedicated DVR-management tool problem? Needs community signal. [S35] |
| **ComfyUI AI Workflow Integration (Item 65)** | OpenShot 3.5.1 [S45] integrates ComfyUI; UCX AiLab could expose a `comfyui-runner` sidecar that submits a JSON workflow to a locally running ComfyUI server (user-managed). Effort 5. Leapfrog candidate if the target audience overlaps with ComfyUI power users. Needs community signal before scoping. |
| **Dia-1.6B / Dia2 next-gen TTS dialogue engine** | Nari Labs Dia-1.6B [S59] is an Apache 2.0, 1.6B-parameter TTS model with two-speaker dialogue synthesis (`[S1]`/`[S2]` speaker tags), voice cloning via audio prompt, and non-verbal sounds (laughs, coughs). Dia2 also released (Nov 2025). More expressive than Kokoro for multi-speaker content. Requires ~6 GB VRAM. Question: does the target user base have GPUs capable of running 1.6B TTS? Assess after Kokoro/F5-TTS sidecar stabilizes. [S59] |
| **Chatterbox voice cloning (zero-shot)** | Resemble AI Chatterbox v0.1.2 [S60] — Apache 2.0 open-source TTS with 3–7s reference audio zero-shot voice clone + perceptual watermarking. Overlaps Dia voice-clone path; assess after Dia evaluation. Lower VRAM requirement than Dia. [S60] |
| **whisper.cpp native Windows sidecar** | whisper.cpp v1.8.4 [S58] now has built-in Silero VAD v6.2 and 12× performance improvement on integrated Intel/AMD GPUs. A C++ binary sidecar would eliminate the Python runtime dependency for basic transcription. Trade-off: loses batched inference (faster-whisper only), speaker diarization, and some post-processing options. Architecture decision: is the install-footprint reduction worth capability regression? [S58] |
| **FFmpeg native `whisper` filter** | FFmpeg 8.0+ includes a built-in `whisper` filtergraph filter for in-pipeline transcription without a Python sidecar. Simpler pipeline but less control than faster-whisper (no batched inference, no speaker diarization, no model selection). Assess as a lightweight fallback path for the subtitle pipeline. [S52] |

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
| S39 | https://github.com/HandBrake/HandBrake/releases/tag/1.11.0 | HandBrake 1.11.0 — ProRes encoder, DNxHR encoder, AMD VCN AV1 10-bit, FFmpeg 8.0.1 |
| S40 | https://github.com/HandBrake/HandBrake/issues/7813 | HandBrake #7813 — auto-scroll queue list to active job |
| S41 | https://github.com/HandBrake/HandBrake/issues/7400 | HandBrake #7400 — auto-move source files to folder after successful encode |
| S42 | https://github.com/HandBrake/HandBrake/issues/7423 | HandBrake #7423 — lock crop/resolution settings across preset changes |
| S43 | https://github.com/HandBrake/HandBrake/issues/7336 | HandBrake #7336 — audio encoder advanced parameters (FDK-AAC cutoff, afterburner, libopus profile) |
| S44 | https://github.com/SYSTRAN/faster-whisper/releases | faster-whisper v1.1.0/v1.2.1 — batched inference 4×, large-v3-turbo model, new VAD models |
| S45 | https://github.com/OpenShot/openshot-qt/releases/tag/v3.5.1 | OpenShot 3.5.1 — ComfyUI AI workflow integration, proxy editing |
| S46 | https://github.com/HandBrake/HandBrake/issues/7339 | HandBrake #7339 — chapter timestamp offset on non-zero-start chapter input |
| S47 | https://github.com/w-okada/voice-changer | w-okada/voice-changer — actively maintained real-time RVC fork (original RVC unmaintained since 2023) |
| S48 | https://github.com/Purfview/whisper-standalone-win/releases | Purfview Whisper-XXL Pro r3.256.1 — silero_v6/nemo_v2/ten VAD models, torch 2.8+CUDA12.8 |
| S49 | https://github.com/ggml-org/whisper.cpp/releases | whisper.cpp v1.8.3–v1.8.4 — Silero VAD v6.2 built-in, 12× iGPU speedup, GPU device selection |
| S50 | https://github.com/nari-labs/dia | Nari Labs Dia-1.6B — two-speaker dialogue TTS, voice cloning via audio prompt, Apache 2.0; Dia2 Nov 2025 |
| S51 | https://github.com/resemble-ai/chatterbox | Chatterbox TTS v0.1.2 — Apache 2.0 open-source TTS, zero-shot voice clone, safetensors |
| S52 | https://ffmpeg.org/index.html | FFmpeg 8.1 "Hoare" (2026-03-16) — D3D12 encode/filter, scale_d3d12, Vulkan ProRes, IAMF mux, whisper filter |
| S53 | https://github.com/Rikorose/DeepFilterNet/releases | DeepFilterNet v0.5.0/v0.5.3/v0.5.6 — DeepFilterNet3 model, MVDR/Wiener multi-frame filtering, attenuation limit |
| S54 | https://github.com/alexheretic/ab-av1 | ab-av1 — Rust CLI VMAF/XPSNR-guided CRF auto-search for SVT-AV1/x265/x264; Windows .exe |
| S55 | https://mkvtoolnix.download/doc/NEWS.md | MKVToolNix v91–v98 NEWS.md — TrueHD in MP4 (v97), --date arg (v95), display-matrix rotation, commentary auto-flag |
| S56 | https://github.com/mifi/lossless-cut/releases | LosslessCut v3.67.2–v3.68.0 — estimated segment size (#2630), mutateSegmentsByExpr, FILES template, YT chapters |
| S57 | https://github.com/justdan96/tsMuxeR | tsMuxeR — archived April 2025; Blu-ray TS muxer dependency declared dead by maintainer |
| S58 | https://github.com/yt-dlp/yt-dlp/releases | yt-dlp 2026.02.21 — CVE-2026-26331 (--netrc-cmd command injection fixed); browser impersonation |
| S59 | https://github.com/nari-labs/dia | Dia-1.6B TTS detail source (Nari Labs) — Apache 2.0, voice cloning, non-verbals, dialogue speaker tags |
| S60 | https://github.com/resemble-ai/chatterbox | Chatterbox detail source — emotion control, perceptual watermarking, Python bindings |
| S61 | https://github.com/Breakthrough/PySceneDetect/releases | PySceneDetect v0.6.7 — EDL end-timestamp fix (DaVinci Resolve import correct), FFmpeg 8.0 bundled |
| S62 | https://github.com/HandBrake/HandBrake/issues/7467 | HandBrake PR #7467 — VAAPI H.264/AV1 hardware encoding (AMD Radeon, Mesa 25), milestone 1.12.0 |
| S63 | https://github.com/HandBrake/HandBrake/issues/7848 | HandBrake #7848 — auto-increment filename collision for batch exports |
| S64 | https://github.com/SubtitleEdit/subtitleedit/releases | SubtitleEdit v5.0.0-beta20 (April 29 2026) — .NET rewrite actively progressing, 20 betas |
| S65 | https://github.com/SYSTRAN/faster-whisper/releases | faster-whisper v1.1.0–v1.2.1 — batched inference 4×, large-v3-turbo, silero_v6 VAD |
| S66 | https://github.com/alexheretic/ab-av1/releases | ab-av1 Windows releases — prebuilt .exe, XPSNR support added as VMAF alternative |
| S67 | https://github.com/HandBrake/HandBrake/issues/7822 | HandBrake #7822 — Qualcomm Snapdragon X Elite ARM64 hardware encoder request |
| S68 | https://github.com/gianni-rosato/svt-av1-psy | SVT-AV1-PSY end-of-life announcement (April 2025); Gianni Rosato project retirement; successor SVT-AV1-HDR link |
| S69 | https://github.com/rigaya/NVEnc/releases | NVEncC 9.15–9.16 — Vship SSIMULACRA2/Butteraugli/CVVDP GPU metrics, parallel multi-GPU encoding |
| S70 | https://github.com/rigaya/QSVEnc/releases | QSVEncC 8.11 — `--vpp-ivtc` / `--vpp-bwdif` deinterlace; msmooth/msharpen filters; libopus layout fix; libvpl 2.16 |
| S71 | https://github.com/rigaya/VCEEnc/releases | VCEEnc 9.05 — AMF 1.5.0 (Adrenalin 25.10.2+); Dolby Vision output; avcodec encoder (SVT-AV1 with VCE filters); parallel file-split encoding |
| S72 | https://github.com/MediaArea/MediaInfo/releases | MediaInfo 26.01 — confirmed latest (Feb 4, 2026) |
| S73 | https://github.com/yt-dlp/yt-dlp/releases | yt-dlp 2026.03.17 — latest release; 3 updates after CVE-2026-26331 fix |
| S74 | https://github.com/microsoft/WindowsAppSDK/releases/tag/v2.0.1 | WinAppSDK 2.0.1 (April 29, 2026) — `SystemBackdropElement` + `CornerRadius`; storage pickers; ORT 1.24.5 bundled |
| S75 | https://codeberg.org/Line-fr/Vship | Vship library — GPU-accelerated SSIMULACRA2, Butteraugli, CVVDP metrics; HIP/CUDA/Vulkan; precompiled binaries |
| S76 | https://github.com/rust-av/Av1an/releases | Av1an v0.5.2 — per-scene quality encoding; scene-change speedup; SVT-AV1/x264/x265/VP9; VapourSynth dependency |
| S77 | https://github.com/obsproject/obs-studio/releases | OBS Studio 32.1.2 — audio mixer revamp, WebRTC simulcast; limited UCX relevance |
| S78 | https://github.com/Purfview/whisper-standalone-win/releases | Purfview Whisper-XXL Pro r3.256.1 (Nov 7) — 4 new VAD models (silero_v6_fw, silero_v6, nemo_v2, ten); torch 2.8+cu128; ORT GPU 1.21.1 |
| S79 | https://github.com/Rikorose/DeepFilterNet/releases | DeepFilterNet v0.5.6 — latest stable; v0.5.4 adds Python 3.11 + macOS/Linux aarch64 wheels; v0.5.3 reverberant attenuation limit |
| S80 | https://github.com/HandBrake/HandBrake/issues/7828 | HandBrake #7828 — encode success reported when video track truncates 50% through; audio/video duration mismatch silent |
| S81 | https://github.com/HandBrake/HandBrake/issues/7801 | HandBrake #7801 — Opus LFE channel distortion/clipping (DTS-HD 5.1 conversion); HandBrake-specific, FFmpeg path unaffected |
| S82 | https://github.com/HandBrake/HandBrake/issues?milestone=5&state=open | HandBrake 1.12.0 milestone open issues (12+ pending) |
| S83 | https://github.com/Uranite/HandBrake-SVT-AV1-HDR | Uranite HandBrake-SVT-AV1-HDR community build — nightly patches + releases; CI for Windows/macOS/Linux; official FFmpeg-Builds SVT-AV1-HDR integration available |
| S84 | https://github.com/zbabac/VCT | VCT (Video Converter & Transcoder) v1.11.0 — C# FFmpeg frontend, batch encoding, MKV transcoding, manual ffmpeg command editing, updated Apr 2026 |
| S85 | https://github.com/Thavarshan/comet | Comet — TypeScript/Electron cross-platform media converter (macOS/Windows/Linux), video/audio/image, bulk conversion, dark mode, Nov 2024 |
| S86 | https://github.com/LorenzoDePasquale/FF-Video-Converter | Neptune (FF-Video-Converter rebranded) — .NET 5 rewrite, HDR10 encoding, color adjustments (brightness/contrast/saturation), pixel format conversion, integrated player, Reddit downloader |
| S87 | https://github.com/WyattBlue/auto-editor | auto-editor v0.7+ — CLI for automatic silence/motion removal, Nim language, per-track threshold DSL, margin control, parallel export |
| S88 | https://github.com/OpenShot/openshot-qt/releases | OpenShot 3.5.1 (Apr 2026) — proxy editing for performance, multi-selection trimming, ComfyUI workflows, UI scaling toggle, DPI-aware rendering |
| S89 | https://github.com/deezer/spleeter | Spleeter 2.1.0+ — Music source separation (vocals/drums/bass/other), TensorFlow, multi-GPU optional, CPU path available |
| S90 | https://github.com/google-ai-edge/mediapipe | MediaPipe — Google on-device ML library, vision (object detect, pose, hand, gesture), text, audio tasks; cross-platform |
| S91 | https://github.com/rust-av/av1-grain | av1-grain Rust crate — AV1 film grain synthesis, photon noise table generation compatible with SVT-AV1/aomenc/rav1e, per-ISO calibration |
| S92 | https://github.com/WyattBlue/auto-editor | auto-editor v0.7+ — CLI for automatic silence/motion removal, Nim language, per-track threshold DSL, margin control, parallel export |
| S93 | https://github.com/OpenShot/openshot-qt/releases | OpenShot 3.5.1 (Apr 2026) — proxy editing for performance, multi-selection trimming, ComfyUI workflows, UI scaling toggle, DPI-aware rendering |
| S94 | https://github.com/deezer/spleeter | Spleeter 2.1.0+ — Music source separation (vocals/drums/bass/other), TensorFlow, multi-GPU optional, CPU path available |
| S95 | https://github.com/google-ai-edge/mediapipe | MediaPipe — Google on-device ML library, vision (object detect, pose, hand, gesture), text, audio tasks; cross-platform |
| S96 | https://github.com/TagStudioDev/TagStudio | TagStudio — Photo/file management with tagging; Python; user-focused UX; AI image discovery |
| S97 | https://github.com/meilisearch/meilisearch | Meilisearch — Lightning-fast full-text search with AI-powered hybrid search; Rust backend |
| S98 | https://github.com/quodlibet/mutagen | Mutagen — Python audio metadata handling (ID3v2, Vorbis, MP4, FLAC, WavPack, TA, APE, etc.) |
| S99 | https://github.com/qdrant/qdrant | Qdrant — Vector database + vector search engine; 1M+ vectors; Rust |
| S100 | https://github.com/ossrs/srs | SRS (Simple Realtime Server) — RTMP/WebRTC/HLS/SRT/DASH/GB28181; H.264/H.265/AV1/VP9; Opus/G.711; May 2026 |
| S101 | https://github.com/bluenviron/mediamtx | mediamtx — SRT/WebRTC/RTSP/RTMP/LL-HLS media proxy in Go; 40+ protocol combinations; May 2026 |
| S102 | https://github.com/ant-media/Ant-Media-Server | Ant Media Server — Ultra-low latency streaming (<0.5s WebRTC); adaptive bitrate; transcoding & scaling; Java |
| S103 | https://github.com/gpac/gpac | GPAC — Ultramedia toolkit: next-gen transcoding, packaging, delivery; MP4 box, DASH, HLS, ISOM; Apr 2026 |
| S104 | https://github.com/CasparCG/server | CasparCG — Professional broadcast playback server; 24/7 production since 2006; multi-output support; C++ |
| S105 | https://github.com/argoproj/argo-workflows | Argo Workflows — Kubernetes workflow orchestration (Netflix Maestro equivalent); May 2026 |
| S106 | https://github.com/lost-pixel/lost-pixel | Lost Pixel — OSS alternative to Percy/Chromatic/Applitools; visual regression testing; Apr 2026 |
| S107 | https://github.com/kubeshop/testkube | Testkube — Test orchestration for cloud-native apps; Kubernetes-native; May 2026 |
| S108 | https://github.com/formatjs/formatjs | FormatJS (react-intl) — i18n/l10n for React; pluralization, date/time formatting, message extraction; May 2026 |
| S109 | https://github.com/WeblateOrg/weblate | Weblate — Web-based localization platform; version control integration; crowdsourced translation; May 2026 |
| S110 | https://github.com/caddyserver/caddy | Caddy — HTTP/1-2-3 web server with automatic HTTPS; extensible; May 2026 |
| S111 | https://github.com/grafana/k6 | k6 (Grafana) — Modern load testing tool in Go/JavaScript; performance benchmarking; May 2026 |
| S112 | https://github.com/prometheus/prometheus | Prometheus — Time-series monitoring + alerting system; foundational to observability; Apr 2026 |
| S113 | https://github.com/grafana/grafana | Grafana — Composable observability platform; metrics/logs/traces visualization; May 2026 |
| S114 | https://github.com/louislam/uptime-kuma | Uptime Kuma — Self-hosted monitoring; lightweight; status page; May 2026 |
| S115 | https://github.com/n8n-io/n8n | n8n — Workflow automation platform; 400+ integrations; native AI; May 2026 |
| S116 | https://github.com/hoppscotch/hoppscotch | Hoppscotch — Open-source API development (Postman alternative); offline/on-prem; May 2026 |
| S117 | https://github.com/neovim/neovim | Neovim — Vim fork with plugin architecture; extensible; May 2026 |
| S118 | https://github.com/NVIDIA/TensorRT | NVIDIA TensorRT — High-performance deep learning inference on NVIDIA GPUs; C++; Apr 2026 |
| S119 | https://github.com/NVIDIA/cutlass | NVIDIA CUTLASS — CUDA templates for high-performance linear algebra; Apr 2026 |
| S120 | https://github.com/Syllo/nvtop | nvtop — GPU monitoring for AMD/Apple/Huawei/Intel/NVIDIA/Qualcomm; Apr 2026 |
| S121 | https://github.com/dusty-nv/jetson-inference | Jetson Inference — NVIDIA Jetson deep learning inference; TensorRT; Oct 2025 |
| S122 | https://github.com/optiscaler/OptiScaler | OptiScaler — GPU upscaling/frame gen bridge; DLSS/FSR/XeSS support; May 2026 |
| S123 | https://github.com/pytorch/pytorch | PyTorch — Tensors + dynamic neural networks in Python with GPU support; May 2026 |
| S124 | https://github.com/huggingface/transformers | Hugging Face Transformers — Model-definition framework for text/vision/audio/multimodal inference/training; May 2026 |
| S125 | https://github.com/deepspeedai/DeepSpeed | DeepSpeed — Deep learning optimization library; distributed training/inference; May 2026 |
| S126 | https://github.com/lz4/lz4 | LZ4 — Extremely fast compression algorithm; C; May 2026 |
| S127 | https://github.com/borgbackup/borg | Borg — Deduplicating archiver with compression + authenticated encryption; Apr 2026 |
| S128 | https://github.com/opencv/opencv | OpenCV — Open source computer vision library; C++; Apr 2026 |
| S129 | https://github.com/roboflow/supervision | Roboflow Supervision — Reusable computer vision tools; Python; Apr 2026 |
| S130 | https://github.com/GraphiteEditor/Graphite | Graphite — Open-source 2D content creation suite; node-based procedural editing; May 2026 |
| S131 | https://github.com/puppeteer/puppeteer | Puppeteer — JavaScript API for Chrome/Firefox automation; browser testing; Apr 2026 |
| S132 | https://github.com/storybookjs/storybook | Storybook — Industry standard workshop for building/documenting/testing UI components; May 2026 |
| S133 | https://github.com/microsoft/playwright | Playwright — Web testing + automation framework (Chromium/Firefox/WebKit); May 2026 |
| S134 | https://github.com/jestjs/jest | Jest — Delightful JavaScript testing framework; May 2026 |
| S135 | https://github.com/pytest-dev/pytest | Pytest — Feature-rich Python testing framework; May 2026 |
| S136 | https://github.com/avajs/ava | AVA — Node.js test runner with concurrent execution; Apr 2026 |
| S137 | https://github.com/pydantic/pydantic | Pydantic — Data validation using Python type hints; May 2026 |
| S138 | https://github.com/apple/pkl | Apple Pkl — Configuration as code language with rich validation + tooling; Apr 2026 |
| S139 | https://github.com/567-labs/instructor | Instructor (LLM) — Structured outputs for LLMs; validation; Apr 2026 |
| S140 | https://github.com/twpayne/chezmoi | Chezmoi — Dotfile management across multiple machines (securely); Apr 2026 |
| S141 | https://github.com/TomWright/dasel | Dasel — Select, filter, map data in JSON/YAML/TOML/CSV; Apr 2026 |
| S142 | https://github.com/protocolbuffers/protobuf | Protocol Buffers — Google data interchange format; language/platform-neutral; May 2026 |
| S143 | https://github.com/google/flatbuffers | FlatBuffers — Memory-efficient serialization library (zero-copy); Apr 2026 |
| S144 | https://github.com/toon-format/toon | TOON — Token-Oriented Object Notation; compact JSON for LLM prompts; Apr 2026 |
| S145 | https://github.com/ijl/orjson | Orjson — Fast Python JSON with dataclass/datetime/numpy support; Apr 2026 |
| S146 | https://github.com/gabime/spdlog | spdlog — Fast C++ logging library; structured logging; Apr 2026 |
| S147 | https://github.com/grafana/loki | Grafana Loki — "Prometheus for logs"; log aggregation system; May 2026 |
| S148 | https://github.com/Delgan/loguru | Loguru — Python logging made simple; structured logging; Apr 2026 |
| S149 | https://github.com/apache/skywalking | Apache SkyWalking — APM system; distributed tracing + performance monitoring; Apr 2026 |
| S150 | https://github.com/ossrs/srs | SRS (Simple Realtime Server) — RTMP/WebRTC/HLS/SRT/DASH; streaming/broadcast reference; May 2026 |
| S151 | https://github.com/deezer/spleeter | Spleeter — Music source separation (vocals/drums/bass/other); TensorFlow; May 2026 |
| S152 | https://github.com/TagStudioDev/TagStudio | TagStudio — Photo/file management with tagging; user-focused UX; Apr 2026 |
| S153 | https://github.com/fraunhoferhhi/vvenc/releases | vvenc 1.14.0 — VVC/H.266 encoder, capped CQF mode, film-grain analysis, ARM SIMD/SVE, Jan 2026 |
| S154 | https://github.com/libjxl/libjxl/releases | libjxl 0.11.2 — JPEG XL ref impl, CVE-2025-12474 (tile dim) + CVE-2026-1837 (gray transform), Sep 2025 |
| S155 | https://github.com/AOMediaCodec/libavif/releases | libavif 1.4.0–1.4.1 — AVIF reference, JPEG gain map import, Sample Transform 16-bit, PNG cICP decode, Mar 2026 |
| S156 | https://github.com/xiph/opus/releases | Opus 1.5 / 1.5.2 — DRED neural packet loss recovery, Deep PLC, 4th/5th order Ambisonics, AVX2 fixes, Sep 2025 |
| S157 | https://www.reddit.com/r/handbrake/top/ | r/handbrake community signal — top-of-year praise post + recurring complaints (preset confusion, queue fragility, HDR), Dec 2025 |
| S158 | https://github.com/GyanD/codexffmpeg/releases | gyan.dev FFmpeg Windows builds — current 8.1 release + nightly git builds, regularly refreshed (Mar–Apr 2026) |
| S159 | https://github.com/quietvoid/dovi_tool/releases | dovi_tool 2.3.2 — Dolby Vision RPU extract/inject/mux/demux/editor; FFmpeg-compat NALU placement; Apr 2025 |
| S160 | https://github.com/quietvoid/hdr10plus_tool/releases | hdr10plus_tool 1.7.2 — HDR10+ dynamic metadata extract/inject/edit/plot; MKV input stable; Dec 2024 |
| S161 | https://github.com/xinntao/Real-ESRGAN/releases | Real-ESRGAN — animevideov3 model + ncnn-vulkan portable Windows binary (Intel/AMD/Nvidia GPU) |
| S162 | https://github.com/bloc97/Anime4K | Anime4K — GLSL real-time shader chain for 1080p anime → 4K via mpv/Plex |
| S163 | https://github.com/vapoursynth/vapoursynth/releases | VapourSynth R75 — Python-scripted frame-server, _Range H.273 prop, optimized plugin manifests; Mar 2026 |
| S164 | https://github.com/HaveAGitGat/Tdarr | Tdarr V2 — distributed conditional transcoding, server+node architecture, Sonarr/Radarr/Plex alongside |
| S165 | https://github.com/PyAV-Org/PyAV/releases | PyAV v17.0.0/v17.0.1 — cuvid hw-memory zero-copy via dlpack, add_mux_stream() remux path; Mar 2026 |
| S95 | https://github.com/google-ai-edge/mediapipe | MediaPipe — Google on-device ML library, vision (object detect, pose, hand, gesture), text, audio tasks; cross-platform |
| S96 | https://github.com/TagStudioDev/TagStudio | TagStudio — Photo/file management with tagging; Python; user-focused UX; AI image discovery |
| S97 | https://github.com/meilisearch/meilisearch | Meilisearch — Lightning-fast full-text search with AI-powered hybrid search; Rust backend |
| S98 | https://github.com/quodlibet/mutagen | Mutagen — Python audio metadata handling (ID3v2, Vorbis, MP4, FLAC, WavPack, TA, APE, etc.) |
