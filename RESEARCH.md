# Research — UniversalConverterX
Date: 2026-07-20 — replaces all prior research (previous pass 2026-07-16 @ v2.22.1 is fully stale).

## Executive Summary
UniversalConverterX (v2.31.5) is a mature offline-first Windows media suite: .NET 10 / WinUI 3 shell, Core strategy engine, `ucx` CLI + REST + PowerShell module, Explorer shell extension, 212 NDJSON sidecar engines, 300+ presets, 53 UI pages, 6 locales. **The entire 2026-07-16 research queue has shipped** — the July CVE floors, ImgConverter ports (batch edit pipeline, binary-search quality targeting, SHA-256 default-deny plugin trust, scan-review table, post-batch actions), CompressorPage size-target + VMAF targeting, the full preset editor, WinAppSDK 2.2 / Mica backdrop, and the 190→212 sidecar health-manifest rollout. The chronic WinUI PRI build blocker is also resolved (`dotnet build -p:Platform=x64`). Verified against CHANGELOG v2.23.0→v2.31.5 and source.

The result: UCX's remaining gaps are narrow and specific, not broad. The highest-value directions now are (1) **closing a security policy gap** — four untrusted-file parsers (libheif, libjxl, libvips, Ghostscript) are absent from `ToolVersionPolicy.cs` despite fresh 2026 parse-triggered CVEs (libheif CVE-2026-32740, CVSS 8.8, fires on the default decode path); (2) **a native FFmpeg two-pass silent no-op** (`FFmpegConverter.cs:234`) that lies to the user; (3) **a runtime UI-automation smoke harness** — the biggest quality gap, since the v2.31.4 nine-page launch-NRE cluster was caught entirely by hand; and (4) **surfacing power UCX already ships** as named workflows — one-click Remux (change container, no re-encode), encode-history replay, Production/Preservation preset families, and JXL lossless-JPEG recompression. Chasing bleeding-edge *encode* formats (AV2, VVC-encode) buys near-zero 2026 playback and is correctly deprioritized; the wins are ergonomics, reliability, and exposing hidden capability.

Top opportunities in priority order: security policy coverage for the 4 ungated parsers → native two-pass correctness → UI-automation harness → Remux action → encode-history replay → atomic queue persistence → JXL lossless-JPEG → track keep/drop UI → Production/Preservation presets → HW-encoder detection (AMD VCN / Intel QSV) → local AI tiers (RIFE, Kokoro TTS, Surya OCR→Markdown).

## Product Map
- **Core workflows:** batch convert (native `IConverterStrategy` + presets), compress (two-pass size-target + ab-av1 VMAF), edit (image pipeline), download (yt-dlp/Deno), record, 212-engine Toolbox/AI Lab, CLI/REST/PowerShell automation, Explorer context menu, watch folders, SQLite history with re-run.
- **Personas:** Windows power users converting mixed local files; creators producing social/web outputs; archivists (HDR, subtitles, metadata, lossless); scripters automating long-tail conversions.
- **Platforms/distribution:** Windows 10 21H2+/11, .NET 10, WinUI 3 (WindowsAppSDK 2.2.0), ARM64 cross-published. WiX MSI + portable ZIP; MSIX/WinGet blocked only on the standing no-code-signing policy. Sidecars frozen under `tools/<engine>/`.
- **Data flows:** UI/CLI → Core strategy or `SidecarRunner` (NDJSON events) → `OutputDurationValidator`/`PostConversionHandler`; settings/history/logs under `%LOCALAPPDATA%/UniversalConverterX`; managed tool downloads SHA-256-verified with rollback and per-tool size caps.

