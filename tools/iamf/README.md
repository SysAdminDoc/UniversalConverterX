# IAMF immersive audio

The IAMF sidecar uses UCX's bundled FFmpeg 8.1.2 runtime to create, package,
and render AOMedia Immersive Audio Model and Formats assets.

- `encode --profile stereo` creates a 48 kHz Opus IAMF audio element and
  stereo mix presentation.
- `encode --profile scalable-5.1` accepts a normal six-channel source and
  creates the standard four-substream scalable stereo + 5.1 representation.
- `package` stream-copies both IAMF stream groups into an audio-only MP4.
- `render --layout stereo|5.1` exports 48 kHz, 24-bit WAV or FLAC. The stereo
  render uses the base layer; 5.1 reconstructs UCX's scalable channel profile.

Every output is staged beside its destination, probed for the promised stream
groups or channel count, and promoted atomically only after verification. The
wrapper does not claim object-based or arbitrary scene-based IAMF rendering.
