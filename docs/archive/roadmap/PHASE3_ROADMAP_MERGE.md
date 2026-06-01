# Phase 3 Gap Analysis — ROADMAP.md Integration Instructions

> **Archive note (2026-06-01):** This merge-plan artifact is retained for
> historical context. The active roadmap lives in
> [`../../../ROADMAP.md`](../../../ROADMAP.md), and current research synthesis
> lives in [`../../../RESEARCH_REPORT.md`](../../../RESEARCH_REPORT.md).

**Date:** 2026-05-XX  
**Document:** Ready for merge into ROADMAP.md  
**Format:** Markdown; compatible with existing ROADMAP structure

---

## Executive Summary

Phase 3 gap analysis evaluated 150 harvested candidate features across 9 categories (Hardware Acceleration, Audio, Batch, AI/ML, Formats, Observability, Platform, Security, Accessibility). Results:

- **Tier 1 (Now):** 2–3 items → ship v2.21–v2.22 (2 weeks)
- **Tier 2 (Next):** 7–8 items → ship v2.23–v2.24 (6–8 weeks)
- **Tier 3 (Later):** 6 items → ship v2.25–v2.27 (12+ weeks)
- **Tier 4 (UC):** 4–5 items → defer Phase 4 design RFPs
- **Tier 5 (Rejected):** 1 item → explicit out-of-scope

**Key findings:**
- 100% charter-aligned (offline-first, no telemetry, no cloud)
- Effort distribution realistic (60–70 engineering days over 6 versions)
- Healthy parity/leapfrog mix (70% catch-up, 30% differentiation)
- Zero circular dependencies; all hard dependencies satisfied by shipped items
- 5 design RFPs recommended for Phase 4 (parallel track)

---

## Tier 1 Items: Now (v2.21–v2.22)

### Item 99: Parallel Job Limit Enforcement + CPU/RAM Throttle

**Category:** Batch Operations | **Type:** parity | **Status:** Spec ready

| Metric | Value |
|--------|-------|
| **Impact** | 3 — Prevents system lock-up on 24-core systems; user safety. |
| **Effort** | 2 — New `MaxParallelJobs` setting + semaphore gating in orchestrator. <1 day. |
| **Risk** | Low — No external deps; testing straightforward. |
| **Dependency** | None; extends Item 8 (Parallel Job Limit Setting, already shipped). |
| **Source** | [Handbrake job-slot limit, table-stakes feature] |

**Implementation sketch:**
1. Extend `ConverterXOptions` with `int MaxParallelJobs` (default: CPU count / 2).
2. Optional `MaxCpuPercent` + `MaxRamMB` thresholds (future; MVP is job count only).
3. Job orchestrator uses semaphore: `SemaphoreSlim(maxParallelJobs)` on each job spawn.
4. Settings UI (SettingsPage.xaml) adds number picker: "Max parallel jobs: [_____]"
5. Real-time enforcement: UI shows "2 of 4 jobs running" in queue.

**Rationale for Now:** User safety (prevents system freeze); low effort; independent; polishes batch experience.

---

### Item 100: DPAPI Cookie Encryption for Streaming Downloads

**Category:** Security | **Type:** parity | **Status:** Spec ready

| Metric | Value |
|--------|-------|
| **Impact** | 4 — Security-critical for YouTube/Twitch download workflows (Item 57 streamkeep sidecar). |
| **Effort** | 2 — Wrap System.Security.Cryptography.ProtectedData; sidecar config encryption. <1 day. |
| **Risk** | Low — Windows DPAPI is OS-native, battle-tested; non-portable to macOS/Linux (acceptable). |
| **Dependency** | Item 57 (streamkeep downloader, already shipped v2.20.1). |
| **Source** | [ROADMAP Item 9, deferred; DPAPI security best practice] |