## Competitive Landscape
- **HandBrake 1.11** — shipped "Production" (ProRes/DNxHR/MOV) and "Preservation" (FFV1-in-MP4, FLAC vs PCM) named preset families, plus AMD VCN AV1 10-bit HW encode. Learn: outcome-named preset families; broaden HW encode past NVENC. Avoid: 4-container ceiling, zero AI story.
- **FastFlix 6.2** — "Apply Last Used Settings" (history replay), atomic + file-locked queue persistence, full vvenc VVC encode UI. Learn: replay UX and queue durability directly patch UCX's untested UI-side `WatchFolderService`. Avoid: nothing notable.
- **MKVToolNix v100** — in-GUI PowerShell post-job action, job-queue *search*, "open copy as new settings" (clone without delete), reads MP4/MOV track names from `udta`. Learn: queue ergonomics + metadata fidelity on remux are table stakes. Avoid: nothing.
- **LosslessCut 3.69 / Shutter Encoder 20.2** — lossless crop/AR via container metadata (UCX shipped a Lossless Cut page v2.24.0); Shutter added blur-faces + speaker-ID diarization to transcription. Learn: diarization pairs with the existing whisper-stt sidecar. Avoid: Shutter's monolithic single-window UX.
- **FileFlows 25/26** — VMAF-target "Optimized" encode (UCX shipped this), Dolby Vision RPU passthrough. Learn: extend HDR fidelity to DV passthrough. Avoid: server-first multi-node scope.
- **Wondershare UniConverter v17 / Movavi** — paywall a **container-only "SuperSpeed" remux**, AI format-recommendation, guided upscale modes, voice clone, 145-language subtitle gen. Learn: the remux action is a trivial `-c copy` UCX can give away free; format-recommendation can be rule-based/offline. Avoid: cloud models, subscriptions, telemetry (Topaz Starlight is cloud — bundle only local equivalents).
- **VERT.sh / ConvertX** (privacy-converter trend) — "files never leave your machine" marketing but WASM 2GB ceilings / Docker friction. Learn: UCX is the stronger native form of this thesis; surface verifiable zero-telemetry + upstream FFmpeg/encoder attribution in-app (HN punishes hidden analytics and missing credit). Avoid: WASM build envy.

## Security, Privacy, and Reliability
**Shipped and verified** (v2.23.0–v2.31.5): `ToolVersionPolicy.cs` min-version gate for FFmpeg 8.1.2 / ImageMagick 7.1.2-15 / Calibre 9.10.0 / 7-Zip 26.01 / LibreOffice 26.2.4 / yt-dlp 2026.07.04 / Deno 2.3.0; shipped ImageMagick `policy.xml`; Ghostscript already invoked with `-dSAFER` (`GhostscriptConverter.cs:101`); MotW/Zone.Identifier propagation; tar-slip guards (`safe_tar_extractall`); CSV formula-injection neutralization; per-tool download size caps; per-call subprocess timeouts across all 212 sidecars.

**Genuine gaps found (2026-07-20):**
- **Four untrusted-file parsers are NOT in `ToolVersionPolicy.cs`** (dictionary at lines 13–20 lists only 7 tools). All have 2026 parse-triggered CVEs:
  - **libheif <1.22.0** — CVE-2026-32740 grid-tile compositing → 64-byte attacker-controlled heap OOB write on the **default decode path**, CVSS 8.8 (+ -32741/-32738/-32814). A repo source comment still references `libheif v1.18.1`. Highest-severity uncovered item.
  - **libjxl** — CVE-2026-1837 grayscale + LCMS2 color transform mis-sizes buffer → write to uninitialized/unallocated memory (UAF). Bump to current 0.11.x.
  - **libvips <8.19.x** (past commit fd28c54) — CVE-2026-3281 `vips_bandrank_build` heap overflow (local, CVSS 4.8, public PoC).
  - **Ghostscript <10.07.1** — not floor-gated (invocation is `-dSAFER`-hardened, but no version floor); long RCE history via crafted PS/EPS/PDF.
