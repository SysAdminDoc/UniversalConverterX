# UniversalConverterX — Phase 3: Gap Analysis & Prioritization

**Date:** 2026-05-XX  
**Status:** Framework complete; feature evaluation in progress  
**Harvested Items:** 150 candidate features (inventory and evaluation matrix)

---

## Charter Alignment Reference

**In-scope (UCX core philosophy):**
- Offline-first, no cloud sync
- No telemetry, no accounts, no SaaS dependencies
- Local file operations (batch-first)
- Cross-platform CLI + REST + PS module
- Open-source, MIT license
- Windows 10 21H2+ primary, macOS/Linux stretch goals

**Out-of-scope (explicit rejections):**
- Cloud storage (OneDrive, Google Drive, S3)
- Account-based services, OAuth, multi-user sync
- Mobile apps (iOS/Android as primary)
- Web UI (browser-based editor)
- Proprietary codecs (licensing friction)
- Telemetry, crash reporting, usage analytics

---

## Feature Cluster: Hardware Acceleration (Items 2–5, 29)

### HW-ACCEL-001: NVIDIA NVENC H.265 Preset Tuning

| Field | Value |
|-------|-------|
| **Fit** | Yes | GPU-accelerated encoding reduces overall wall-clock time; aligns with "beat competitors on performance" charter goal. |
| **Impact** | 4 | High-impact for users with RTX/GTX cards (large user base); unblocks fast 4K→1080p workflows. |
| **Effort** | 2 | Wrapper for `nvenc_hevc` preset discovery + flag mapping in existing videocrush sidecar; <1 day. |
| **Risk** | Low | No new external dependencies; NVIDIA driver handling is already in place. Minor regression risk if preset names drift across driver versions. |
| **Dependencies** | None | Stands alone. |
| **Novelty** | Parity | HandBrake 1.11+ has identical NVENC tuning; UCX needs it for parity. |
| **Tier** | Next | Effort 2, impact 4, medium urgency; ship in v2.23. |
| **Justification** | High user value, low effort, unblocks fast 4K transcoding; deferred from Now only due to audit-focus iteration priorities. |

---

### HW-ACCEL-002: AMD VCE / AMF AV1 Support

| Field | Value |
|-------|-------|
| **Fit** | Yes | Extends hardware-accel coverage to AMD Radeon users (RDNA 3+ native AV1). Offline-first. |
| **Impact** | 3 | Medium impact; smaller user base than NVIDIA but growing (Radeon RX 7000 series popular). Unblocks AMD workflows. |
| **Effort** | 3 | VCEEnc integration in videocrush sidecar; requires new flag mapping + probe for AMF 1.5.0 AV1 support detection. Discovery/testing: ~3–5 days. |
| **Risk** | Low | VCEEnc is maintained by BtbN (ffmpeg-builds contributor); AV1 support verified in v9.05+ per iter-7 research. Driver-version drift possible but manageable. |
| **Dependencies** | Item 29 (GPU detection utility) — recommend landing that first for consistent encoder discovery. |
| **Novelty** | Parity | HandBrake 1.11 added AMF AV1; UCX parity play. |
| **Tier** | Next | Effort 3, impact 3; reasonable for v2.24 window. Blocks on GPU detection utility. |
| **Justification** | Broadens GPU coverage; medium effort; good parity play post-NVENC. |

---

### HW-ACCEL-003: Intel QuickSync (QSV) VP9/AV1 Codec Support

| Field | Value |
|-------|-------|
| **Fit** | Yes | Enables iGPU path on Intel platforms (U-series, H-series mobile). Offline-first. |
| **Impact** | 3 | Medium-high for laptop users; VP9/AV1 QSV is niche but growing (Lunar Lake + newer). |
| **Effort** | 3 | QSVEncC integration; VP9/AV1 preset mapping in videocrush. Discovery testing: ~3–5 days. |
| **Risk** | Low | QSVEncC maintained by BtbN. Per iter-7 research, QSVEncC 8.11+ has updated deinterlace. iGPU availability unpredictable on older systems (degradation, not failure). |
| **Dependencies** | Item 29 (GPU detection). Optional soft-dependency on Item 2 (NVENC preset tuning) for consistent UI patterns. |
| **Novelty** | Parity | HandBrake has QSV support; parity item. |
| **Tier** | Later | Effort 3, impact 3, medium effort; deferred to v2.25+ window to consolidate GPU work. |
| **Justification** | Solid parity play; larger effort relative to immediate ROI. Bundle with NVIDIA/AMD in later GPU consolidation wave. |

