# VideoTag sidecar

`videotag` samples local images or videos with MediaPipe EfficientDet-Lite0 int8
and writes COCO object detections to JSON. It does not alter the source media.

## Operations

```powershell
# Report runtime and verified-model readiness
videotag.exe probe

# The only networked operation; requires explicit Apache-2.0 consent
videotag.exe download-model --accept-license

# Offline inference (2-second sampling by default)
videotag.exe tag --input video.mp4 --output video_ai_tags.json
```

The Apache-2.0 model comes from the immutable
`google-ai-edge/mediapipe` EfficientDet-Lite0 int8 v1 path. Its exact size is
4,602,795 bytes and its SHA-256 is
`0720bf247bd76e6594ea28fa9c6f7c5242be774818997dbbeffc4da460c723bb`.
Downloads use a private adjacent staging file and are atomically promoted only
after both checks succeed. The `tag` operation fails closed when the
model/runtime is missing or invalid, enables UCX's process network guard before
loading LiteRT, limits sampled frames and detections, and atomically promotes
the JSON report.

The runtime intentionally uses `ai-edge-litert`, whose portable metrics layer is
a no-op, instead of MediaPipe Tasks, whose current SDK documentation discloses
usage and performance metrics. All image/video bytes remain on the machine.