- **No confirmation the version gate BLOCKS execution.** `ToolVersionPolicy.Assess` is consumed by `SidecarHealthService`, `ToolsCommand`, and `SettingsWindow` (warn/report surfaces). Needs live validation that `ConversionOrchestrator` refuses a job when `MeetsMinimum == false` rather than only warning.
- **ImageMagick floor is 7.1.2-15** (covers the SVG→MVG injection); consider bumping to 7.1.2-27 to also cover CVE-2026-25638 (MSL memory-exhaustion DoS). Low priority.
- **Deno-mandatory-for-YouTube claim is unverified.** The 2026-07-16 research asserted YouTube extraction now requires an external Deno runtime; the security refresh could not confirm a hard cutover (Deno remains the *recommended* optional JS interpreter as of yt-dlp 2026.06.09). Needs live validation before treating Deno provisioning as load-bearing.
- **ONNX Runtime 1.27 drops CUDA 12** (CUDA 13 only). Pin ORT to 1.26.x for any sidecar shipping CUDA 12 GPU packs; audit before bumping.
- **7-Zip CVE-2026-58052** (RAR5 `:Zone.Identifier:$DATA` MotW bypass) has **no patched release** — cannot be version-gated away; UCX's own MotW propagation is the compensating control (already shipped — verify it re-stamps archive-extraction outputs).

**Reliability residue:** UI-side `WatchFolderService` (FSW callback/threading) has no test coverage — the testable admission logic was correctly extracted to Core (`WatchFileAdmission` + tests), but the orchestration path is unexercised and lacks atomic/file-locked queue persistence (FastFlix 6.2 pattern). No runtime UI-automation smoke beyond the static UIA gate.

## Architecture Assessment
- **Native FFmpeg two-pass is a silent no-op** — `FFmpegConverter.cs:234-238` logs `"Two-pass encoding requested but not implemented in single-pass mode"` and proceeds single-pass. Real two-pass/size-targeting runs only through the videocrush sidecar; the native `VideoOptions.TwoPass=true` flag lies. Reject the flag or wire it.
- **Biggest quality gap: no runtime UI-automation smoke.** The v2.31.4 launch-crash cluster (9 pages `SelectionChanged` NRE, three `x:Uid`-on-Window `XamlParseException`, density-pass clipping) was all caught by hand. A headless/offscreen WinUI drive-and-screenshot harness over `src/UniversalConverterX.UI/Views/Pages/*.xaml.cs` init handlers would gate these pre-ship.
- **Live/dynamic DASH unsupported** — `tools/streamkeep/streamkeep/dash.py:55` logs dynamic MPD as unsupported. Niche but a real capability limit.
- **Sidecar `find_ffmpeg`/`emit` consolidation is only partially drained** — `tools/_lib/ucx_sidecar.py` now carries the NDJSON protocol, FFmpeg discovery, `run()`/timeout, and tar-safety, and v2.31.5 routed all 212 through `run()`, but per-sidecar boilerplate remains (P3 debt).
- **Doc drift:** `CLAUDE.md` carries materially false claims — "Services … currently stubs" (Navigation/Dialog/Settings are fully implemented in `Services.cs`), "29 tools / 10 sidecar engines / 8 pages" (actual: 212 sidecars, 53 pages). Misleads any agent doing the Session Start Ritual.
- **Hygiene:** 8 stray root `.md` files predate the AGENTS.md hygiene rule (all gitignored, untracked): `COMPLETED.md`, `RESEARCH_REPORT.md`, `PHASE4_LAUNCH_SUMMARY.md`, `PHASE4_READINESS_CHECKLIST.md`, `POLISH_AUDIT_SUMMARY.md`, `PREMIUM_POLISH_CHECKLIST.md`, `PREMIUM_POLISH_FINAL_SUMMARY.md`, `LOGO_PROMPTS.md`. Note: PHASE4 files hold "Item 101–120", so the roadmap ID scheme must continue at **121**.
- **Test coverage is otherwise strong** — HistoryStore (SQLite), shell-extension preset quoting, end-to-end preset execution, and `WatchFileAdmission` all have tests; sidecar contract gate covers all 212 (static/`--help` for most, functional freeze-exec for a 5-engine subset).