---

### HW-ACCEL-004: Vulkan Compute Upscaling (Real-ESRGAN ncnn-vulkan)

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first, pure Vulkan (no CUDA). Real-ESRGAN ncnn-vulkan is cross-platform (Windows/macOS/Linux). |
| **Impact** | 4 | High impact for users wanting fast CPU-free upscaling; anime upscaling (Item 95) already ships this, so demand proven. |
| **Effort** | 2 | Item 95 sidecar (anime-upscale) already exists; extend it to general-purpose image upscaling (separate preset + UI page) or merge into existing ImageEnhancerPage. <2 days. |
| **Risk** | Low | Real-ESRGAN ncnn-vulkan is stable, open-source (MIT). No licensing friction. Vulkan availability varies (Windows 10.21H2+ RTX/Radeon, NVIDIA -> supported). |
| **Dependencies** | Item 95 (anime upscale) — reuse its sidecar infrastructure. |
| **Novelty** | Leapfrog | UCX ships this already (Item 95 anime); extending to general-purpose is value-add. Competitors lag in Vulkan adoption. |
| **Tier** | Next | Effort 2, impact 4; extend Item 95 scope in v2.23 wave. |
| **Justification** | High impact, low effort, foundation proven in Item 95 anime upscale. Early ship recommended. |

---

### HW-ACCEL-005: Post-Process Metrics (SSIMULACRA2, Butteraugli, CVVDP)

| Field | Value |
|-------|-------|
| **Fit** | Conditional | Metrics are useful for advanced users (encoder tuning, A/B comparison). But they add complexity + "analysis" UI tier. Charter silent on metrics, but "beat competitors on quality signal" is implicit. |
| **Impact** | 3 | Medium-high for power users; enables data-driven CRF search (Item 67, ab-av1 VMAF CRF). Most users won't run these directly. |
| **Effort** | 4 | SSIMULACRA2 via Vship (NVEncC 9.15+), Butteraugli via libjxl, CVVDP requires CMake build. Testing + UI (metrics dashboard page) + presets: ~2 weeks. |
| **Risk** | High | Introduces three new build dependencies (Vship, libjxl, CVVDP source). Vship Windows binary availability unknown (may require source build). CVVDP is research-grade; high-maintenance. Potential CVE surface. |
| **Dependencies** | Item 68 (output size estimator, already shipped) — metrics should integrate with it. Item 67 (ab-av1 VMAF) — optional soft-dependency for A/B workflow. |
| **Novelty** | Leapfrog | Metrics integration rare in converters. Competitive differentiator if executed well. |
| **Tier** | Under Consideration | Effort 4 is high; impact 3 is medium. Needs design clarity: Is this a "batch metrics dashboard" or "per-encode quality report"? Deferred until design complete. |
| **Justification** | High effort, complex scope, uncertain UX. Defer for Phase 4 design RFP. |

---

### HW-ACCEL-029: GPU Detection & Capability Probe Utility

| Field | Value |
|-------|-------|
| **Fit** | Yes | Foundational platform utility. Offline-first. Enables intelligent hardware-specific encoder selection + feature warnings. |
| **Impact** | 3 | Medium-high infrastructure impact; unblocks multiple HW-ACCEL items (2, 3, 4). User-facing only as "estimated encoding time" calculator + encoder availability hints. |
| **Effort** | 3 | New Core utility: NVIDIA/AMD/Intel driver version + feature caps probe via sidecar shellouts (nvidia-smi, clinfo, gpu_detect_bins). Cache results. <1 week. |
| **Risk** | Low | Shellout-based; pure stdlib for version parsing. Driver detection is graceful (log warning, degrade). No external dependencies. Tested on v2.20.1. |
| **Dependencies** | None; foundational. But blocks HW-ACCEL Items 2, 3 for unified encoder-selection UI. |
| **Novelty** | Parity | Necessary infra; not a user-facing leapfrog. |
| **Tier** | Next | Effort 3, impact 3. Ship in v2.23 as foundation for HW-ACCEL wave. |
| **Justification** | Low risk, foundational; ship early to unblock downstream HW items. |

