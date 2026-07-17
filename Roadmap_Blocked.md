# UniversalConverterX — Blocked Roadmap Items

Items that cannot proceed without external input, credentials, hardware, or upstream dependencies.

---

### 66. FFmpeg 8.1 D3D12 Filter Pipeline

D3D12 encoder presets shipped (h264/av1_d3d12va via videocrush) and the bundled FFmpeg is already pinned to 8.1.2. Remaining scope was wiring `scale_d3d12` + `deinterlace_d3d12` into a GPU zero-copy filter chain.

Impact: 3 · Effort: 2 · Type: platform + leapfrog

**Blocker:** Requires a GPU whose Direct3D 12 video engine supports hardware encode/decode and the video-processor filters. On the available hardware, `scale_d3d12` runs in isolation but `h264_d3d12va`/`av1_d3d12va` encode, D3D12 hardware decode, and `deinterlace_d3d12` all fail (encode: "Encode failed"; deinterlace: HRESULT 0x887A0005 DXGI_ERROR_INVALID_CALL). The intended zero-copy pipeline (d3d12 decode → scale_d3d12/deinterlace_d3d12 → d3d12 encode) cannot be built or verified without a supporting GPU. Verify on a machine with a modern discrete GPU whose driver exposes working D3D12 video encode + video-processor deinterlace.

---

### 25. MSIX Packaging + WinGet Submission

Build a `.msixbundle` using `makeappx.exe`. Submit a manifest to `microsoft/winget-pkgs` so users can install via `winget install MavenImaging.UniversalConverterX`.

Impact: 4 · Effort: 3 · Type: distribution

**Blocker:** Requires a code-signing certificate. Cannot produce a trusted MSIX without one.

---

### 44. DVD Burn / CD Burner (Disc Tools)

Write video files to DVD-Video structure or data files to a CD/DVD using `growisofs` / `cdrecord` / Windows `IDiscRecorder2` COM API.

Impact: 2 · Effort: 4 · Type: parity

**Blocker:** tsMuxeR (the standard Blu-ray TS muxer) was archived by its maintainer in April 2025. Blu-ray authoring must pivot to `eac3to` or be scoped to data-DVD only. Requires design decision before implementation.

---

### 47. Qualcomm NPU / ARM64 Native Build

Publish a native ARM64 build targeting Snapdragon X Elite / X Plus devices. Requires ARM64 .NET 10 publish, ARM64 WinUI 3 validation, and verifying Python sidecars under ARM64 Python or x64 emulation. ONNX Runtime 1.25.0 removed ArmNN EP — must target QNN EP only.

Impact: 2 · Effort: 4 · Type: platform

**Blocker:** Needs a Snapdragon X Elite device to verify QNN EP availability, ARM64 Python sidecar compatibility, and WinUI 3 ARM64 rendering. Cannot be validated without hardware.

---

### 89. AVIF Gain Map HDR — remaining: gain-map writing

AVIF tuning controls shipped (speed/subsampling/lossless). **Remaining:** full Apple-style JPEG gain-map writing.

Impact: 3 · Effort: 2 · Type: format coverage

**Blocker:** Requires `pillow-avif-plugin` (or an equivalent bundled encoder) to expose the libavif 1.4.x gain-map writing API. No redistributable Windows build exposes it yet, so the round-trip write cannot be implemented or tested. Overlaps the libvips/libultrahdr path tracked under Item 117.

---

### 95. Anime Upscale — remaining: Anime4K GLSL backend

Real-ESRGAN ncnn-vulkan backend shipped. **Remaining:** Anime4K GLSL shader-chain backend.

Impact: 3 · Effort: 3 · Type: AI

**Blocker:** Needs a realtime GLSL rendering path plus an mpv-script bridge, and is deferred pending community signal that the GLSL backend is wanted over the shipped Real-ESRGAN engine. Product-signal gate, not a coding gap.

---

### 117. UltraHDR / ISO 21496-1 Gain-Map Preservation

Preserve ISO 21496-1 gain maps when converting UltraHDR JPEG photos to JPEG or AVIF through libvips 8.18 / libultrahdr.

Impact: 3 · Effort: 3 · Type: format coverage

**Blocker:** Requires a redistributable Windows libvips 8.18 build with `uhdrload` / `uhdrsave` enabled plus a legally redistributable ISO 21496-1 gain-map fixture. Neither is present in the repository or managed tool inventory, so the required round-trip preservation check cannot be run or added to CI without selecting those external artifacts.
