"""Hardware-accelerated video frame decoding for UCX sidecars (ROADMAP Item 98).

Sidecars that walk every frame of long-form video in a Python loop (motion
energy, colourisation, stabilisation, …) traditionally decode on the CPU via
OpenCV's ``VideoCapture``. On HD/4K that decode is the dominant cost. This
helper decodes with PyAV v17 using NVDEC (the ``*_cuvid`` family) when a CUDA
device is present, offloading decode to the GPU's dedicated video engine, and
falls back cleanly to PyAV software decode. When PyAV itself is unavailable it
reports so, letting callers keep their existing OpenCV path.

Design notes:
  * The consumer of these frames is CPU code (OpenCV, NumPy), so each frame is
    downloaded to host memory once. NVDEC still offloads the expensive decode;
    a fully GPU-resident dlpack path awaits a GPU-native frame consumer.
  * ``UCX_HWDECODE=0`` forces software decode — an escape hatch for drivers or
    clips where NVDEC misbehaves.
  * Any hardware error during setup transparently degrades to software decode,
    so a broken GPU never breaks a sidecar.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, Tuple

_ENV_DISABLE = "UCX_HWDECODE"
_cuda_probe: bool | None = None


def pyav_available() -> bool:
    try:
        import av  # noqa: F401
        return True
    except Exception:
        return False


def _hw_requested() -> bool:
    return os.environ.get(_ENV_DISABLE, "1").strip().lower() not in ("0", "false", "no", "off")


def cuda_decode_available() -> bool:
    """True when PyAV can create a CUDA hardware-decode device on this machine.

    The result is probed once and cached. Honours ``UCX_HWDECODE=0``.
    """
    global _cuda_probe
    if _cuda_probe is not None:
        return _cuda_probe
    if not _hw_requested() or not pyav_available():
        _cuda_probe = False
        return False
    try:
        import av
        from av.codec.hwaccel import HWAccel

        has_cuvid = any(c.endswith("_cuvid") for c in av.codecs_available)
        if not has_cuvid:
            _cuda_probe = False
            return False
        # Constructing the accelerator validates that a CUDA device exists.
        HWAccel(device_type="cuda", allow_software_fallback=False)
        _cuda_probe = True
    except Exception:
        _cuda_probe = False
    return _cuda_probe


def iter_frames(
    path: str | Path,
    *,
    pix_fmt: str = "bgr24",
    allow_hw: bool = True,
) -> Iterator[Tuple[int, "object"]]:
    """Yield ``(frame_index, ndarray)`` for every video frame in ``path``.

    ``ndarray`` is a NumPy array in ``pix_fmt`` (default OpenCV-style ``bgr24``).
    NVDEC is used when ``allow_hw`` and a CUDA device is present; on any hardware
    error the decode restarts in software. Raises ``RuntimeError`` if PyAV is not
    installed so callers can fall back to their own decoder.
    """
    if not pyav_available():
        raise RuntimeError("PyAV is not available for hardware decode.")

    import av
    from av.codec.hwaccel import HWAccel

    use_hw = bool(allow_hw) and cuda_decode_available()

    if use_hw:
        try:
            yield from _decode(av, path, pix_fmt,
                               HWAccel(device_type="cuda", allow_software_fallback=True))
            return
        except av.error.FFmpegError:
            # NVDEC refused this stream (unsupported codec/profile) — fall back.
            pass
    yield from _decode(av, path, pix_fmt, None)


def _decode(av, path, pix_fmt, hwaccel):
    container = av.open(str(path), hwaccel=hwaccel) if hwaccel else av.open(str(path))
    try:
        index = 0
        for frame in container.decode(video=0):
            yield index, frame.to_ndarray(format=pix_fmt)
            index += 1
    finally:
        container.close()


def frames_or_opencv(path: str | Path, cv2, *, pix_fmt: str = "bgr24"):
    """Yield ``(frame_index, ndarray)`` using NVDEC when available, else OpenCV.

    A drop-in replacement for a ``cv2.VideoCapture`` read loop in analysis
    sidecars: NVDEC offloads decode to the GPU when a CUDA device is present, and
    on any failure (no PyAV, no CUDA, unsupported stream) it transparently falls
    back to OpenCV's software ``VideoCapture`` so behaviour never regresses.
    """
    if cuda_decode_available():
        try:
            yield from iter_frames(path, pix_fmt=pix_fmt)
            return
        except Exception:
            pass  # fall through to OpenCV

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return
    index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            yield index, frame
            index += 1
    finally:
        capture.release()


def decode_backend(allow_hw: bool = True) -> str:
    """Return a human-readable label for the decode backend that would be used."""
    if not pyav_available():
        return "opencv"
    return "nvdec" if (allow_hw and cuda_decode_available()) else "pyav-software"
