#!/usr/bin/env python3
"""UCX LipSight sidecar — NDJSON wrapper for headless lip-reading transcription."""

import sys
import os
import json
import argparse
import tempfile
import shutil
import subprocess
import math

# ── Bootstrap ────────────────────────────────────────────────────────────────
def _bootstrap():
    if sys.version_info < (3, 8):
        print("Python 3.8+ required"); sys.exit(1)
    required = ['opencv-python', 'requests', 'numpy']
    for pkg in required:
        mod = pkg.replace('-', '_').lower()
        if mod == 'opencv_python':
            mod = 'cv2'
        try:
            __import__(mod)
        except ImportError:
            for flags in [[], ['--user'], ['--break-system-packages']]:
                try:
                    subprocess.check_call(
                        [sys.executable, '-m', 'pip', 'install', pkg, '-q'] + flags,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break
                except subprocess.CalledProcessError:
                    continue
    for pkg in ['mediapipe']:
        try:
            __import__(pkg)
        except ImportError:
            for flags in [[], ['--user'], ['--break-system-packages']]:
                try:
                    subprocess.check_call(
                        [sys.executable, '-m', 'pip', 'install', pkg, '-q'] + flags,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break
                except subprocess.CalledProcessError:
                    continue

_bootstrap()

import cv2
import numpy as np
import requests

try:
    import mediapipe as _mp
    _HAS_MEDIAPIPE = True
except Exception:
    _HAS_MEDIAPIPE = False
    _mp = None

# ── NDJSON helpers ───────────────────────────────────────────────────────────
def emit(obj: dict):
    sys.stdout.write(json.dumps(obj) + '\n')
    sys.stdout.flush()

def emit_progress(percent: float, stage: str, eta: int | None = None):
    payload: dict = {"event": "progress", "percent": round(percent, 1), "stage": stage}
    if eta is not None:
        payload["eta_seconds"] = eta
    emit(payload)

def emit_log(msg: str, level: str = "info"):
    emit({"event": "log", "level": level, "message": msg})

def emit_complete(output: str):
    size = os.path.getsize(output) if os.path.exists(output) else 0
    emit({"event": "complete", "output": output, "size_bytes": size})

def emit_error(msg: str):
    emit({"event": "error", "message": msg})


# ── Face + speech analysis (inline, no GUI deps) ─────────────────────────────
MOUTH_OUTER = [61,146,91,181,84,17,314,405,321,375,291,409,270,269,267,0,37,39,40,185]
MOUTH_INNER = [78,95,88,178,87,14,317,402,318,324,308,415,310,311,312,13,82,81,80,191]

class FaceAnalyzer:
    def __init__(self):
        self.face_mesh = None
        self._backend = 'none'
        self._cascade = None
        if _HAS_MEDIAPIPE:
            try:
                self.face_mesh = _mp.solutions.face_mesh.FaceMesh(
                    static_image_mode=False, max_num_faces=1,
                    refine_landmarks=True,
                    min_detection_confidence=0.5,
                    min_tracking_confidence=0.5)
                self._backend = 'mediapipe'
            except Exception:
                pass
        if self._backend == 'none':
            try:
                p = os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml')
                self._cascade = cv2.CascadeClassifier(p)
                if not self._cascade.empty():
                    self._backend = 'opencv'
            except Exception:
                pass

    @property
    def available(self):
        return self._backend != 'none'

    def open_ratio(self, frame) -> float:
        if self._backend == 'mediapipe':
            return self._mp_ratio(frame)
        if self._backend == 'opencv':
            return self._cv_ratio(frame)
        return 0.0

    def _mp_ratio(self, frame) -> float:
        h, w = frame.shape[:2]
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = self.face_mesh.process(rgb)
            if res.multi_face_landmarks:
                lm = res.multi_face_landmarks[0]
                t, b = lm.landmark[13], lm.landmark[14]
                l, r = lm.landmark[61], lm.landmark[291]
                mh = math.sqrt((t.x - b.x) ** 2 + (t.y - b.y) ** 2)
                mw = math.sqrt((l.x - r.x) ** 2 + (l.y - r.y) ** 2)
                return mh / max(mw, 0.001)
        except Exception:
            pass
        return 0.0

    def _cv_ratio(self, frame) -> float:
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self._cascade.detectMultiScale(gray, 1.1, 5, minSize=(80, 80))
            if len(faces) > 0:
                fx, fy, fw, fh = faces[0]
                mx1 = max(0, fx + int(fw * 0.2))
                my1 = max(0, fy + int(fh * 0.65))
                mx2 = min(frame.shape[1], fx + int(fw * 0.8))
                my2 = min(frame.shape[0], fy + fh + 5)
                mg = gray[my1:my2, mx1:mx2]
                if mg.size > 0:
                    gx = cv2.Sobel(mg, cv2.CV_64F, 1, 0, ksize=3)
                    gy = cv2.Sobel(mg, cv2.CV_64F, 0, 1, ksize=3)
                    return min(np.mean(np.sqrt(gx ** 2 + gy ** 2)) / 50.0, 0.3)
        except Exception:
            pass
        return 0.0

    def close(self):
        if self.face_mesh:
            try:
                self.face_mesh.close()
            except Exception:
                pass


def segment_video(video_path: str, threshold: float = 0.06) -> list[tuple[float, float]]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    analyzer = FaceAnalyzer()
    if not analyzer.available:
        emit_log("No face detection available — treating video as one segment", "warn")
        return [(0.0, total / fps)]

    emit_log(f"Analyzing {total} frames for speech segments ({analyzer._backend})...")
    cap = cv2.VideoCapture(video_path)
    ratios: list[tuple[int, float]] = []
    step = max(1, int(fps / 10))
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % step == 0:
            ratios.append((idx, analyzer.open_ratio(frame)))
        if idx % 200 == 0 and total > 0:
            emit_progress(idx / total * 15, f"Analyzing frame {idx}/{total}")
        idx += 1
    cap.release()
    analyzer.close()

    if not ratios:
        return [(0.0, total / fps)]

    min_seg = int(0.5 * 25)
    min_lead = int(0.3 * 25)
    segs: list[tuple[float, float]] = []
    speech = False
    start = 0
    sil = 0
    for fn, r in ratios:
        if r > threshold:
            if not speech:
                start = fn
                speech = True
            sil = 0
        elif speech:
            sil += step
            if sil >= min_lead:
                end = fn - sil
                if (end - start) >= min_seg:
                    segs.append((start / fps, end / fps))
                speech = False
                sil = 0
    if speech:
        end = ratios[-1][0]
        if (end - start) >= min_seg:
            segs.append((start / fps, end / fps))

    emit_log(f"Found {len(segs)} speech segment(s)")
    return segs if segs else [(0.0, total / fps)]


# ── Backends ─────────────────────────────────────────────────────────────────
class HuggingFaceSpaceBackend:
    KNOWN_SPACES = [
        "https://mpc001-auto-avsr.hf.space",
        "https://vumichien-av-hubert.hf.space",
    ]

    def __init__(self, custom_url: str = ""):
        self.custom_url = custom_url.strip().rstrip('/')

    def transcribe(self, video_path: str) -> str:
        import hashlib, random
        spaces = []
        if self.custom_url:
            spaces.append(self.custom_url)
        spaces.extend(self.KNOWN_SPACES)
        last_err = None

        for base in spaces:
            name = base.split("//")[1].split(".")[0] if "//" in base else base
            try:
                emit_log(f"Trying HuggingFace Space: {name}...")
                try:
                    requests.get(base, timeout=15)
                except requests.exceptions.ConnectionError:
                    emit_log(f"{name} unreachable — skipping", "warn")
                    continue

                emit_log(f"Uploading {os.path.basename(video_path)}...")
                with open(video_path, 'rb') as f:
                    up = requests.post(
                        f"{base}/upload",
                        files={"files": (os.path.basename(video_path), f, "video/mp4")},
                        timeout=120)
                up.raise_for_status()
                uploaded = up.json()
                fpath = uploaded[0] if isinstance(uploaded, list) else uploaded

                emit_log("Running inference (may take 30-120s)...")
                session = hashlib.md5(str(random.random()).encode()).hexdigest()[:12]

                for api_path in ["/api/predict", "/run/predict"]:
                    for payload in [
                        {"data": [{"path": fpath, "orig_name": os.path.basename(video_path)}], "session_hash": session},
                        {"data": [fpath], "session_hash": session},
                    ]:
                        try:
                            r = requests.post(f"{base}{api_path}", json=payload, timeout=300)
                            if r.status_code in (404, 422):
                                continue
                            r.raise_for_status()
                            data = r.json().get("data", [])
                            if data and data[0]:
                                return str(data[0]).strip()
                        except (requests.exceptions.HTTPError, requests.exceptions.Timeout):
                            continue

                emit_log(f"No valid response from {name}", "warn")
            except Exception as exc:
                last_err = str(exc)
                emit_log(f"{name}: {exc}", "warn")

        raise RuntimeError(
            f"All HuggingFace Spaces unavailable. Last error: {last_err}. "
            f"Try --backend local or supply --hf-url with a custom Space."
        )


class LocalAutoAVSRBackend:
    def __init__(self, model_dir: str | None = None):
        self.model_dir = model_dir or os.path.join(
            os.environ.get('APPDATA', os.path.expanduser('~')),
            '.lipsight', 'models', 'auto_avsr')
        self._ready = False

    def _ensure(self):
        if self._ready:
            return
        emit_log("Setting up local Auto-AVSR (first run may take several minutes)...")
        os.makedirs(self.model_dir, exist_ok=True)

        try:
            import torch
            emit_log(f"PyTorch {torch.__version__} (CUDA: {torch.cuda.is_available()})")
        except ImportError:
            emit_log("Installing PyTorch...")
            for cmd in [
                [sys.executable, '-m', 'pip', 'install', 'torch', 'torchvision', 'torchaudio',
                 '--index-url', 'https://download.pytorch.org/whl/cu121', '-q'],
                [sys.executable, '-m', 'pip', 'install', 'torch', 'torchvision', 'torchaudio', '-q'],
            ]:
                try:
                    subprocess.check_call(cmd, timeout=900)
                    break
                except Exception:
                    continue

        for pkg in ['sentencepiece', 'pytorch-lightning', 'hydra-core', 'omegaconf']:
            try:
                __import__(pkg.replace('-', '_').replace('.', '_').lower())
            except ImportError:
                subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'], timeout=300)

        repo = os.path.join(self.model_dir, 'repo')
        if not os.path.isdir(repo):
            emit_log("Cloning Auto-AVSR repository...")
            subprocess.check_call(
                ['git', 'clone', '--depth', '1',
                 'https://github.com/mpc001/auto_avsr.git', repo],
                timeout=120)

        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-e', repo, '-q'], timeout=300)
        except Exception:
            if repo not in sys.path:
                sys.path.insert(0, repo)

        self._ready = True
        emit_log("Local Auto-AVSR setup complete")

    def transcribe(self, video_path: str) -> str:
        self._ensure()
        repo = os.path.join(self.model_dir, 'repo')
        if repo not in sys.path:
            sys.path.insert(0, repo)

        emit_log("Running local inference...")
        for script in ['infer.py', 'eval.py', 'predict.py', 'demo.py']:
            sp = os.path.join(repo, script)
            if os.path.exists(sp):
                try:
                    result = subprocess.run(
                        [sys.executable, sp, '--video_path', video_path, '--modality', 'video'],
                        capture_output=True, text=True, timeout=300, cwd=repo)
                    if result.returncode == 0:
                        for line in reversed(result.stdout.strip().split('\n')):
                            ln = line.strip()
                            if ln and not ln.startswith(('[', '=', 'W', 'I', 'D')):
                                return ln
                        return result.stdout.strip()
                    emit_log(f"{script} error: {(result.stderr or result.stdout)[:200]}", "warn")
                except subprocess.TimeoutExpired:
                    raise RuntimeError("Local inference timed out (>5 min)")
                except Exception as exc:
                    emit_log(f"{script}: {exc}", "warn")

        raise RuntimeError(
            f"Could not run inference. Repo may need additional setup.\n"
            f"Manual: cd {repo} && python infer.py --video_path \"{video_path}\" --modality video"
        )


class ReplicateBackend:
    API = "https://api.replicate.com/v1"
    MODEL = "basord/lip-reading-ai-vsr"

    def __init__(self, token: str):
        self.token = token
        self.h = {"Authorization": f"Token {token}", "Content-Type": "application/json"}

    def transcribe(self, video_path: str) -> str:
        import time
        emit_log("Uploading to Replicate...")
        with open(video_path, 'rb') as f:
            r = requests.post(
                f"{self.API}/files",
                headers={"Authorization": f"Token {self.token}"},
                files={"content": (os.path.basename(video_path), f, "video/mp4")},
                data={"content_type": "video/mp4"},
                timeout=120)
        r.raise_for_status()
        url = r.json().get("urls", {}).get("get", "") or r.json().get("url", "")
        if not url:
            raise RuntimeError("No upload URL from Replicate")

        r = requests.get(f"{self.API}/models/{self.MODEL}/versions", headers=self.h, timeout=30)
        r.raise_for_status()
        ver = r.json()["results"][0]["id"]

        emit_log("Running Replicate prediction...")
        r = requests.post(f"{self.API}/predictions", headers=self.h,
                          json={"version": ver, "input": {"video": url}}, timeout=30)
        r.raise_for_status()
        pred = r.json()
        get_url = pred.get("urls", {}).get("get", f"{self.API}/predictions/{pred['id']}")

        for elapsed in range(0, 300, 2):
            time.sleep(2)
            p = requests.get(get_url, headers=self.h, timeout=30).json()
            st = p.get("status", "")
            if st == "succeeded":
                out = p.get("output", "")
                if isinstance(out, dict):
                    return out.get("text", str(out))
                if isinstance(out, list):
                    return " ".join(str(o) for o in out)
                return str(out) if out else "(empty)"
            if st in ("failed", "canceled"):
                raise RuntimeError(f"Prediction {st}: {p.get('error', '?')}")
            if elapsed % 10 == 0 and elapsed > 0:
                emit_log(f"Waiting for Replicate... ({elapsed}s)")
        raise RuntimeError("Replicate prediction timed out (>5 min)")


class CustomEndpointBackend:
    def __init__(self, url: str, key: str = ""):
        self.url = url
        self.key = key

    def transcribe(self, video_path: str) -> str:
        emit_log(f"Sending to custom endpoint: {self.url}...")
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        with open(video_path, 'rb') as f:
            r = requests.post(
                self.url,
                files={'video': (os.path.basename(video_path), f, 'video/mp4')},
                headers=headers,
                timeout=300)
        r.raise_for_status()
        d = r.json()
        return d.get('text', d.get('transcription', str(d)))


# ── SRT / TXT / JSON export ───────────────────────────────────────────────────
def _ts(s: float) -> str:
    h = int(s) // 3600
    m = (int(s) % 3600) // 60
    sec = s - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}".replace('.', ',')

def write_srt(results: list[dict], path: str):
    with open(path, 'w', encoding='utf-8') as f:
        for i, r in enumerate(results, 1):
            f.write(f"{i}\n{_ts(r['start'])} --> {_ts(r['end'])}\n{r['text']}\n\n")

def write_txt(results: list[dict], path: str):
    with open(path, 'w', encoding='utf-8') as f:
        for r in results:
            f.write(f"[{_ts(r['start'])} -> {_ts(r['end'])}] {r['text']}\n")

def write_json(results: list[dict], path: str):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'results': results}, f, indent=2)

