# Research — UniversalConverterX

## Executive Summary
UniversalConverterX is a local-first Windows conversion suite: .NET 10/WinUI 3 UI, Core conversion strategies, CLI, Explorer shell extension, 188 NDJSON sidecars, and 404 presets. Its strongest current shape is breadth plus offline trust; the highest-value direction is making that breadth verifiable before adding more engines. Top opportunities, in order: (Verified) extend dependency-floor checks beyond ML runtimes to file parsers such as Pillow; (Verified) normalize ML sidecar floors already identified in `ROADMAP.md`; (Verified) move hard-coded sidecar health/capability data into per-sidecar manifests; (Verified) publish release manifests/SBOMs with hashes and bundled-tool inventory; (Verified) extend UIA checks beyond AutomationIds to names, help text, and state semantics; (Verified) clean public planning docs so `ROADMAP.md` stays actionable-only; (Verified) add shell-extension preset invocation smoke tests; (Verified) add preset/queue compatibility warnings for updates; (Verified) evaluate WinAppSDK 2.2 `VideoScaler` as an optional local backend.

## Product Map
- Core workflows: batch conversion, preset execution, compression/editing/downloading/recording pages, AI/media toolbox flows, CLI `ucx`, and Explorer context-menu conversion.
- User personas: Windows power users converting mixed local files, creators preparing video/audio/social outputs, archivists preserving HDR/subtitles/metadata, and technical users scripting long-tail conversions.
- Platforms and distribution: Windows 10/11, .NET 10, WinUI 3, x64/ARM64 project targets, MSI/MSIX scaffolding, PowerShell module, portable sidecar layout under `tools/<engine>/`.
- Key integrations and data flows: WinUI pages create jobs/presets; Core strategies and sidecars execute local tools; sidecars emit NDJSON; logs/history/crash bundles live under `%LocalAppData%/UniversalConverterX`; tool downloads use SHA-256 checked staging and rollback.

## Competitive Landscape
- HandBrake: does queue/preset upgrade warnings and conservative release notes well. Learn from explicit compatibility warnings and decoded-frame/output integrity expectations; avoid narrowing UCX into a video-only transcoder.
- LosslessCut: does fast lossless segment workflows and explicit packaging caveats well. Learn from timestamp/export accuracy checks and ARM64 artifact self-tests; avoid preview/export drift.
- File Converter, StaxRip, and FFmpegFreeUI: do Windows context-menu conversion, advanced tool orchestration, release digests, and hardware-profile surfaces well. Learn from shell-entry smoke coverage and asset manifests; avoid exposing advanced encoder settings without capability preflight.
- Subtitle Edit and OpenShot: do caption/OCR stages, proxy/preflight UX, UI scaling, and editing states well. Learn from complete workflow states and accessibility-scaled controls; avoid trying to clone full subtitle or NLE authoring.
- Video2X, Topaz Video, VideoProc, Wondershare, and Movavi: do guided AI enhancement, model choice, GPU/driver messaging, batch AI workflows, and before/after expectations well. Learn from capability-gated previews; avoid cloud/subscription/telemetry tradeoffs.
- Tdarr and Unmanic: do worker health, plugin metadata, conditional processing, logging, and metrics well. Learn from explicit manifest-driven health and plugin boundaries; avoid making UCX server-first or multi-user by default.

## Security, Privacy, and Reliability
- Verified: `dotnet list src\UniversalConverterX.sln package --vulnerable --include-transitive` reports no vulnerable NuGet packages; `FluentAssertions` and `xunit.runner.visualstudio` remain intentionally behind latest in test projects.
- Verified: `tools/stemkit/requirements.txt` allows `onnxruntime>=1.17`, while `tools/videosubtitleremover/requirements.txt` already documents an ONNX Runtime `>=1.25.1` security floor and ONNX Runtime v1.27.0 includes more security fixes.
- Verified: non-ML parser floors are now a security gap: multiple sidecars allow Pillow versions below 12.2.0 (`tools/alphacut`, `tools/videosubtitleremover`, `tools/mediathumb`, `tools/lutgen`, `tools/retroimg`, and others), while Pillow 12.2.0 and GHSA-pwv6-vv43-88gr address image/PSD/PDF/FITS parsing vulnerabilities.
- Verified: `src/UniversalConverterX.UI/Services/SidecarHealthService.cs` hard-codes model/GPU/tool requirements in `ModelEngines`, `VulkanEngines`, `CudaOptionalEngines`, and `EngineToolRequirements`; this will drift as sidecars and presets grow.
- Verified: `tests/uia_contract/check_uia.py` passes but only enforces `AutomationProperties.AutomationId`; Microsoft guidance treats accessible names as primary identifiers and `HelpText` as needed supplemental detail.
- Verified: `src/UniversalConverterX.ShellExtension/ExplorerCommand.cs` and `Presets/PresetReader.cs` implement a differentiating Explorer flow, but the test suite has no dedicated shell-extension command/preset quoting smoke.
- Verified: `tools/whisper-cpp/build.ps1` can warn that placeholder SHA-256 verification is skipped; release manifest/SBOM work should make skipped verification visible at artifact level.
- Verified: `README.md` still links `COMPLETED.md` and `RESEARCH_REPORT.md`; `ROADMAP.md` still includes shipped/partial legacy content despite `AGENTS.md` requiring active incomplete work only.
- Missing guardrails: non-ML dependency security-floor gate, manifest-driven sidecar health metadata, release artifact manifest/SBOM, semantic UIA gate, shell-extension invocation tests, and update compatibility notices for queues/custom presets.
- Recovery and rollback needs: release-level hash verification, sidecar/tool inventory rollback visibility, shell-extension failure diagnostics, and update warnings when queued jobs or custom presets may no longer match encoder/tool defaults.