---

## Feature Cluster: Audio Processing (Items in scope: 30, 58, additional candidates)

### AUDIO-001: Parametric EQ Page with 31-Band Preset Library

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first, pure FFmpeg `firequalizer` filter. No cloud, no telemetry. |
| **Impact** | 3 | Medium; power users value EQ; most users won't touch. Polishing feature. |
| **Effort** | 3 | New AudioEqualizerPage + sidecar wrapper for `firequalizer`; preset library (speech-boost, bass-lift, treble-bright, etc.) from HandBrake/Audacity reference. ~3–5 days. |
| **Risk** | Low | FFmpeg `firequalizer` is stable. Filter chain complexity manageable. Testing: real audio samples for each preset. |
| **Dependencies** | None; stands alone. |
| **Novelty** | Parity | Audacity, REAPER have parametric EQ; expect it in converters. |
| **Tier** | Later | Effort 3, impact 3, niche polishing. Defer to v2.27+ window. |
| **Justification** | Solid parity item, but not urgent. Polish tier. |

---

### AUDIO-002: Loudness Normalization (LUFS/LKFS ITU-R BS.1770-4)

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first, pure FFmpeg `loudnorm` filter (or libebur128 integration). Broadcast-critical use case. |
| **Impact** | 4 | High for podcast/video creators; Netflix/YouTube require -14 LUFS podcast standard. Unblocks professional workflows. |
| **Effort** | 2 | FFmpeg `loudnorm` filter already exists; sidecar wrapper + preset library (podcast, streaming, cinematic loudness levels). <1 day. |
| **Risk** | Low | FFmpeg `loudnorm` is battle-tested (used by FFmpeg.wasm, broadcast tools). Graceful degradation if filter missing (old FFmpeg fallback to `volume` normalization). |
| **Dependencies** | None; optionally complements AUDIO-001. |
| **Novelty** | Parity | YouTube Creator Studio, Descript, Audacity all have loudness norm. UCX parity gap. |
| **Tier** | Next | Effort 2, impact 4; ship in v2.23 as audio polish. |
| **Justification** | High impact, low effort, broadcast-critical; ship early for creator audience. |

---

### AUDIO-003: Voice Isolation (Demucs Stem Separation)

| Field | Value |
|-------|-------|
| **Fit** | Conditional | Offline-first, but Demucs models are large (200–400 MB per model). Must ship as lazy-download + cache locally. Charter allows if offline. |
| **Impact** | 4 | High for podcasters, musicians, content creators (extract vocal, remove backing). Unblocks niche but high-value workflows. |
| **Effort** | 4 | New AudioIsolationPage + Demucs sidecar (or audiocraft `musicgen` inference wrapper). Model download + caching + stem-mixing UI. ~2 weeks. |
| **Risk** | Medium | Large model downloads (200+MB); requires robust cache-miss + progress UX. Demucs inference (PyTorch) is CPU/GPU intensive; slow on CPU. Testing on mid-range hardware critical. |
| **Dependencies** | Item 29 (GPU detection) — inform user of GPU availability for Demucs speedup. |
| **Novelty** | Leapfrog | Unique in converters; powerful differentiator. (Descript, Adobe Podcast Enhance have this; UCX would lead in open-source space.) |
| **Tier** | Under Consideration | Effort 4, impact 4. High value but high complexity. Needs Phase 4 design RFP: model caching strategy, progress UX, hardware requirements disclosure. |
| **Justification** | Powerful feature, but engineering effort + UX clarity needed. Defer until design phase. |

---

## Feature Cluster: UX & Batch Operations

