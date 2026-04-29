<!-- codex-branding:start -->
<p align="center"><img src="icon.png" width="128" alt="Lip Sight"></p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-preview-58A6FF?style=for-the-badge">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-4ade80?style=for-the-badge">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Python%20GUI-58A6FF?style=for-the-badge">
</p>
<!-- codex-branding:end -->

# LipSight

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

> AI-powered lip reading tool that transcribes speech from silent video using state-of-the-art visual speech recognition models.

## Quick Start

```bash
git clone https://github.com/SysAdminDoc/LipSight.git
cd LipSight
python LipSight.py  # Auto-installs all dependencies on first run
```

## Features

| Feature | Description |
|---------|-------------|
| 🧠 Auto-AVSR Inference | Cloud inference via Replicate API using the state-of-the-art Auto-AVSR model (~80% word accuracy) |
| 👁️ Face/Mouth Detection | Real-time MediaPipe face mesh with mouth ROI visualization and open/close ratio tracking |
| 🎬 Smart Segmentation | Automatic speech segment detection via mouth movement analysis — timestamps estimated per segment |
| 📹 Video Preview | Frame-by-frame scrubbing with annotated face landmarks and speaking/silent status overlay |
| 💾 Multi-Format Export | Export results as SRT subtitles, timestamped TXT, or structured JSON |
| 🌐 Custom Endpoints | Support for self-hosted inference servers alongside Replicate API |
| 🎨 Dark Theme | Professional Catppuccin Mocha dark interface |
| ⚡ Threaded Processing | All heavy operations run on background threads — GUI never locks |
| 🔧 Zero Configuration | Auto-bootstraps all dependencies (PyQt6, OpenCV, MediaPipe, Replicate) |

## How It Works

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Video Input    │────>│  Face Analysis   │────>│  Segmentation   │────>│   Inference      │
│                  │     │                  │     │                  │     │                  │
│  MP4/MOV/AVI/   │     │  MediaPipe Face  │     │  Mouth movement  │     │  Auto-AVSR via   │
│  MKV/WebM       │     │  Mesh detection  │     │  based splitting │     │  Replicate API   │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └────────┬─────────┘
                                                                                  │
                         ┌─────────────────┐     ┌─────────────────┐              │
                         │   Export         │<────│   Results        │<─────────────┘
                         │                  │     │                  │
                         │  SRT / TXT /     │     │  Timestamped     │
                         │  JSON / Clipboard│     │  transcription   │
                         └─────────────────┘     └─────────────────┘
```

## Prerequisites

- **Python 3.8+**
- **Replicate API token** — get one free at [replicate.com/account/api-tokens](https://replicate.com/account/api-tokens)
- **ffmpeg** (optional) — enables faster video segment extraction. Falls back to OpenCV if not present.

## Usage

1. Launch `LipSight.py`
2. Go to **Settings** tab → paste your Replicate API token → **Save Settings**
3. Click **Load Video** and select an MP4/MOV/AVI file
4. *(Optional)* Click **Analyze Segments** to detect speech regions via mouth movement
5. Click **Lip Read** to begin transcription
6. Export results as SRT, TXT, JSON, or copy to clipboard

## Configuration

Settings are persisted to `~/.lipsight/config.json` (or `%APPDATA%\.lipsight\config.json` on Windows).

| Setting | Description | Default |
|---------|-------------|---------|
| Replicate API Token | Authentication for cloud inference | — |
| Custom Endpoint URL | Self-hosted VSR server URL | — |
| Auto-Segment | Split video by mouth movement before processing | Enabled |
| Mouth Open Threshold | Sensitivity for speech detection (3–15) | 6 |
| Inference Backend | Replicate API or Custom Endpoint | Replicate |

## Accuracy Notes

Visual-only lip reading is fundamentally limited by the **homophene problem** — many sounds (p/b/m, k/g, f/v) look identical on lips. Current state-of-the-art achieves ~80% word accuracy on benchmark data under ideal conditions:

- Frontal face view, single speaker
- Good lighting, no obstructions
- Clear lip movement

Real-world accuracy varies. This tool is best suited for getting the gist of speech when audio is unavailable — not for precise transcription.

## Models & Research

LipSight uses the **Auto-AVSR** model family, which represents the current state of the art in deployable visual speech recognition:

- [Auto-AVSR](https://github.com/mpc001/auto_avsr) — Apache 2.0, ~20% WER on LRS3
- [VALLR](https://arxiv.org/abs/2503.21408) — Latest research (ICCV 2025), 18.7% WER using LLaMA integration
- [AV-HuBERT](https://github.com/facebookresearch/av_hubert) — Meta's self-supervised visual encoder

## FAQ / Troubleshooting

**Q: The transcription is inaccurate**
A: Ensure the video has a clear, frontal view of the speaker's face with good lighting. Lip reading AI currently achieves ~80% accuracy at best — significantly below audio-based transcription.

**Q: Processing is slow**
A: Cloud inference depends on Replicate's queue. Each segment takes ~10–30 seconds. Consider analyzing segments first and processing fewer, targeted clips.

**Q: No face detected**
A: The video needs a clearly visible face. Check the video preview — green landmarks should appear on the mouth region.

## License

MIT