**Implementation sketch:**
1. New `Core/Security/DpapiProvider.cs`: `Encrypt(plaintext) -> ciphertext` + `Decrypt(ciphertext) -> plaintext`.
2. Sidecar config encryption: When streamkeep stores cookies (YAML/JSON), call `DpapiProvider.Encrypt()` on sensitive fields.
3. On sidecar startup, load encrypted config + decrypt via DPAPI (user-context bound, so each Windows user has unique encryption key).
4. Tested on Windows 10 21H2+; macOS/Linux gracefully skip (no-op pass-through; users accept plaintext risk or don't enable streamkeep).

**Rationale for Now:** Security-critical; low effort; unblocks Item 57 hardening; promotes from Next tier.

---

## Tier 2 Items: Next (v2.23–v2.24)

### Item 101: GPU Detection & Capability Probe Utility

**Category:** Hardware Acceleration | **Type:** parity | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 3 — Infrastructure for intelligent encoder selection; unblocks Items 102–104. |
| **Effort** | 3 — GPU vendor detection + feature caps probe. ~1 week. |
| **Risk** | Low — Graceful degradation; no external dependencies beyond vendor CLIs. |
| **Dependency** | None; foundational. Blocks Items 102–104 for consistent encoder-selection UI. |
| **Source** | [FFmpeg 8.1 D3D12/Vulkan, GPU detection best practice] |

**Implementation sketch:**
1. New `Core/Hardware/GpuCapabilityProbe.cs`: detect NVIDIA/AMD/Intel via shellout to vendor tools (nvidia-smi, clinfo, gpu_detect_bins).
2. Cache results in `%LocalAppData%/UniversalConverterX/gpu-cache.json` (5-minute TTL, avoid repeated probing).
3. Surface in UI: Converter page → "Estimated encoding time (with GPU)" vs. "without GPU" hints.
4. Use in sidecar selection: videocrush receives `--gpu-vendor nvidia` flag; wrapper selects NVENC-optimal presets.

**Sequencing:** Ship in v2.23 **first**, before Items 102–104.

---

### Item 102: NVIDIA NVENC H.265 Preset Tuning

**Category:** Hardware Acceleration | **Type:** parity | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 4 — High user value for RTX/GTX users; fast 4K→1080p transcoding. |
| **Effort** | 2 — Extend videocrush sidecar with NVENC preset discovery + flag mapping. <2 days. |
| **Risk** | Low — NVIDIA driver handling already in place; preset names stable across recent driver versions. |
| **Dependency** | Item 101 (GPU detection, soft; can run in parallel if 101 delayed). |
| **Source** | [HandBrake 1.11+ NVENC tuning; NVIDIA encoder presets] |

**Implementation sketch:**
1. `tools/videocrush/nvenc-presets.json`: map user-facing presets (default/fast/medium/slow/lossless) → NVIDIA SDK preset enums.
2. Videocrush CLI gains `--nvenc-preset {default|fast|medium|slow|lossless}`.
3. New ConverterPage presets: "to-h265-nvenc-fast", "to-h265-nvenc-slow", etc.
4. UI: Converter page → H.265 codec dropdown gains NVENC option with preset picker.

**Sequencing:** Ship in v2.23, after Item 101 (can run parallel if Item 101 delayed).

---

### Item 103: AMD VCE/AMF AV1 Support

**Category:** Hardware Acceleration | **Type:** parity | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 3 — Broadens GPU coverage to AMD Radeon users (RDNA 3+ native AV1). |
| **Effort** | 3 — VCEEnc integration + flag mapping + probe for AMF 1.5.0 AV1. ~3–5 days. |
| **Risk** | Low — VCEEnc maintained by BtbN; AMF AV1 verified in v9.05+. |
| **Dependency** | Item 101 (GPU detection, soft). |
| **Source** | [VCEEnc 9.05, AMF 1.5.0; AMD GPU market growth] |

**Implementation sketch:**
1. Similar to Item 102: `tools/videocrush/vceenc-presets.json`.
2. Videocrush detects AMD GPU (via Item 101) and routes to VCEEnc.
3. New presets: "to-av1-vceenc-fast", "to-av1-vceenc-slow", etc.

**Sequencing:** v2.23, in parallel with Item 102.

---

### Item 104: Vulkan Compute Upscaling (Real-ESRGAN ncnn-vulkan)

**Category:** Hardware Acceleration | **Type:** leapfrog | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 4 — High user value; foundation proven in Item 95 (anime-upscale sidecar). |
| **Effort** | 2 — Extend anime-upscale sidecar with general-image upscaling preset. <2 days. |
| **Risk** | Low — Reuses Item 95 infrastructure (Real-ESRGAN ncnn-vulkan already shipped). |
| **Dependency** | Item 95 (anime-upscale, shipped v2.20.1). |
| **Source** | [Real-ESRGAN ncnn-vulkan, cross-platform Vulkan support] |

**Implementation sketch:**
1. Extend Item 95 anime-upscale sidecar: new operation "upscale-general" (not anime-specific).
2. New ImageEnhancerPage preset or separate UpscalerPage: "2x upscale" (Real-ESRGAN default), "4x upscale".
3. UI: File picker + scale factor slider + model selector (RealESRGAN_x2plus, RealESRGAN_x4plus).

**Sequencing:** v2.23, independent timeline (can run in parallel with Items 101–103).

---

### Item 105: LUFS/LKFS Loudness Normalization (ITU-R BS.1770-4)

**Category:** Audio Processing | **Type:** parity | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 4 — Broadcast-critical (Netflix/YouTube -14 LUFS standard); creator audience. |
| **Effort** | 2 — FFmpeg `loudnorm` filter wrapper + preset library. <1 day. |
| **Risk** | Low — FFmpeg `loudnorm` battle-tested; graceful fallback to `volume` on older FFmpeg. |
| **Dependency** | None. |
| **Source** | [FFmpeg loudnorm filter; YouTube/Netflix loudness standards] |

**Implementation sketch:**
1. New `tools/audio-loudness/sidecar.py`: wrapper for FFmpeg `loudnorm` filter.
2. CLI: `audio-loudness --input in.wav --target-loudness -14 --output out.wav`.
3. Preset library: "podcast" (-16 LUFS), "streaming" (-14), "cinematic" (-24).
4. UI: New AudioLoudnessPage in Toolbox; file picker + target LUFS slider + preset combo + encode settings.

**Sequencing:** v2.23, independent (can run in parallel).

---

### Item 106: Job Queue Persistence (Crash Recovery)

**Category:** Batch Operations | **Type:** parity | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 4 — Reliability blocker; users running 12-hour batch jobs lose progress on crash. |
| **Effort** | 3 — New `JobQueue` table + restore logic + prompt UI. ~1 week. |
| **Risk** | Low — SQLite transactions; graceful incomplete-job resume. |
| **Dependency** | Item 6 (HistoryService, shipped v2.19.0+). |
| **Source** | [HandBrake queue persistence; batch reliability best practice] |

**Implementation sketch:**
1. Extend `HistoryService.db` schema: new `PendingJobs` table (id, guid, preset, input, output, status, checkpoint).
2. On app launch, check for pending jobs; if found, show dialog: "Resume 3 interrupted jobs?" → [Resume] [Clear].
3. On job completion, mark as `done`; on crash/app exit, jobs remain `pending`.
4. Sidecar output streams stored to disk (log file per job); on resume, attach to sidecar stdout for real-time progress display.

**Sequencing:** v2.24 (depends on v2.23 queue polish; moderate effort).

---

### Item 107: HEVC Main 10 Profile HDR Support

**Category:** Video Format Support | **Type:** parity | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 3 — HDR content increasingly common (UHD Blu-ray, streaming); professional workflows. |
| **Effort** | 2 — Extend videocrush sidecar with Main 10 flag + HDR metadata passthrough. <2 days. |
| **Risk** | Low — FFmpeg Main 10 mature; HDR pipeline (Item 69) already stable. |
| **Dependency** | Item 69 (SVT-AV1-HDR tuning, shipped v2.20.1); soft. |
| **Source** | [HandBrake 1.11+ Main 10; HDR codec support] |

**Implementation sketch:**
1. Videocrush CLI gains `--hevc-profile main10` (in addition to existing `main`).
2. New preset: "to-h265-hdr" (Main 10 + HDR metadata passthrough via FFmpeg `-c:v hevc_nvenc -profile:v main10`).
3. UI: Converter page H.265 codec → checkbox "Enable HDR (Main 10 profile)".

**Sequencing:** v2.23, soft-dependency on Item 69 (already shipped; can proceed immediately).

---

### Item 108: JPEG XL Gain-Map HDR Writing

**Category:** Image Format Support | **Type:** leapfrog | **Status:** Design ready

| Metric | Value |
|--------|-------|
| **Impact** | 3 — Professional photographer audience; HDR image interchange growing. |
| **Effort** | 3 — Extend imagecrush sidecar with pillow-jxl-plugin gain-map writing. ~1 week. |
| **Risk** | Low — pillow-jxl-plugin 1.3.4+ stable; libjxl security issues fixed. |
| **Dependency** | Item 88 (pillow-jxl-plugin pin, shipped v2.20.1); soft. |
| **Source** | [libavif 1.4.x gain-map, JPEG XL HDR interchange] |

**Implementation sketch:**
1. Extend `tools/image-convert/sidecar.py`: new operation "convert-jxl-hdr" (gain-map writing).
2. CLI: `image-convert --input hdr.exr --operation convert-jxl-hdr --output out.jxl`.
3. New ImageConverterPage preset: "to-jxl-hdr" (lossless + gain-map).
4. UI: Gain-map intensity slider (0–1, default 1.0).

**Sequencing:** v2.24 (HDR consolidation wave; pairs with Item 107).

---

## Tier 3 Items: Later (v2.25–v2.27)

### Items 109–114: Later-Tier Features (Tier 3)

Listed in order of recommended shipping:

| Item | Feature | Category | Impact | Effort | Version |
|------|---------|----------|--------|--------|---------|
| 109 | Intel QuickSync VP9/AV1 | Hardware | 3 | 3 | v2.25 |
| 110 | Parametric EQ 31-Band | Audio | 3 | 3 | v2.26 |
| 111 | Sidecar Health Dashboard | Observability | 2 | 2 | v2.26 |
| 112 | TTS Engine Selection (Dia/FastPitch) | AI/ML | 2 | 3 | v2.27 |
| 113 | Batch Workflow Templates | Batch Ops | 3 | 3 | v2.27 |
| 114 | UIA Full Accessibility Audit | Accessibility | 3 | 4 | v2.26–v2.27 |

**Implementation notes:**
- Items 109–110: GPU consolidation + audio polish wave (v2.25–v2.26).
- Items 111–113: Diagnostics + automation + voice polish (v2.26–v2.27).
- Item 114: Standalone accessibility iteration (overlaps with Items 111–113); requires dedicated design pass.

---

## Tier 4 Items: Under Consideration (Design RFPs Phase 4)

### Five Design RFP Topics (Parallel Track, Phase 4)

| RFP Title | Related Items | Decision Gate | Timeline |
|-----------|---------------|---------------|----------|
| **Metrics & Quality Signal** | HW-ACCEL-005 (post-process metrics), Item 67/68 (ab-av1 CRF search) | Design: A/B workflow UX + metrics dashboard layout | End of June 2026 |
| **Voice Isolation & AI Audio** | AUDIO-003 (Demucs stem separation) | Design: Model caching strategy, progress UX, hardware disclosure | End of June 2026 |
| **REST API & Programmability** | PLATFORM-001 (REST API) | Design: OpenAPI spec, auth story, job submission contract | End of June 2026 |
| **Advanced / Opt-In Features** | OBS-002 (Prometheus metrics), SEC-001 (sandbox) | Design: Security messaging, firewall implications, audit trail | End of June 2026 |
| **VVC Patent & Licensing** | FORMAT-VIDEO-002 (H.266 vvenc) | Legal audit: MPEG-I VVC patent pool, adoption risk | End of May 2026 |

**Process:**
1. Each RFP gets 1–2 week design phase (PM + architect + optional legal).
2. Output: Spec doc + recommendation (Go/No-Go/Defer).
3. If Go → promote to Tier 2 or 3; if No-Go → move to Rejected.
4. Phase 5 (July–August 2026) executes Go items; Phase 6+ executes Defer items.

---

## Tier 5: Rejected Items

### Item 115: Sidecar Process Sandbox / AppContainer Isolation

**Category:** Security | **Type:** defensive | **Status:** Deferred indefinitely

| Metric | Value |
|--------|-------|
| **Impact** | 2 — Narrow audience (enterprises, security-conscious users). |
| **Effort** | 5 — AppContainer + Job Object + seccomp + macOS sandbox setup; >4 weeks. |
| **Risk** | High — Complex OS-specific code; regression risk; edge cases (temp cleanup, IPC). |
| **Reasoning** | Effort:Impact ratio unfavorable (5:2). Defensive feature (not growth-driving). Out of scope for v2.21–v2.27 window. Candidate for v3.0+ "hardened edition" if market demand justifies. |

**Explicit rejection rationale:** Charter goal is "beat competitors on format coverage, batch UX, programmability, AI depth." Process sandboxing is not a differentiator in this space. Ship competitive core features first; defensive hardening is v3.0+ scope.

---

## ROADMAP.md Merge Instructions

### File Structure

```
ROADMAP.md
├─ Existing: Legend + Tier 1 (Items 1–7) + Tier 2 (Items 20–52) + Tier 3 (Items 53–86) + UC (Items 87–97)
│
└─ New Phase 3 items (v2.21–v2.27 window): Items 99–114 + RFP topics + Rejected
```

### Merge Strategy

1. **Location:** Insert new sections after existing Item 98 (post-iter-7 additions).
2. **Format:** Match existing ROADMAP template (Impact/Effort/Type/Sources/Closing commit notes).
3. **Tier assignment:**
   - Items 99–100 → Insert after existing Tier 1, update Tier 1 section header: "Tier 1 — Now (v2.21–v2.22) — 11–13 items"
   - Items 101–108 → Insert after existing Tier 2, update header: "Tier 2 — Next (v2.23–v2.24) — 25–35 items"
   - Items 109–114 → Insert after existing Tier 3, update header: "Tier 3 — Later (v2.25–v2.27) — 36–50 items"
   - Items 115+ → Tier 5 Rejected section (new or appended)

4. **Cross-references:** Update existing ROADMAP items if soft-dependencies are discovered (e.g., Item 7 → add cross-ref to Item 100 DPAPI).

5. **Sources:** Append new source citations (S166–S180 estimated for Phase 3 harvest docs; these three docs count as sources).

### Markdown Template (Copy-Paste for Each Item)

```markdown
### N. [Feature Title] — Status

Brief one-liner.

| Property | Value |
|----------|-------|
| **Impact** | N — rationale |
| **Effort** | N — sketch |
| **Risk** | Low/Medium/High — notes |
| **Dependencies** | [list or "None"] |
| **Type** | parity/leapfrog |
| **Closing commit:** [commit hash or TBD] — [change summary] |

---
```

### Version Numbering

- **Items 1–98:** Existing (shipped or planned v2.20.x–v2.22.x)
- **Items 99–114:** Phase 3 (planned v2.21–v2.27)
- **Items 115+:** Rejected or Deferred

Total items after Phase 3 merge: **114 (v2.20.1 baseline) + optional RFP Go items** → estimated **120–140 total by end of Phase 5**.

---

## Summary Table for ROADMAP.md Header

Add to ROADMAP.md line 3–4 (status update):

```markdown
**Status:** v2.20.1 · 176 sidecar engines · 274+ presets · 45 UI pages
**Phase 3 harvest:** 150 candidate features evaluated; 25 items promoted to Now/Next/Later; 5 design RFPs Phase 4
**Total ROADMAP items:** 114 (Items 1–114: shipped or planned v2.20.1–v2.27)
```

---

## Appendix: Full Feature Tally by Tier (Post-Merge)

| Tier | Existing | Phase 3 New | Total | Versions |
|------|----------|-----------|-------|----------|
| **Now (T1)** | 7 | 2 | 9–11 | v2.21–v2.22 |
| **Next (T2)** | 33 | 8 | 41–43 | v2.23–v2.24 |
| **Later (T3)** | 33 | 6 | 39–41 | v2.25–v2.27 |
| **UC (T4)** | 12 | 5 | 17 | Phase 4 RFP gate |
| **Rejected (T5)** | 13 | 1 | 14 | N/A |
| **TOTAL** | 98 | 22 | 120 | v2.20.1–v2.27+ |

**RFP Go items (Phase 5):** Estimated 3–5 items (post-RFP design completion) → **123–128 total by v2.28**.

---

## Stakeholder Approval Checklist

- [ ] Engineering lead: Effort estimates realistic? Dependency sequencing sound?
- [ ] PM: Tier allocation aligns with market priorities? Parity/leapfrog mix acceptable?
- [ ] Security: Phase 4 RFP topics include security review? DPAPI implementation approved?
- [ ] Accessibility: Item 114 (UIA audit) properly scoped for dedicated iteration?
- [ ] Legal: FORMAT-VIDEO-002 (VVC) licensing audit needed before RFP gate?
- [ ] QA: Testing capacity for 8-week Next-tier wave (v2.23–v2.24)?

---

**Phase 3 Gap Analysis:** COMPLETE  
**Next milestone:** Phase 4 design RFPs (parallel track, complete by end of June 2026)  
**Phase 5 ready:** Yes, pending Phase 4 RFP gate clearance

---

*Document prepared for ROADMAP.md integration. Ready to commit as supplementary docs ([PHASE3_GAP_ANALYSIS.md](../research/PHASE3_GAP_ANALYSIS.md), [PHASE3_FEATURES_MATRIX.csv](../research/PHASE3_FEATURES_MATRIX.csv), [PHASE3_EXTENDED_ANALYSIS.md](../research/PHASE3_EXTENDED_ANALYSIS.md)).*
