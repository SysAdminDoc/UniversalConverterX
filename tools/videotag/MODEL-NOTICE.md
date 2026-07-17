# VideoTag model notice

The model is not bundled. `download-model --accept-license` retrieves the
versioned MediaPipe EfficientDet-Lite0 int8 v1 object detector from Google's
immutable MediaPipe model path, verifies its exact 4,602,795-byte size and
SHA-256, and only then installs it atomically.

- Model source: `google-ai-edge/mediapipe`
- Model license: Apache License 2.0
- Model URL: `https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/int8/1/efficientdet_lite0.tflite`
- SHA-256: `0720bf247bd76e6594ea28fa9c6f7c5242be774818997dbbeffc4da460c723bb`

Tagging is local and performs no network requests. The sidecar uses standalone
LiteRT rather than MediaPipe Tasks because MediaPipe Tasks documents SDK usage
and performance metrics; LiteRT's portable metrics implementation is a no-op.
