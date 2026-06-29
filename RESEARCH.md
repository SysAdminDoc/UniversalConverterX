# Research — UniversalConverterX

## Executive Summary
UniversalConverterX is a local-first Windows conversion suite: a .NET 10 / WinUI 3 shell, native Core conversion strategies, CLI/Explorer integrations, and 188 Python/WebView sidecars with 400+ presets. Its strongest current shape is breadth plus offline trust, but the highest-value direction is now reliability: make restore/build state truthful, make destructive source-file actions actually run end-to-end, validate native converter outputs, and turn sidecar/package metadata into release-grade evidence. Top opportunities, in priority order: (Verified) fix current `dotnet restore` NU1605 package downgrade and version drift; (Verified) wire `PostConversionHandler` through Core/CLI/UI before source delete/move is trusted; (Verified) fail native conversions on missing/zero-byte outputs; (Verified) align ML sidecar dependency floors with current ONNX Runtime security releases; (Verified) finish the existing release manifest/hashes roadmap item; (Likely) add operation-level capability metadata so placeholder sidecar paths are hidden or clearly blocked; (Verified) evaluate WinAppSDK 2.2 `VideoScaler` as an optional local upscaling backend; (Verified) clean public planning/docs links so README does not point users at stale legacy planning files.

## Product Map
- Core workflows: drag/drop batch conversion, preset execution, compressor/editor/downloader/recorder pages, AI/media toolbox flows, CLI `ucx`, Explorer preset invocation.
- User personas: Windows power users converting mixed media, creators making social/video/audio deliverables, archivists preserving HDR/subtitles/metadata, technical users scripting specialty conversions.
- Platforms and distribution: Windows 10/11, .NET 10, WinUI 3, x64/ARM64 project targets, MSI/MSIX scaffolding, PowerShell module, portable sidecar model under `tools/<engine>/`.
- Key integrations and data flows: WinUI pages create jobs/presets; Core strategies launch external tools; sidecars emit NDJSON; history/log/crash/cache files stay in `%LocalAppData%/UniversalConverterX`; tool downloads use SHA-256 checked staging/rollback.

## Competitive Landscape
- HandBrake: strong release discipline, queue/preset upgrade warnings, and active issue traffic around batch corruption, default audio flags, and encode reliability. Learn from conservative upgrade/queue safety; avoid becoming video-only.
- LosslessCut: fast lossless editing with segment/project workflows and visible release caveats for packaging/playback regressions. Learn from precise file-operation recovery and explicit warnings; avoid timestamp/preview mismatch in export paths.
- Subtitle Edit: subtitle production depth, active v5.0 releases, OCR/sync/translation breadth. Learn from workflow completeness for captions; avoid trying to clone a full subtitle editor when UCX can orchestrate practical pipeline stages.
- OpenShot / Shutter Encoder: broad FFmpeg GUI surface with proxy editing, UI scaling, pro filters, and direct FFmpeg access. Learn from proxy/preview ergonomics and advanced-mode escape hatches; avoid exposing unsupported controls without preflight.
- Wondershare UniConverter / Movavi / Any Video Converter / VideoProc: commercial suites package guided AI, downloader, compressor, subtitle, and DVD flows. Learn from first-run clarity and guided statuses; avoid cloud/subscription/telemetry tradeoffs.
- Topaz Video AI / Upscayl / Video2X: focused AI enhancement products normalize before/after preview, model choice, GPU capability messaging, and long-running job expectations. Learn from compare/preview and hardware gating; avoid silent model or driver failures.
- Tdarr: worker health, conditional transcoding rules, plugin-style local automation. Learn from explicit worker/plugin manifests; avoid making UCX server-first or multi-user by default.

## Security, Privacy, and Reliability
- Verified: `dotnet restore src\UniversalConverterX.sln` currently fails with NU1605 because `tests/UniversalConverterX.Core.Tests/UniversalConverterX.Core.Tests.csproj` pins `Microsoft.Extensions.Options` 10.0.0 while `src/UniversalConverterX.Core/UniversalConverterX.Core.csproj` requires 10.0.9.
- Verified: version truth is split: `README.md` and app projects show 2.21.9, while `Directory.Build.props` and `src/Directory.Build.props` still show 2.21.7; release manifests depend on these surfaces staying aligned.
- Verified: `src/UniversalConverterX.Core/Utilities/PostConversionHandler.cs` and tests exist, but `rg "PostConversionHandler.Execute" src tests` finds only tests; `ConversionOrchestrator` returns converter results without executing source keep/move/delete actions.
- Verified: `src/UniversalConverterX.UI/Views/SettingsWindow.xaml.cs` still loads/saves deprecated `DeleteSourceOnSuccess`, and `SettingsWindow.xaml` says "Move to Recycle Bin" while `PostConversionHandler.ExecuteDelete` uses `File.Delete`.
- Verified: native converter success in `src/UniversalConverterX.Core/Converters/BaseConverterStrategy.cs` records `OutputFileSize = 0` when output is missing but still returns `ConversionResult.Succeeded`; sidecar duration validation does not cover this native path.
- Verified: `tools/stemkit/requirements.txt` allows `onnxruntime>=1.17`, below the newer ONNX Runtime security floor already recognized in other sidecars; ONNX Runtime v1.27.0 release notes list security fixes.
- Missing guardrails: package graph lock/restore gate, generated version consistency check, native output file integrity checks, operation-level sidecar capability metadata, and release manifest/SBOM hash publication.
- Recovery and rollback needs: source-action audit trail after successful conversion, zero-byte/truncated-output quarantine, release manifest hash verification, and ARM64/x64 packaging smoke with sidecar/tool inventory.

