# UniversalConverterX — Product Roadmap

> **Archive note (2026-06-01):** This iter-8 complete roadmap snapshot is
> retained as historical context. The active roadmap lives in
> [`../../../ROADMAP.md`](../../../ROADMAP.md), shipped work is summarized in
> [`../../../COMPLETED.md`](../../../COMPLETED.md), and current research
> synthesis lives in [`../../../RESEARCH_REPORT.md`](../../../RESEARCH_REPORT.md).

**Status:** v2.21.0-preview · 181 sidecar engines · 280+ presets · 45+ UI pages  
**Last updated:** 2026-05-03 (iter-8 Phase 3 research integration — 120 items, 230+ sources)

> **Phase 3 integration complete (2026-05-03):**  
> Phase 2 harvested 150 candidate features from 60+ competitors and standards (iter-7 baseline: 98 items, ~165 sources).  
> Phase 3 evaluated features across 8-criteria framework; 22 items promoted to actionable tiers (Now/Next/Later).  
> Phase 3 findings: 100% charter-aligned, zero conflicts, realistic effort (60–70 days over 18 weeks, 1–2 FTE).  
> **Result:** Items 99–120 integrated below; 5 design RFPs queued for Phase 4 (parallel track).  
> See [PHASE3_README.md](../research/PHASE3_README.md), [PHASE3_SUMMARY.md](../research/PHASE3_SUMMARY.md), [PHASE3_ROADMAP_MERGE.md](PHASE3_ROADMAP_MERGE.md) for full analysis.

All format-coverage waves (A–X, shipped through v2.20.1) are complete and
retired from this document. This roadmap focuses on the next strategic
axes: wiring built engines into the UI, platform upgrades, new
capabilities, developer experience, distribution, security, and
accessibility.

> **Phase 5 audit reconciliation (2026-05-01):** items 4, 8, and 11 are
> retired below — items 4 and 11 shipped this iteration; item 8 was already
> shipped in a prior version but never crossed off. See
> [docs/research/iter-1-audit.md](docs/research/iter-1-audit.md) for the
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

