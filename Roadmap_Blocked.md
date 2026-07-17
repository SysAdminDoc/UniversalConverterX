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

### 47. Qualcomm NPU / ARM64 Native Build

Publish a native ARM64 build targeting Snapdragon X Elite / X Plus devices. Requires ARM64 .NET 10 publish, ARM64 WinUI 3 validation, and verifying Python sidecars under ARM64 Python or x64 emulation. ONNX Runtime 1.25.0 removed ArmNN EP — must target QNN EP only.

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

**Blocker:** The source/build and provider-probe work is active as Item 47-a.
After that ships, a Snapdragon X Elite / X Plus device is still required to
verify QNN EP inference, ARM64 Python/native sidecar compatibility, and WinUI 3
ARM64 rendering on the target hardware.