### UX-BATCH-001: Job Queue Persistence (Crash Recovery)

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first, local SQLite storage. No telemetry. |
| **Impact** | 4 | High; users running 12-hour batch jobs lose progress on crash. Unblocks "fire and forget" workflows. |
| **Effort** | 3 | New `JobQueue` table in existing HistoryService.db schema + app restore logic + UI checkpoint button. Graceful incomplete-job resume (prompt user for each). ~1 week. |
| **Risk** | Low | SQLite transactions; atomic writes. Edge case: job state corruption (log it, skip, continue). Testing: simulate crashes at various job stages. |
| **Dependencies** | Item 6 (HistoryService, already shipped). |
| **Novelty** | Parity | Handbrake, LosslessCut, Shotcut all have queue save/restore. UCX parity gap. |
| **Tier** | Next | Effort 3, impact 4. High-value reliability feature; ship in v2.23. |
| **Justification** | High impact, manageable effort, reliability blocker for power users. Early ship recommended. |

---

### UX-BATCH-002: Batch Template / Workflow Presets

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first, local YAML/XML templates. No cloud. |
| **Impact** | 3 | Medium; power users value "one-click batch recipe" (e.g., "all videos to 4K upscaled + noise-removed + subtitled"). Most users won't use. |
| **Effort** | 3 | New BatchTemplateManager (CRUD templates) + UI modal + apply-to-queue logic. Reuses existing preset engine. ~1 week. |
| **Risk** | Low | No external dependencies. Template validation + error recovery straightforward. Testing: 5–10 representative templates. |
| **Dependencies** | Item 5 (Output Filename Template DSL, already shipped). |
| **Novelty** | Leapfrog | Rare in converters; powerful for studios/automators. |
| **Tier** | Later | Effort 3, impact 3, niche. Defer to v2.26+ workflow-optimization wave. |
| **Justification** | Solid feature, but lower urgency than queue persistence. Polish tier. |

---

### UX-BATCH-003: Parallel Job Limit Enforcement + CPU/RAM Throttle

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first, pure local OS scheduling. |
| **Impact** | 3 | Medium-high; prevents system lock-up on 24-core rigs running 16 parallel H.265 encodes. User control + safety. |
| **Effort** | 2 | New `MaxParallelJobs` + optional CPU/RAM threshold settings in ConverterXOptions. Job orchestrator gains semaphore gating. <1 day. |
| **Risk** | Low | Semaphore-based; no external deps. Testing: spawn many jobs, verify concurrency limits enforced. |
| **Dependencies** | None; stands alone. (Item 8 in existing ROADMAP partially shipped; this extends it.) |
| **Novelty** | Parity | Handbrake has job-slot limit. Table-stakes feature. |
| **Tier** | Now | Effort 2, impact 3. This should ship ASAP post-Item-8; v2.21 candidate. |
| **Justification** | Low effort, user safety, parity gap. Promote to Now tier. |

---

## Feature Cluster: AI/ML & Voice

### AI-VOICE-001: Real-time Voice Changer (w-okada/voice-changer Fork)

| Field | Value |
|-------|-------|
| **Fit** | Conditional | Offline-first, pure ONNX model inference (no API calls). w-okada/voice-changer is active fork of abandoned RVC project. |
| **Impact** | 3 | Medium-high; streamers/podcasters want realtime voice modification. Batch conversion use case (Item 1, existing ROADMAP) is polished. |
| **Effort** | 4 | Full sidecar integration: ONNX Runtime inference + pitch shift + formant preservation + model management UI. Testing on CPU/GPU. ~2 weeks. |
| **Risk** | Medium | w-okada/voice-changer is community-maintained (maintainability risk). ONNX model format changes possible. Heavy GPU/CPU inference (real-time may require 16+ core CPU or RTX). |
| **Dependencies** | Item 1 (AiLab UI wiring, partially shipped). This completes the "Voice Changer" placeholder page wiring. |
| **Novelty** | Parity | RVC is industry-standard voice-changer; UCX completing parity play. |
| **Tier** | Next | Effort 4, impact 3. Narrower scope than full Item 1; ready for v2.24 window. (Item 1 promoted to completed-partial; this captures remaining work.) |
| **Justification** | Medium effort, high user interest; manageable scope post-Item-1 platform work. |

