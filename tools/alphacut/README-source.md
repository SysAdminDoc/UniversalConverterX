# AlphaCut v1.2.0

**Video background removal & compositing.**

AlphaCut uses ONNX segmentation models to isolate subjects from video backgrounds, with built-in compositing, batch processing.

![Version](https://img.shields.io/badge/Version-v1.2.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.9+-blue?style=flat-square&logo=python)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-Windows%20|%20Linux%20|%20macOS-blue?style=flat-square)

---

## Features

**AI & Processing**
- 8 AI Models — U2Net, ISNet, BiRefNet — from fast drafts to cinema-quality edges
- 7 Output Formats — ProRes 4444+Alpha, WebM VP9+Alpha, Animated WebP, Animated GIF, PNG sequences, green screen, grayscale matte
- Chroma-Key Fallback — auto-detect green/blue screens; FFmpeg chroma-key for 10x speed boost
- Pipelined I/O — parallel decode/infer/save threads for higher throughput
- Frame Skip — process every Nth frame with mask reuse (up to 10x speedup)
- Benchmark Mode — test 10 samples to estimate total processing time
- Memory Monitoring — live RAM % during processing with warnings
- Resume Interrupted Jobs — progress saved every 50 frames, auto-resumes on restart

**Advanced Compositing**
- Background Replacement — solid color (6 presets + custom picker) or image file
- Color Spill Suppression — reduce green/blue/red spill along mask edges
- Shadow Preservation — detect and keep ground shadows via luminance analysis
- Mask Inversion — remove subject instead of background

**Batch & Workflow**
- Batch Queue — drop multiple files or a folder, process sequentially
- Job Table — per-file thumbnails, status, progress %, and output path
- CLI Mode — full argparse interface for headless/scripted operation (with auto chroma-key detection)
- Auto-Naming — configurable output patterns ({name}, {model}, {format}, {date})
- Export Presets — save/load all settings including compositing
- Recent Files — last 20 files quick-access menu

**UI/UX**
- Before/After Split View with draggable divider
- Smart Model Picker, Toast Notifications, Animated Progress
- System Tray integration, Scrubable Preview
- Menu Bar — File, Tools (Model Manager, Settings Folder), Help (Updates, About)
- About Dialog — version, system info, GitHub links
- Update Checker — checks GitHub releases on startup and on demand
- Model Manager — view/delete cached ONNX models with size info
- Settings Persistence — all preferences saved between sessions

## Requirements

| Requirement | Details |
|---|---|
| **Python** | 3.9+ |
| **FFmpeg** | On PATH |
| **NVIDIA GPU** | Optional — CUDA 12 + cuDNN 9 |

## Quick Start

```bash
# GUI
python AlphaCut.py

# CLI — basic
python AlphaCut.py -i video.mp4 -f prores -m BiRefNet

# CLI — background replacement
python AlphaCut.py -i video.mp4 -f webm --bg-image beach.jpg

# CLI — green spill + shadow preservation
python AlphaCut.py -i greenscreen.mp4 -f prores --spill 60 --shadow 40

# CLI — batch with frame skip
python AlphaCut.py -i vid1.mp4 vid2.mp4 vid3.mp4 -f webm --frame-skip 3

# CLI — invert mask + custom background
python AlphaCut.py -i video.mp4 -f prores --invert --bg-color 0,0,0
```

## CLI Reference

| Flag | Default | Description |
|---|---|---|
| `-i`, `--input` | — | Input video file(s) |
| `-o`, `--output` | Auto-named | Output path |
| `-m`, `--model` | `u2net_human_seg` | Model name (partial match) |
| `-f`, `--format` | `mp4` | mp4, prores, webm, webp_anim, png_seq, greenscreen, matte |
| `--max-res` | 0 (original) | Max resolution |
| `--edge` | 0 | Edge softness (0-100) |
| `--shift` | 0 | Mask shift (-20 to +20) |
| `--temporal` | 0 | Temporal smooth (0-7) |
| `--frame-skip` | 1 | Process every Nth frame |
| `--invert` | — | Invert mask |
| `--spill` | 0 | Spill suppression (0-100) |
| `--spill-color` | green | Spill color: green, blue, red |
| `--shadow` | 0 | Shadow preservation (0-100) |
| `--bg-color` | — | Background R,G,B |
| `--bg-image` | — | Background image path |
| `--no-audio` | — | Strip audio |

## AI Models

| Model | Speed | Quality | Best For |
|---|---|---|---|
| `u2netp` | Fast | Good | Quick previews |
| `u2net_human_seg` | Fast | Great | **People (default)** |
| `silueta` | Fast | Good | People (small) |
| `u2net` | Medium | Great | General subjects |
| `isnet-general-use` | Medium | Great | General subjects |
| `isnet-anime` | Medium | Great | Anime / illustrations |
| `BiRefNet-portrait` | Slow | Excellent | Portraits, hair detail |
| `BiRefNet-general` | Slow | Excellent | **Best overall** |

## Architecture

```
AlphaCut.py (single file, ~2,650 lines)
├── Crash Handler + Bootstrap (auto-installs all deps)
├── AlphaCutEngine — ONNX inference + mask refinement
│   ├── Edge refinement, temporal smoothing
│   ├── Spill suppression, shadow preservation
│   ├── Mask inversion, background compositing
│   ├── SHA-256 model integrity verification
│   └── Engine cache (singleton)
├── ProcessingWorker — Pipelined frame processing
│   ├── Reader thread → AI inference → Saver thread
│   ├── Frame skip with mask reuse
│   └── Resume from last saved frame
├── BatchWorker — Sequential multi-file processing
├── BenchmarkWorker — 10-frame speed estimation
├── PreviewFrameWorker — Single-frame preview
├── UpdateChecker — GitHub releases API
├── AboutDialog — Version/system info
├── ModelManagerDialog — Download/delete models
├── SplitPreviewWidget — Before/after comparison
├── ToastWidget — Floating notifications
├── CLI — Full argparse headless interface
└── Settings/Presets — JSON persistence
```
