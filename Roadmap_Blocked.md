# UniversalConverterX — Blocked Roadmap Items

Items that cannot proceed without external input, credentials, hardware, or upstream dependencies.

---

### 66. FFmpeg 8.1 D3D12 Hardware Validation

The opt-in VideoCrush path now probes one real frame through D3D12 decode,
optional `deinterlace_d3d12`, `scale_d3d12`, and D3D12 encode before running a
job. Probe failure falls back automatically to software BWDIF/scaling and the
original software encoder. Argument-planning tests and a headless smoke prove
the fallback on the available machine.

Impact: 3 · Effort: 2 · Type: platform + leapfrog

**Blocker:** Successful zero-copy execution still requires a GPU/driver whose
Direct3D 12 video engine supports the requested decoder, video-processor
filters, and encoder together. The available RTX 4070 SUPER exposes the FFmpeg
components but rejects the runtime processor/encode path, so only the guarded
fallback can be verified here. Run the same smoke on a supporting device to
capture positive-path evidence; no product code or fallback work remains.

---

### 47. Qualcomm QNN On-Device Validation

The repository now cross-publishes ARM64-native apphosts for the CLI, WinUI
app, Explorer shell extension COM host, and FFmpeg proxy. A PE-header gate
verified all four as ARM64 and emitted an explicit sidecar architecture report;
the 32 currently installed frozen sidecars are x64 and therefore require
Windows x64 emulation or an ARM64 rebuild. `ucx tools qnn --json` probes a local
ARM64 Python/ONNX Runtime environment and fails closed unless it exposes
`QNNExecutionProvider`.

The generic Intel NPU candidate was qualified on 2026-07-17 and does not
justify a separate acceleration backend. On an Intel Core Ultra 9 285 with
Intel AI Boost, OpenVINO 2026.2 reported the NPU ready, but Windows App SDK
2.2 `VideoScaler` reported `NotSupportedOnCurrentSystem`. Five warmed trials
of the same eight-layer 192x192 convolution workload produced median
throughput of 815 frames/s on the NPU (four asynchronous requests) versus
1,510 frames/s through ONNX Runtime 1.22 CUDA on an RTX 4070 SUPER (one
request). CUDA was 1.85x faster, so UCX keeps its existing CUDA and portable
fallback paths instead of adding an Intel-only runtime for lower throughput.

Impact: 2 · Effort: 4 · Type: platform

**Blocker:** A Snapdragon X Elite / X Plus device is required to run the final
QNN inference smoke, launch the native WinUI build, and exercise representative
x64-emulated and ARM64 Python sidecars. The available x64 host proved the
cross-publish, PE architecture gate, and negative provider path but cannot
produce genuine Snapdragon runtime evidence. No remaining source/build work is
hidden behind this entry.
---

### 214. Running-app visual/theme pass and page-body audit

The requested running-app light/dark captures and route-by-route visual
verification are blocked in this environment. `AGENTS.md` requires operator
display isolation, and no isolated virtual-display runner is available, so a
headless source audit cannot satisfy the capture and `--ui-smoke` acceptance
criteria. Revisit on an isolated virtual-display or CI runner.

---

### 134. Opus 1.6 HD interoperability validation

UCX now fails closed for explicit Opus sample rates outside the bundled
FFmpeg/libopus encoder's supported set and hides the incompatible 44.1 kHz and
96 kHz choices when Opus is selected. No user-facing Opus HD option remains.

**Blocker:** The pinned FFmpeg 8.1.2/libopus build rejects 96 kHz and exposes
only the RFC 6716 sample-rate set. Opus 1.6's experimental HD layer requires a
qext-enabled build, and the acceptance test additionally requires remux and
decode verification through two independent players. No qext-enabled FFmpeg
integration or independent player pair is present in this offline-first
repository/environment. Revisit when an upstream-integrated, pinned build and
headless player fixtures are available; no remaining UCX guard work is hidden
behind this entry.

## Roadmap cleanup — 2026-08-10 — tools/videocrush/ROADMAP.md

**Blocked on:** The source roadmap marked this work as parked, optional, or dependent on external input.

Blocked items moved from the actionable roadmap:

- AI upscaling via Real-ESRGAN / Video2X as pre-pass

- Auto-subtitle via Whisper during encode

- Scene-detect cut + trim suggestions (ffmpeg select filter with preview)

- Built-in GIF creator with palette optimization

- Cloud-target upload (S3 / R2 / Backblaze / SFTP) after encode

- Battery-aware encoding (pause on battery, resume on AC)

