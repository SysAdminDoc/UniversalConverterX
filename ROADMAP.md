# UniversalConverterX — Product Roadmap

**Status:** v2.32.0 · 212 sidecar engines · 300+ presets · 53 UI pages
**Last updated:** 2026-07-19

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

## Under Consideration

---

## Research-Driven Additions

_2026-07-20 research pass. IDs continue from Item 120 (max used, in archived PHASE4 notes). Evidence in [`RESEARCH.md`](RESEARCH.md)._

### P0 — Security / data-safety (root-cause)

### P1 — Reliability / trust + quick wins

- [ ] P1 — Item 124 — Runtime UI-automation smoke harness for page init
  Why: the v2.31.4 nine-page launch-NRE cluster + three window `x:Uid` XamlParseExceptions were all caught by hand; a headless drive-and-screenshot gate would catch them pre-ship. Single biggest quality gap.
  Evidence: RESEARCH.md Architecture Assessment; `src/UniversalConverterX.UI/Views/Pages/*.xaml.cs` init handlers; existing static `tests/uia_contract/check_uia.py` is not runtime.
  Touches: new `tests/` UI-automation project (WinAppDriver/UIA or offscreen host), `build.ps1` gate.
  Acceptance: CI/build launches the app offscreen, navigates all 53 pages, asserts no unhandled exception, captures a screenshot per page; a reintroduced page-init NRE fails the gate.
  Complexity: L

- [ ] P1 — Item 126 — Encode-history replay / "Apply Last Used Settings"
  Why: SQLite HistoryStore already persists versioned re-run payloads; a one-click "re-apply this job's full settings to new inputs" is a top FastFlix feature and nearly free.
  Evidence: FastFlix 6.x CHANGES; `HistoryStore` re-run payloads already exist.
  Touches: History page in `.UI`, `HistoryStore`, `ucx` CLI.
  Acceptance: from any history row, "Apply settings" pre-fills the relevant page with that job's parameters; "Apply last used" is available on convert/compress pages; covered by a ViewModel test.
  Complexity: M

- [ ] P1 — Item 128b — Surface per-track keep/drop toggles in the Converter preflight UI
  Why: the Core `-map` selection + CLI flags shipped (v2.32.x); the remaining piece is the preflight-table toggle UI wired to `AudioTrackSelection`/`SubtitleTrackSelection`.
  Evidence: `FFmpegConverter.BuildStreamMapArgs`; `ConversionOptions.AudioTrackSelection`; `ucx convert --audio-tracks/--subtitle-tracks`.
  Touches: Converter preflight table in `.UI`.
  Acceptance: preflight lists each input stream with a keep/drop toggle bound to the selection lists; default preserves all.
  Complexity: S

### P2 — Formats, codecs, preset ergonomics

- [ ] P2 — Item 130b — Offer detected HW encoders in the Compressor/Convert UI
  Why: the runtime detection shipped (`FfmpegEncoderProbe`, live-verified detecting av1_amf/av1_qsv/hevc_qsv/NVENC via `ucx encoders`); the remaining piece is populating the UI encoder dropdown from the probe and passing the chosen encoder through.
  Evidence: `FfmpegEncoderProbe.Probe`; `ucx encoders`; `HardwareAcceleration` enum.
  Touches: Compressor/Convert encoder selection in `.UI`.
  Acceptance: the encoder dropdown lists the probe's detected HW encoders; selecting one routes it through FFmpeg; NVENC-only machines are unchanged.
  Complexity: S

- [ ] P2 — Item 132 — Job-queue search + "clone job as new settings"
  Why: MKVToolNix v100 added searchable queue jobs and non-destructive clone; batch-UX polish over UCX's existing queue.
  Evidence: MKVToolNix v100 NEWS.md.
  Touches: queue/History UI in `.UI`.
  Acceptance: queue/history is filterable by filename/format/warning text; a job can be cloned into a fresh editable job without deleting the original; ViewModel test covers filter + clone.
  Complexity: M

- [ ] P2 — Item 133 — Read MP4/MOV track names from `udta` on remux
  Why: metadata fidelity — mkvmerge v100 now reads track names from MP4 user-data atoms; UCX should preserve them through remux.
  Evidence: MKVToolNix v100 NEWS.md.
  Touches: `FFmpegConverter.cs` / probe layer, remux path (Item 125).
  Acceptance: remuxing an MP4/MOV with named tracks preserves the names on output; verified against a fixture with `udta` track names.
  Complexity: S

- [ ] P2 — Item 134 — Opus 1.6 "HD" (96 kHz) + libopus floor bump
  Why: libopus 1.6 adds 96 kHz Opus HD, band-width extension, and LACE/NoLACE + DRED speech enhancement — free quality wins from a floor bump plus one exposed option.
  Evidence: Opus 1.6 release (Phoronix / opus-codec.org).
  Touches: audio sidecar(s), Opus encode option in `.UI`, dependency floor.
  Acceptance: Opus HD (48/96 kHz) selectable; encoded output reports the expected sample rate; DRED path documented; floor bumped to 1.6.x.
  Complexity: S

- [ ] P2 — Item 136 — KEPUB output + KFX input + KCC comic pipeline for ebook/comic conversion
  Why: Calibre 9.11 supports KEPUB in/out and KFX input; KCC produces device-optimized comics — extends the ebook/archive story. Format conversion only; no DeDRM.
  Evidence: Calibre 9.11 conversion docs; Kindle Comic Converter (github.com/ciromattia/kcc).
  Touches: `tools/ebookconvert/`, a new comic sidecar, presets.
  Acceptance: EPUB↔KEPUB and KFX→EPUB convert successfully; CBZ/CBR→device-profiled EPUB/MOBI works; DRM-protected inputs are rejected with a clear message (no DeDRM shipped).
  Complexity: M

