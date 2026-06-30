# Research — UniversalConverterX

## Executive Summary
UniversalConverterX is a local-first Windows media and file-conversion suite: a .NET 10 / WinUI 3 shell, native Core converter strategies, CLI and Explorer integrations, and 188 NDJSON sidecars with 404 presets. Its strongest current shape is breadth plus offline trust; the highest-value direction is reliability and operational truth, not more surface area. Top opportunities, in order: (Verified) fix the current `dotnet restore` NU1605 package downgrade and version drift; (Verified) wire post-conversion source actions through Core/CLI/UI before delete/move is trusted; (Verified) fail native conversions on missing or zero-byte outputs; (Verified) normalize ML sidecar security floors; (Verified) publish release manifests with hashes and tool inventory; (Verified) clean `ROADMAP.md` into an actionable-only queue; (Verified) extend the UIA gate beyond AutomationIds to accessible names/states; (Likely) move hard-coded sidecar capability data into manifests before a plugin ecosystem; (Verified) evaluate WinAppSDK 2.2 `VideoScaler` as an optional local upscaling backend; (Verified) align public README planning links with current doc hygiene.

## Product Map
- Core workflows: drag/drop batch conversion, preset execution, compression/editing/downloading/recording pages, AI/media toolbox flows, CLI `ucx`, and Explorer preset invocation.
- User personas: Windows power users converting mixed media, creators preparing video/audio/social deliverables, archivists preserving HDR/subtitles/metadata, and technical users scripting specialty conversions.
- Platforms and distribution: Windows 10/11, .NET 10, WinUI 3, x64/ARM64 project targets, MSI/MSIX scaffolding, PowerShell module, portable sidecar layout under `tools/<engine>/`.
- Key integrations and data flows: WinUI pages create jobs/presets; Core strategies launch external tools; sidecars emit NDJSON; history/log/crash/cache files stay under `%LocalAppData%/UniversalConverterX`; tool downloads use SHA-256 checked staging and rollback.

## Competitive Landscape
- HandBrake: strong release discipline, queue/preset upgrade warnings, and active reliability requests around output naming, audio defaults, path ordering, and acceleration flags. Learn from conservative queue/output safety; avoid becoming video-only.
- LosslessCut: fast lossless editing with segment/project workflows, packaging caveats, timestamp repair requests, and merged bitstream crop/aspect controls. Learn from precise file-operation recovery and explicit export warnings; avoid timestamp/preview mismatch.
- File Converter / FFmpeg Batch AV Converter / StaxRip / FFmpegFreeUI: Windows users value Explorer-context entry, batch queues, explicit FFmpeg command visibility, hardware profiles, and fast local workflows. Learn from low-friction entry points and advanced escape hatches; avoid scattering features across many unverified mini-surfaces.
- Subtitle Edit: subtitle production depth, active v5 releases, OCR/sync/translation breadth. Learn from complete caption pipeline stages; avoid trying to clone a full subtitle editor when UCX can orchestrate practical conversions.
- OpenShot: broad FFmpeg GUI surface with proxy editing, UI scaling, pro filters, and direct FFmpeg access. Learn from preview/proxy ergonomics and disabled-state clarity; avoid exposing controls without capability preflight.
- Wondershare UniConverter / Movavi / VideoProc: commercial suites package guided AI, downloader, compressor, subtitle, DVD, and device presets as polished user flows. Learn from first-run clarity and guided statuses; avoid cloud/subscription/telemetry tradeoffs.
- Topaz Video AI: focused AI enhancement products normalize before/after preview, model choice, GPU capability messaging, and long-running job expectations. Learn from compare/preview and hardware gating; avoid silent model or driver failures.
- Tdarr / Unmanic: automation transcoders emphasize worker health, conditional rules, plugin-style processing, and health checks. Learn from explicit worker/plugin manifests; avoid making UCX server-first or multi-user by default.

## Security, Privacy, and Reliability
- Verified: `dotnet restore src\UniversalConverterX.sln` fails with NU1605 because `tests/UniversalConverterX.Core.Tests/UniversalConverterX.Core.Tests.csproj` pins `Microsoft.Extensions.Options` 10.0.0 while `src/UniversalConverterX.Core/UniversalConverterX.Core.csproj` requires 10.0.9.
- Verified: version truth is split: `README.md` and app projects show 2.21.9, while `Directory.Build.props` and `src/Directory.Build.props` show 2.21.7.
- Verified: `src/UniversalConverterX.Core/Utilities/PostConversionHandler.cs` and tests exist, but `rg "PostConversionHandler.Execute" src tests` finds only tests; `ConversionOrchestrator` returns converter results without source keep/move/delete actions.
- Verified: `src/UniversalConverterX.UI/Views/SettingsWindow.xaml.cs` still loads/saves deprecated `DeleteSourceOnSuccess`; `SettingsWindow.xaml` says "Move to Recycle Bin" while `PostConversionHandler.ExecuteDelete` uses `File.Delete`.
- Verified: `src/UniversalConverterX.Core/Converters/BaseConverterStrategy.cs` records `OutputFileSize = 0` when output is missing but still returns `ConversionResult.Succeeded`; sidecar duration validation does not cover native converters.
- Verified: `tools/stemkit/requirements.txt` allows `onnxruntime>=1.17`, below the newer ONNX Runtime floor already recognized in `tools/videosubtitleremover/requirements.txt`; ONNX Runtime v1.27.0 includes security fixes.
- Verified: `python tests\uia_contract\check_uia.py` passes, but `tests/uia_contract/check_uia.py` only enforces `AutomationProperties.AutomationId`; it does not verify accessible names, help text for disabled/destructive controls, or progress/state announcements.
- Verified: `python tests\sidecar_contract\check_contract.py` passes for 188 sidecars; `SidecarHealthService` remains hard-coded instead of manifest-driven.
- Missing guardrails: restore/package graph gate, version consistency test, native output file integrity checks, operation-level sidecar capability metadata, accessible-name/state UIA gate, release manifest/SBOM hash publication, and an actionable-only roadmap cleanup.
- Recovery and rollback needs: source-action audit trail after successful conversion, zero-byte/truncated-output quarantine, release hash verification, and x64/ARM64 artifact smoke with sidecar/tool inventory.

