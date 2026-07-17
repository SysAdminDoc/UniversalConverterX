# UniversalConverterX — Blocked Roadmap Items

Items that cannot proceed without external input, credentials, hardware, or upstream dependencies.

---

### 66. FFmpeg 8.1 D3D12 Filter Pipeline

D3D12 encoder presets shipped (h264/av1_d3d12va via videocrush) and the bundled FFmpeg is already pinned to 8.1.2. Remaining scope was wiring `scale_d3d12` + `deinterlace_d3d12` into a GPU zero-copy filter chain.

Impact: 3 · Effort: 2 · Type: platform + leapfrog

**Blocker:** Requires a GPU whose Direct3D 12 video engine supports hardware encode/decode and the video-processor filters. On the available hardware, `scale_d3d12` runs in isolation but `h264_d3d12va`/`av1_d3d12va` encode, D3D12 hardware decode, and `deinterlace_d3d12` all fail (encode: "Encode failed"; deinterlace: HRESULT 0x887A0005 DXGI_ERROR_INVALID_CALL). The intended zero-copy pipeline (d3d12 decode → scale_d3d12/deinterlace_d3d12 → d3d12 encode) cannot be built or verified without a supporting GPU. Verify on a machine with a modern discrete GPU whose driver exposes working D3D12 video encode + video-processor deinterlace.

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