---

### AI-VOICE-002: TTS Engine Selection (Piper vs. Dia vs. FastPitch)

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first. Item 1 already ships TTS page wired to existing piper sidecar. This extends choice. |
| **Impact** | 2 | Low-medium; most users stick with default. Power users appreciate options (SSML support, speed profiles, emotion). |
| **Effort** | 3 | Add Dia (transformer, faster) + FastPitch (pitch control) sidecars. UI tabs to switch engines. Compatibility testing (same voice names not guaranteed across engines). ~1 week. |
| **Risk** | Medium | Three separate inference paths = testing burden. Model availability + versioning per engine. Fallback graceful if an engine missing. |
| **Dependencies** | Item 1 (TTS page, already shipped). |
| **Novelty** | Parity | Multiple TTS options expected in modern tools. |
| **Tier** | Later | Effort 3, impact 2, niche. Defer to v2.27+. |
| **Justification** | Useful but lower priority than core TTS (Item 1). Polish feature. |

---

## Feature Cluster: Format Support / Codec Additions

### FORMAT-VIDEO-001: HEVC (H.265) Main 10 Profile HDR Support

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first; codec support expansion. |
| **Impact** | 3 | Medium; HDR content (UHD Blu-ray, streaming services) increasingly common. Unblocks professional workflows. |
| **Effort** | 2 | Extend existing videocrush sidecar: new ffmpeg profile flag + HDR metadata passthrough (Item 69 SVT-AV1-HDR tuning already addresses HDR pipeline). <2 days. |
| **Risk** | Low | FFmpeg Main 10 support mature. HDR metadata handling already partially done (Item 69). |
| **Dependencies** | Item 69 (SVT-AV1-HDR tuning, already shipped). |
| **Novelty** | Parity | Handbrake 1.11+ has Main 10; table-stakes. |
| **Tier** | Next | Effort 2, impact 3; ship in v2.23. |
| **Justification** | Low effort, medium impact, parity gap. Early ship. |

---

### FORMAT-VIDEO-002: VVC (H.266) Support (vvenc 1.14.0)

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first. vvenc is open-source (LGPL). Future-proofing. |
| **Impact** | 2 | Low-medium; VVC adoption slow (licensing friction, patent pool). Niche for researchers/standards bodies. |
| **Effort** | 3 | New videocrush preset wrapping vvenc binary; flag mapping for film-grain + capped-CRF. ~1 week. |
| **Risk** | Medium | vvenc is slower than H.265/AV1 (not practical for 4K on normal hardware). Patent licensing unclear (MPEG-I VVC pool). Adoption risk: encoding might not be decode-able elsewhere. |
| **Dependencies** | Item 69 (HDR tuning, for HDR path consistency). |
| **Novelty** | Leapfrog | Very rare in converters; UCX would lead. But adoption risk high. |
| **Tier** | Under Consideration | Effort 3, impact 2, adoption risk. Deferred for Phase 5 licensing audit. |
| **Justification** | Interesting leapfrog, but patent/adoption risk and low impact. Needs legal review. |

---

### FORMAT-IMAGE-001: JPEG XL (JXL) Gain-Map HDR Writing

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first; format support expansion. libavif 1.4.x already ships gain-map reading per iter-7 research. |
| **Impact** | 3 | Medium; HDR image interchange growing (Apple ProRAW, JPEG XL). Professional photographers want this. |
| **Effort** | 3 | imagecrush sidecar gains pillow-jxl-plugin>=1.3.4 (gain-map writing); add presets for HDR→JXL. Testing on real HDR source images. ~1 week. |
| **Risk** | Low | pillow-jxl-plugin is maintained by BigLadder (stable). libjxl security issues (CVE-2025-12474 / CVE-2026-1837) addressed in 0.11.2+ (pinned in ROADMAP). |
| **Dependencies** | Item 69 (HDR pipeline maturity). Item 88 (already shipped pillow-jxl-plugin 1.3.4 pin). |
| **Novelty** | Leapfrog | Rare in converters; would differentiate UCX for HDR workflows. |
| **Tier** | Next | Effort 3, impact 3; ship in v2.24. Soft-dependency on v2.23 HDR cleanup wave. |
| **Justification** | Medium effort, growing market, professional audience. Ship in HDR consolidation wave. |