## Architecture Assessment
- `Directory.Build.props` is not the single version source in practice because projects also carry explicit `<Version>` values; add a version-truth test or centralize version properties.
- `ConversionOrchestrator` is the right boundary for source-file post actions because CLI, UI, and native strategies all pass through it; add tests proving post actions run only after verified output.
- `BaseConverterStrategy` should treat missing/zero-byte output as failure unless a converter explicitly declares stdout/no-output semantics; competitor issue traffic shows "success with bad output" is a trust-killer.
- `SidecarHealthService` is useful but hard-coded; existing roadmap Item 52 should evolve into bundled sidecar manifests before third-party plugins so health requirements, supported ops, and placeholder paths cannot drift.
- `SettingsWindow` needs to reflect `PostConversionAction` and `PostConversionArchiveFolder`, not the deprecated bool, and must use truthful copy for hard delete vs recycle/archive.
- Test gaps: no restore/package-cadence test, no version consistency test, no native converter output-integrity test, no UI/CLI test for source move/delete, no operation-level sidecar capability coverage.
- Documentation gaps: `README.md` still links legacy planning files (`COMPLETED.md`, `RESEARCH_REPORT.md`) despite current hygiene saying `RESEARCH.md` and `ROADMAP.md` are the planning surfaces.
- Coverage note: this refresh adds security, reliability, testing, docs, distribution, offline-resilience, and upgrade work; accessibility, i18n, plugin ecosystem, and migration already have active roadmap coverage; mobile, cloud, and multi-user modes conflict with the local single-user charter.

## Rejected Ideas
- Cloud conversion or hosted AI execution (Wondershare/Topaz/Movavi): contradicts the no-cloud/no-telemetry thesis.
- Generic remote plugin marketplace (Tdarr/OBS inspiration): local manifest/drop-folder plugins fit; remote trust, moderation, and payments do not.
- Full multi-user distributed transcoding fleet (Tdarr): useful architecture reference, but UCX is a local Windows app; manifest/worker health is enough now.
- DRM ripping/decryption for commercial discs (commercial converter pressure): legal and maintenance risk; keep non-DRM disc handling.
- Replacing existing sidecars with one monolithic FFmpeg GUI (Shutter/OpenShot pattern): would discard UCX's strongest differentiator, the broad NDJSON sidecar ecosystem.

## Sources
Local project:
- https://github.com/SysAdminDoc/UniversalConverterX

OSS competitors:
- https://github.com/HandBrake/HandBrake/releases/tag/1.11.2
- https://github.com/HandBrake/HandBrake/issues/7949
- https://github.com/HandBrake/HandBrake/issues/7942
- https://github.com/mifi/lossless-cut/releases/tag/v3.69.0
- https://github.com/mifi/lossless-cut/issues/2948
- https://github.com/mifi/lossless-cut/issues/2939
- https://github.com/SubtitleEdit/subtitleedit/releases/tag/v5.0.0
- https://github.com/OpenShot/openshot-qt/releases/tag/v3.5.1
- https://github.com/zbabac/VCT/releases/tag/v1.11.0
- https://github.com/Thavarshan/comet
- https://github.com/HaveAGitGat/Tdarr

Commercial/adjacent:
- https://videoconverter.wondershare.com/
- https://www.movavi.com/videoconverter/
- https://www.any-video-converter.com/en/features.php
- https://www.topazlabs.com/topaz-video-ai
- https://www.videoproc.com/video-converter-ai/

Standards/dependencies/security:
- https://github.com/microsoft/WindowsAppSDK/releases/tag/v2.2.0
- https://github.com/dotnet/runtime/releases/tag/v10.0.9
- https://github.com/microsoft/onnxruntime/releases/tag/v1.27.0
- https://github.com/yt-dlp/yt-dlp/releases/tag/2026.06.09
- https://github.com/FFmpeg/FFmpeg
- https://github.com/rigaya/NVEnc/releases/tag/9.22
- https://github.com/fluentassertions/fluentassertions/releases/tag/8.10.0
- https://xunit.net/releases/v3/3.2.2
- https://github.com/advisories/GHSA-2m69-gcr7-jv3q
- https://learn.microsoft.com/nuget/consume-packages/install-use-packages-dotnet-cli
- https://github.com/microsoft/winget-pkgs

## Open Questions
- What signing certificate/material is available locally for MSI/MSIX and release artifacts?
- Should source-file delete mean permanent delete, Recycle Bin, or only archive move by policy?
