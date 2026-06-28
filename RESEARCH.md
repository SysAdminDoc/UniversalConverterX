# Research - UniversalConverterX

## Executive Summary
UniversalConverterX is a local-first Windows media and file-conversion suite built on a .NET 10 / WinUI 3 shell plus a large NDJSON sidecar ecosystem. Its strongest shape is breadth plus offline control: converter, downloader, recorder, batch presets, diagnostics, and specialized local AI workflows all share one shell. The highest-value direction is reliability and trust before more format sprawl: patch the current SQLitePCLRaw vulnerability, turn update detection into signed install/rollback, reconcile shipped workflows still labeled Future, add preflight health for sidecar binaries/models, persist active batch queues, and refresh platform/package upgrades already visible from local package checks.

Top opportunities: P0 SQLitePCLRaw security patch; P0 signed tool update/install flow; P1 shipped workflow discoverability repair; P1 persistent queue resume; P1 sidecar capability/preflight panel; P2 WinAppSDK and package refresh; P2 portable release manifest with hashes.

## Product Map
- Core workflows: batch convert/compress, preset execution, sidecar-backed media tools, downloader cookie-auth flows, local diagnostics/history.
- User personas: Windows power users converting mixed media, creators preparing social/video/audio assets, archivists preserving metadata/HDR/subtitles, technical users running specialty format transforms.
- Platforms and distribution: Windows 10/11, x64/arm64 projects, MSI/MSIX scaffolding, CLI `ucx`, Explorer shell extension, PowerShell module.
- Key integrations and data flows: C# orchestrator selects native strategies; WinUI pages launch sidecar `.exe` tools; sidecars stream NDJSON events; history/log/cache data stays under `%LocalAppData%/UniversalConverterX`; update checks query public GitHub Releases when enabled.

## Competitive Landscape
- HandBrake: strong queue, encoder, and hardware-acceleration discipline. Learn from its queue UX and conservative encode reliability. Avoid becoming video-only or hiding sidecar/tool health.
- Shutter Encoder: broad FFmpeg GUI with pro workflows and portable distribution. Learn from direct access to advanced FFmpeg features. Avoid dense controls without preflight validation.
- LosslessCut: fast lossless editing and careful overwrite/recovery behavior. Learn from focused recovery-safe file operations. Avoid promising broad conversion coverage where precision editing is the main user need.
- Subtitle Edit: best-in-class subtitle editing, OCR, sync, and translation breadth. Learn from subtitle production as a workflow, not a single conversion. Avoid bundling cloud translation as a default.
- Wondershare UniConverter / Any Video Converter / Movavi: polished commercial suites with AI enhancer, downloader, compressor, subtitle, DVD, and one-click flows. Learn from discoverability and guided status states. Avoid subscriptions, cloud processing, telemetry, and paywall-driven feature splits.
- Topaz Video AI / Upscayl / Video2X: focused AI enhancement with preview/compare expectations. Learn from before/after preview and model selection. Avoid silent model downloads or opaque GPU failure states.
- Tdarr: distributed conditional transcoding and plugin pattern. Learn from explicit plugin manifests and worker health. Avoid turning UCX into a server-first multi-user platform.

## Security, Privacy, and Reliability
- Verified: `dotnet list src\UniversalConverterX.sln package --vulnerable --include-transitive` reports high-severity `SQLitePCLRaw.lib.e_sqlite3` 2.1.11 via `src/UniversalConverterX.UI/UniversalConverterX.UI.csproj`.
- Verified: `src/UniversalConverterX.Core/Services/ToolManager.cs` exposes `AutoDownloadTools` plumbing but `DownloadToolAsync` still returns "Automatic download not implemented"; `src/UniversalConverterX.UI/Services/UpdateCheckService.cs` detects updates but does not install, verify checksums, or roll back.
- Verified: `src/UniversalConverterX.UI/Views/Pages/ToolboxPage.xaml.cs` still labels shipped or preset-backed workflows as `Future`/unpowered, including metadata editor, auto-crop, intro/outro, lens correction, VR converter, and disc tools.
- Verified: `src/UniversalConverterX.UI/Services/SidecarRunner.cs` has a stuck-sidecar watchdog and UTF-8 NDJSON parsing, but users only learn about missing binaries/models at execution time.
- Verified: `src/UniversalConverterX.UI/Services/HistoryService.cs` records completed jobs, but there is no durable active queue resume for a crash/restart in the current batch pages.
- Missing guardrails: signed update installation, per-tool checksum/SBOM manifest, pre-run capability health, model-download consent ledger, and rollback for replaced sidecar binaries.
- Recovery needs: resumable batch queue, failed-job retry with original args, atomic tool replacement, old-binary quarantine, and a health report included in crash bundles.

