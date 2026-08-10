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

### P2 — Product depth, performance, and compatibility

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

---

## Audit Findings — 2026-08-02

_Deep audit-only pass (principal-eng / QA / security / UX). Baseline was clean: `build.ps1 -Target Test` = 17/17 gates pass, 0 failures. Findings below are verified reachable unless marked Needs-repro. IDs continue the existing `Item NNN` scheme. Each entry is self-contained — the implementer needs no audit context._

### P1 — correctness, data-safety, security

### P2 — reliability, correctness edges, security hardening, performance

- [ ] P2 — Item 183 — Potrace emits `-b` without its required backend name — PDF/DXF/GeoJSON/XFig output is dead on arrival
  Category: correctness
  Where: `src/UniversalConverterX.Core/Converters/PotraceConverter.cs:136-147` (`GetBackendFlag`), `:66-77`/`:130-133` (`BuildArguments`).
  Problem: `GetBackendFlag` returns the bare string `"-b"` for pdf/dxf/geojson/fig, but potrace's `-b/--backend` requires a name (`-b pdf`). The next token added is a tracing option (e.g. `-z`), which potrace then parses as the backend name → "unrecognized backend" and immediate failure. Every potrace conversion to pdf/dxf/geojson/fig fails; dxf/geojson/fig have no other converter, so those routes are entirely broken.
  Evidence: args become `["-b","-z",...]`; reachable via `GetBestConverter("png","dxf")` (only potrace claims dxf).
  Fix: return two tokens, e.g. `["-b","pdf"]`/`["-b","dxf"]`/`["-b","geojson"]`/`["-b","xfig"]`.
  Acceptance: `png→dxf` with potrace installed produces a non-empty DXF; unit test asserts `BuildArguments` contains adjacent `"-b","dxf"`.
  Confidence: Verified. Effort: S

- [ ] P2 — Item 184 — `heif-enc -t` emitted without the required thumbnail-size argument
  Category: correctness
  Where: `src/UniversalConverterX.Core/Converters/LibHeifConverter.cs:116-126`.
  Problem: when `options.Image.Width <= 256`, a bare `-t` is added (`:119`), then `-o <out>` follows (`:123`); heif-enc's `-t/--thumb` takes a numeric size, so it consumes `-o` as the size and the output filename is lost → parse failure / no output. The `Width<=256 ⇒ make a thumbnail` heuristic is also questionable (a small target size is not a thumbnail request).
  Evidence: args become `[-q,60,-t,-o,<out>,<in>]`.
  Fix: pass the size (`["-t", size]`) or drop the thumbnail heuristic entirely; verify against the shipped heif-enc.
  Acceptance: `png→heic` with Width=200 produces the file and heif-enc exits 0.
  Confidence: Likely (heif-enc option contract). Effort: S