### P2/P3 — Local AI engines (SHA-256-pinned, consent-gated, kill-switchable)

- [ ] P2 — Item 137 — RIFE 4.25+ frame-interpolation sidecar
  Why: 30→60/120 fps interpolation is a common creator request; RIFE runs locally (ncnn/Vulkan or CUDA); Video2X/SVFI validate the design.
  Evidence: Video2X 6.x; SVFI model-spec.
  Touches: new `tools/` interpolation sidecar, AI Lab page, model download (SHA-256 pinned).
  Acceptance: a clip interpolates to a target fps with pinned-model download + consent gate + `UCX_*=0` kill-switch honored; falls back cleanly when no GPU.
  Complexity: L

- [ ] P2 — Item 138 — Kokoro-82M TTS engine option
  Why: Apache-2.0, 82M params, CPU-realtime, 54 voices — best license/quality/hardware balance for the existing TTS sidecar.
  Evidence: Kokoro TTS local-setup writeups.
  Touches: `tools/voice-changer`/TTS sidecar, model pack (SHA-256 pinned).
  Acceptance: Kokoro selectable as a TTS engine, produces audio on CPU without GPU, pinned model + consent gate; existing engine unaffected.
  Complexity: M

- [ ] P2 — Item 139 — BiRefNet background-removal backend for alphacut
  Why: BiRefNet keeps hair/fur edges that rembg/ISNet lose; exposed by rembg v2 as `birefnet-general`. Edge-fidelity upgrade on an existing sidecar.
  Evidence: BiRefNet writeups; rembg v2.
  Touches: `tools/alphacut/`, model pack (~930MB, pinned).
  Acceptance: alphacut offers a BiRefNet backend selectable in UI; pinned-model + consent gate; default rembg path unchanged.
  Complexity: M

- [ ] P2 — Item 140 — Surya OCR + Marker PDF→Markdown pipeline
  Why: Surya (90+ langs, strong olmOCR-bench) + Marker give deterministic layout/table/equation extraction to Markdown — upgrades subocr and adds a doc→Markdown converter.
  Evidence: Surya/Marker (datalab); OSS-OCR roundups.
  Touches: `tools/subocr` (or new doc sidecar), a new document converter surface.
  Acceptance: a scanned PDF converts to structured Markdown (headings/tables preserved) fully offline; pinned models; batch-capable.
  Complexity: L

- [ ] P3 — Item 141 — Speaker diarization in whisper-stt transcription
  Why: Shutter 20.2 added speaker-ID; pairs local pyannote/NeMo diarization with the existing whisper-stt sidecar.
  Evidence: Shutter Encoder 20.2 changelog.
  Touches: `tools/whisper-stt`, subtitle output format, model pack.
  Acceptance: transcripts optionally include speaker labels; runs offline with pinned models; toggle off by default.
  Complexity: L

- [ ] P3 — Item 142 — GPU-gated restore tier: SeedVR2 / DiffBIR (denoise + upscale)
  Why: modern one-step diffusion restoration for old/noisy footage and stills, runnable on the dev's RTX; local equivalent of Topaz Starlight (which is cloud/paywalled).
  Evidence: SeedVR2 / DiffBIR / SUPIR repos; AI-restoration roundups.
  Touches: new/existing enhance sidecar, AI Lab, pinned models, GPU capability probe.
  Acceptance: a restore pass runs on a CUDA GPU with pinned model + consent gate, degrades gracefully (clear message) without a supported GPU; no cloud calls.
  Complexity: XL

- [ ] P3 — Item 143 — DDColor / ColorMNet colorization quality tier
  Why: better temporal stability than the current Zhang CPU model in the colorize sidecar (vs-deoldify bundles these).
  Evidence: vs-deoldify (github.com/dan64/vs-deoldify).
  Touches: `tools/colorize`, model packs (pinned).
  Acceptance: DDColor/ColorMNet selectable as a quality tier; pinned model + consent gate; existing CPU path retained as default/fallback.
  Complexity: L

### P3 — Capability + debt

- [ ] P3 — Item 144 — Live/dynamic DASH download support
  Why: `dash.py` logs dynamic MPD (`type=dynamic`) as unsupported — live streams silently fail.
  Evidence: `tools/streamkeep/streamkeep/dash.py:55`.
  Touches: `tools/streamkeep/streamkeep/dash.py`, downloader tests.
  Acceptance: a live/dynamic MPD downloads a bounded segment window (or clearly reports the recording semantics) instead of the current unsupported-log.
  Complexity: M

- [ ] P3 — Item 145 — VVC/H.266 decode support (reconsider decode-only stance)
  Why: Intel Lunar Lake HW-decodes VVC to 8K60 and DVB mandates it; FastFlix ships vvenc — decode is now worth wiring even though encode stays deprioritized.
  Evidence: FastFlix 6.0; dacast H.266 overview; RESEARCH.md Rejected Ideas split.
  Touches: FFmpeg decode probe, format detection tables.
  Acceptance: a VVC-encoded input is detected and transcoded to a common target using the available decoder; encode remains out (documented).
  Complexity: M

- [ ] P3 — Item 146 — Complete shared sidecar `find_ffmpeg`/`emit` consolidation
  Why: `tools/_lib/ucx_sidecar.py` centralized the protocol/runtime/timeout but per-sidecar boilerplate remains across 212 engines; finishing it reduces drift and CVE-patch surface.
  Evidence: RESEARCH.md Architecture; `tools/_lib/ucx_sidecar.py`.
  Touches: `tools/_lib/`, per-sidecar `sidecar.py` files.
  Acceptance: sidecars import shared discovery/emit helpers rather than re-declaring them; contract gate still passes for all 212.
  Complexity: L

