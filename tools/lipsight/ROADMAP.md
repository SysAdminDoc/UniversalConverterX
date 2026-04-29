# LipSight Roadmap

AI-powered lip-reading from silent video using Auto-AVSR via Replicate. PyQt6 GUI with MediaPipe face detection, automatic segmentation, SRT/TXT/JSON export. Roadmap focuses on local inference, multi-speaker, and accuracy-boosting pre-processing.

## Planned Features

### Inference
- **Local ONNX runtime** — ship a quantized Auto-AVSR ONNX model for CPU/CUDA/DirectML inference, no Replicate roundtrip
- **VALLR backend** — support the ICCV 2025 VALLR + LLaMA model for state-of-the-art 18.7% WER
- **AV-HuBERT backend** — self-supervised visual encoder as alternative
- **Whisper fusion mode** — when audio is present (not truly silent), run Whisper alongside lip-reading and arbitrate per-token confidence
- **Batch inference** — send all segments in one Replicate call when backend supports batching

### Preprocessing (big accuracy wins)
- **Face alignment** — Procrustes-align each frame's mouth ROI to a canonical pose, removes head-motion noise
- **Super-resolution for small faces** — apply Real-ESRGAN / GFPGAN to faces <96px before lip-reading
- **Stabilization** — optical-flow stabilize the mouth ROI across frames
- **Lighting normalization** — CLAHE on the mouth crop to reduce shadow/over-exposure effects
- **Multi-speaker segmentation** — detect multiple faces, label speakers A/B, output speaker-attributed SRT

### Video UX
- **Scrubber with waveform-style mouth-movement curve** — visualize the open/close ratio over time to pick segments by eye
- **Manual segment editor** — drag handles on the timeline to define custom regions
- **Side-by-side playback** — video + annotated mouth ROI + transcription subtitles live
- **Confidence overlay** — color-code each word by model confidence

### Export
- **Burn-in subtitles** — ffmpeg-pipe to render final video with subtitles baked in
- **WebVTT** alongside SRT
- **Segment export** — cut video into per-segment clips for further review
- **Structured JSON schema** — stable schema versioned for downstream consumers (speaker, start, end, text, confidence, per-word)

### Workflow
- **Project files** — save video + segmentation + transcription + edits as a `.lipsight` bundle
- **Review mode** — human-in-the-loop correction: flag low-confidence words, human types fix, fine-tune adapter from corrections
- **CLI mode** — `lipsight --input a.mp4 --backend onnx --output out.srt` headless
- **Watch folder** — auto-process new videos dropped into a folder

## Competitive Research
- **Auto-AVSR (upstream)** — Apache 2.0, ~20% WER on LRS3; already the current backend. Track new releases.
- **VALLR (ICCV 2025)** — 18.7% WER using LLaMA integration; top of the leaderboard as of 2025. High-priority port.
- **AV-HuBERT (Meta)** — strong self-supervised encoder; useful as a general feature extractor.
- **Commercial: SpeechMatics / Liopa** — closed-source medical/legal-focused; document strengths so we know where OSS tools underperform.
- **Whisper (OpenAI)** — audio-based, not visual, but fusion with Whisper dramatically improves noisy-audio scenarios.

## Nice-to-Haves
- Real-time webcam mode: live captions from the user's face
- Language support beyond English (LRS-Mandarin, LRS-French datasets exist)
- Deaf-accessibility mode: large, high-contrast captions rendered on top of the video preview
- On-device mobile (Android/iOS) port with TFLite-quantized model
- Federated correction contribution (opt-in): user-corrected transcriptions flow back to a public fine-tuning dataset
- Watermark detection: auto-flag if video has TikTok/YouTube/IG watermark that obscures the mouth

## Open-Source Research (Round 2)

### Related OSS Projects
- abb128/LiveCaptions — https://github.com/abb128/LiveCaptions — Linux desktop live captioning; local inference via aprilasr; Flatpak distribution; no network
- MidCamp/live-captioning — https://github.com/MidCamp/live-captioning — browser-based using Chrome Web Speech API; zero-install for event accessibility
- steveseguin/captionninja — https://github.com/steveseguin/captionninja — browser mic → STT → websocket → overlay, pairs with Electron Capture for desktop pinning
- botbahlul/Live-Subtitle — https://github.com/botbahlul/Live-Subtitle — Android app recognizing VLC streams, adds MLKit translate
- zats/SpeechRecognition — https://github.com/zats/SpeechRecognition — iOS SFSpeechRecognizer demo generating subtitles in real-time
- XR-Access-Initiative/chirp-captions — https://github.com/XR-Access-Initiative/chirp-captions — Unity VR captions system, paired with Whisperer
- livekit-examples/live-translated-captioning — https://github.com/livekit-examples/live-translated-captioning — LiveKit agent with Deepgram; swap-in any STT
- openai/whisper — https://github.com/openai/whisper — the STT baseline
- ggerganov/whisper.cpp — https://github.com/ggerganov/whisper.cpp — C++ Whisper port, offline-capable, CPU-friendly
- SYSTRAN/faster-whisper — https://github.com/SYSTRAN/faster-whisper — CTranslate2 Whisper; 4x faster, lower VRAM
- mpc001/auto_avsr — https://github.com/mpc001/auto_avsr — audio-visual speech recognition (lip reading + audio fusion); closest to the project's name
- facebookresearch/av_hubert — https://github.com/facebookresearch/av_hubert — audio-visual HuBERT; lip-reading research baseline
- rizkiarm/LipNet — https://github.com/rizkiarm/LipNet — end-to-end sentence-level lip reading (Keras); classic reference

### Features to Borrow
- **Local-only STT with whisper.cpp** (abb128/LiveCaptions model) — no cloud, no API keys, no telemetry; matches the project's privacy positioning
- **faster-whisper backend for CPU users** — 4x perf gain vs. reference whisper, same weights
- **Audio + visual fusion (AV-HuBERT / Auto-AVSR)** — the "LipSight" differentiator; pure-lip-reading mode for muted video, fused mode when audio exists
- **Word-level timestamps** (whisper.cpp `-t` flag) — enables click-to-jump on caption transcripts and precise alignment for export as SRT/VTT
- **Live overlay + pin-on-top mode** (CaptionNinja) — always-on-top transparent overlay window for any foreground app
- **Real-time translation pipeline** (LiveKit demo, Live-Subtitle) — STT → MT → display; let user pick target language
- **Export formats: SRT, VTT, TXT, JSON with timestamps** — feed downstream tools
- **Session recording + searchable transcript archive** — save every session, full-text search past meetings
- **Global hotkey to start/stop capture** — matches the "accessibility overlay" use case

### Patterns & Architectures Worth Studying
- abb128/LiveCaptions **loopback audio capture on Linux via PipeWire/PulseAudio** — direct read-from-monitor-sink; on Windows this is WASAPI loopback
- whisper.cpp's **streaming decode** — progressive partials that stabilize as more audio arrives; render "faded" partial text, commit when stable
- Auto-AVSR's **two-stream encoder + late fusion** — audio path + lip path, fused only at final layers; tolerates mic noise / masked faces individually
- CaptionNinja's **WebSocket fan-out** — one source, N overlay clients (great for streamers)
- **Face/mouth ROI detection** (mediapipe face-mesh) for lip-reading path — landmarks 78/95/308/317/13/14/80/310 bound the lip region tightly
