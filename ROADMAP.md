# UniversalConverterX — Product Roadmap

**Status:** v2.28.0 · 207 sidecar engines · 295+ presets · 45+ UI pages
**Last updated:** 2026-07-17

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

## Under Consideration

| Item | Question blocking placement |
|------|-----------------------------|
| **ComfyUI AI Workflow Integration** | Effort 5. Needs community signal. |
| **Dia-1.6B / Dia2 TTS** | 6 GB VRAM requirement. Assess after Kokoro/F5-TTS stabilizes. |
| **Chatterbox voice cloning** | Overlaps Dia; assess after Dia evaluation. |
| **AI Video Metadata Tagging (MediaPipe)** (Item 76) | Charter concern re: video understanding scope. |
| **Searchable Output Library (Meilisearch)** (Item 79) | Heavyweight dependency. |
| **Vector Semantic Search (Qdrant)** (Item 80) | ML inference for preset search — feasibility unclear. |