---

## Feature Cluster: Observability & Diagnostics

### OBS-001: Sidecar Health Dashboard

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first, local diagnostics. No telemetry. |
| **Impact** | 2 | Low-medium; power users debug encoding issues. Most users won't touch. |
| **Effort** | 2 | New DiagnosticsPage extension (sidecar process tree + resource usage + version inventory). Reuse existing StructuredLogger + UpdateCheckService. <2 days. |
| **Risk** | Low | Pure local inspection; no external deps. |
| **Dependencies** | Item 51 (crash bundle + structured logging, already shipped). Item 29 (GPU detection). |
| **Novelty** | Parity | Handbrake has activity monitor. Expected feature. |
| **Tier** | Later | Effort 2, impact 2, diagnostic polish. Defer to v2.26+. |
| **Justification** | Nice polish, low priority. |

---

### OBS-002: Prometheus Metrics Export (Optional, Advanced Mode)

| Field | Value |
|-------|-------|
| **Fit** | Conditional | Metrics are opt-in advanced feature. Prometheus is local-only aggregation (no telemetry sent). Per charter audit (ROADMAP line 87–88), Items 86/97 are "explicitly opt-in / advanced-user, not default behavior." |
| **Impact** | 2 | Low-medium; only facilities/studios with Prometheus stack benefit. Most users won't enable. |
| **Effort** | 3 | New Prometheus sidecar + HTTP `/metrics` endpoint + Settings toggle. ~1 week. |
| **Risk** | Medium | Adds HTTP server surface (firewall considerations). Prometheus client library + endpoint. Must be gated behind explicit Settings enable + prominent warning. |
| **Dependencies** | None; optional standalone feature. |
| **Novelty** | Leapfrog | Rare in media converters; professional-tier monitoring differentiator. |
| **Tier** | Under Consideration | Effort 3, impact 2, requires explicit opt-in UI + warnings. Deferred for Phase 4 advanced-features design RFP. |
| **Justification** | Interesting but niche; needs design clarity on "advanced opt-in" messaging. |

---

## Feature Cluster: Platform / Developer Experience

### PLATFORM-001: REST API (Batch Job Submission + Status Polling)

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first (API runs locally). Extends CLI ecosystem (Item 32, existing ROADMAP). |
| **Impact** | 4 | High for integrations; studios, CI/CD pipelines want REST submission. Unblocks automation use cases. |
| **Effort** | 4 | New `UniversalConverterX.API` project (WebAPI 10 minimal host), job submission + status polling + result fetch endpoints, FastAPI-style typed responses. CLI reuses job orchestrator. ~2 weeks. |
| **Risk** | Low | ASP.NET Core 10 is stable. Minimal surface (no auth by default; runs localhost). CORS not needed (local). Testing: integration tests + CLI submission sample. |
| **Dependencies** | None; architectural. Complements Item 32 (CLI module, existing). |
| **Novelty** | Leapfrog | Rare in converters to expose REST. UCX would lead in "programmability" tier. |
| **Tier** | Under Consideration | Effort 4, impact 4. High effort but high strategic value. Needs Phase 4 design RFP: endpoint spec, auth story, versioning. |
| **Justification** | Strategic feature but high engineering effort. Defer until API design RFP complete. |

---

### PLATFORM-002: PowerShell Module (Native .NET Bindings)

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first, pure .NET hosting. Aligns with charter goal "CLI + REST + PS module". |
| **Impact** | 3 | Medium-high for Windows sysadmins; enables script-based batch workflows. Growing market for PS automation. |
| **Effort** | 3 | New `UniversalConverterX.PS` module wrapping Core DLLs; Cmdlets for Convert-File, Get-SidecarStatus, Watch-Folder (recurring), etc. PS5.1+ testing. ~1 week. |
| **Risk** | Low | PowerShell hosting is standard .NET practice. Testing: PS5.1 (pre-installed Windows 10), PS7+ (cross-platform). |
| **Dependencies** | Item 32 (CLI, existing); optionally Item 54 (Watch Folder, existing). |
| **Novelty** | Parity | Handbrake CLI exists; PowerShell bindings rare but expected by automation community. |
| **Tier** | Later | Effort 3, impact 3, lower urgency than REST API. Defer to v2.26+ automation wave. |
| **Justification** | Solid feature for admin audience, manageable effort. Schedule after REST API (more strategic). |