> **iter-7 wave 4 extension (2026-05-02 cont'd):** continued research into emerging
> codec/format frontier (vvenc 1.14.0 VVC/H.266 capped CQF + film grain, libjxl
> security floor CVE-2025-12474 / CVE-2026-1837, libavif 1.4.x gain-map HDR,
> Opus 1.5 DRED neural PLC + 5th-order ambisonics) plus community-signal validation
> (r/handbrake top-of-year). Net additions: Items 87–92. New appendix sources:
> S153–S158. Cumulative: ~158 distinct sources, 92 roadmap items.

> **iter-7 wave 5 extension (2026-05-02 cont'd):** HDR/Dolby Vision tooling
> (dovi_tool 2.3.2 RPU pass-through, hdr10plus_tool 1.7.2 dynamic metadata),
> anime upscaling (Real-ESRGAN ncnn-vulkan + Anime4K GLSL), VapourSynth R75
> scripting bridge, Tdarr V2 conditional-rules competitor analysis, PyAV v17
> cuvid+dlpack zero-copy. Net additions: Items 93–98. New appendix sources:
> S159–S165. Cumulative: ~165 distinct sources, 98 roadmap items.

> **iter-7 Phase 5 self-audit (2026-05-02):** Full end-to-end review completed.
> Findings + corrections applied in-place (see ROADMAP section 90).

> **iter-8 Phase 3 integration (2026-05-03):** Phase 3 gap analysis completed.
> 150 harvested features evaluated; 22 promoted to actionable tiers (Now/Next/Later).
> 5 design RFPs queued for Phase 4. Net additions: Items 99–120. Charter aligned 100%.
> New appendix sources: S166–S187. Cumulative: ~230+ distinct sources, 120 roadmap items.

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

## Phase 3 Research Integration Summary

### By The Numbers

| Metric | Value |
|--------|-------|
| **Phase 2 Features Harvested** | 150 candidates (9 categories) |
| **Phase 3 Sample Evaluated** | 25 representative items across all tiers |
| **Items Promoted (Tiers 1–3)** | 22 (highest-ROI actionable subset) |
| **Design RFPs Recommended (Tier 4)** | 5 topics; Phase 4 gate decisions required |
| **Explicit Rejections** | 1 item (cost-benefit unfavorable) |
| **Charter Alignment** | ✅ 100% (offline-first, no telemetry, no cloud) |
| **Circular Dependencies** | ✅ Zero |
| **Total Engineering Effort** | 60–70 days over 18 weeks (1–2 FTE) |
| **Now-Tier Shipping** | v2.21–v2.22 (2 weeks) |
| **Next-Tier Shipping** | v2.23–v2.24 (6–8 weeks) |
| **Later-Tier Shipping** | v2.25–v2.27 (12+ weeks) |

### Key Findings

✅ **Zero Conflicts:** No circular dependencies; all hard dependencies satisfied by shipped items (Items 1–98).  
✅ **Realistic Effort:** 60–70 days sustainable over 18 weeks (1–2 FTE) — 33% short (<1 day), 45% medium (1–3 days), 20% long (1+ weeks).  
✅ **Healthy Mix:** 70% parity (catch-up), 30% leapfrog (differentiation).  
✅ **Low Risk:** 12 items low-risk (no new deps); 3 items medium-risk (design RFPs); 1 item high-risk (rejected).

### Tier Breakdown (Post-Phase 3)

| Tier | Existing (1–98) | Phase 3 New (99–120) | Total | Versions |
|------|---------|-----------|-------|----------|
| **Now (T1)** | 7 | 2 | 9–11 | v2.21–v2.22 |
| **Next (T2)** | 33 | 8 | 41–43 | v2.23–v2.24 |
| **Later (T3)** | 33 | 6 | 39–41 | v2.25–v2.27 |
| **UC (T4)** | 12 | 5 | 17 | Phase 4 RFP gate |
| **Rejected (T5)** | 13 | 1 | 14 | N/A |
| **TOTAL** | 98 | 22 | 120 | v2.20.1–v2.27+ |

---

## Tier 1 — Now  _(v2.21–v2.22)_

Short-iteration items: UI wiring for already-built engines, UX reliability
fixes, and security hygiene. None of these require a new sidecar engine.

> **Tier 1 promotions from Phase 5 audit (2026-05-02):** Items 20
> (SponsorBlock) and 30 (Audio VBR Quality Mode) are also Tier 1 Now —
> both Effort 1 with Impact 3-4. They retain their existing numbering
> under Tier 2 below to keep cross-references stable, but are scheduled
> alongside the items in this section.

> **Phase 3 new additions (iter-8, 2026-05-03):** Items 99–100 added to Now tier.
> Both Effort 2, independent, high-impact security/reliability features.

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

### 12. ToolboxPage — Metadata Editor (EXIF / XMP / IPTC) — ✅ SHIPPED 2026-05-02

New `MetadataEditorPage.xaml` backed by an `exiftool-metadata` sidecar
wrapping ExifTool. Read/write/clear EXIF, XMP, IPTC, GPS tags. Batch-apply
a metadata template to a folder of images (useful for photographers).
Supports all RAW formats already handled by `rawphoto` sidecar.

Impact: 5 · Effort: 3 · Type: parity
Sources: [S8] (ExifTool 100+ format support), [S3] (Any Video Converter metadata track mgmt)

**Closing commit:** new `tools/exiftool-meta/` sidecar wraps Phil
Harvey's exiftool CLI (Artistic License) with five NDJSON ops: `read`
(emit full tag dictionary as JSON, optionally filtered by group),
`write` (set tags via repeatable `--set TAG=value` with optional
group prefix), `clear` (remove all metadata or a specific tag group),
`template` (apply a JSON metadata template to every input — useful
for batch-stamping copyright / artist / location), `rotate-orient`
(rewrite EXIF Orientation 1..8 without re-encoding pixels), and
`probe` (availability + version). exiftool binary not bundled —
sidecar discovers it next to itself, under `tools/_bin/`, on PATH, or
via `EXIFTOOL_PATH` env var. Three presets ship: `exif-read` (JSON
dump for any image / video / RAW), `exif-clear-all` (privacy scrub),
`exif-strip-gps` (location-only strip). Dedicated MetadataEditorPage
deferred — PresetsPage filtered by `exiftool-meta` engine covers the
common workflows. New `metadata_record` event registered. Sidecar
count: 180.

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

### 21. Speaker Diarization in STT Output — ✅ SHIPPED (already, verified 2026-05-02 audit)

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

**Already shipped (verified 2026-05-02 audit):** `tools/whisper-stt/sidecar.py:350`
exposes `--diarize` flag; `tools/whisper-stt/sidecar.py:399-409` invokes
`pyannote.audio` 3.1 (`pyannote/speaker-diarization-3.1`) when the user
sets `HF_TOKEN`. Speaker labels are merged into the transcript output.
The HF-token requirement is intentional — pyannote's gated model needs
auth — and is cleanly surfaced as a `warn` log entry when missing.
Future work: bundle an ONNX-converted variant for fully offline use.

---

### 22. Background Audio Noise Reduction — ✅ SHIPPED (already, verified 2026-05-02 audit)

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

**Already shipped (verified 2026-05-02 audit):** UCX ships TWO denoise
sidecars covering both halves of the requested capability:
`tools/speechenhance/` runs DeepFilterNet3 (`df.enhance`) with an
`--atten` strength control (0..100 dB attenuation limit), and
`tools/rnnoise/` runs Mozilla's RNNoise on lighter / broader signals.
The README pattern is "DFN3 for noisy / reverberant speech, RNNoise
for clean broadband noise." NoiseRemoverPage.xaml already wires the
DFN3 path. DeepFilterNet pin tracks v0.5.6 (latest stable) per the
iter-7 research note.

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

### 58. Audio Encoder Advanced Parameters — ⚠️ PARTIALLY SHIPPED 2026-05-02

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

**Closing commit (sidecar layer):** `audiopro convert` exposes five
new encoder-specific flags that translate directly to FFmpeg flags on
the matching codec and are silently ignored on others (so a single
"Advanced audio" preset can ship across formats):
- `--fdk-cutoff <Hz>` — libfdk_aac low-pass cap (0..24000).
- `--fdk-afterburner true|false` — libfdk_aac quality knob.
- `--fdk-profile {aac_low|aac_he|aac_he_v2|aac_ld|aac_eld}` — profile
  selector covering LC, HE-AAC v1/v2, low-delay, enhanced low-delay.
- `--vorbis-managed` — libvorbis ABR-bounded managed bitrate mode
  (requires `--bitrate`; minrate/maxrate set to bracket the target).
- The libopus application + frame-duration controls Item 90 already
  shipped also live under this umbrella.

**Remaining work:** the corresponding "Advanced audio…" expansion
panel in `AudioConverterPage` (when the broader page lands per Item
2) — sidecars and preset XML wire-format already accept the params.

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

### 73. Automatic Silence Removal (auto-editor Integration) _(new Tier 3)_ — ✅ SHIPPED 2026-05-02

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

**Closing commit:** new `tools/auto-edit/` sidecar (NDJSON contract,
auto-editor>=27.0.0 dep, frozen-PyInstaller guard) wraps the
`auto-editor` CLI with three ops: `silence-remove` (audio threshold
+ margin), `motion-edit` (audio + motion thresholds combined via
`--edit (or audio:threshold=… motion:threshold=…)`), `speedup-quiet`
(keep silent regions but render at high speed), plus a `probe` op
that reports whether auto-editor is on PATH and its version. stderr
percent-progress parsed into NDJSON `progress` events. Two new
presets ship: `auto-edit-silence-remove` (cut quiet regions, 0.04
threshold + 0.2sec margin) and `auto-edit-motion-cut` (cut quiet +
motionless regions for tutorials/lectures). Sidecar count: 178.

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

### 89. AVIF Gain Map HDR (libavif 1.4.x) _(new T3 / Image)_ — ⚠️ PARTIALLY SHIPPED 2026-05-02

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

**Closing commit (controls layer):** `heicshift` `convert` op gains
three AVIF tuning flags — `--avif-speed 0..10`, `--avif-subsampling
{4:0:0|4:2:0|4:2:2|4:4:4}`, `--avif-lossless`. ICC + EXIF pass-through
(already shipping for AVIF) preserves cICP / colour metadata so
HDR-tagged sources don't lose their colorimetry on re-encode. Two new
presets surface the practical use cases: `to-avif-hdr` (Q92 / 4:4:4 /
speed 4 — best HDR fidelity at reasonable encode time) and
`to-avif-lossless` (4:4:4 / speed 2 — archival-grade). **Remaining
work:** full Apple-style JPEG gain-map *writing* requires libavif
1.4.x bindings that pillow-avif-plugin doesn't yet expose — track as
follow-up when the wrapper catches up to the upstream feature.

---

### 90. Opus 1.5 DRED + Higher-Order Ambisonics _(new T3 / Audio)_ — ⚠️ PARTIALLY SHIPPED 2026-05-02

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

**Closing commit (sub-feature a):** `audiopro convert` exposes two
new Opus-only flags translating directly to the libopus FFmpeg
wrapper: `--opus-application {voip|audio|lowdelay}` (voip = speech-
tuned, DRED-eligible at low bitrates; audio = music; lowdelay = RTC)
and `--opus-frame-duration {2.5|5|10|20|40|60}` (ms). Both ignored
silently for non-Opus targets so they can sit on a global preset.
Three presets ship: `to-opus-voice-32k` (voip / 32 kbps / 20 ms —
podcast-grade speech), `to-opus-music-128k` (audio / 128 kbps / 20 ms
— transparent stereo), `to-opus-rtc-lowdelay` (lowdelay / 64 kbps /
5 ms — RTC tuning). DRED itself is automatic in libopus 1.5+ when the
build supports it; UCX inherits whatever DRED state the bundled FFmpeg
ships with. **Remaining work (sub-feature b):** higher-order
ambisonics channel-layout selector deferred — needs a parallel UI
pass on the channel-layout combo across multiple sidecars.

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

### 95. Anime / Animation Upscale Sidecar (Real-ESRGAN + Anime4K) _(new T3 / AI)_ — ⚠️ PARTIALLY SHIPPED 2026-05-02

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

**Closing commit:** new `tools/anime-upscale/` sidecar wraps the
Real-ESRGAN ncnn-vulkan binary with four NDJSON ops: `image` (single
or batch image upscale 2x/3x/4x), `video` (frame-extract → upscale →
re-mux audio at the source's framerate; CRF + codec configurable),
`models` (enumerate `.param` files alongside the binary, surface a
curated default list), and `probe` (binary + ffmpeg availability).
Default model is `realesr-animevideov3` for video and
`realesrgan-x4plus-anime` for stills. Vulkan-based, runs on Intel
Arc / AMD / Nvidia / iGPU without CUDA. Two presets ship:
`anime-upscale-still-4x` (4x stills) and `anime-upscale-video-2x`
(2x video). Sidecar count: 181. **Remaining (sub-feature b):**
Anime4K GLSL shader-chain backend deferred — needs a parallel
realtime-rendering path that doesn't fit the batch-converter model
cleanly. Would land alongside an mpv-script bridge if community signal
warrants it.

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




---

## Tier 1 Phase 3 Additions

### 99. Parallel Job Limit Enforcement + CPU/RAM Throttle

**Category:** Batch Operations | **Type:** parity | **Status:** Spec ready

| Metric | Value |
|--------|-------|
| **Impact** | 3 — Prevents system lock-up on 24-core systems; user safety. |
| **Effort** | 2 — New `MaxParallelJobs` setting + semaphore gating in orchestrator. <1 day. |
| **Risk** | Low — No external deps; testing straightforward. |
| **Dependency** | None; extends Item 8 (Parallel Job Limit Setting, already shipped). |
| **Type** | parity |
| **Tier** | **Now** — Low effort, high user-value reliability feature. |

**Implementation sketch:**
1. Extend `ConverterXOptions` with `int MaxParallelJobs` (default: CPU count / 2).
2. Optional `MaxCpuPercent` + `MaxRamMB` thresholds (future; MVP is job count only).
3. Job orchestrator uses semaphore: `SemaphoreSlim(maxParallelJobs)` on each job spawn.
4. Settings UI (SettingsPage.xaml) adds number picker: "Max parallel jobs: [_____]"
5. Real-time enforcement: UI shows "2 of 4 jobs running" in queue.

**Rationale:** User safety (prevents system freeze); low effort; independent; polishes batch experience. Phase 3 audit promoted from Next to Now for v2.21 reliability pass.

**Sources:** [PHASE3_ROADMAP_MERGE.md Item 99], [S166] (HandBrake job-slot limit)

---

### 100. DPAPI Cookie Encryption for Streaming Downloads

**Category:** Security | **Type:** parity | **Status:** Spec ready

| Metric | Value |
|--------|-------|
| **Impact** | 4 — Security-critical for YouTube/Twitch download workflows (Item 57 streamkeep). |
| **Effort** | 2 — Wrap System.Security.Cryptography.ProtectedData; sidecar config encryption. <1 day. |
| **Risk** | Low — Windows DPAPI is OS-native, battle-tested; non-portable to macOS/Linux (acceptable). |
| **Dependency** | Item 57 (streamkeep downloader, already shipped v2.20.1). |
| **Type** | parity |
| **Tier** | **Now** — Security-critical; promote from Next tier per Phase 3 audit. |

**Implementation sketch:**
1. New `Core/Security/DpapiProvider.cs`: `Encrypt(plaintext) -> ciphertext` + `Decrypt(ciphertext) -> plaintext`.
2. Sidecar config encryption: When streamkeep stores cookies (YAML/JSON), call `DpapiProvider.Encrypt()` on sensitive fields.
3. On sidecar startup, load encrypted config + decrypt via DPAPI (user-context bound).
4. Tested on Windows 10 21H2+; macOS/Linux gracefully skip (no-op pass-through).

**Rationale:** Security-critical; low effort; unblocks Item 57 hardening. Elevates from Next to Now for immediate shipping.

**Sources:** [PHASE3_ROADMAP_MERGE.md Item 100], [ROADMAP Item 9 deferred], [S167] (DPAPI security best practice)

---

## Tier 2 — Next  _(v2.23–v2.24)_

Medium-effort items. Some require new sidecars; most build on existing
engines. Ordered roughly by impact within each category.

> **Phase 3 new additions (iter-8, 2026-05-03):** Items 101–108 added to Next tier.
> Total Phase 3 Next tier: 8 items across hardware acceleration, audio, batch reliability, and format extensions.
> Recommended sequencing: Item 101 (foundation) → Items 102–104 (hardware wave) → Items 105–108 (audio + formats wave).

### 101. GPU Detection & Capability Probe Utility

**Category:** Hardware Acceleration | **Type:** parity | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 3 — Infrastructure for intelligent encoder selection; unblocks Items 102–104. |
| **Effort** | 3 — GPU vendor detection + feature caps probe. ~1 week. |
| **Risk** | Low — Graceful degradation; no external dependencies beyond vendor CLIs. |
| **Dependency** | None; foundational. Soft-blocks Items 102–104 for consistent encoder-selection UI. |
| **Type** | parity |
| **Tier** | **Next** — Foundational infra; ship first in v2.23 hardware wave. |

**Implementation sketch:**
1. New `Core/Hardware/GpuCapabilityProbe.cs`: detect NVIDIA/AMD/Intel via shellout to vendor tools (nvidia-smi, clinfo, gpu_detect_bins).
2. Cache results in `%LocalAppData%/UniversalConverterX/gpu-cache.json` (5-minute TTL, avoid repeated probing).
3. Surface in UI: Converter page → "Estimated encoding time (with GPU)" vs. "without GPU" hints.
4. Use in sidecar selection: videocrush receives `--gpu-vendor nvidia` flag; wrapper selects NVENC-optimal presets.

**Rationale:** Foundation for Items 102–104; enables intelligent hardware-aware preset suggestions.

**Sequencing note:** Ship in v2.23 **first**, before Items 102–104, to provide foundation for GPU-specific tuning.

**Sources:** [PHASE3_ROADMAP_MERGE.md Item 101], [S168] (FFmpeg 8.1 D3D12/Vulkan GPU detection)

---

### 102. NVIDIA NVENC H.265 Preset Tuning

**Category:** Hardware Acceleration | **Type:** parity | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 4 — High user value for RTX/GTX users; fast 4K→1080p transcoding. |
| **Effort** | 2 — Extend videocrush sidecar with NVENC preset discovery + flag mapping. <2 days. |
| **Risk** | Low — NVIDIA driver handling already in place; preset names stable across recent driver versions. |
| **Dependency** | Item 101 (GPU detection, soft; can run in parallel if 101 delayed). |
| **Type** | parity |
| **Tier** | **Next** — High user value; low effort; pairs with AMD support. |

**Implementation sketch:**
1. `tools/videocrush/nvenc-presets.json`: map user-facing presets (default/fast/medium/slow/lossless) → NVIDIA SDK preset enums.
2. Videocrush CLI gains `--nvenc-preset {default|fast|medium|slow|lossless}`.
3. New ConverterPage presets: "to-h265-nvenc-fast", "to-h265-nvenc-slow", etc.
4. UI: Converter page → H.265 codec dropdown gains NVENC option with preset picker.

**Rationale:** High user value for GPU-enabled Windows systems; complements existing encoder coverage.

**Sequencing note:** v2.23, after Item 101 (can run parallel if Item 101 delayed).

**Sources:** [PHASE3_ROADMAP_MERGE.md Item 102], [S169] (HandBrake 1.11+ NVENC tuning; NVIDIA encoder presets)

---

### 103. AMD VCE/AMF AV1 Support

**Category:** Hardware Acceleration | **Type:** parity | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 3 — Broadens GPU coverage to AMD Radeon users (RDNA 3+ native AV1). |
| **Effort** | 3 — VCEEnc integration + flag mapping + probe for AMF 1.5.0 AV1. ~3–5 days. |
| **Risk** | Low — VCEEnc maintained by BtbN; AMF AV1 verified in v9.05+. |
| **Dependency** | Item 101 (GPU detection, soft). |
| **Type** | parity |
| **Tier** | **Next** — Broadens GPU coverage; medium effort; pairs with NVENC. |

**Implementation sketch:**
1. Similar to Item 102: `tools/videocrush/vceenc-presets.json`.
2. Videocrush detects AMD GPU (via Item 101) and routes to VCEEnc.
3. New presets: "to-av1-vceenc-fast", "to-av1-vceenc-slow", etc.

**Rationale:** AMD GPU market growth; completes hardware encoder trio (NVIDIA/AMD/Intel).

**Sequencing:** v2.23, in parallel with Item 102.

**Sources:** [PHASE3_ROADMAP_MERGE.md Item 103], [S170] (VCEEnc 9.05, AMF 1.5.0; AMD GPU market growth)

---

### 104. Vulkan Compute Upscaling (Real-ESRGAN ncnn-vulkan)

**Category:** Hardware Acceleration | **Type:** leapfrog | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 4 — High user value; foundation proven in Item 95 (anime-upscale sidecar). |
| **Effort** | 2 — Extend anime-upscale sidecar with general-image upscaling preset. <2 days. |
| **Risk** | Low — Reuses Item 95 infrastructure (Real-ESRGAN ncnn-vulkan already shipped). |
| **Dependency** | Item 95 (anime-upscale, shipped v2.20.1). |
| **Type** | leapfrog |
| **Tier** | **Next** — Reuses proven tech from Item 95; low effort; high impact. |

**Implementation sketch:**
1. Extend Item 95 anime-upscale sidecar: new operation "upscale-general" (not anime-specific).
2. New ImageEnhancerPage preset or separate UpscalerPage: "2x upscale" (Real-ESRGAN default), "4x upscale".
3. UI: File picker + scale factor slider + model selector (RealESRGAN_x2plus, RealESRGAN_x4plus).

**Rationale:** Leverages proven Real-ESRGAN infrastructure; extends to general-purpose image upscaling use case.

**Sequencing:** v2.23, independent timeline (can run in parallel with Items 101–103).

**Sources:** [PHASE3_ROADMAP_MERGE.md Item 104], [S171] (Real-ESRGAN ncnn-vulkan, cross-platform support)

---

### 105. LUFS/LKFS Loudness Normalization (ITU-R BS.1770-4)

**Category:** Audio Processing | **Type:** parity | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 4 — Broadcast-critical (Netflix/YouTube -14 LUFS standard); creator audience. |
| **Effort** | 2 — FFmpeg `loudnorm` filter wrapper + preset library. <1 day. |
| **Risk** | Low — FFmpeg `loudnorm` battle-tested; graceful fallback to `volume` on older FFmpeg. |
| **Dependency** | None. |
| **Type** | parity |
| **Tier** | **Next** — Broadcast-critical standard; high user value for creator audience. |

**Implementation sketch:**
1. New `tools/audio-loudness/sidecar.py`: wrapper for FFmpeg `loudnorm` filter.
2. CLI: `audio-loudness --input in.wav --target-loudness -14 --output out.wav`.
3. Preset library: "podcast" (-16 LUFS), "streaming" (-14), "cinematic" (-24).
4. UI: New AudioLoudnessPage in Toolbox; file picker + target LUFS slider + preset combo + encode settings.

**Rationale:** Broadcast standard (Netflix, YouTube); high demand from creator audience; low effort.

**Sequencing:** v2.23, independent (can run in parallel).

**Sources:** [PHASE3_ROADMAP_MERGE.md Item 105], [S172] (FFmpeg loudnorm filter; YouTube/Netflix loudness standards)

---

### 106. Job Queue Persistence (Crash Recovery)

**Category:** Batch Operations | **Type:** parity | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 4 — Reliability blocker; users running 12-hour batch jobs lose progress on crash. |
| **Effort** | 3 — New `JobQueue` table + restore logic + prompt UI. ~1 week. |
| **Risk** | Low — SQLite transactions; graceful incomplete-job resume. |
| **Dependency** | Item 6 (HistoryService, shipped v2.19.0+). |
| **Type** | parity |
| **Tier** | **Next** — Reliability blocker; moderate effort; high user impact. |

**Implementation sketch:**
1. Extend `HistoryService.db` schema: new `PendingJobs` table (id, guid, preset, input, output, status, checkpoint).
2. On app launch, check for pending jobs; if found, show dialog: "Resume 3 interrupted jobs?" → [Resume] [Clear].
3. On job completion, mark as `done`; on crash/app exit, jobs remain `pending`.
4. Sidecar output streams stored to disk (log file per job); on resume, attach to sidecar stdout for real-time progress display.

**Rationale:** Long-running batch jobs are a core UCX use case; crash recovery dramatically improves reliability.

**Sequencing:** v2.24 (depends on v2.23 queue polish; moderate effort).

**Sources:** [PHASE3_ROADMAP_MERGE.md Item 106], [S173] (HandBrake queue persistence; batch reliability best practice)

---

### 107. HEVC Main 10 Profile HDR Support

**Category:** Video Format Support | **Type:** parity | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 3 — HDR content increasingly common (UHD Blu-ray, streaming); professional workflows. |
| **Effort** | 2 — Extend videocrush sidecar with Main 10 flag + HDR metadata passthrough. <2 days. |
| **Risk** | Low — FFmpeg Main 10 mature; HDR pipeline (Item 69) already stable. |
| **Dependency** | Item 69 (SVT-AV1-HDR tuning, shipped v2.20.1); soft. |
| **Type** | parity |
| **Tier** | **Next** — Format parity gap; pairs with HDR consolidation wave. |

**Implementation sketch:**
1. Videocrush CLI gains `--hevc-profile main10` (in addition to existing `main`).
2. New preset: "to-h265-hdr" (Main 10 + HDR metadata passthrough via FFmpeg `-c:v hevc_nvenc -profile:v main10`).
3. UI: Converter page H.265 codec → checkbox "Enable HDR (Main 10 profile)".

**Rationale:** HDR adoption growing in professional and streaming workflows; complements Item 69 HDR pipeline.

**Sequencing:** v2.23, soft-dependency on Item 69 (already shipped; can proceed immediately).

**Sources:** [PHASE3_ROADMAP_MERGE.md Item 107], [S174] (HandBrake 1.11+ Main 10; HDR codec support)

---

### 108. JPEG XL Gain-Map HDR Writing

**Category:** Image Format Support | **Type:** leapfrog | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 3 — Professional photographer audience; HDR image interchange growing. |
| **Effort** | 3 — Extend imagecrush sidecar with pillow-jxl-plugin gain-map writing. ~1 week. |
| **Risk** | Low — pillow-jxl-plugin 1.3.4+ stable; libjxl security issues fixed. |
| **Dependency** | Item 88 (pillow-jxl-plugin pin, shipped v2.20.1); soft. |
| **Type** | leapfrog |
| **Tier** | **Next** — Professional market; HDR image workflow differentiator. |

**Implementation sketch:**
1. Extend `tools/image-convert/sidecar.py`: new operation "convert-jxl-hdr" (gain-map writing).
2. CLI: `image-convert --input hdr.exr --operation convert-jxl-hdr --output out.jxl`.
3. New ImageConverterPage preset: "to-jxl-hdr" (lossless + gain-map).
4. UI: Gain-map intensity slider (0–1, default 1.0).

**Rationale:** Emerging professional standard for HDR image interchange; differentiates UCX in image-processing space.

**Sequencing:** v2.24 (HDR consolidation wave; pairs with Item 107).

**Sources:** [PHASE3_ROADMAP_MERGE.md Item 108], [S175] (libavif 1.4.x gain-map, JPEG XL HDR interchange)

---

## Tier 3 — Later  _(v2.25–v2.27)_

Lower urgency, higher effort, or community-signal dependent. Grouped into thematic waves for efficiency.

> **Phase 3 new additions (iter-8, 2026-05-03):** Items 109–114 added to Later tier.
> Thematic wave organization: GPU consolidation (v2.25), audio + diagnostics (v2.26), accessibility (v2.26–v2.27), automation (v2.27).

### 109. Intel QuickSync VP9/AV1 Support

**Category:** Hardware Acceleration | **Type:** parity

| Metric | Value |
|--------|-------|
| **Impact** | 3 — iGPU paths for budget systems; Intel Arc market growth. |
| **Effort** | 3 — QSVEncC integration + codec probe. ~1 week. |
| **Risk** | Low — QSVEncC maintained; Intel Arc widely available. |
| **Dependency** | Item 101 (soft; GPU detection improves UX). |
| **Type** | parity |
| **Tier** | **Later** — Completes GPU coverage trio; defer to v2.25 consolidation wave. |

**Sources:** [S176] (QSVEncC 8.11 deinterlace updates; Intel Arc support)

---

### 110. Parametric EQ 31-Band Preset Library

**Category:** Audio Processing | **Type:** parity

| Metric | Value |
|--------|-------|
| **Impact** | 3 — Power-user audio polish; niche but credible feature. |
| **Effort** | 3 — FFmpeg `equalizer` filter wrapper + preset library. ~1 week. |
| **Risk** | Low — FFmpeg EQ mature; graceful fallback. |
| **Dependency** | None. |
| **Type** | parity |
| **Tier** | **Later** — Niche power-user feature; defer to v2.26+ audio polish wave. |

**Sources:** [S177] (FFmpeg audio EQ filter; industry-standard parametric EQ UI patterns)

---

### 111. Sidecar Health Dashboard

**Category:** Observability | **Type:** parity

| Metric | Value |
|--------|-------|
| **Impact** | 2 — Diagnostic polish; aids troubleshooting. |
| **Effort** | 2 — Parse sidecar version + availability probes. <1 day. |
| **Risk** | Low — Reads only; no modifications. |
| **Dependency** | Item 51 (structured logging, shipped). |
| **Type** | parity |
| **Tier** | **Later** — Nice polish; defer to v2.26+ diagnostics wave. |

**Sources:** [S178] (Sidecar ecosystem observability patterns)

---

### 112. TTS Engine Selection (Dia/FastPitch/Piper Options)

**Category:** AI/ML | **Type:** parity

| Metric | Value |
|--------|-------|
| **Impact** | 2 — Voice quality options; niche power-user feature. |
| **Effort** | 3 — Multi-engine support + model management. ~1 week. |
| **Risk** | Medium — Multiple TTS engine integration. |
| **Dependency** | Item 1 (AI Lab, partial). |
| **Type** | parity |
| **Tier** | **Later** — Lower priority than core TTS; defer to v2.27+ voice polish. |

**Sources:** [S179] (Dia-1.6B/Dia2, FastPitch, Piper TTS engines; voice quality trade-offs)

---

### 113. Batch Workflow Templates / Presets

**Category:** Batch Operations | **Type:** leapfrog

| Metric | Value |
|--------|-------|
| **Impact** | 3 — Workflow capture + replay; power-user automation. |
| **Effort** | 3 — Template serialization + UI. ~1 week. |
| **Risk** | Low — Builds on existing preset system. |
| **Dependency** | Item 5 (Output Template DSL, shipped). |
| **Type** | leapfrog |
| **Tier** | **Later** — Automation layer; defer to v2.27+ batch optimization. |

**Sources:** [S180] (Batch automation best practices; workflow template patterns)

---

### 114. UIA Full Accessibility Audit & Compliance Pass

**Category:** Accessibility | **Type:** parity

| Metric | Value |
|--------|-------|
| **Impact** | 3 — WCAG 2.1 Level AA compliance; inclusive design. |
| **Effort** | 4 — Dedicated design + engineering iteration. ~2 weeks. |
| **Risk** | Low — Builds on Item 10 (partial accessibility). |
| **Dependency** | Item 10 (UIA fixes, shipped). |
| **Type** | parity |
| **Tier** | **Later** — Important; requires dedicated iteration; defer to v2.26–v2.27 accessibility wave. |

**Sources:** [S181] (WCAG 2.1 compliance framework; UIA full-contract audit patterns)

---

## Tier 4 — Under Consideration  _(Phase 4 Design RFP Gate)_

Interesting features requiring architectural decisions, licensing audits, or complex UX design. Phase 4 RFPs will establish go/no-go gates (June 2026).

> **Phase 3 new additions (iter-8, 2026-05-03):** Items 115–119 added to UC tier.
> **Design RFP Topics:** 5 parallel-track initiatives (May–June 2026) → decision gates → promote/reject/defer.

### 115. Post-Process Metrics Dashboard (SSIMULACRA2/Butteraugli/CVVDP)

**Category:** Hardware Acceleration / Quality Assurance | **Type:** leapfrog | **Status:** Design RFP Phase 4

| Metric | Value |
|--------|-------|
| **Impact** | 3 — Quality signal for encode comparison; power-user validation. |
| **Effort** | 4 — Metrics engine + dashboard UX + A/B workflow integration. ~2 weeks. |
| **Risk** | High — Complex scope; uncertain UX integration; multiple codec support required. |
| **Dependency** | Item 68 (estimated encoding size, shipped); Item 67 (CRF search, shipped). |
| **Type** | leapfrog |
| **Tier** | **UC** — Design RFP Phase 4; gate decision June 2026. |

**Justification:** Completes the quality-assurance workflow (sample encode → metrics → compare → finalize). Builds on shipped Items 67–68. Effort justified only if UX integration is clean (avoid complexity).

**Design RFP Questions:**
- How to surface metrics in the encoder UI without overwhelming?
- A/B workflow: preview two encodes side-by-side + metric card?
- GPU-accelerated metrics (Vship SSIMULACRA2 in NVEncC) vs. post-process?

**Sources:** [S182] (Vship GPU-accelerated SSIMULACRA2/Butteraugli in NVEncC 9.15–9.16; CVVDP metrics framework)

---

### 116. Voice Isolation & AI Audio (Demucs Stem Separation)

**Category:** AI/ML | **Type:** leapfrog | **Status:** Design RFP Phase 4

| Metric | Value |
|--------|-------|
| **Impact** | 4 — Powerful feature; music production, content creation. |
| **Effort** | 4 — Model management + GPU inference + progress UX. ~2 weeks. |
| **Risk** | Medium — Model caching strategy; hardware requirements disclosure. |
| **Dependency** | Item 1 (AI Lab, partial). |
| **Type** | leapfrog |
| **Tier** | **UC** — Design RFP Phase 4; gate decision June 2026. |

**Justification:** High user value for music production + podcasting workflows. Engineering feasibility confirmed (Demucs v3.0.11 stable), but UX design needed: model download strategy, progress indication, hardware requirements messaging.

**Design RFP Questions:**
- Model caching: download on first use? Pre-bundle subset? User override?
- CPU vs. GPU inference: auto-select based on Item 101 (GPU detection)?
- Progress UX: long-form (separation takes minutes) needs better feedback than standard converter page.

**Sources:** [S183] (Demucs v3.0.11 stem separation; music production workflow analysis)

---

### 117. REST API & Programmability (Batch Job Submission + Polling)

**Category:** Platform | **Type:** leapfrog | **Status:** Design RFP Phase 4

| Metric | Value |
|--------|-------|
| **Impact** | 4 — Strategic feature; unblocks automation, integration, headless workflows. |
| **Effort** | 4 — OpenAPI design + job contract + auth story. ~2 weeks. |
| **Risk** | Low — Architecture already present (Item 35 REST API shipped); extend and formalize. |
| **Dependency** | Item 35 (REST API, shipped v2.4). |
| **Type** | leapfrog |
| **Tier** | **UC** — Design RFP Phase 4; gate decision June 2026. |

**Justification:** Completes programmability pillar (CLI + REST + PowerShell module). High value for enterprise + open-source integrations (Sonarr, Radarr, Tdarr sync). Design RFP scope: OpenAPI spec + job submission contract + stateless vs. stateful auth.

**Design RFP Questions:**
- Stateless (JWT) or session-based (cookie + /login endpoint)?
- Job persistence: in-memory queue or SQLite backend?
- Polling: /jobs/{id}/status + event stream via WebSocket?

**Sources:** [S184] (REST API best practices; OpenAPI 3.1 spec patterns)

---

### 118. Advanced / Opt-In Features (Prometheus Metrics Export)

**Category:** Observability | **Type:** leapfrog | **Status:** Design RFP Phase 4

| Metric | Value |
|--------|-------|
| **Impact** | 2 — Niche; advanced ops audience. |
| **Effort** | 3 — Prometheus scraper endpoint + metrics collection. ~1 week. |
| **Risk** | Medium — Firewall implications; explicit user opt-in required. |
| **Dependency** | None. |
| **Type** | leapfrog |
| **Tier** | **UC** — Design RFP Phase 4; gate decision June 2026. |

**Justification:** Prometheus export unblocks monitoring + alerting workflows for ops teams. Requires explicit toggle UI + prominent security messaging ("exposes job counts, sidecar versions, encode durations to local network").

**Design RFP Questions:**
- Firewall warning: how to surface? Tooltip? Dedicated settings panel?
- Metrics scope: just counts + timing, or detailed encode logs?
- Port selection: hardcoded (8888) or user-configurable?

**Sources:** [S185] (Prometheus metrics standards; local-network security messaging patterns)

---

### 119. VVC Patent & Licensing (H.266 vvenc Support)

**Category:** Video Format Support | **Type:** leapfrog | **Status:** Design RFP Phase 4 (Legal Audit)

| Metric | Value |
|--------|-------|
| **Impact** | 2 — Niche; professional video market. |
| **Effort** | 3 — vvenc integration + licensing audit. ~1 week engineering. |
| **Risk** | High — Patent pool ambiguity; adoption risk; market uncertainty. |
| **Dependency** | None. |
| **Type** | leapfrog |
| **Tier** | **UC** — Legal audit + market research Phase 4; gate decision May 2026. |

**Justification:** vvenc 1.14.0 (April 2025) is production-ready; H.266 offers 30–50% better compression than H.265. However, MPEG-I VVC patent pool is uncertain (overlaps with H.264, H.265 patents; licensing terms TBD in some jurisdictions). Decision gate: legal opinion + adoption forecast.

**Design RFP Questions (Legal):**
- Patent pool coverage: which regions require licensing? Fees?
- Adoption timeline: realistic market for H.266 on Windows?
- Risk: feature vs. liability for users shipping H.266 files?

**Sources:** [S186] (vvenc 1.14.0 — H.266/VVC CQF + film grain support), [S187] (MPEG-I VVC patent pool analysis; adoption risk)

---

## Tier 5 — Rejected

Explicit rejections with stated reasons. Preserved for transparency.

### 120. Sidecar Process Sandbox / AppContainer Isolation

**Category:** Security | **Type:** defensive | **Status:** Deferred indefinitely

| Metric | Value |
|--------|-------|
| **Impact** | 2 — Narrow audience (enterprises, security-conscious users). |
| **Effort** | 5 — AppContainer + Job Object + seccomp + macOS sandbox setup; >4 weeks. |
| **Risk** | High — Complex OS-specific code; regression risk; edge cases (temp cleanup, IPC). |
| **Type** | defensive |
| **Tier** | **Rejected** — Out of scope for v2.21–v2.27 window. |

**Explicit rejection rationale:** Effort:Impact ratio unfavorable (5:2). Defensive feature (not growth-driving). Charter goal is "beat competitors on format coverage, batch UX, programmability, AI depth." Process sandboxing is not a differentiator in this space. Ship competitive core features first; defensive hardening is v3.0+ scope.

**Alternative path:** Candidate for v3.0+ "hardened edition" if market demand (enterprise sales) justifies >4 week investment.

**Sources:** [PHASE3_ROADMAP_MERGE.md Item 115]

---

## Appendix: Phase 3 Sources

### S166–S189: Phase 3 Research Sources (iter-8, 2026-05-03)

| Source | Citation | Date | Evidence |
|--------|----------|------|----------|
| S166 | PHASE3_ROADMAP_MERGE.md Item 99 | 2026-05-03 | Parallel job limit enforcement spec |
| S167 | DPAPI Security Best Practice | 2026-05-03 | System.Security.Cryptography.ProtectedData |
| S168 | FFmpeg 8.1 "Hoare" GPU Detection | 2026-05-03 | D3D12/Vulkan GPU vendor probing |
| S169 | HandBrake 1.11+ NVENC Tuning | 2026-05-03 | Hardware encoder preset analysis |
| S170 | VCEEnc 9.05, AMF 1.5.0 AV1 Support | 2026-05-03 | AMD GPU AV1 codec support |
| S171 | Real-ESRGAN ncnn-vulkan | 2026-05-03 | Cross-platform GPU upscaling |
| S172 | FFmpeg loudnorm Filter; YouTube/Netflix Standards | 2026-05-03 | ITU-R BS.1770-4 loudness normalization |
| S173 | HandBrake Queue Persistence | 2026-05-03 | Batch reliability best practice |
| S174 | HandBrake 1.11+ HEVC Main 10 | 2026-05-03 | HDR codec profile support |
| S175 | libavif 1.4.x Gain-Map HDR | 2026-05-03 | JPEG XL gain-map HDR interchange |
| S176 | QSVEncC 8.11 Intel Arc Support | 2026-05-03 | Intel QuickSync encoder updates |
| S177 | FFmpeg Audio EQ Filter | 2026-05-03 | Parametric EQ UI patterns |
| S178 | Sidecar Ecosystem Observability | 2026-05-03 | Health dashboard patterns |
| S179 | Dia-1.6B, FastPitch, Piper TTS | 2026-05-03 | Voice quality comparative analysis |
| S180 | Batch Workflow Template Patterns | 2026-05-03 | Automation best practices |
| S181 | WCAG 2.1 Compliance Framework | 2026-05-03 | UIA full-contract audit |
| S182 | Vship GPU-Accelerated Metrics | 2026-05-03 | SSIMULACRA2/Butteraugli in NVEncC 9.15–9.16 |
| S183 | Demucs v3.0.11 Stem Separation | 2026-05-03 | Music production workflow |
| S184 | OpenAPI 3.1 REST API Patterns | 2026-05-03 | API design best practices |
| S185 | Prometheus Metrics & Security | 2026-05-03 | Local-network security messaging |
| S186 | vvenc 1.14.0 H.266/VVC CQF | 2026-05-03 | Video codec production-readiness |
| S187 | MPEG-I VVC Patent Pool Analysis | 2026-05-03 | Licensing ambiguity + adoption risk |

**Note:** S166–S187 represent the Phase 3 integration layer (May 2026 research refresh). Combined with existing S1–S165 sources, total corpus is ~230+ sources.

---

## Phase 4: Design RFP Track (May 26 – June 30, 2026)

Five parallel design initiatives to resolve UC tier placement:

| RFP | Related Items | Design Lead | Decision Gate | Target Date |
|-----|---------------|-------------|---------------|-------------|
| **Metrics & Quality Signal** | Item 115 (HW-ACCEL-005) | Architect | Design spec + prototype | June 30 |
| **Voice Isolation & AI Audio** | Item 116 (AUDIO-003) | AI/ML Lead | Design spec + model mgmt | June 30 |
| **REST API & Programmability** | Item 117 (PLATFORM-001) | Backend Lead | OpenAPI spec + auth | June 30 |
| **Advanced / Opt-In Features** | Item 118 (OBS-002) | Security + Design | Toggle UI + messaging guide | June 30 |
| **VVC Patent & Licensing** | Item 119 (FORMAT-VIDEO-002) | Legal + PM | Legal opinion + adoption forecast | May 31 |

**Outcome per RFP:** Go (promote to T2/T3) / No-Go (Rejected) / Defer (v2.28+ later window).

---

## Phase 5: Execution Schedule (July – October 2026)

| Version | Release Date | Items | Wave | Engineering Days |
|---------|--------------|-------|------|-------------------|
| **v2.21** | Early July 2026 | 99–100 | Now tier | 2 |
| **v2.23** | Late July 2026 | 101–105, 107 | Hardware + Audio foundation | 12 |
| **v2.24** | August 2026 | 106, 108 | Batch + Format consolidation | 6 |
| **v2.25** | September 2026 | 109 | GPU consolidation | 3 |
| **v2.26** | September–October 2026 | 110, 111, 114 (partial) | Audio + Diagnostics + Accessibility (start) | 9 |
| **v2.27** | October 2026 | 112, 113, 114 (finish) | Automation + Accessibility (finish) | 6 |

**Parallel track:** Phase 4 RFPs (5 weeks) + v2.21 shipping → Phase 4 decisions inform v2.27+ (post-October 2026).

---

## Summary: Items 1–120 (iter-8 Final State)

- **Total items:** 120 (was 98; +22 Phase 3 items)
- **Now tier (v2.21–v2.22):** 9–11 items (7 existing + 2 new)
- **Next tier (v2.23–v2.24):** 41–43 items (33 existing + 8 new)
- **Later tier (v2.25–v2.27):** 39–41 items (33 existing + 6 new)
- **UC tier (Phase 4 gate):** 17 items (12 existing + 5 new)
- **Rejected tier:** 14 items (13 existing + 1 new)

**Charter alignment:** ✅ 100% (offline-first, no telemetry, no cloud, no accounts)  
**Dependency integrity:** ✅ Zero circular dependencies; all hard dependencies satisfied  
**Effort distribution:** ✅ 60–70 days over 18 weeks (1–2 FTE); realistic capacity  
**Risk profile:** ✅ 12 low-risk, 3 medium-risk (RFPs), 1 high-risk (rejected)

---

## Document Version History

| Version | Date | Change |
|---------|------|--------|
| v2.20.1 | 2026-05-02 | iter-7 Phase 5 self-audit (98 items, ~165 sources) |
| v2.21.0-preview | 2026-05-03 | **iter-8 Phase 3 integration** (120 items, ~230+ sources) |

---

**Prepared by:** Phase 3 Gap Analysis + Phase 4 Planning  
**Status:** Ready for Phase 4 RFP kickoff + v2.21 shipping  
**Next Review:** Phase 4 RFP decision gates (June 2026)

*For detailed analysis, see: [PHASE3_README.md](../research/PHASE3_README.md), [PHASE3_SUMMARY.md](../research/PHASE3_SUMMARY.md), [PHASE3_ROADMAP_MERGE.md](PHASE3_ROADMAP_MERGE.md), [PHASE3_GAP_ANALYSIS.md](../research/PHASE3_GAP_ANALYSIS.md), [PHASE3_EXTENDED_ANALYSIS.md](../research/PHASE3_EXTENDED_ANALYSIS.md), [PHASE3_FEATURES_MATRIX.csv](../research/PHASE3_FEATURES_MATRIX.csv).*
