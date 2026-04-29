# RecordCast sidecar

| | |
|---|---|
| **UCX module** | Recorder |
| **Integration phase** | v2.1 parity pass |
| **Source ported** | First-party shim |
| **Entry point** | `sidecar.py` |
| **Runtime** | Python 3.10+ + FFmpeg |

## What this engine does

RecordCast captures the Windows desktop with FFmpeg `gdigrab` and emits UCX NDJSON progress events. The first shipped scope is fixed-duration screen capture with MP4/H.264 output.

Webcam, microphone, and system-audio recording are intentionally not implemented here yet because they require Windows device enumeration, user consent, and per-device FFmpeg input mapping.

## Build

```powershell
pwsh tools/recordcast/build.ps1
```

The build writes `tools/recordcast/recordcast.exe`, which the WinUI shell locates through `SidecarRunner`.

## Contract

```powershell
recordcast.exe record --output C:\Temp\capture.mp4 --duration 30 --framerate 30 --crf 20
```

Events follow the shared sidecar contract in [`../README.md`](../README.md).