## Roadmap cleanup — 2026-08-10 — tools/vertigo/ROADMAP.md

**Blocked on:** The source roadmap marked this work as parked, optional, or dependent on external input.

Blocked items moved from the actionable roadmap:

- [~] **T4b · Pyannote speaker diarization** · v0.11.0 · WhisperX (BSD-2) + pyannote (MIT)
  `core.diarize` module landed with `diarize()` + `align_to_faces()`;
  UI wiring deferred because it requires a HuggingFace token +
  terms-acceptance flow. Users who opt in can drive the module
  directly.


- [~] **B-roll auto-insertion** · `core.broll` planner module
  (KeyBERT + Pexels + CLIP); UI deferred because Pexels requires a
  free API key / signup. Planner is importable for users who want
  to drive it programmatically.

---

## Roadmap cleanup — 2026-08-10 — tools/clipforge/ROADMAP.md

**Blocked on:** The source roadmap marked this work as parked, optional, or dependent on external input.

Blocked items moved from the actionable roadmap:

- Optional GPU upscaler swap (waifu2x-ncnn-vulkan, anime4k) alongside Real-ESRGAN

- Built-in "Discord-safe" auto-bitrate solver that hits an exact target file size in one pass via VBR bitrate math

- Drag-and-drop `.srt` onto the player to preview burned subs before export

- Color grade panel with 1D/3D LUT stacking and side-by-side before/after split

- Project watermark presets (logo PNG with position, opacity, fade-in/out)

- Mini web UI mode for headless render boxes (Flask + the same FFmpeg core)

## Roadmap cleanup — 2026-08-10 — tools/gifstudio/ROADMAP.md

**Blocked on:** The source roadmap marked this work as parked, optional, or dependent on external input.

Blocked items moved from the actionable roadmap:

- **Motion-tracked sticker** — OpenCV.js-based point tracking so a sticker follows a subject
  across frames.

- **AI caption suggestion** using an in-browser speech-to-text on source audio.

- **Automatic thumbnail choice** — detect best frame (least blur / best composition) to use as
  preview thumbnail.

- **Batch mode** — apply the same edits to multiple source videos.

- **Embeddable share page** — after export, generate a standalone HTML page with the GIF + loop
  control the user can host themselves.

- **Plugin hooks** — JS plugin API for community filters/effects.

## Roadmap cleanup — 2026-08-10 — tools/framesnap/ROADMAP.md

**Blocked on:** The source roadmap marked this work as parked, optional, or dependent on external input.

Blocked items moved from the actionable roadmap:

- **Frame similarity search** — perceptual hash across all frames, find near-duplicate frames;
  useful for dedup before contact-sheet export.

- **OCR on extracted frames** (Tesseract) — export a `frames.txt` of detected text per mark.

- **QR/barcode detection** on the current frame for debugging-shot workflows.

- **Custom scrubber shortcuts** — configurable mouse-wheel step size per video (persisted per
  file).

- **Cloud sync of sessions** — optional `.fsnap` + video-hash in Dropbox/GDrive so marks travel
  with the user.

- **Side-by-side A/B viewer** for comparing two files at the same frame position.

## Roadmap cleanup — 2026-08-10 — tools/lipsight/ROADMAP.md

**Blocked on:** The source roadmap marked this work as parked, optional, or dependent on external input.

Blocked items moved from the actionable roadmap:

- Real-time webcam mode: live captions from the user's face

- Language support beyond English (LRS-Mandarin, LRS-French datasets exist)

- Deaf-accessibility mode: large, high-contrast captions rendered on top of the video preview

- On-device mobile (Android/iOS) port with TFLite-quantized model

- Federated correction contribution (opt-in): user-corrected transcriptions flow back to a public fine-tuning dataset

- Watermark detection: auto-flag if video has TikTok/YouTube/IG watermark that obscures the mouth

## Roadmap cleanup — 2026-08-10 — tools/heicshift/ROADMAP.md

**Blocked on:** The source roadmap marked this work as parked, optional, or dependent on external input.

Blocked items moved from the actionable roadmap:

- Web-worker-style parallel decode via subprocess pool to sidestep Python GIL

- Face-aware quality: detect faces, hold higher quality in face regions (JPEG ROI, AVIF film-grain off)

- Perceptual quality target: `--target-ssim 0.98` binary-searches quality instead of a fixed KB goal

- Drag-to-dock mini-window mode for quick single-file conversions

- Plugin system: drop `.py` into `~/.heicshift/plugins/` to register a new decoder or post-processor

- Self-updater checking GitHub releases (opt-in)