FORMAT_WRITERS = {'srt': write_srt, 'txt': write_txt, 'json': write_json}


# ── Core transcription ────────────────────────────────────────────────────────
def run_transcription(video_path: str, output_path: str, backend,
                      no_segment: bool, threshold: float):
    segs: list[tuple[float, float]]
    if no_segment:
        cap = cv2.VideoCapture(video_path)
        dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 25.0)
        cap.release()
        segs = [(0.0, dur)]
    else:
        emit_progress(5, "Detecting speech segments")
        segs = segment_video(video_path, threshold)

    emit_log(f"Processing {len(segs)} segment(s)")
    results: list[dict] = []
    td = tempfile.mkdtemp(prefix='ucx_lipsight_')
    try:
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        for i, (s, e) in enumerate(segs):
            base_pct = 20 + i / len(segs) * 75
            emit_progress(base_pct, f"Segment {i + 1}/{len(segs)} [{s:.1f}s-{e:.1f}s]")
            emit_log(f"Segment {i + 1}/{len(segs)} [{s:.1f}s — {e:.1f}s]")

            clip = os.path.join(td, f"seg_{i:04d}.mp4")
            try:
                subprocess.run(
                    ['ffmpeg', '-y', '-i', video_path,
                     '-ss', str(s), '-t', str(e - s),
                     '-c:v', 'libx264', '-an', '-preset', 'ultrafast', clip],
                    capture_output=True, timeout=120)
            except Exception:
                # ffmpeg unavailable — fallback to OpenCV frame copy
                clip_cap = cv2.VideoCapture(video_path)
                writer = cv2.VideoWriter(clip, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
                clip_cap.set(cv2.CAP_PROP_POS_FRAMES, int(s * fps))
                for _ in range(int((e - s) * fps)):
                    ok, fr = clip_cap.read()
                    if not ok:
                        break
                    writer.write(fr)
                writer.release()
                clip_cap.release()

            if not os.path.exists(clip) or os.path.getsize(clip) == 0:
                emit_log(f"Segment {i + 1}: clip extraction failed — skipping", "warn")
                continue

            try:
                text = backend.transcribe(clip)
                r = {'start': s, 'end': e, 'text': text.strip(), 'segment': i + 1}
                results.append(r)
                emit({
                    "event": "segment",
                    "index": i + 1,
                    "start": round(s, 3),
                    "end": round(e, 3),
                    "text": text.strip(),
                })
                emit_log(f"Segment {i + 1}: {text.strip()[:80]}")
            except Exception as exc:
                emit_log(f"Segment {i + 1} failed: {exc}", "warn")

        emit_progress(95, "Writing output file")
        ext = os.path.splitext(output_path)[1].lower().lstrip('.')
        writer_fn = FORMAT_WRITERS.get(ext, write_srt)
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        writer_fn(results, output_path)

    finally:
        shutil.rmtree(td, ignore_errors=True)

    emit_log(f"Done — {len(results)} segment(s) transcribed")
    return results


# ── Argument parser ───────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="UCX LipSight sidecar")
    p.add_argument('--input', required=True, help='Input video path')
    p.add_argument('--output', required=True, help='Output transcript path (.srt/.txt/.json)')
    p.add_argument('--backend', choices=['hf', 'local', 'replicate', 'custom'], default='hf',
                   help='Inference backend (default: hf)')
    p.add_argument('--hf-url', default='', help='Custom HuggingFace Space URL')
    p.add_argument('--replicate-token', default='', help='Replicate API token')
    p.add_argument('--custom-url', default='', help='Custom endpoint URL')
    p.add_argument('--custom-key', default='', help='Custom endpoint bearer key')
    p.add_argument('--no-segment', action='store_true',
                   help='Skip speech segmentation, process full video as one unit')
    p.add_argument('--threshold', type=float, default=0.06,
                   help='Mouth-open ratio threshold for speech detection (default: 0.06)')
    p.add_argument('--model-dir', default=None,
                   help='Model cache directory (overrides UCX_MODEL_DIR env)')
    return p


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = build_parser()
    args = parser.parse_args()

    model_dir = args.model_dir or os.environ.get('UCX_MODEL_DIR')

    if not os.path.isfile(args.input):
        emit_error(f"Input file not found: {args.input}")
        sys.exit(1)

    backend_name = args.backend
    if backend_name == 'hf':
        backend = HuggingFaceSpaceBackend(args.hf_url)
    elif backend_name == 'local':
        backend = LocalAutoAVSRBackend(model_dir)
    elif backend_name == 'replicate':
        if not args.replicate_token:
            emit_error("--replicate-token required for replicate backend")
            sys.exit(1)
        backend = ReplicateBackend(args.replicate_token)
    else:  # custom
        if not args.custom_url:
            emit_error("--custom-url required for custom backend")
            sys.exit(1)
        backend = CustomEndpointBackend(args.custom_url, args.custom_key)

    emit_log(f"Backend: {backend_name} | Input: {os.path.basename(args.input)}")
    emit_progress(0, "Starting")

    try:
        run_transcription(
            args.input, args.output, backend,
            no_segment=args.no_segment,
            threshold=args.threshold)
        emit_progress(100, "Complete")
        emit_complete(args.output)
    except Exception as exc:
        emit_error(str(exc))
        sys.exit(1)


if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        import multiprocessing
        multiprocessing.freeze_support()
    main()
