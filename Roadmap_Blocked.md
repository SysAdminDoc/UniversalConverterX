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
the 31 currently installed frozen sidecars are x64 and therefore require
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