- [ ] P2 — Item 185 — Ghostscript `-sOutputFile=` treats `%` in user paths as a page-number template
  Category: correctness
  Where: `src/UniversalConverterX.Core/Converters/GhostscriptConverter.cs:143`.
  Problem: `%` is legal in Windows filenames; GS interprets `%d`/`%03d`/`%s` in OutputFile as a multi-page template. Converting to e.g. `report 100%d.png` writes `report 1001.png`… per page and the requested path never exists → `ValidateSuccessfulOutput` fails (or stray files litter the directory).
  Evidence: `-sOutputFile={job.OutputPath}` with no escaping.
  Fix: escape `%` as `%%` in the OutputFile value (GS's documented escape).
  Acceptance: pdf→png with a `%` in the output filename succeeds at the exact requested path.
  Confidence: Verified. Effort: S

- [ ] P2 — Item 186 — FFmpeg `-progress pipe:1 -stats_period 0.1` is appended after the output path and ignored
  Category: correctness
  Where: `src/UniversalConverterX.Core/Converters/FFmpegConverter.cs:164-168` (and pass-2 at `:247-249`).
  Problem: ffmpeg treats options after the last output file as trailing and ignores them. The machine-readable `-progress pipe:1` channel never activates and the 0.1 s cadence never applies; progress works only by accident via default ~0.5 s stderr stats that `ParseProgress` happens to match. Any future reliance on the `pipe:1` key=value stream silently gets nothing.
  Evidence: `args.Add(job.OutputPath)` then `args.AddRange(["-progress","pipe:1","-stats_period","0.1"])`.
  Fix: move `-progress pipe:1 -stats_period 0.1` to global position (before `-i`); adjust `BuildPassArguments` tail handling.
  Acceptance: a conversion run with `-v warning` shows no "Trailing option(s)" warning and progress arrives at 10 Hz.
  Confidence: Verified. Effort: S

- [ ] P2 — Item 187 — Potrace's ImageMagick preprocessing fallback runs `magick` without the hardened policy
  Category: security
  Where: `src/UniversalConverterX.Core/Converters/PotraceConverter.cs:353-401` (`ConvertWithImageMagickPreprocessAsync`) vs `src/UniversalConverterX.Core/Converters/ImageMagickConverter.cs:161-172`; policy at `src/UniversalConverterX.Core/Security/ImageMagick/policy.xml`.
  Problem: the hardened `policy.xml` (blocks MVG/MSL/URL coders and `@file` indirect reads, caps decompression-bomb resources) is applied via `MAGICK_CONFIGURE_PATH` only in `ImageMagickConverter.ConfigureProcessStartInfo`. Potrace's fallback calls `ExecuteProcessAsync(magickPath, …)` through Potrace's own (no-op) `ConfigureProcessStartInfo`, so a crafted "PNG" that is actually MVG/MSL (ImageMagick sniffs by content) is processed with protections off. Reachable when a raster→(dxf/geojson/fig or forced-potrace) job runs and `mkbitmap` is absent but `magick` is present.
  Evidence: only `ImageMagickConverter` sets `MAGICK_CONFIGURE_PATH`; the potrace fallback does not.
  Fix: extract the env setup into a shared helper and set `MAGICK_CONFIGURE_PATH` on the fallback `ProcessStartInfo` too.
  Acceptance: a test asserts the fallback `ProcessStartInfo.Environment` contains `MAGICK_CONFIGURE_PATH`; an MVG-as-png fixture fails with "not authorized".
  Confidence: Likely (policy bypass verified; exploit depth depends on the installed ImageMagick build). Effort: S

- [ ] P2 — Item 188 — Concurrent LibreOffice jobs share one user profile — parallel batches fail or no-op
  Category: reliability
  Where: `src/UniversalConverterX.Core/Converters/LibreOfficeConverter.cs:134-161`; `src/UniversalConverterX.Core/Services/ConversionOrchestrator.cs:409-443`.
  Problem: no `-env:UserInstallation=…` anywhere in the repo (grep confirmed). `ConvertBatchAsync` runs up to 4 jobs in parallel; two simultaneous `soffice --headless --convert-to` instances contend on the profile lock — the second connects to the first or fails, often exiting 0 without converting. Same failure if the user has desktop LibreOffice open. Combined with Item 169, a no-output run can be papered over with a stale file.
  Evidence: `Parallel.ForEachAsync(degree ≤ 4)` over one soffice binary + default profile; no per-job profile isolation.
  Fix: override `ConfigureProcessStartInfo` to add `-env:UserInstallation=file:///<per-job-temp>` and clean it up.
  Acceptance: a batch of 4 docx→pdf in parallel succeeds 4/4 repeatedly, and works while a desktop soffice instance is open.
  Confidence: Likely (well-documented LibreOffice behavior). Effort: S

- [ ] P2 — Item 189 — Explorer context menu parses 459 preset XML files synchronously on the shell thread every right-click
  Category: perf
  Where: `src/UniversalConverterX.ShellExtension/ExplorerCommand.cs:177,192,237` → `Presets/PresetReader.cs:92-151`; `ShellExtensionRegistrar.cs:166` (apartment-threaded COM).
  Problem: `EnumSubCommands`→`BuildSubmenu`→`PresetReader.LoadAll()` runs `XmlReader.Create`+`XDocument.Load` on every `*.preset.xml` (the repo ships 459 files / ~1.7 MB) with no cache/memoization/size cap, and `Clone()` rebuilds the whole submenu a second time. This runs on the Explorer UI thread; a cold-cache right-click stalls Explorer and Windows' slow-handler watchdog may drop the menu.
  Evidence: `LoadAll` enumerates up to four directories per invocation; no cache; `Clone` at `:235-239` re-runs it.
  Fix: a process-static cache keyed on directory mtime, plus a hard file-count/time budget; build the submenu once and reuse for `Clone`.
  Acceptance: right-clicking a file with 459 presets present builds the menu in < 50 ms after warm-up and does not re-parse on `Clone`; add a benchmark/guard test.
  Confidence: Verified (structure), Likely (stall magnitude). Effort: M

- [ ] P2 — Item 190 — Shell extension holds cross-instance mutable static selection state
  Category: correctness
  Where: `src/UniversalConverterX.ShellExtension/ExplorerCommand.cs:21,56,91,209,237` (`static List<string> LastSelectionPaths`).
  Problem: `LastSelectionPaths` is a static list written by `GetState` on one COM object and read by `EnumSubCommands`/`Clone` on another; Explorer creates a command object per menu and may run `GetState` for a second selection between the first menu's `GetState` and its `EnumSubCommands`. The submenu — and each `PresetSubCommand._selection` captured at `:209` — can then belong to a different selection than the menu shown, i.e. converting the wrong files. It is also an unsynchronized `List<string>` touched from different threads.
  Evidence: static field mutated per-instance; captured into per-command selection.
  Fix: carry the selection per command instance (no static), captured atomically in `GetState`.
  Acceptance: two overlapping selections produce menus whose actions each operate on their own file set; add a unit test around the state capture.
  Confidence: Likely. Effort: S

- [ ] P2 — Item 191 — REST `/convert` has no concurrency cap; per-job containment does not bound the aggregate
  Category: security (DoS)
  Where: `src/UniversalConverterX.Console/Commands/ServeCommand.cs:188,360-410,442-453`; `src/UniversalConverterX.Core/Security/ProcessContainment.cs:30-33`.
  Problem: `JobManager.Start` spawns a process per request; `SweepFinished` only evicts jobs finished > 1 h ago, so a burst removes nothing. Each job gets its own job object with `MaxProcesses:128` and `MaxMemoryBytes: 90% of RAM` — a PER-JOB ceiling, so N concurrent jobs each get 90% of RAM and 128 processes. With Item 170 (no auth), one web page can wedge the machine.
  Evidence: unconditional per-request `Start`; per-job (not aggregate) limits.
  Fix: a global semaphore + queue-depth limit returning 429 when exceeded; an aggregate resource budget across live jobs.
  Acceptance: issuing 100 rapid `/convert` requests caps concurrent processes at the configured limit and returns 429 beyond queue depth.
  Confidence: Verified. Effort: S

- [ ] P2 — Item 192 — REST accept loop leaks a `Task.Delay` and a CTS registration per request
  Category: reliability
  Where: `src/UniversalConverterX.Console/Commands/ServeCommand.cs:85-90`.
  Problem: each loop iteration creates `Task.Delay(Timeout.Infinite, stopCts.Token)` and, when `GetContextAsync` wins the `WhenAny`, never cancels/disposes it — leaving a permanent `CancellationTokenRegistration` on `stopCts` and a live Task. Memory and the CTS callback list grow linearly with total requests served, degrading a long-running headless server.
  Evidence: a fresh infinite-delay task per iteration, never released until shutdown.
  Fix: register the loop against the token once (or call `listener.Stop()` from the cancellation callback to unblock `GetContextAsync`).
  Acceptance: serving N requests leaves the `stopCts` registration count and Task count flat; add a leak assertion or manual profile.
  Confidence: Verified. Effort: S

- [ ] P2 — Item 193 — CLI `--tools-path` accepts unexpanded `%VAR%` and materializes it as a literal directory
  Category: correctness
  Where: `src/UniversalConverterX.Console/Commands/ToolsCommand.cs:25-27,170-177`; `ConvertCommand.cs:75-77,179`; `ConfigCommand.cs:102-108`; sink `src/UniversalConverterX.Core/Services/ToolDownloader.cs:53-54`.
  Problem: no CLI surface calls `Environment.ExpandEnvironmentVariables`, so a cmd-style `%TEMP%\x` becomes a literal relative directory under the CWD when `ToolDownloader` does `Directory.CreateDirectory(...)`. The repo already carries the artifact: `%TEMP%\ucx-cli-tool-smoke\` at the repo root (from the smoke command in CLAUDE.md). `ucx config set tools-path` warns "Directory does not exist" and stores the literal anyway.
  Evidence: the stray `%TEMP%` directory exists in the working tree; no expansion at any CLI boundary.
  Fix: at the shared option boundary, `ExpandEnvironmentVariables` then reject any value still containing `%` (or `$env:`) with a non-zero exit; delete the committed `%TEMP%` artifact.
  Acceptance: `ucx tools download <t> --tools-path "%TEMP%\x"` writes under the real temp dir (or errors), and never creates a literal `%TEMP%` folder.
  Confidence: Verified. Effort: S

- [ ] P2 — Item 194 — `ucx convert` silently drops explicitly-named missing files and still exits 0
  Category: correctness
  Where: `src/UniversalConverterX.Console/Commands/ConvertCommand.cs:549-571` (no `else` after `File.Exists`), success message `:396`, all-missing guard `:172-176`.
  Problem: a non-glob argument that doesn't exist is silently ignored; `ucx convert a.mov missing.mov b.mov -o mp4` converts two files, prints "✓ All 2 file(s) converted successfully!" and returns 0. The "No matching files found" guard fires only when EVERY input is missing. For scripts/CI this is a silent partial failure.
  Evidence: the input-collection loop has `else if (File.Exists(pattern)) Add(pattern);` with no terminal `else`.
  Fix: for a literal (non-glob) argument that doesn't exist, emit an error and return non-zero.
  Acceptance: `ucx convert real.mov missing.mov -o mp4` exits non-zero and names the missing file.
  Confidence: Verified. Effort: S

- [ ] P2 — Item 195 — Drag-drop handlers await `GetStorageItemsAsync()` unguarded across ~25 pages
  Category: correctness (robustness)
  Where: e.g. `src/UniversalConverterX.UI/Views/Pages/SlideshowPage.xaml.cs:69-87`, `VoiceChangerPage.xaml.cs:69-87`, `BatchRenamePage.xaml.cs:59-78`, `HomePage.xaml.cs:270-283`, `NoiseRemoverPage.xaml.cs:127+` (grep: `GetStorageItemsAsync` appears across many UI pages).
  Problem: every `DropZone_Drop` is `async void` doing `await e.DataView.GetStorageItemsAsync()` with no try/catch. Virtual drag sources (Outlook attachments, ZIP/virtual shell folders, delayed-render providers, RDP redirected drags) make this throw `COMException`; because the handler is `async void` and the global `UnhandledException` handler sets `Handled=false` outside the smoke harness, the process crashes. Also `GetDeferral` is never used (0 hits), so the `DataView` is accessed after the handler returns — works today, fragile by contract.
  Evidence: widespread `async void` drop handlers with no exception guard; no `GetDeferral` in the project.
  Fix: a shared helper `Task<IReadOnlyList<IStorageItem>?> TrySnapshotDropAsync(DragEventArgs e)` that takes the deferral, catches, and returns null; adopt it across pages.
  Acceptance: dropping an Outlook attachment onto any drop zone either queues a temp copy or no-ops with a status message — never crashes.
  Confidence: Likely (crash path certain; trigger frequency varies). Effort: L

- [ ] P2 — Item 196 — Downloader Paste crashes the app when the clipboard is locked or the text task faults
  Category: correctness (robustness)
  Where: `src/UniversalConverterX.UI/Views/Pages/DownloaderPage.xaml.cs:306-332`.
  Problem: `Paste_Click` calls `Clipboard.GetContent()` with no try/catch — this throws `COMException` (`CLIPBRD_E_CANT_OPEN`) whenever another app transiently holds the clipboard (RDP, clipboard managers, Office). Second defect: `pkg.GetTextAsync().AsTask().ContinueWith(t => … t.Result …)` — `ContinueWith` runs on faulted tasks too and `t.Result` rethrows `AggregateException` inside the dispatcher callback. Both reach the global handler → process exit.
  Evidence: plain void handler, no try; continuation has no `OnlyOnRanToCompletion`/`IsFaulted` check.
  Fix: wrap `GetContent()` in try/catch (status message on failure); make the handler `async`, `try { var text = await pkg.GetTextAsync(); } catch { return; }`.
  Acceptance: clicking Paste while a test process holds `OpenClipboard()` shows a status message instead of crashing; a faulted `GetTextAsync` is swallowed.
  Confidence: Verified. Effort: S

- [ ] P2 — Item 197 — Settings Save crashes and loses edits on any disk-write failure
  Category: correctness (robustness)
  Where: `src/UniversalConverterX.UI/Views/SettingsWindow.xaml.cs:663-670` (`Save_Click`, async void, no try) + `src/UniversalConverterX.Core/Configuration/ConverterXOptions.cs:336-352` (`Save`: `Directory.CreateDirectory`/`File.WriteAllText(tmp,…)` unguarded; only the subsequent `File.Move` has a catch).
  Problem: disk full, AV quarantine lock, or read-only `%LocalAppData%` throws `IOException` through the async void handler → process crash and the user's edits are lost. The UI-side `SettingsService.Save()` (Services.cs:172-205) swallows exactly this class — the two savers are inconsistent.
  Evidence: unguarded write in `ConverterXOptions.Save`; `Save_Click` has no catch.
  Fix: try/catch in `Save_Click` that shows the error and keeps the window open; or make `ConverterXOptions.Save()` non-throwing like `SettingsService.Save()`.
  Acceptance: with the settings directory made read-only, Save shows an error and the window stays open with edits intact.
  Confidence: Verified (path), environmental trigger. Effort: S

- [ ] P2 — Item 198 — "Open plugins folder" is an unguarded async void that crashes on locked-down profiles
  Category: correctness (robustness)
  Where: `src/UniversalConverterX.UI/Views/SettingsWindow.xaml.cs:136-142`.
  Problem: `OpenPluginsFolder_Click` calls `Directory.CreateDirectory` (throws on restricted profiles) and `StorageFolder.GetFolderFromPathAsync` (throws `FileNotFoundException`/`UnauthorizedAccessException` for inaccessible paths) with no try/catch → crash. Every other "open folder" affordance (HomePage:308-322, DownloaderPage:691-713, HistoryPage:128-143) is wrapped; this one is the outlier.
  Evidence: no try/catch around the two throwing calls.
  Fix: wrap in try/catch, fall back to the existing `ShowMessageAsync("Plugins folder", path)`.
  Acceptance: with the plugins directory ACL-denied, the click shows the path dialog instead of crashing.
  Confidence: Verified. Effort: S

- [ ] P2 — Item 199 — "Install missing tools" handler has try/finally but no catch → crash on failure
  Category: correctness (robustness)
  Where: `src/UniversalConverterX.UI/Views/SettingsWindow.xaml.cs:366-418` (`DownloadAllTools_Click`, async void; try at `:385`, finally at `:413`, no catch).
  Problem: unlike `ToolAction_Click` (which catches, `:355`), the bulk-install handler has no catch; if `DownloadToolsAsync` or the follow-up `ShowMessageAsync` throws, the exception escapes the async void handler to the global crash path. A network/IO failure during bulk install can crash the app instead of showing an error.
  Evidence: try/finally with no catch on an async void handler.
  Fix: add a catch that surfaces the failure via the InfoBar/dialog and resets the button, mirroring `ToolAction_Click`.
  Acceptance: forcing a throw in the batch downloader shows an error and the app stays alive.
  Confidence: Likely (missing catch definite; reachable throw plausible via IO/`ShowMessageAsync`). Effort: S

- [ ] P2 — Item 200 — `WatchFoldersPage` leaks every visited instance via singleton event subscriptions
  Category: reliability (leak)
  Where: `src/UniversalConverterX.UI/Views/Pages/WatchFoldersPage.xaml.cs:19-20`.
  Problem: the constructor subscribes lambdas to `_service.Profiles.CollectionChanged` and `_service.Recent.CollectionChanged` on the singleton `WatchFolderService` and never unsubscribes (no `OnNavigatedFrom`/`Unloaded`, no `NavigationCacheMode`, so each navigation constructs a fresh page). Every visit permanently roots a full page tree, and every subsequent watch event runs `UpdateUi()` once per dead page against its detached controls.
  Evidence: `Frame.Navigate` creates new instances; zero unsubscribes in the file; HomePage (`:39-113`) shows the correct Loaded/Unloaded attach/detach pattern this page missed.
  Fix: mirror HomePage — named handlers attached in `Loaded`, detached in `Unloaded`.
  Acceptance: navigate to Watch Folders 5×, trigger one watch event → `UpdateUi` hits once; a memory snapshot shows a single live `WatchFoldersPage`.
  Confidence: Verified. Effort: S

- [ ] P2 — Item 201 — PresetsPage kills any run longer than 1 hour and reports it as "cancelled by user"
  Category: correctness / ux
  Where: `src/UniversalConverterX.UI/Views/Pages/PresetsPage.xaml.cs:362` (`new CancellationTokenSource(TimeSpan.FromHours(1))`) + `PresetExecutor.cs:76-78`; same message-conflation at `TextToSpeechPage.xaml.cs:40`, `TrackManagerPage.xaml.cs:142`.
  Problem: every preset run is wrapped in a 1-hour timeout CTS. AI presets on this surface (Real-ESRGAN video, CodeFormer, subtitle removal) routinely exceed 1 h on batches. At the cap the sidecar tree is killed, `PresetExecutor` maps the `OperationCanceledException` to "cancelled / Cancelled by user.", and the card shows Failed (cancelled) — the user is told they cancelled a job they didn't, with hours of work discarded and no way to raise the limit.
  Evidence: `TimeSpan.FromHours(1)` CTS at line 362; OCE→"cancelled by user" mapping in `PresetExecutor`.
  Fix: remove the wall-clock cap on preset runs (the runner's silence watchdog already handles stuck sidecars), or add a per-run cancel button plus a distinct "timed out" error code separate from user-cancel.
  Acceptance: a 61+ minute preset run completes; a watchdog kill reports "stuck/timeout", never "cancelled by user".
  Confidence: Verified. Effort: S

- [ ] P2 — Item 202 — Recorder cancel hard-kills FFmpeg mid-mux, leaving a corrupt recording it neither cleans nor flags
  Category: correctness (data)
  Where: `src/UniversalConverterX.UI/Views/Pages/RecorderPage.xaml.cs:364-368,326-347`; `src/UniversalConverterX.UI/Services/SidecarRunner.cs:429` (`Kill(entireProcessTree:true)`).
  Problem: Cancel → `_cts.Cancel()` → hard process-tree kill. For a screen recording writing non-fragmented MP4/H.264, a hard kill means no moov atom → the partial file at `outputPath` is unplayable; the page marks the job "Cancelled" and leaves the dead file in the output folder with no cleanup and no warning. This is the one surface where cancel destroys unique, unrecoverable data (the recording itself) rather than a re-runnable conversion. (Distinct from the known per-page CTS divergence — this is the cancel-cleanup gap.)
  Evidence: recordcast job is "MP4 H.264, CRF"; cancel path hard-kills; no partial-file cleanup/label.
  Fix: recordcast should stop gracefully (send `q`/SIGINT to ffmpeg, or record fragmented / add faststart on stop); failing that, delete or clearly label the partial file on cancel.
  Acceptance: cancelling a 60 s recording at t=10 s yields either a playable ~10 s file or no file — never a dead file presented as finished.
  Confidence: Needs-repro (confirm whether recordcast already uses fragmented MP4). Effort: M

- [ ] P2 — Item 203 — Downloader silently reroutes output to %TEMP% and never shows where files land
  Category: ux / correctness
  Where: `src/UniversalConverterX.UI/Views/Pages/DownloaderPage.xaml.cs:42-54`.
  Problem: if `~\Downloads\UniversalConverterX` can't be created, the page falls back to `%TEMP%\UniversalConverterX-Downloads` without telling the user; if that also fails the sidecar gets a nonexistent `--output-dir`. Files in TEMP are subject to disk-cleanup deletion, no UI element ever displays `_outputDir`, and it ignores `ConverterXOptions.DefaultOutputDirectory`.
  Evidence: silent catch → TEMP fallback; no surfacing of the effective directory; configured default not consulted.
  Fix: prefer `DefaultOutputDirectory` before TEMP; surface the effective output directory in the page header/status, and warn when the fallback is used.
  Acceptance: with Downloads redirected read-only, the page visibly states where files will be written before the first download.
  Confidence: Verified. Effort: S

### P3 — debt, polish, lower-value correctness

- [ ] P3 — Item 204 — `ProgressWindow` is dead UI carrying latent bugs
  Category: maintainability
  Where: `src/UniversalConverterX.UI/Views/ProgressWindow.xaml{,.cs}` (only reference is a comment at `MainWindow.xaml.cs:93`).
  Problem: no `new ProgressWindow(...)` exists anywhere; the window (Pause/Cancel/Open-folder, per-file list) is unreachable, yet localized, styled, and maintained (~15 K). If wired as-is it ships three bugs: no `Closed` handler cancels `_cts` (closing mid-run leaves the loop + ffmpeg children detached), a `while(_isPaused) await Task.Delay(100)` busy-loop that spins forever if closed while paused, and the only unwrapped `Process.Start` among its peers.
  Evidence: project-wide grep for `new ProgressWindow` returns nothing.
  Fix: delete the window and its `x:Uid` resources (update UIA/localization baselines), or wire it as the shared progress surface and fix the three issues.
  Acceptance: no orphaned type; build clean; localization gate passes.
  Confidence: Verified. Effort: S

- [ ] P3 — Item 205 — LosslessCut timeline playhead is a hardcoded white rectangle, low-contrast in light theme
  Category: visual
  Where: `src/UniversalConverterX.UI/Views/Pages/LosslessCutPage.xaml:106` (`<Rectangle x:Name="Playhead" Width="2" Fill="White"/>`).
  Problem: the 2px scrub playhead is a literal `Fill="White"` over the thumbnail strip whose fallback surface is `SurfaceLightBrush` (`#dfe7f1`, near-white) in light theme, so it nearly vanishes; it also disappears over bright video frames in either theme (no outline/shadow). The sibling `SelectionBand` correctly uses `AccentGreenBrush`.
  Evidence: literal `White` vs the file's theme-token pattern; light surface behind it (App.xaml:65).
  Fix: use a theme-adaptive brush (e.g. `AccentPrimaryBrush`/`AccentRedBrush`) or add a contrasting 1px outline/drop-shadow so it reads over light surfaces and bright media.
  Acceptance: the playhead is clearly visible on the empty light-theme strip and over a white video frame.
  Confidence: Likely. Effort: S

- [ ] P3 — Item 206 — Dead hardcoded border color on `DangerButtonStyle`
  Category: visual (debt)
  Where: `src/UniversalConverterX.UI/App.xaml:401` (`<Setter Property="BorderBrush" Value="#7f1d1d"/>` with `BorderThickness="0"` at `:402`).
  Problem: a fixed dark-red hex sits next to zero thickness so it renders nothing today; if the thickness is ever raised, this non-token color is frozen across both themes (wrong on the light `SurfaceDanger` `#fde1e3`). It's the lone literal brush among this file's ThemeResource tokens.
  Evidence: literal `#7f1d1d` vs the file's `BorderStrongBrush`/`AccentRedBrush` pattern; inert due to `BorderThickness=0`.
  Fix: remove the setter, or point it at a themed danger token if a border is intended.
  Acceptance: no literal color remains in `DangerButtonStyle`.
  Confidence: Verified. Effort: S

- [ ] P3 — Item 207 — REST metrics report 0 for non-lowercase engine names; null exit counted as failure
  Category: correctness
  Where: `src/UniversalConverterX.Console/Commands/ServeCommand.cs:397-398` vs `:416-427`; `:463-469`.
  Problem: `_metrics` is keyed on `engine.Trim().ToLowerInvariant()`, but `MetricsSnapshot` groups live jobs by the raw `job.Engine` (`StringComparer.Ordinal`) and looks them up by the lowercased key, so `POST /convert {"engine":"Converter"}` succeeds (`:175` is OrdinalIgnoreCase) yet its running/retained gauges stay 0. Also `EngineJobCounters.MarkCompleted` counts a null `ExitCode` as a failure.
  Evidence: key casing mismatch between store and snapshot; null-exit branch increments `_failed`.
  Fix: normalize engine name consistently for both counters and snapshot; treat null exit as unknown, not failed.
  Acceptance: metrics report correct running/retained for a mixed-case engine; an aborted-before-exit job isn't miscounted as failed.
  Confidence: Verified. Effort: S

- [ ] P3 — Item 208 — Residual Spectre markup-injection sinks in CLI output
  Category: correctness
  Where: `src/UniversalConverterX.Console/Commands/ConvertPresetCommand.cs:116-119` (interpolates `match.Name` into `MarkupLine`), `:142-148` (`table.AddRow(p.Name, p.Folder, p.Engine,…)` renders args as markup); `ToolsCommand.cs:128` (`versionStr` from tool stdout), `:192` (`result.ErrorMessage`).
  Problem: a `[` in a user-writable preset name (`%LocalAppData%\UniversalConverterX\presets`) or in a third-party tool's version banner throws inside Spectre and yields the wrong exit code — the same class already fixed elsewhere (compare `EnginesCommand.cs:63-67`, which escapes correctly).
  Evidence: unescaped user/external strings passed to Spectre markup sinks.
  Fix: `Markup.Escape(...)` these values before rendering.
  Acceptance: a preset named `x[y` lists without throwing and with the correct exit code; add a test.
  Confidence: Verified. Effort: S

- [ ] P3 — Item 209 — Shell registrar self-invokes regsvr32 (dead recursive hook) and builds a PowerShell command string
  Category: maintainability / security
  Where: `src/UniversalConverterX.ShellExtension/ShellExtensionRegistrar.cs:334-349,38-45` and `:102-122`.
  Problem: `[ComRegisterFunction] Register` calls `Register(assembly.Location)`, which shells `regsvr32 /s <that same dll>`. Under .NET 10 `comhost` the managed hook is never invoked (dead code), but it is a recursive `regsvr32` loop if anything (RegAsm, a test harness, a packaging script) calls it directly. Separately `RegisterSparsePackage` interpolates `$manifestPath` into `-Command "Add-AppxPackage -Path '<path>' -Register"`; a `'` in the path breaks the quoting.
  Evidence: the register hook re-invokes regsvr32 on itself; string-built PowerShell command.
  Fix: drop the dead hook; pass the manifest path via `ArgumentList` / a properly-escaped argument.
  Acceptance: registration does not recurse; a path containing `'` registers correctly.
  Confidence: Likely. Effort: S

- [ ] P3 — Item 210 — FFmpeg-proxy client does not pin the pipe server to the current user
  Category: security (defense-in-depth)
  Where: `src/UniversalConverterX.FfmpegProxy/Program.cs:33-37` vs `src/UniversalConverterX.UI/Services/SidecarRunner.cs:821-827`.
  Problem: the server creates the pipe with `PipeOptions.CurrentUserOnly`; the client omits it (and any `TokenImpersonationLevel`), so it connects to whatever server holds that name. The 128-bit random pipe name (`SidecarRunner.cs:735`) makes squatting impractical, but the asymmetry is free to fix and is the only thing between a spoofed "approved" response and the real ffmpeg argument vector at `:72-73`. Note the `ValidateResponseArguments` shell-metachar screen (`:113-119`) is decorative — `ArgumentList` never goes through a shell — so it shouldn't be relied on as the review guard.
  Evidence: server sets `CurrentUserOnly`, client does not.
  Fix: connect with `PipeOptions.CurrentUserOnly` (and set impersonation level) on the client.
  Acceptance: the proxy client refuses to connect to a same-name pipe owned by another user; add a test if feasible.
  Confidence: Likely. Effort: S

- [ ] P3 — Item 211 — PowerShell module edge cases: `-Crf 0`/`-TargetMb 0` dropped; strict-mode NDJSON property access
  Category: correctness
  Where: `integrations/powershell/UniversalConverterX.psm1:333-334` (`if ($Crf)`/`if ($TargetMb)`) and `:23,150-163`.
  Problem: `if ($Crf)`/`if ($TargetMb)` are falsy at 0, so `-Crf 0` (lossless x264/x265) and `-TargetMb 0` are silently dropped. Under `Set-StrictMode -Version Latest` + `$ErrorActionPreference='Stop'`, an NDJSON line missing `event`/`level`/`message`/`percent` throws `PropertyNotFoundException` and aborts the whole cmdlet; the author guarded `stage` this way at `:152` but left the other five unguarded.
  Evidence: truthiness checks on numeric params; unguarded property access under strict mode.
  Fix: use `$PSBoundParameters.ContainsKey(...)` for numeric params; guard the NDJSON property reads with `$ev.PSObject.Properties[...]` like `stage`.
  Acceptance: `-Crf 0` passes `--crf 0`; a minimal NDJSON line doesn't abort the cmdlet.
  Confidence: Verified. Effort: S

- [ ] P3 — Item 212 — "Open output folder" selects the folder in its parent instead of opening it
  Category: ux
  Where: `src/UniversalConverterX.UI/Views/Pages/RecorderPage.xaml.cs:528-550` (`OpenContainingFolder`, called by `:370`); same pattern in `DownloaderPage` `OpenOutput_Click:427`.
  Problem: for a directory argument the code runs `explorer.exe /select,"<dir>"`, which opens the PARENT with `<dir>` highlighted rather than opening the directory's contents. Buttons labeled "Open output folder" should show the folder's files.
  Evidence: `/select,"folder"` is built even when the target resolves to the directory itself.
  Fix: when the target is an existing directory, launch `explorer.exe "<dir>"` (no `/select`); keep `/select` only for file paths (per-file reveal).
  Acceptance: "Open output folder" opens that folder's contents; per-file reveal still highlights the file.
  Confidence: Verified. Effort: S

### Refinement to an existing item (not a duplicate)

- Item 162 (implement or remove every persisted setting): this audit confirmed specific additional ghost settings beyond the four already listed — `DefaultQuality`, `PreserveMetadataByDefault`, `DefaultHardwareAcceleration`, `ContextMenuStyle`, and `QuickConvertPresets` have NO runtime consumer in `src/` (only Settings/CLI-config read/write), the Settings "Register menu"/"Remove menu" buttons only show an info dialog (`SettingsWindow.xaml.cs:460-472`), and `AccentColor_Click` never writes `_options.AccentColor`. Fold these into Item 162's implement-or-remove sweep and its no-op-setting contract test. (The hardware-accel index/enum persistence bug is tracked separately as Item 180.)

### Unaudited — needs a dedicated pass

- [ ] P2 — Item 213 — Python sidecar security/correctness audit did not complete
  Category: testing
  Where: `tools/` — 212 sidecar engines (~78k Python lines) and the shared `tools/_lib/ucx_sidecar.py`.
  Problem: the Python audit agent for this pass terminated on an API limit before covering the sidecars. Areas specifically not verified this pass: archive-extraction path traversal beyond the comic/notetaking/gameasset paths routed through `safe_tar_extractall` in v2.31.4; remaining unbounded `subprocess.run` calls in nested op-modules (e.g. `clipforge_ops`); decompression-bomb / malformed-binary-header handling in pure-format parsers; fork-bomb guards in auto-installing sidecars.
  Fix: run a dedicated read-only Python audit (start with `_lib`, then sample across FFmpeg/archive/download/AI/pure-parser families), verifying against `tests/sidecar_contract/check_contract.py`.
  Acceptance: each sidecar family has a documented verdict (clean or a filed finding); `_lib` extraction/timeout helpers confirmed used everywhere they should be.
  Confidence: N/A (scope marker). Effort: L

- [ ] P3 — Item 214 — Running-app visual/theme pass and several UI page bodies were not line-audited
  Category: testing
  Where: light/dark running-app captures beyond the routes checked; page bodies only pattern-swept (ToolboxPage 59K, ColorizeVideoPage, DvdRipPage, VmafAnalysisPage, VideoEnhancerPage, UniversalConvertPage, and others per the UI audit's "not audited" list); services `UpdateCheckService`, `UiPresetLoader`, `AppLocalizer`, `PresetSemanticSearch`, `QnnCapabilityProbe`; all ViewModels.
  Problem: the second theming agent (running-app captures) hit an API limit; note it also observed a nondeterministic off-by-one in the `--ui-smoke` capture (some captures show the previous route), which is itself worth confirming as a harness bug so smoke PNGs can be trusted.
  Fix: a dedicated running-app light/dark visual pass with reliable per-route capture, plus line audits of the listed page bodies/services/VMs.
  Acceptance: each listed surface has a documented verdict; the `--ui-smoke` capture-vs-route off-by-one is reproduced and fixed or ruled out.
  Confidence: N/A (scope marker). Effort: M