## Architecture Assessment
- `SidecarHealthService` should consume validated per-sidecar manifests before a third-party plugin ecosystem; `tests/sidecar_contract/check_contract.py` is the right enforcement point.
- Security-floor checks should be split into ML runtimes and file parsers because image/document/archive parsers accept untrusted local inputs even when no model is involved.
- Release truth should be generated once from build outputs: app version, package/runtime targets, sidecar binaries, external tool versions, SHA-256 hashes, skipped-verification flags, and signing state.
- Shell-extension behavior belongs in a small testable command/preset layer so spaces, quotes, missing registry paths, and preset overrides can be verified without Explorer automation.
- Upgrade strategy needs a compatibility channel: HandBrake and StaxRip both warn before updates that may affect queued jobs or custom presets; UCX already has settings migrations and update probing, but not user-facing compatibility notes.
- Test and documentation gaps: no non-ML dependency-floor test, no manifest schema for sidecar capabilities, no semantic UIA gate, no shell-extension smoke, no public artifact manifest, and stale planning links in README.
- Coverage note: recommended work covers security, accessibility, observability, testing, docs, distribution/packaging, plugin ecosystem, offline/resilience, migration, and upgrade strategy. i18n/l10n is already represented in older roadmap content and should be re-evaluated after roadmap cleanup; mobile and multi-user modes are intentionally secondary to the local single-user Windows charter.

## Rejected Ideas
- Cloud conversion or hosted AI execution (Wondershare/Topaz/VideoProc/Cloud-style products): contradicts the local-first/no-telemetry product thesis.
- Remote plugin marketplace (Tdarr/Unmanic inspiration): local manifests and drop-folder style plugins fit; remote trust, moderation, and payments do not.
- Full distributed transcoding fleet (Tdarr/Unmanic): useful architecture reference, but UCX should remain a desktop app with local health/preflight.
- Full subtitle editor clone (Subtitle Edit): UCX should orchestrate conversion/OCR/sync stages, not own every authoring workflow.
- DRM ripping/decryption for commercial discs (commercial converter pressure): legal and maintenance risk; keep non-DRM disc handling only.
- Cross-platform/mobile rewrite (OpenShot/LosslessCut/Video2X portability): conflicts with current WinUI/.NET Windows-specific investment.
- New root planning markdown files: `AGENTS.md` requires `RESEARCH.md` and `ROADMAP.md` only for active research/planning.

## Sources
Local project:
- https://github.com/SysAdminDoc/UniversalConverterX

OSS competitors and adjacent projects:
- https://github.com/HandBrake/HandBrake/releases/tag/1.11.2
- https://github.com/HandBrake/HandBrake/issues/6516
- https://github.com/mifi/lossless-cut/releases/tag/v3.69.0
- https://github.com/mifi/lossless-cut/issues/2939
- https://github.com/Tichau/FileConverter/releases/tag/v2.2
- https://github.com/staxrip/staxrip/releases/tag/v2.52.4
- https://github.com/SubtitleEdit/subtitleedit/releases/tag/v5.0.0
- https://github.com/OpenShot/openshot-qt/releases/tag/v3.5.1
- https://github.com/HaveAGitGat/Tdarr
- https://github.com/Unmanic/unmanic/releases/tag/0.4.0
- https://github.com/Lake1059/FFmpegFreeUI/releases/tag/6.0.28
- https://github.com/k4yt3x/video2x/releases/tag/6.4.0
- https://github.com/transitive-bullshit/awesome-ffmpeg

Commercial products:
- https://videoconverter.wondershare.com/
- https://www.movavi.com/videoconverter/whats-new.html
- https://www.videoproc.com/video-converting-software/feature-ai-frame-interpolation.htm
- https://docs.topazlabs.com/topaz-video/quick-start

Community and engineering:
- https://github.com/Netflix/vmaf
- https://www.reddit.com/r/handbrake/comments/1q0383p/handbrake_keeps_changing_av1_to_h264/
- https://stackoverflow.com/questions/tagged/ffmpeg?tab=Newest

Standards, dependencies, and security:
- https://github.com/microsoft/WindowsAppSDK/releases/tag/v2.2.0
- https://learn.microsoft.com/en-us/windows/apps/design/accessibility/basic-accessibility-information
- https://learn.microsoft.com/en-us/windows/package-manager/winget/hash
- https://cyclonedx.org/specification/overview/
- https://github.com/microsoft/onnxruntime/releases/tag/v1.27.0
- https://github.com/python-pillow/Pillow/releases/tag/12.2.0
- https://github.com/advisories/GHSA-pwv6-vv43-88gr
- https://github.com/yt-dlp/yt-dlp/releases/tag/2026.06.09
- https://github.com/opencv/opencv/releases/tag/5.0.0

## Open Questions
- None that block prioritization or implementation planning.