## Architecture Assessment
- `Directory.Build.props` is not the single version source in practice because projects also carry explicit `<Version>` values; centralize or add a version-truth test.
- `ConversionOrchestrator` is the right boundary for post-conversion source actions because CLI, UI, batch conversion, and native strategies pass through it; tests should prove actions run only after verified output exists.
- `BaseConverterStrategy` should treat missing or zero-byte outputs as failure unless a converter explicitly declares stdout/no-output semantics; competitor issue traffic shows "success with bad output" damages trust.
- `SidecarHealthService` should become generated from bundled sidecar manifests before third-party plugins so health requirements, supported operations, model caches, and external tools cannot drift.
- `SettingsWindow` needs to use `PostConversionAction` and `PostConversionArchiveFolder`, not the deprecated bool, and must use truthful copy for hard delete vs recycle/archive.
- `ROADMAP.md` is currently not an actionable-only queue: it still contains many `SHIPPED` and `PARTIALLY SHIPPED` legacy entries plus appendix-style source inventory, while `AGENTS.md` requires incomplete work only.
- Test gaps: no restore/package-cadence test, no version consistency test, no native output-integrity test, no UI/CLI test for source move/delete, no operation-level sidecar capability coverage, and no semantic accessibility gate.
- Documentation gaps: `README.md` and `ROADMAP.md` still link or mention legacy planning files (`COMPLETED.md`, `RESEARCH_REPORT.md`) despite current hygiene saying `RESEARCH.md` and `ROADMAP.md` are the active planning surfaces.
- Coverage note: recommended work covers security, accessibility, observability, testing, docs, distribution, plugin ecosystem, offline/resilience, migration, and upgrade strategy. i18n/l10n already exists as Item 41; mobile and multi-user modes remain intentionally secondary to the local single-user Windows charter.

## Rejected Ideas
- Cloud conversion or hosted AI execution (Wondershare/Topaz/Movavi): contradicts the no-cloud/no-telemetry thesis.
- Generic remote plugin marketplace (Tdarr inspiration): local manifest/drop-folder plugins fit; remote trust, moderation, and payments do not.
- Full multi-user distributed transcoding fleet (Tdarr/Unmanic): useful architecture reference, but UCX is a local Windows app; manifest/worker health is enough now.
- Separate ARM64 packaging item (LosslessCut ARM64 caveat): already covered by existing native ARM64/packaging and release-manifest work; do not duplicate.
- Full subtitle editor clone (Subtitle Edit): caption depth is valuable, but UCX should orchestrate conversion/sync/OCR stages rather than own every authoring workflow.
- DRM ripping/decryption for commercial discs (commercial converter pressure): legal and maintenance risk; keep non-DRM disc handling.
- Replacing sidecars with one monolithic FFmpeg GUI (OpenShot-style pattern): would discard UCX's broad NDJSON sidecar ecosystem.

## Sources
Local project:
- https://github.com/SysAdminDoc/UniversalConverterX

OSS competitors:
- https://github.com/HandBrake/HandBrake/releases/tag/1.11.2
- https://github.com/HandBrake/HandBrake/issues/7949
- https://github.com/HandBrake/HandBrake/issues/7942
- https://github.com/mifi/lossless-cut/releases/tag/v3.69.0
- https://github.com/mifi/lossless-cut/issues/2930
- https://github.com/mifi/lossless-cut/issues/2789
- https://github.com/mifi/lossless-cut/pull/2846
- https://github.com/SubtitleEdit/subtitleedit/releases/tag/v5.0.0
- https://github.com/OpenShot/openshot-qt/releases/tag/v3.5.1
- https://github.com/Tichau/FileConverter
- https://github.com/eibols/ffmpeg_batch
- https://github.com/staxrip/staxrip
- https://github.com/HaveAGitGat/Tdarr
- https://github.com/Unmanic/unmanic
- https://github.com/Lake1059/FFmpegFreeUI

Commercial/adjacent:
- https://videoconverter.wondershare.com/
- https://www.movavi.com/videoconverter/
- https://www.topazlabs.com/topaz-video-ai
- https://www.videoproc.com/video-converter-ai/

Community/awesome lists:
- https://github.com/krzemienski/awesome-video
- https://www.reddit.com/r/handbrake/top/

Standards/dependencies/security:
- https://github.com/microsoft/WindowsAppSDK/releases/tag/v2.2.0
- https://learn.microsoft.com/windows/apps/design/accessibility/accessibility-overview
- https://learn.microsoft.com/windows/windows-app-sdk/api/winrt/microsoft.ui.xaml.automation.automationproperties
- https://github.com/dotnet/runtime/releases/tag/v10.0.9
- https://github.com/microsoft/onnxruntime/releases/tag/v1.27.0
- https://github.com/yt-dlp/yt-dlp/releases/tag/2026.06.09
- https://learn.microsoft.com/nuget/consume-packages/install-use-packages-dotnet-cli
- https://github.com/advisories/GHSA-2m69-gcr7-jv3q

## Open Questions
- What signing certificate/material is available locally for MSI/MSIX and release artifacts?
- Should source-file delete mean permanent delete, Recycle Bin, or archive move by project policy?