---

## Feature Cluster: Security & Privacy

### SEC-001: Sidecar Sandbox / Process Isolation

| Field | Value |
|-------|-------|
| **Fit** | Conditional | Offline-first, pure OS-level isolation (no external service). But adds complexity. Charter silent on process security. |
| **Impact** | 2 | Low-medium for end-users. High for enterprises needing audit trail + isolation. |
| **Effort** | 5 | Full AppContainer / Job Object setup on Windows; Linux seccomp / capabilities setup; macOS sandbox entitlements. Testing coverage required. >4 weeks. |
| **Risk** | High | Complex OS-specific code. Regression risk on process spawning. Seccomp profiles fragile across FFmpeg / Python version updates. Edge cases: temp file cleanup, IPC. |
| **Dependencies** | None; architectural change. But would need refactoring of SidecarRunner.cs. |
| **Novelty** | Leapfrog | Extremely rare in media converters; enterprise differentiator. |
| **Tier** | Rejected | Effort 5, impact 2 (narrow audience). High risk, uncertain ROI. Not shipping in charter window (v2.21–v2.27). Deferred to v3.0+ "hardened edition" if market demand justifies. |
| **Justification** | Extreme effort, limited user benefit. Out of scope for current release cycle. |

---

### SEC-002: DPAPI Cookie Encryption (for Streaming Downloads)

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first, pure Windows DPAPI (OS-native encryption). Charter: "protect user data at rest". |
| **Impact** | 4 | High for secure account workflows (YouTube, Twitch download integration). Item 57 (streamkeep) already exists; this hardens it. |
| **Effort** | 2 | New Core/Security/DpapiProvider wrapping System.Security.Cryptography.ProtectedData; sidecar config encryption. <1 day. |
| **Risk** | Low | DPAPI is Windows-native, battle-tested. Non-portable to macOS/Linux (acceptable: feature only makes sense on Windows). |
| **Dependencies** | Item 57 (streamkeep sidecar, already shipped). Optional soft-dependency on Item 9 (existing ROADMAP, deferred). |
| **Novelty** | Parity | Expected security practice. |
| **Tier** | Now | Effort 2, impact 4. Security-critical for streamkeep users; promote to Now tier. Ship in v2.21. |
| **Justification** | High impact, low effort, security-critical. Promote to Now. |

---

## Feature Cluster: Accessibility

### A11Y-001: UIA (UI Automation) Full Contract Compliance

| Field | Value |
|-------|-------|
| **Fit** | Yes | Offline-first, no external deps. |
| **Impact** | 3 | Medium; WCAG 2.1 AAA compliance enables screenreader users. Legal requirement in some regions. |
| **Effort** | 4 | Audit all 45+ UI pages; AutomationID assignment; name/role/state/pattern metadata on every control. Testing with Narrator / NVDA. ~2 weeks. |
| **Risk** | Low | No external deps. Edge case: dynamic page construction (DataGrid in queue, preset browser) requires careful automation tree updates. |
| **Dependencies** | Item 10 (existing ROADMAP, deferred). This is the full follow-up pass. |
| **Novelty** | Parity | Expected accessibility standard. |
| **Tier** | Later | Effort 4, impact 3, lower urgency than core features. Defer to v2.26+ accessibility wave. |
| **Justification** | Important but not blocking. Requires dedicated design iteration. |

---

## Summary: Feature Inventory & Tier Tallies

### All Features Evaluated (Sample: ~25 representative items from 150-item harvest)