## Rejected Ideas
- **VVC/H.266 *encode* investment** (FastFlix ships vvenc): decode-only still suffices in 2026, but *decode* support is now roadmap-eligible given Intel Lunar Lake HW decode + DVB mandate — split the old blanket rejection.
- **AV2 encode** (AOM AV2 1.0, 2026-05-28): no ffmpeg/browser/HW ecosystem; encoder is impractically slow. Decode-probe only when ffmpeg lands support.
- **Topaz Starlight / UniFab cloud models** (UniConverter 17 licensing): cloud-only; bundle local equivalents (SeedVR2/DiffBIR/Real-ESRGAN) instead — never call their endpoints.
- **Calibre DeDRM plugin** (KFX round-trip idea): legally sensitive; ship KEPUB/KFX *format* conversion only, never DRM removal.
- **aria2c external downloader for streamkeep** (yt-dlp GHSA-vx4q-3cr2-7cg2): upstream removed HLS/DASH-via-aria2c after RCE — never reintroduce; use native `-N` concurrent fragments.
- **WASM/browser build** (VERT.sh envy): 2GB WASM ceilings are exactly what UCX's native form beats.
- **Cloud/model-marketplace anything** (Wondershare/Topaz pressure): contradicts the offline/no-telemetry charter.
- **Nuitka sidecar migration** (packaging comparisons): PyInstaller onedir already wins; the real lever is shared-runtime consolidation, not switching freezers.

## Sources
OSS / releases:
- https://github.com/HandBrake/HandBrake/releases/tag/1.11.0
- https://www.omgubuntu.co.uk/2026/03/handbrake-update-prores-encoding
- https://github.com/cdgriffith/FastFlix/blob/master/CHANGES
- https://github.com/cdgriffith/FastFlix/releases/tag/6.2.1
- https://mkvtoolnix.download/doc/NEWS.md
- https://www.bunkus.org/2026/07/2026-07-05-mkvtoolnix-v100-released/
- https://www.shutterencoder.com/changelog
- https://fileflows.com/
- https://github.com/staxrip/staxrip/issues/1353
- https://github.com/k4yt3x/video2x
- https://github.com/VERT-sh/VERT
- https://github.com/C4illin/ConvertX/issues
- https://news.ycombinator.com/item?id=43663865

Commercial:
- https://betanews.com/2025/12/22/wondershare-adds-topaz-labs-ai-video-tools-to-uniconverter-17/
- https://www.dealarious.com/blog/wondershare-uniconverter-vs-movavi/

Security (CVE):
- https://jfrog.com/blog/pixelsmash-critical-ffmpeg-vulnerability-turns-media-files-into-weapons/
- https://cve.threatint.eu/CVE/CVE-2026-32740
- https://ubuntu.com/security/notices/USN-8526-1
- https://github.com/advisories/GHSA-76gx-97cq-65f5
- https://radar.offseq.com/threat/cve-2026-3281-heap-based-buffer-overflow-in-libvip-f2781821
- https://github.com/ImageMagick/ImageMagick/security/advisories/GHSA-xpg8-7m6m-jf56
- https://github.com/kovidgoyal/calibre/security/advisories/GHSA-32vh-whvh-9fxr
- https://socprime.com/blog/cve-2026-48095-7-zip-heap-overflow-flaw/
- https://nvd.nist.gov/vuln/detail/CVE-2026-58052
- https://github.com/yt-dlp/yt-dlp/security/advisories/GHSA-vx4q-3cr2-7cg2
- https://ghostscript.com/releases/cve/index.html
- https://imagemagick.org/script/security-policy.php

Formats / AI / platform:
- https://en.wikipedia.org/wiki/Advanced_Professional_Video
- https://cloudinary.com/blog/jpeg-xl-and-the-pareto-front
- https://www.phoronix.com/news/Opus-1.6-Released
- https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- https://localaimaster.com/blog/kokoro-tts-local-setup
- https://ice-ice-bear.github.io/posts/2026-04-15-birefnet/
- https://github.com/microsoft/onnxruntime/releases

## Open Questions
- Does `ConversionOrchestrator` **block** a job when `ToolVersionPolicy.Assess` returns `MeetsMinimum == false`, or only warn via `SidecarHealthService`? Determines whether Item 121 is "add tools to policy" or "add tools + enforce block." (Needs live validation — inspect the orchestrator invocation path.)
- Is an external Deno runtime **mandatory** for YouTube extraction in the shipped yt-dlp channel, or still optional? Prior research treated it as load-bearing; the 2026 CVE refresh could not confirm. (Needs live validation against the current extractor.)
- MSIX/WinGet remains gated on the standing no-code-signing policy — a product decision, not a research question.