## Architecture Assessment
- `ToolManager` and `UpdateCheckService` should converge: detection, install, checksum verification, version cache, and UI status need one trusted path rather than separate "check" and "manual install" stories.
- `ToolboxPage.SeedTiles()` is now a large hand-maintained inventory; the existing roadmap Item 52 sidecar manifest would reduce drift, but a short-term reconciliation pass is still needed.
- `SidecarRunner` is robust at process boundaries, but preflight belongs before execution: surface missing `.exe`, missing external binaries, missing model weights, unsupported GPU, and expected download size.
- `HistoryService` is useful post-run evidence, but it is not a job queue. Persisting queued/running args would close the reliability gap competitors expose through queue files.
- Test gaps: no automated assertion that every `Future` tile lacks a shipped route/preset; no package-vulnerability gate; no end-to-end updater rollback smoke.
- Documentation gaps: `README.md` still points to old planning files (`COMPLETED.md`, `RESEARCH_REPORT.md`) despite current hygiene requiring `RESEARCH.md` and `ROADMAP.md`.

## Rejected Ideas
- Cloud conversion or hosted AI execution: contradicts the project's no-cloud/no-telemetry thesis and commercial competitors already own that lane.
- Multi-user server mode: Tdarr-style worker fleets are useful inspiration, but UCX is a single-PC Windows app; queue resilience is the right near-term investment.
- DRM decryption for commercial media: legal and maintenance risk; keep non-DRM disc/file handling only.
- Rebuilding a full subtitle editor: Subtitle Edit already owns deep subtitle authoring; UCX should integrate practical sync/OCR/burn/export workflows.
- Generic app-store plugin marketplace: local manifest discovery is enough; remote moderation, trust, and payments do not fit the project.

## Sources
Competitors:
- https://handbrake.fr/
- https://github.com/HandBrake/HandBrake/releases
- https://github.com/mifi/lossless-cut
- https://github.com/SubtitleEdit/subtitleedit/releases
- https://www.shutterencoder.com/
- https://www.movavi.com/videoconverter/
- https://videoconverter.wondershare.com/
- https://www.any-video-converter.com/en/features.php
- https://www.topazlabs.com/topaz-video-ai
- https://github.com/upscayl/upscayl
- https://github.com/k4yt3x/video2x
- https://home.tdarr.io/

Dependencies and standards:
- https://ffmpeg.org/
- https://github.com/BtbN/FFmpeg-Builds/releases
- https://github.com/yt-dlp/yt-dlp/releases
- https://github.com/microsoft/WindowsAppSDK/releases
- https://learn.microsoft.com/windows/apps/windows-app-sdk/
- https://github.com/advisories/GHSA-2m69-gcr7-jv3q
- https://learn.microsoft.com/nuget/consume-packages/install-use-packages-dotnet-cli
- https://github.com/microsoft/winget-pkgs
- https://exiftool.org/
- https://mediaarea.net/en/MediaInfo
- https://github.com/quietvoid/dovi_tool
- https://github.com/quietvoid/hdr10plus_tool
- https://github.com/alexheretic/ab-av1
- https://github.com/Uranite/HandBrake-SVT-AV1-HDR
- https://github.com/rust-av/Av1an
- https://github.com/vapoursynth/vapoursynth/releases

## Open Questions
- Which signing material is available locally for MSI/MSIX/tool binaries?
- Should tool replacement install into the app-local `tools/` tree only, or also support `%LocalAppData%/UniversalConverterX/tools/` user installs?