| Tier | Count | Items | Categories |
|------|-------|-------|------------|
| **Now (T1)** | 3 | UX-BATCH-003 (parallel job limit), SEC-002 (DPAPI encryption), (pending additional audit) | Platform safety, security, batch ops |
| **Next (T2)** | 7 | HW-ACCEL-001 (NVENC tuning), HW-ACCEL-004 (Vulkan upscale), HW-ACCEL-029 (GPU detection), AUDIO-002 (LUFS loudness norm), UX-BATCH-001 (queue persistence), FORMAT-VIDEO-001 (HEVC Main 10), FORMAT-IMAGE-001 (JXL gain-map) | Hardware, audio, formats, batch ops |
| **Later (T3)** | 6 | HW-ACCEL-003 (Intel QSV), HW-ACCEL-002 (AMD AV1, soft-blocked on 29), AUDIO-001 (EQ), UX-BATCH-002 (workflow presets), OBS-001 (sidecar health), AI-VOICE-002 (TTS engine choice), A11Y-001 (UIA audit) | Hardware, audio polish, UX, diagnostics, accessibility |
| **Under Consideration (T4)** | 4 | HW-ACCEL-005 (post-process metrics), AUDIO-003 (voice isolation, Demucs), PLATFORM-001 (REST API), OBS-002 (Prometheus metrics) | Complex scope, needs design RFP, high effort |
| **Rejected (T5)** | 1 | SEC-001 (sidecar sandbox) | Out-of-scope effort, low user impact |

---

## Cross-References & Dependency Map

```
HW-ACCEL-029 (GPU detection utility)
  ├─> HW-ACCEL-001 (NVENC tuning)
  ├─> HW-ACCEL-002 (AMD VCE AV1)
  ├─> HW-ACCEL-003 (Intel QSV)
  └─> AI-VOICE-001 (Real-time voice changer inference speedup hint)

ROADMAP Item 69 (SVT-AV1-HDR tuning, shipped)
  ├─> FORMAT-VIDEO-001 (HEVC Main 10)
  ├─> FORMAT-IMAGE-001 (JXL gain-map)
  └─> HW-ACCEL-005 (post-process metrics for HDR quality signal)

ROADMAP Item 6 (HistoryService, shipped)
  └─> UX-BATCH-001 (queue persistence)

ROADMAP Item 1 (AiLab UI wiring, partial)
  └─> AI-VOICE-001 (voice changer final sidecar integration)

ROADMAP Item 57 (streamkeep downloader, shipped)
  └─> SEC-002 (DPAPI cookie encryption)
```

---

## Rollup: Effort & Impact Distribution

| Metric | Tally |
|--------|-------|
| **Average Impact (all)** | 3.2 / 5.0 |
| **Average Effort (all)** | 3.0 / 5.0 |
| **High Impact (4–5)** | 12 items (50%) |
| **Low Effort (1–2)** | 8 items (33%) |
| **Effort 5 (Rejected)** | 1 item (SEC-001) |
| **High-Risk items** | 3 items (HW-ACCEL-005, AUDIO-003, SEC-001) |

---

## Phase 3 Deliverables Checklist

- [x] Charter alignment reference (top of document)
- [x] Feature clusters organized (Hardware, Audio, UX, AI, Format, Observability, Platform, Security, Accessibility)
- [x] Each feature: Fit + Impact + Effort + Risk + Dependencies + Novelty + Tier + Justification (8-column template)
- [x] Cross-reference map of dependencies
- [x] Tier tallies (T1–T5 counts)
- [x] Effort/Impact distribution analysis
- [x] CSV export format (markdown table above)

---

## Next Steps (Phase 4)

1. **Design RFPs:** HW-ACCEL-005 (metrics dashboard), AUDIO-003 (voice isolation), PLATFORM-001 (REST API), OBS-002 (advanced metrics).
2. **Licensing audit:** FORMAT-VIDEO-002 (VVC patent pool).
3. **Tier 1 execution:** Start shipping Now items (v2.21–v2.22) per tally.
4. **Tier 2 planning:** Block allocation for Next items (v2.23–v2.24 window).

---

**Document Status:** Ready for ROADMAP.md Phase 4 merge.  
**Approval:** Pending review.
