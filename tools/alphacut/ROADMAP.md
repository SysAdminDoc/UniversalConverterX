# AlphaCut — Development Roadmap

## Completed

- [x] **PyInstaller single-exe packaging** — `.github/workflows/build.yml`; 3-platform matrix (Windows exe, Linux binary, macOS binary); triggered via `workflow_dispatch`; artifacts uploaded to GitHub Release automatically. *(v1.1.0)*
- [x] **Animated WebP / transparent export** — `webp_anim` format added; pure-Python PIL encode; RGBA transparency; quality slider; warns on > 300 frames. *(v1.1.0)*
- [x] **SHA-256 model integrity verification** — `.sha256` sidecar written after download; verified on every load; auto-re-download on mismatch. *(v1.1.0)*
- [x] **requirements.txt** — pinned dependencies for clean installs. *(v1.1.0)*
- [x] **Animated GIF export** — `gif_anim` format with 256-colour palette + binary transparency; uses PIL `disposal=2` for proper restoration. *(v1.2.0)*
- [x] **Built-in chroma-key fallback** — `detect_chroma_background()` auto-detects green/blue screens by corner-patch colour dominance; `ChromaDetectWorker` runs detection background; `ChromaKeyWorker` uses FFmpeg chroma-key filter for 10× speedup on synthetic backgrounds. *(v1.2.0)*
- [x] **Batch thumbnail previews** — `ThumbnailLoader` extracts 80px thumbnails from batch videos; `JobTable` redesigned to 5 columns with thumbnail column. *(v1.2.0)*
- [x] **CLI chroma-key support** — `--chroma-key` flag in argparse; auto-detects in headless mode. *(v1.2.0)*

## Future Ideas

- [ ] Inno Setup installer for Windows
- [ ] ROI selection / manual mask painting
- [ ] Multi-GPU support
- [ ] Drag-out support (drag output file to NLE)
- [ ] Localization scaffold (i18n-ready strings)
- [ ] Thumbnail grid for batch preview
- [ ] Virtual camera output (pyvirtualcam for OBS/Zoom live use)
- [ ] FFmpeg-pipe RGB24 stdin mode (for scriptable pipelines)
- [ ] MatAnyone foreground/alpha pair export (for NLEs without alpha support)

## Open-Source Research (Round 2)

### Related OSS Projects
- **danielgatis/rembg** — https://github.com/danielgatis/rembg — U2Net/ISNet/BiRefNet runner, CLI/HTTP/Python/Docker, FFmpeg-pipe mode for RGB24 stdin.
- **nadermx/backgroundremover** — https://github.com/nadermx/backgroundremover — CLI-first image+video removal, reference for checkpoint auto-download UX.
- **Ckrest/rvm-virtual-camera** — https://github.com/Ckrest/rvm-virtual-camera — Real-time Robust Video Matting to a virtual cam; reference for live preview + OBS-friendly output.
- **PeterL1n/RobustVideoMatting** — https://github.com/PeterL1n/RobustVideoMatting — Upstream RVM model with temporal coherence; cleaner edges than frame-by-frame U2Net on fast motion.
- **Akascape/Rembg-Fuse** — https://github.com/Akascape/Rembg-Fuse — DaVinci Resolve Fusion plugin; reference for node-graph compositing UX and alpha-over-plate workflows.
- **Shlok-crypto/Background-Remover-RealTime** — https://github.com/Shlok-crypto/Background-Remover-RealTime — Webcam replace+blur pipeline.
- **sunwood-ai-labs/video-background-remover-cli** — https://github.com/Sunwood-ai-labs/video-background-remover-cli — rembg + OpenCV, exports transparent WebP/GIF and MatAnyone foreground+alpha pair.

### Features to Consider Next
- **Virtual camera output** (rvm-virtual-camera) — pipe the alpha composite to an OBS Virtual Camera endpoint on Windows (via `pyvirtualcam`) for live Zoom/Meet use; a huge distribution multiplier.
- **FFmpeg-pipe RGB24 mode** (rembg) — accept `ffmpeg -i IN -f rawvideo -pix_fmt rgb24 - | alphacut --pipe` so long pipelines can fuse with upstream filters without disk I/O.
- **MatAnyone foreground/alpha pair export** (video-background-remover-cli) — not just ProRes4444 — also export a separate foreground RGB video and a matte video so downstream NLEs without alpha-aware decoders still work.
- **Temporal-coherent model path** (RVM) — add RVM as a 9th model for live/interview footage where U2Net flickers on hair/edges frame-to-frame.
- **Interactive refine-mask brush** (Rembg-Fuse node graph) — manual one-frame brush fix that propagates via optical flow; addresses the "98% perfect, but this one leaf" problem.
- **Optical-flow mask propagation** (RVM recurrent state) — when frame-skipping, blend masks via DIS optical flow instead of straight reuse so fast-moving edges don't lag.
- **ONNX + NCNN Vulkan dual backend** (RVM, rvm-virtual-camera) — ship the same model as NCNN for Vulkan users (Apple Silicon & AMD), avoiding CUDA-only lock-in.

### Patterns & Architectures Worth Studying
- **Producer / matter / compositor triple-queue pipeline** (rembg FFmpeg-pipe mode) — already matches AlphaCut's pipelined I/O design; extending to a 4th "encoder" stage with bounded queues makes backpressure explicit.
- **Model-registry JSON with auto-download + SHA-256 verification** (rembg, nadermx/backgroundremover) — one `models.json` that declares name/url/hash/size/license, keeps the app small and lets users drop new models without rebuilding.
- **Virtual-camera plugin on Windows via UnifiedCamera / pyvirtualcam** — reference pattern for exposing the alpha-composite feed as a webcam to other apps.
