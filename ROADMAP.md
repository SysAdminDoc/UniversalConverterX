# UniversalConverterX — Product Roadmap

**Status:** v2.22.0 · 190 sidecar engines · 290+ presets · 45+ UI pages
**Last updated:** 2026-07-01

Blocked items live in [`Roadmap_Blocked.md`](Roadmap_Blocked.md).
Shipped work is recorded in [`CHANGELOG.md`](CHANGELOG.md).

**Design charter:** Offline-first. No cloud. No accounts. No telemetry.
Windows 10 21H2+. Beat every competitor on: format coverage, batch UX,
programmability (CLI + REST + PS module), and AI depth.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| **Now** | Ship next (v2.21–v2.22). High certainty, well-scoped. |
| **Next** | v2.23–v2.27 window. Design complete or dependencies blocked on Now items. |
| **Later** | v2.27+. Higher effort, lower urgency, or needs community signal. |
| **UC** | Under Consideration — needs more investigation before placement. |
| **Impact** | User value 1 (niche) – 5 (universal). |
| **Effort** | Engineering cost 1 (hours) – 5 (weeks of cross-cutting work). |

---

## Tier 1 — Now _(v2.21–v2.22)_

## Tier 2 — Next _(v2.23–v2.27)_

## Tier 3 — Later _(v2.27+)_

### 42. Lossless Trim / Cut — remaining: timeline scrubber UI

Sidecar layer shipped (clipforge `trim --lossless` + preset). **Remaining:** `LosslessCutPage.xaml` with keyframe-aware timeline scrubber.

Impact: 4 · Effort: 3 · Type: parity

---

### 43. DVD Rip / Copy (Non-DRM Discs Only)

Read unprotected DVD VIDEO_TS → MP4/MKV via `libdvdread` + FFmpeg. Scope: menu-free ISOs, non-commercial home videos. DRM exclusion documented in UI.

Impact: 3 · Effort: 4 · Type: parity

---

### 48. AI Video Colorization (B&W → Color)

Per-frame colorization of grayscale footage using DeOldify. Requires PyTorch + ~1.5 GB model download (explicit user confirmation required). GPU-gated. Wire to `ColorizeVideoPage.xaml` with single-frame preview.

Impact: 3 · Effort: 4 · Type: leapfrog

---

### 49. AI Video Background Removal

Segment and replace video background using BRIA-RMBG 2.0 or MODNet. Output: VP9/WebM with transparency, PNG sequence, or chroma-key fill. GPU-gated.

Impact: 3 · Effort: 4 · Type: leapfrog

---

### 50. CEA-608/708 Closed Caption Extraction

Wrap CCExtractor for broadcast caption extraction (MPEG-TS, MXF, MPEG-2 PS). Extend `ccextract` sidecar scope to include VOBSUB/PGS OCR and SCC input format.

Impact: 2 · Effort: 3 · Type: parity

---

### 55. Video Summarizer (AI Condensed Highlight)

3-sidecar orchestration: Whisper → local LLM (llama.cpp or Phi Silica) → FFmpeg concat. Ships the "Planned" Video Summarizer tile in AiLabPage.

Impact: 3 · Effort: 4 · Type: leapfrog

---

### 66. FFmpeg 8.1 D3D12 Filter Pipeline — remaining: FFmpeg binary upgrade + filter chain

D3D12 encoder presets shipped (h264/av1_d3d12va via videocrush). **Remaining:** upgrade bundled FFmpeg binary to ≥8.1 and wire `scale_d3d12` + `deinterlace_d3d12` GPU zero-copy filter chains.

Impact: 3 · Effort: 2 · Type: platform + leapfrog

---

### 74. Proxy File Generation for Faster Preview

Auto-generate 480p/5Mbps proxy files for faster preview in VmafAnalysisPage and CompressorPage.

Impact: 2 · Effort: 3 · Type: UX + performance

---

### 90. Opus 1.5 — remaining: ambisonics channel-layout selector

Opus application/frame-duration controls shipped. **Remaining:** higher-order ambisonics channel-layout selector across multiple sidecars.

Impact: 2 · Effort: 2 · Type: codec coverage

---

### 98. PyAV v17 Hardware-Memory Zero-Copy Path

Audit sidecars touching hardware-decoded video. Migrate hot loops to PyAV v17 with cuvid + dlpack export. Avoids CPU↔GPU copies on long-form video.

Impact: 3 · Effort: 2 · Type: performance

---

## Under Consideration

| Item | Question blocking placement |
|------|-----------------------------|
| **OCR full pipeline** | Already have `pdfocr`; would a dedicated `ocrkit` add value? |
| **Spatial audio conversion** (Ambisonics ↔ binaural ↔ 5.1 ↔ 7.1) | FFmpeg partial support; assess demand. |
| **Community preset repository** | Needs governance + security review of contributed XML. |
| **EDL / XML timeline import** | Niche; assess demand. |
| **NPU acceleration** | Measure throughput gain vs. CUDA GPU before committing. |
| **Deinterlace framerate auto-doubling** | Needs UX decision about auto-enable. |
| **Per-track audio delay control** | Needs UI design. |
| **C2PA Content Credentials** | Rust compile dependency justified for the audience? |
| **IAMF immersive audio** | Identify 3+ concrete user workflows first. |
| **Commercial / ad detection (Comskip)** | UCX use case or dedicated DVR tool? |
| **ComfyUI AI Workflow Integration** | Effort 5. Needs community signal. |
| **Dia-1.6B / Dia2 TTS** | 6 GB VRAM requirement. Assess after Kokoro/F5-TTS stabilizes. |
| **Chatterbox voice cloning** | Overlaps Dia; assess after Dia evaluation. |
| **whisper.cpp native sidecar** | Footprint vs. capability regression trade-off. |
| **FFmpeg native `whisper` filter** | Lightweight fallback for subtitle pipeline. |
| **Av1an per-scene parallel encoding** (Item 71) | VapourSynth dependency is heavy. Effort 5. Assess demand. |
| **Music Source Separation (Spleeter)** (Item 75) | ~100 MB model. UC pending demand. |
| **AI Video Metadata Tagging (MediaPipe)** (Item 76) | Charter concern re: video understanding scope. |
| **Searchable Output Library (Meilisearch)** (Item 79) | Heavyweight dependency. |
| **Vector Semantic Search (Qdrant)** (Item 80) | ML inference for preset search — feasibility unclear. |
| **Pkl Preset DSL** (Item 82) | Adds Pkl compiler dependency. |
| **Prometheus Dashboard** (Item 86) | Optional for advanced batch ops. UC pending demand. |
| **VapourSynth Scripting Bridge** (Item 96) | Survey demand from mpv/encoder forums. |
| **Conditional Rules Engine (Tdarr-style)** (Item 97) | Deep design space. Start simple, promote on signal. |

---

## Research-Driven Additions

### 2026-07-16 additions (continue Item numbering from 98)
