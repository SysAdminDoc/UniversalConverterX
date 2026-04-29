#!/usr/bin/env python3
"""
LipSight v1.1 — AI Lip Reading Tool
Powered by Auto-AVSR (state-of-the-art visual speech recognition)
Supports: Local PyTorch inference (FREE), HuggingFace Spaces (FREE), Replicate API, Custom Endpoints
"""

import sys, os, subprocess, json, time, tempfile, threading, math, hashlib, random, shutil
from pathlib import Path
from datetime import timedelta


# codex-branding:start
def _branding_icon_path() -> Path:
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "icon.png")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "icon.png")
    current = Path(__file__).resolve()
    candidates.extend([current.parent / "icon.png", current.parent.parent / "icon.png", current.parent.parent.parent / "icon.png"])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path("icon.png")
# codex-branding:end


# ── Auto-Bootstrap ──────────────────────────────────────────────────────────
def _bootstrap():
    """Auto-install dependencies and configure prerequisites."""
    if sys.version_info < (3, 8):
        print("Python 3.8+ required"); sys.exit(1)

    required = ['PyQt6', 'opencv-python', 'requests', 'numpy']
    for pkg in required:
        mod = pkg.split('[')[0].replace('-', '_').lower()
        if mod == 'opencv_python': mod = 'cv2'
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
try:
    import mediapipe as _mp
    _HAS_MEDIAPIPE = True
except Exception:
    _HAS_MEDIAPIPE = False
    _mp = None
import requests
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *, QIcon

APP_NAME = "LipSight"
APP_VERSION = "1.1.0"

# ── Catppuccin Mocha ────────────────────────────────────────────────────────
C = {
    'base': '#1e1e2e', 'mantle': '#181825', 'crust': '#11111b',
    'surface0': '#313244', 'surface1': '#45475a', 'surface2': '#585b70',
    'overlay0': '#6c7086', 'overlay1': '#7f849c', 'text': '#cdd6f4',
    'subtext0': '#a6adc8', 'subtext1': '#bac2de',
    'blue': '#89b4fa', 'green': '#a6e3a1', 'red': '#f38ba8',
    'peach': '#fab387', 'yellow': '#f9e2af', 'mauve': '#cba6f7',
    'teal': '#94e2d5', 'sky': '#89dceb', 'lavender': '#b4befe',
    'flamingo': '#f2cdcd', 'rosewater': '#f5e0dc',
}

DARK_STYLE = f"""
QMainWindow, QWidget {{ background-color: {C['base']}; color: {C['text']}; }}
QMenuBar {{ background-color: {C['mantle']}; color: {C['text']}; }}
QPushButton {{
    background-color: {C['blue']}; color: {C['base']}; border: none;
    padding: 8px 18px; border-radius: 6px; font-weight: bold; font-size: 13px;
}}
QPushButton:hover {{ background-color: {C['sky']}; }}
QPushButton:pressed {{ background-color: {C['lavender']}; }}
QPushButton:disabled {{ background-color: {C['surface1']}; color: {C['overlay0']}; }}
QPushButton#dangerBtn {{ background-color: {C['red']}; }}
QPushButton#dangerBtn:hover {{ background-color: {C['flamingo']}; }}
QPushButton#secondaryBtn {{ background-color: {C['surface0']}; color: {C['text']}; }}
QPushButton#secondaryBtn:hover {{ background-color: {C['surface1']}; }}
QPushButton#accentBtn {{ background-color: {C['mauve']}; }}
QPushButton#accentBtn:hover {{ background-color: {C['lavender']}; }}
QPushButton#greenBtn {{ background-color: {C['green']}; color: {C['base']}; }}
QPushButton#greenBtn:hover {{ background-color: {C['teal']}; }}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {C['surface0']}; color: {C['text']};
    border: 1px solid {C['surface1']}; border-radius: 6px; padding: 8px;
    selection-background-color: {C['blue']}; selection-color: {C['base']}; font-size: 13px;
}}
QLineEdit:focus, QTextEdit:focus {{ border: 1px solid {C['blue']}; }}
QComboBox {{
    background-color: {C['surface0']}; color: {C['text']};
    border: 1px solid {C['surface1']}; border-radius: 6px; padding: 8px; font-size: 13px;
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background-color: {C['base']}; color: {C['text']};
    border: 1px solid {C['surface1']}; selection-background-color: {C['blue']};
}}
QLabel {{ color: {C['text']}; font-size: 13px; }}
QLabel#dimLabel {{ color: {C['overlay0']}; font-size: 12px; }}
QGroupBox {{
    border: 1px solid {C['surface1']}; border-radius: 10px;
    margin-top: 1.2em; padding: 16px 12px 12px 12px; color: {C['text']};
    font-weight: bold; font-size: 13px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 8px; color: {C['lavender']}; }}
QProgressBar {{
    background-color: {C['surface0']}; border: none; border-radius: 5px;
    text-align: center; color: {C['text']}; font-size: 12px; min-height: 10px;
}}
QProgressBar::chunk {{ background-color: {C['blue']}; border-radius: 5px; }}
QSlider::groove:horizontal {{ height: 6px; background: {C['surface0']}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: {C['blue']}; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px;
}}
QSlider::sub-page:horizontal {{ background: {C['blue']}; border-radius: 3px; }}
QScrollBar:vertical {{
    background: {C['mantle']}; width: 8px; border: none; border-radius: 4px;
}}
QScrollBar::handle:vertical {{ background: {C['surface1']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {C['surface2']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QTabWidget::pane {{ border: 1px solid {C['surface1']}; background: {C['base']}; border-radius: 8px; }}
QTabBar::tab {{
    background: {C['mantle']}; color: {C['overlay0']}; padding: 10px 20px;
    border: none; font-size: 13px; font-weight: bold;
}}
QTabBar::tab:selected {{ color: {C['text']}; border-bottom: 2px solid {C['blue']}; }}
QTabBar::tab:hover {{ color: {C['subtext1']}; }}
QTableWidget {{
    background-color: {C['base']}; alternate-background-color: {C['mantle']};
    color: {C['text']}; border: 1px solid {C['surface1']};
    gridline-color: {C['surface0']}; font-size: 13px; border-radius: 6px;
}}
QTableWidget::item:selected {{ background-color: {C['blue']}; color: {C['base']}; }}
QHeaderView::section {{
    background-color: {C['mantle']}; color: {C['subtext0']};
    border: none; border-bottom: 1px solid {C['surface1']}; padding: 8px;
    font-weight: bold; font-size: 12px;
}}
QStatusBar {{ background-color: {C['mantle']}; color: {C['overlay0']}; font-size: 12px; }}
QToolTip {{
    background-color: {C['surface0']}; color: {C['text']};
    border: 1px solid {C['surface1']}; padding: 6px; border-radius: 6px;
}}
QCheckBox {{ color: {C['text']}; spacing: 8px; }}
"""

# ── Config ──────────────────────────────────────────────────────────────────
def get_config_dir():
    base = os.environ.get('APPDATA', os.path.expanduser('~'))
    path = os.path.join(base, '.lipsight')
    os.makedirs(path, exist_ok=True)
    return path

def load_config():
    try:
        with open(os.path.join(get_config_dir(), 'config.json')) as f: return json.load(f)
    except: return {}

def save_config(cfg):
    with open(os.path.join(get_config_dir(), 'config.json'), 'w') as f: json.dump(cfg, f, indent=2)


# ── Face Detection ──────────────────────────────────────────────────────────
class FaceAnalyzer:
    """Face/mouth detection: MediaPipe preferred, OpenCV Haar cascade fallback."""

    MOUTH_OUTER = [61,146,91,181,84,17,314,405,321,375,291,409,270,269,267,0,37,39,40,185]
    MOUTH_INNER = [78,95,88,178,87,14,317,402,318,324,308,415,310,311,312,13,82,81,80,191]

    def __init__(self):
        self.face_mesh = None
        self._backend = 'none'
        self._cascade = None

        if _HAS_MEDIAPIPE:
            try:
                self.face_mesh = _mp.solutions.face_mesh.FaceMesh(
                    static_image_mode=False, max_num_faces=1,
                    refine_landmarks=True, min_detection_confidence=0.5, min_tracking_confidence=0.5)
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
    def available(self): return self._backend != 'none'
    @property
    def backend_name(self): return self._backend

    def analyze_frame(self, frame):
        if self._backend == 'mediapipe': return self._mp(frame)
        if self._backend == 'opencv': return self._cv(frame)
        return frame.copy(), None, 0.0, None

    def _mp(self, frame):
        h, w = frame.shape[:2]
        out = frame.copy()
        roi, ratio = None, 0.0
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = self.face_mesh.process(rgb)
            if res.multi_face_landmarks:
                lm = res.multi_face_landmarks[0]
                pts = [(int(lm.landmark[i].x*w), int(lm.landmark[i].y*h)) for i in self.MOUTH_OUTER]
                if pts:
                    arr = np.array(pts)
                    x1, y1 = arr.min(0) - 20; x2, y2 = arr.max(0) + 20
                    x1, y1, x2, y2 = max(0,x1), max(0,y1), min(w,x2), min(h,y2)
                    roi = (x1, y1, x2, y2)
                    cv2.rectangle(out, (x1,y1), (x2,y2), (137,180,250), 2)
                    for i in self.MOUTH_OUTER:
                        cv2.circle(out, (int(lm.landmark[i].x*w), int(lm.landmark[i].y*h)), 2, (166,227,161), -1)
                    for i in self.MOUTH_INNER:
                        cv2.circle(out, (int(lm.landmark[i].x*w), int(lm.landmark[i].y*h)), 2, (180,190,254), -1)
                    t, b = lm.landmark[13], lm.landmark[14]
                    l, r = lm.landmark[61], lm.landmark[291]
                    mh = math.sqrt((t.x-b.x)**2+(t.y-b.y)**2)
                    mw = math.sqrt((l.x-r.x)**2+(l.y-r.y)**2)
                    ratio = mh / max(mw, 0.001)
                    col = (166,227,161) if ratio > 0.06 else (108,112,134)
                    cv2.putText(out, "SPEAKING" if ratio>0.06 else "SILENT", (x1,y1-8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
        except: pass
        return out, roi, ratio, None

    def _cv(self, frame):
        h, w = frame.shape[:2]
        out = frame.copy()
        roi, ratio = None, 0.0
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self._cascade.detectMultiScale(gray, 1.1, 5, minSize=(80,80))
            if len(faces) > 0:
                fx,fy,fw,fh = faces[0]
                cv2.rectangle(out, (fx,fy), (fx+fw,fy+fh), (69,71,90), 1)
                mx1, my1 = max(0,fx+int(fw*0.2)), max(0,fy+int(fh*0.65))
                mx2, my2 = min(w,fx+int(fw*0.8)), min(h,fy+fh+5)
                roi = (mx1, my1, mx2, my2)
                cv2.rectangle(out, (mx1,my1), (mx2,my2), (137,180,250), 2)
                mg = gray[my1:my2, mx1:mx2]
                if mg.size > 0:
                    gx = cv2.Sobel(mg, cv2.CV_64F, 1, 0, ksize=3)
                    gy = cv2.Sobel(mg, cv2.CV_64F, 0, 1, ksize=3)
                    ratio = min(np.mean(np.sqrt(gx**2+gy**2)) / 50.0, 0.3)
                cv2.putText(out, "DETECTED", (mx1,my1-8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (137,180,250), 1, cv2.LINE_AA)
        except: pass
        return out, roi, ratio, None

    def close(self):
        if self.face_mesh:
            try: self.face_mesh.close()
            except: pass


# ── Video Segmenter ─────────────────────────────────────────────────────────
class VideoSegmenter:
    def __init__(self, threshold=0.06):
        self.threshold = threshold

    def segment(self, video_path, progress_cb=None, log_cb=None):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened(): raise RuntimeError(f"Cannot open: {video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        analyzer = FaceAnalyzer()
        if not analyzer.available:
            cap.release()
            if log_cb: log_cb("⚠️  No face detection — whole video as one segment")
            return [(0.0, total/fps)]

        if log_cb: log_cb(f"📐 Analyzing {total} frames ({analyzer.backend_name})...")
        ratios = []; idx = 0; step = max(1, int(fps/10))
        while True:
            ret, frame = cap.read()
            if not ret: break
            if idx % step == 0:
                _, _, r, _ = analyzer.analyze_frame(frame)
                ratios.append((idx, r))
            idx += 1
            if progress_cb and idx % 50 == 0: progress_cb(int(idx/max(total,1)*100))
        cap.release(); analyzer.close()
        if not ratios: return [(0.0, total/fps)]

        ms, ml = int(0.5*25), int(0.3*25)
        segs, speech, start, sil = [], False, 0, 0
        for fn, r in ratios:
            if r > self.threshold:
                if not speech: start = fn; speech = True
                sil = 0
            elif speech:
                sil += step
                if sil >= ml:
                    end = fn - sil
                    if (end-start) >= ms: segs.append((start/fps, end/fps))
                    speech = False; sil = 0
        if speech:
            end = ratios[-1][0]
            if (end-start) >= ms: segs.append((start/fps, end/fps))
        if log_cb: log_cb(f"🔍 Found {len(segs)} speech segments")
        return segs if segs else [(0.0, total/fps)]


# ══════════════════════════════════════════════════════════════════════════════
# INFERENCE BACKENDS
# ══════════════════════════════════════════════════════════════════════════════

class HuggingFaceSpaceBackend:
    """FREE inference via public HuggingFace Gradio Spaces — no token, no signup."""

    KNOWN_SPACES = [
        "https://mpc001-auto-avsr.hf.space",
        "https://vumichien-av-hubert.hf.space",
    ]

    def __init__(self, custom_url=""):
        self.custom_url = custom_url.strip().rstrip('/')

    def transcribe(self, video_path, log_cb=None):
        spaces = []
        if self.custom_url: spaces.append(self.custom_url)
        spaces.extend(self.KNOWN_SPACES)
        last_err = None

        for base in spaces:
            name = base.split("//")[1].split(".")[0] if "//" in base else base
            try:
                if log_cb: log_cb(f"🤗 Trying Space: {name}...")

                # Check reachability
                try:
                    requests.get(base, timeout=15)
                except requests.exceptions.ConnectionError:
                    if log_cb: log_cb(f"   ❌ Unreachable"); continue

                # Upload file
                if log_cb: log_cb(f"   📤 Uploading video...")
                with open(video_path, 'rb') as f:
                    up = requests.post(f"{base}/upload",
                        files={"files": (os.path.basename(video_path), f, "video/mp4")}, timeout=120)
                up.raise_for_status()
                uploaded = up.json()
                fpath = uploaded[0] if isinstance(uploaded, list) else uploaded

                # Predict (try multiple Gradio API versions)
                if log_cb: log_cb(f"   🧠 Running inference (may take 30-120s)...")
                session = hashlib.md5(str(random.random()).encode()).hexdigest()[:12]

                for api_path in ["/api/predict", "/run/predict"]:
                    for payload in [
                        {"data": [{"path": fpath, "orig_name": os.path.basename(video_path)}], "session_hash": session},
                        {"data": [fpath], "session_hash": session},
                    ]:
                        try:
                            r = requests.post(f"{base}{api_path}", json=payload, timeout=300)
                            if r.status_code in (404, 422): continue
                            r.raise_for_status()
                            data = r.json().get("data", [])
                            if data and data[0]:
                                if log_cb: log_cb(f"   ✅ Got result")
                                return str(data[0]).strip()
                        except (requests.exceptions.HTTPError, requests.exceptions.Timeout):
                            continue

                if log_cb: log_cb(f"   ⚠️  No valid response")
            except Exception as e:
                last_err = str(e)
                if log_cb: log_cb(f"   ❌ {e}")

        raise RuntimeError(
            f"All HuggingFace Spaces unavailable.\n"
            f"Last error: {last_err}\n\n"
            f"Options: Try again later, use Local backend, or set a custom Space URL.")


class LocalAutoAVSRBackend:
    """FREE local inference — auto-downloads PyTorch + Auto-AVSR."""

    MODEL_DIR = os.path.join(get_config_dir(), 'models', 'auto_avsr')
    REPO_URL = "https://github.com/mpc001/auto_avsr.git"

    def __init__(self):
        self._ready = False

    def _pip(self, pkgs, log_cb=None):
        for pkg in pkgs:
            mod = pkg.split('[')[0].split('=')[0].split('>')[0].split('<')[0].replace('-','_').lower()
            if mod == 'opencv_python': mod = 'cv2'
            try: __import__(mod); continue
            except ImportError: pass
            if log_cb: log_cb(f"   📦 Installing {pkg}...")
            for fl in [[], ['--user'], ['--break-system-packages']]:
                try:
                    subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'] + fl, timeout=600)
                    break
                except: continue

    def _ensure_setup(self, log_cb=None):
        if self._ready: return
        if log_cb: log_cb("🔧 Setting up local Auto-AVSR...")

        # PyTorch
        try:
            import torch
            if log_cb: log_cb(f"   ✅ PyTorch {torch.__version__} (CUDA: {torch.cuda.is_available()})")
        except ImportError:
            if log_cb: log_cb("   📦 Installing PyTorch (may take several minutes)...")
            for cmd in [
                [sys.executable, '-m', 'pip', 'install', 'torch', 'torchvision', 'torchaudio', '--index-url', 'https://download.pytorch.org/whl/cu121', '-q'],
                [sys.executable, '-m', 'pip', 'install', 'torch', 'torchvision', 'torchaudio', '-q'],
            ]:
                try: subprocess.check_call(cmd, timeout=900); break
                except: continue
            import torch
            if log_cb: log_cb(f"   ✅ PyTorch {torch.__version__}")

        self._pip(['sentencepiece', 'pytorch-lightning', 'hydra-core', 'omegaconf'], log_cb)

        # Clone repo
        os.makedirs(self.MODEL_DIR, exist_ok=True)
        repo = os.path.join(self.MODEL_DIR, 'repo')
        if not os.path.isdir(repo):
            if log_cb: log_cb("   📥 Cloning Auto-AVSR repository...")
            try:
                subprocess.check_call(['git', 'clone', '--depth', '1', self.REPO_URL, repo], timeout=120)
            except FileNotFoundError:
                raise RuntimeError("Git not installed. Install from https://git-scm.com/download/win")
            except Exception as e:
                raise RuntimeError(f"Clone failed: {e}")

        # Install package
        if log_cb: log_cb("   📦 Installing Auto-AVSR package...")
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-e', repo, '-q'], timeout=300)
        except:
            if repo not in sys.path: sys.path.insert(0, repo)

        self._ready = True
        if log_cb: log_cb("   ✅ Local setup complete")

    def transcribe(self, video_path, log_cb=None):
        self._ensure_setup(log_cb)
        import torch

        repo = os.path.join(self.MODEL_DIR, 'repo')
        if repo not in sys.path: sys.path.insert(0, repo)

        if log_cb: log_cb("🧠 Running local inference...")

        # Try CLI inference
        for script in ['infer.py', 'eval.py', 'predict.py', 'demo.py']:
            sp = os.path.join(repo, script)
            if os.path.exists(sp):
                try:
                    result = subprocess.run(
                        [sys.executable, sp, '--video_path', video_path, '--modality', 'video'],
                        capture_output=True, text=True, timeout=300, cwd=repo)
                    if result.returncode == 0:
                        lines = result.stdout.strip().split('\n')
                        for line in reversed(lines):
                            l = line.strip()
                            if l and not l.startswith(('[','=','W','I','D')): return l
                        return result.stdout.strip()
                    else:
                        err = result.stderr.strip() or result.stdout.strip()
                        if log_cb: log_cb(f"   ⚠️  {script} error: {err[:200]}")
                except subprocess.TimeoutExpired:
                    raise RuntimeError("Inference timed out (>5min)")
                except Exception as e:
                    if log_cb: log_cb(f"   ⚠️  {script}: {e}")

        raise RuntimeError(
            f"Could not run inference. The Auto-AVSR repo may require additional setup.\n\n"
            f"Manual steps:\n  cd {repo}\n  python infer.py --video_path \"{video_path}\" --modality video")


class ReplicateBackend:
    """Cloud inference via Replicate API — requires token."""

    API = "https://api.replicate.com/v1"
    MODEL = "basord/lip-reading-ai-vsr"

    def __init__(self, token):
        self.token = token
        self.h = {"Authorization": f"Token {token}", "Content-Type": "application/json"}

    def transcribe(self, video_path, log_cb=None):
        if log_cb: log_cb("☁️  Uploading to Replicate...")
        try:
            # Upload
            with open(video_path, 'rb') as f:
                r = requests.post(f"{self.API}/files", headers={"Authorization": f"Token {self.token}"},
                    files={"content": (os.path.basename(video_path), f, "video/mp4")},
                    data={"content_type": "video/mp4"}, timeout=120)
            r.raise_for_status()
            url = r.json().get("urls", {}).get("get", "") or r.json().get("url", "")
            if not url: raise RuntimeError("No upload URL returned")

            # Version
            r = requests.get(f"{self.API}/models/{self.MODEL}/versions", headers=self.h, timeout=30)
            r.raise_for_status()
            ver = r.json()["results"][0]["id"]

            # Predict
            if log_cb: log_cb("☁️  Running prediction...")
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
                    if isinstance(out, dict): return out.get("text", str(out))
                    if isinstance(out, list): return " ".join(str(o) for o in out)
                    return str(out) if out else "(empty)"
                if st in ("failed", "canceled"):
                    raise RuntimeError(f"Prediction {st}: {p.get('error','?')}")
                if log_cb and elapsed % 10 == 0 and elapsed > 0:
                    log_cb(f"☁️  Waiting... ({elapsed}s)")
            raise RuntimeError("Timed out")
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"Replicate HTTP {e.response.status_code}: {e.response.text[:200]}")


class DirectAPIBackend:
    def __init__(self, url, key=""):
        self.url = url; self.key = key
    def transcribe(self, video_path, log_cb=None):
        if log_cb: log_cb(f"🌐 Sending to {self.url}...")
        h = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        with open(video_path, 'rb') as f:
            r = requests.post(self.url, files={'video': (os.path.basename(video_path), f, 'video/mp4')},
                headers=h, timeout=300)
        r.raise_for_status()
        d = r.json()
        return d.get('text', d.get('transcription', str(d)))


# ── Export ──────────────────────────────────────────────────────────────────
def _ts(s):
    h=int(s)//3600; m=(int(s)%3600)//60; sec=s-h*3600-m*60
    return f"{h:02d}:{m:02d}:{sec:06.3f}".replace('.',',')

def export_srt(res, fp):
    with open(fp,'w',encoding='utf-8') as f:
        for i,r in enumerate(res,1): f.write(f"{i}\n{_ts(r['start'])} --> {_ts(r['end'])}\n{r['text']}\n\n")

def export_txt(res, fp):
    with open(fp,'w',encoding='utf-8') as f:
        for r in res: f.write(f"[{_ts(r['start'])} -> {_ts(r['end'])}] {r['text']}\n")

def export_json(res, fp):
    with open(fp,'w',encoding='utf-8') as f: json.dump({'results':res,'version':APP_VERSION},f,indent=2)


# ── Workers ─────────────────────────────────────────────────────────────────
class ProcessingWorker(QThread):
    progress = pyqtSignal(int); log = pyqtSignal(str)
    segment_result = pyqtSignal(dict); finished = pyqtSignal(list); error = pyqtSignal(str)

    def __init__(self, vpath, backend, segs=None):
        super().__init__()
        self.vpath, self.backend, self.segs = vpath, backend, segs
        self._stop = False

    def cancel(self): self._stop = True

    def run(self):
        try:
            results = []
            if self.segs and len(self.segs) > 1:
                td = tempfile.mkdtemp(prefix='lipsight_')
                cap = cv2.VideoCapture(self.vpath)
                fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release()

                for i,(s,e) in enumerate(self.segs):
                    if self._stop: break
                    self.log.emit(f"🎬 Segment {i+1}/{len(self.segs)} [{s:.1f}s-{e:.1f}s]")
                    sp = os.path.join(td, f"seg_{i:04d}.mp4")
                    try:
                        subprocess.run(['ffmpeg','-y','-i',self.vpath,'-ss',str(s),'-t',str(e-s),
                            '-c:v','libx264','-an','-preset','ultrafast',sp], capture_output=True, timeout=60)
                    except:
                        cap2 = cv2.VideoCapture(self.vpath)
                        wr = cv2.VideoWriter(sp, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w,h))
                        cap2.set(cv2.CAP_PROP_POS_FRAMES, int(s*fps))
                        for _ in range(int((e-s)*fps)):
                            ok,fr = cap2.read()
                            if not ok: break
                            wr.write(fr)
                        wr.release(); cap2.release()

                    if os.path.exists(sp) and os.path.getsize(sp) > 0:
                        try:
                            txt = self.backend.transcribe(sp, log_cb=self.log.emit)
                            r = {'start':s,'end':e,'text':txt.strip(),'segment':i+1}
                            results.append(r); self.segment_result.emit(r)
                        except Exception as ex:
                            self.log.emit(f"⚠️  Segment {i+1}: {ex}")
                    self.progress.emit(int((i+1)/len(self.segs)*100))
                shutil.rmtree(td, ignore_errors=True)
            else:
                self.log.emit("🎬 Processing entire video...")
                self.progress.emit(10)
                txt = self.backend.transcribe(self.vpath, log_cb=self.log.emit)
                cap = cv2.VideoCapture(self.vpath)
                dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 25.0)
                cap.release()
                r = {'start':0.0,'end':dur,'text':txt.strip(),'segment':1}
                results.append(r); self.segment_result.emit(r); self.progress.emit(100)

            self.log.emit(f"✅ Complete — {len(results)} segment(s)")
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class SegmentWorker(QThread):
    progress = pyqtSignal(int); log = pyqtSignal(str)
    finished = pyqtSignal(list); error = pyqtSignal(str)
    def __init__(self, vp): super().__init__(); self.vp = vp
    def run(self):
        try: self.finished.emit(VideoSegmenter().segment(self.vp, self.progress.emit, self.log.emit))
        except Exception as e: self.error.emit(str(e))


class FrameWorker(QThread):
    frame_ready = pyqtSignal(QImage, float, dict); finished = pyqtSignal()
    def __init__(self, vp, n): super().__init__(); self.vp, self.n = vp, n
    def run(self):
        try:
            cap = cv2.VideoCapture(self.vp)
            if not cap.isOpened(): self.finished.emit(); return
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            cap.set(cv2.CAP_PROP_POS_FRAMES, self.n)
            ok, frame = cap.read(); cap.release()
            if not ok or frame is None: self.finished.emit(); return
            try:
                a = FaceAnalyzer()
                out, roi, ratio, _ = a.analyze_frame(frame) if a.available else (frame, None, 0.0, None)
                a.close()
            except: out, roi, ratio = frame, None, 0.0
            rgb = np.ascontiguousarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
            h, w, ch = rgb.shape
            img = QImage(rgb.data, w, h, ch*w, QImage.Format.Format_RGB888).copy()
            self.frame_ready.emit(img, self.n/fps, {'open_ratio': ratio})
        except: pass
        self.finished.emit()


# ── Widgets ─────────────────────────────────────────────────────────────────
class VideoPreview(QLabel):
    def __init__(self):
        super().__init__(); self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(480,270)
        self.setStyleSheet(f"background-color:{C['crust']};border:1px solid {C['surface1']};border-radius:8px;color:{C['overlay0']};font-size:16px;")
        self._pm = None; self.setText("📹  Load a video to begin")
    def set_frame(self, img):
        self._pm = QPixmap.fromImage(img); self._upd()
    def _upd(self):
        if self._pm: self.setPixmap(self._pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    def resizeEvent(self, e): super().resizeEvent(e); self._upd()

class Toast(QLabel):
    def __init__(self, p, msg, col=C['green'], ms=2500):
        super().__init__(msg, p)
        self.setStyleSheet(f"background-color:{C['surface0']};color:{col};border:1px solid {col};border-radius:8px;padding:10px 20px;font-size:13px;font-weight:bold;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter); self.adjustSize()
        self.move(p.width()//2-self.width()//2, 20); self.show(); self.raise_()
        QTimer.singleShot(ms, self.deleteLater)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════════════
BACKENDS = ["🤗 HuggingFace Space (Free)", "💻 Local Auto-AVSR (Free)", "☁️ Replicate API (Token)", "🌐 Custom Endpoint"]

class LipSightWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}"); self.resize(1300,840); self.setMinimumSize(1000,650)
        self.cfg = load_config()
        self.video_path = None; self.video_info = {}; self.segments = []; self.results = []
        self._fw = self._sw = self._pw = None
        self._build(); self._connect()
        fa = FaceAnalyzer()
        self._log(f"✅ Face detection: {fa.backend_name}" if fa.available else "⚠️  No face detection — segmentation disabled")
        fa.close()
        self._log(f"🔧 Backend: {BACKENDS[self.cfg.get('backend_index', 0)]}")

    def _build(self):
        cw = QWidget(); self.setCentralWidget(cw)
        root = QVBoxLayout(cw); root.setSpacing(0); root.setContentsMargins(0,0,0,0)

        # Header
        hdr = QWidget(); hdr.setFixedHeight(56)
        hdr.setStyleSheet(f"background-color:{C['mantle']};border-bottom:1px solid {C['surface0']};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(16,0,16,0)
        lg = QLabel(f"👁️  {APP_NAME}"); lg.setStyleSheet(f"font-size:18px;font-weight:bold;color:{C['blue']};background:transparent;border:none;")
        hl.addWidget(lg)
        vl = QLabel(f"v{APP_VERSION}"); vl.setStyleSheet(f"font-size:11px;color:{C['overlay0']};background:transparent;border:none;")
        hl.addWidget(vl); hl.addStretch()
        self.badge = QLabel(BACKENDS[self.cfg.get('backend_index',0)])
        self.badge.setStyleSheet(f"background-color:{C['surface0']};color:{C['teal']};padding:4px 12px;border-radius:12px;font-size:12px;font-weight:bold;")
        hl.addWidget(self.badge); root.addWidget(hdr)

        body = QWidget(); bl = QHBoxLayout(body); bl.setContentsMargins(12,12,12,0); bl.setSpacing(12)

        # Left
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(8)
        self.preview = VideoPreview(); ll.addWidget(self.preview, stretch=1)

        sr = QHBoxLayout()
        self.t_lbl = QLabel("00:00.000"); self.t_lbl.setStyleSheet(f"color:{C['overlay1']};font-family:monospace;font-size:12px;")
        sr.addWidget(self.t_lbl)
        self.slider = QSlider(Qt.Orientation.Horizontal); self.slider.setMinimum(0); self.slider.setMaximum(0)
        sr.addWidget(self.slider, stretch=1)
        self.d_lbl = QLabel("00:00.000"); self.d_lbl.setStyleSheet(f"color:{C['overlay1']};font-family:monospace;font-size:12px;")
        sr.addWidget(self.d_lbl); ll.addLayout(sr)

        br = QHBoxLayout(); br.setSpacing(8)
        self.b_load = QPushButton("📂  Load Video"); br.addWidget(self.b_load)
        self.b_analyze = QPushButton("🔍  Analyze"); self.b_analyze.setObjectName("accentBtn"); self.b_analyze.setEnabled(False); br.addWidget(self.b_analyze)
        self.b_process = QPushButton("🧠  Lip Read"); self.b_process.setObjectName("greenBtn"); self.b_process.setEnabled(False); br.addWidget(self.b_process)
        self.b_cancel = QPushButton("⏹"); self.b_cancel.setObjectName("dangerBtn"); self.b_cancel.setEnabled(False); self.b_cancel.setFixedWidth(50); br.addWidget(self.b_cancel)
        ll.addLayout(br)

        self.prog = QProgressBar(); self.prog.setFixedHeight(6); self.prog.setTextVisible(False); ll.addWidget(self.prog)

        sts = QHBoxLayout(); sts.setSpacing(16)
        self.sf = self._mk("FRAMES"); self.sfps = self._mk("FPS"); self.sres = self._mk("RES"); self.sseg = self._mk("SEGS"); self.smo = self._mk("MOUTH")
        for s in [self.sf,self.sfps,self.sres,self.sseg,self.smo]: sts.addWidget(s)
        sts.addStretch(); ll.addLayout(sts)
        bl.addWidget(left, stretch=6)

        # Right tabs
        tabs = QTabWidget(); tabs.setMinimumWidth(380)

        # Results
        rw = QWidget(); rl = QVBoxLayout(rw); rl.setContentsMargins(8,8,8,8)
        self.tbl = QTableWidget(); self.tbl.setColumnCount(3)
        self.tbl.setHorizontalHeaderLabels(["Time","Dur","Transcription"])
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl.setAlternatingRowColors(True); self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.tbl.verticalHeader().setVisible(False)
        rl.addWidget(self.tbl)
        self.txte = QTextEdit(); self.txte.setReadOnly(True); self.txte.setMaximumHeight(120)
        self.txte.setPlaceholderText("Full transcript..."); rl.addWidget(self.txte)
        er = QHBoxLayout()
        self.bsrt=QPushButton("💾 SRT"); self.bsrt.setObjectName("secondaryBtn"); self.bsrt.setEnabled(False)
        self.btxt=QPushButton("📄 TXT"); self.btxt.setObjectName("secondaryBtn"); self.btxt.setEnabled(False)
        self.bjsn=QPushButton("{ } JSON"); self.bjsn.setObjectName("secondaryBtn"); self.bjsn.setEnabled(False)
        self.bcpy=QPushButton("📋 Copy"); self.bcpy.setObjectName("secondaryBtn"); self.bcpy.setEnabled(False)
        for b in [self.bsrt,self.btxt,self.bjsn,self.bcpy]: er.addWidget(b)
        rl.addLayout(er); tabs.addTab(rw, "📝 Results")

        # Log
        lw = QWidget(); ll2 = QVBoxLayout(lw); ll2.setContentsMargins(8,8,8,8)
        self.logw = QPlainTextEdit(); self.logw.setReadOnly(True)
        self.logw.setStyleSheet(f"font-family:'Consolas','Cascadia Code',monospace;font-size:12px;background-color:{C['crust']};")
        ll2.addWidget(self.logw); tabs.addTab(lw, "📋 Log")

        # Settings
        sw = QWidget(); sl = QVBoxLayout(sw); sl.setContentsMargins(12,12,12,12); sl.setSpacing(10)

        bg = QGroupBox("Inference Backend"); bgl = QVBoxLayout(bg)
        self.be_combo = QComboBox(); self.be_combo.addItems(BACKENDS)
        self.be_combo.setCurrentIndex(self.cfg.get('backend_index',0))
        self.be_combo.currentIndexChanged.connect(self._on_be)
        bgl.addWidget(self.be_combo); sl.addWidget(bg)

        self.stack = QStackedWidget()

        # P0: HF
        p0 = QWidget(); p0l = QVBoxLayout(p0); p0l.setContentsMargins(0,4,0,0)
        h0 = QLabel("🤗 Free — no signup. Connects to public Gradio Spaces.\nSpaces may sleep; wake-up takes 30-60s.")
        h0.setObjectName("dimLabel"); h0.setWordWrap(True); p0l.addWidget(h0)
        p0l.addWidget(QLabel("Custom Space URL (optional):"))
        self.hf_url = QLineEdit(); self.hf_url.setPlaceholderText("https://user-space.hf.space")
        self.hf_url.setText(self.cfg.get('hf_space_url','')); p0l.addWidget(self.hf_url); p0l.addStretch()
        self.stack.addWidget(p0)

        # P1: Local
        p1 = QWidget(); p1l = QVBoxLayout(p1); p1l.setContentsMargins(0,4,0,0)
        h1 = QLabel("💻 Free & offline. Auto-downloads PyTorch + model (~4GB).\nGPU recommended. First run takes several minutes.")
        h1.setObjectName("dimLabel"); h1.setWordWrap(True); p1l.addWidget(h1)
        self.b_dl = QPushButton("📥  Pre-Download Model"); self.b_dl.setObjectName("accentBtn")
        self.b_dl.clicked.connect(self._pre_dl); p1l.addWidget(self.b_dl); p1l.addStretch()
        self.stack.addWidget(p1)

        # P2: Replicate
        p2 = QWidget(); p2l = QVBoxLayout(p2); p2l.setContentsMargins(0,4,0,0)
        p2l.addWidget(QLabel("API Token:"))
        self.rep_tok = QLineEdit(); self.rep_tok.setPlaceholderText("r8_xxx"); self.rep_tok.setEchoMode(QLineEdit.EchoMode.Password)
        self.rep_tok.setText(self.cfg.get('replicate_api_token','')); p2l.addWidget(self.rep_tok)
        rh = QLabel("Get token at replicate.com/account/api-tokens"); rh.setObjectName("dimLabel"); p2l.addWidget(rh); p2l.addStretch()
        self.stack.addWidget(p2)

        # P3: Custom
        p3 = QWidget(); p3l = QVBoxLayout(p3); p3l.setContentsMargins(0,4,0,0)
        p3l.addWidget(QLabel("URL:")); self.ep_url = QLineEdit(); self.ep_url.setPlaceholderText("https://..."); self.ep_url.setText(self.cfg.get('custom_endpoint','')); p3l.addWidget(self.ep_url)
        p3l.addWidget(QLabel("Key:")); self.ep_key = QLineEdit(); self.ep_key.setEchoMode(QLineEdit.EchoMode.Password); self.ep_key.setText(self.cfg.get('custom_endpoint_key','')); p3l.addWidget(self.ep_key); p3l.addStretch()
        self.stack.addWidget(p3)

        sl.addWidget(self.stack); self.stack.setCurrentIndex(self.cfg.get('backend_index',0))

        sg = QGroupBox("Segmentation"); sgl = QVBoxLayout(sg)
        self.chk_seg = QCheckBox("Auto-segment by mouth movement"); self.chk_seg.setChecked(self.cfg.get('auto_segment',True)); sgl.addWidget(self.chk_seg)
        sl.addWidget(sg)

        self.b_save = QPushButton("💾  Save Settings"); sl.addWidget(self.b_save); sl.addStretch()
        tabs.addTab(sw, "⚙️ Settings")
        bl.addWidget(tabs, stretch=4); root.addWidget(body, stretch=1)
        self.statusBar().showMessage("Ready — load a video to begin")

    def _mk(self, lbl):
        w = QWidget(); w.setFixedWidth(80); l = QVBoxLayout(w); l.setContentsMargins(0,0,0,0); l.setSpacing(0)
        v = QLabel("—"); v.setAlignment(Qt.AlignmentFlag.AlignCenter); v.setStyleSheet(f"font-size:15px;font-weight:bold;color:{C['blue']};"); l.addWidget(v)
        b = QLabel(lbl); b.setAlignment(Qt.AlignmentFlag.AlignCenter); b.setStyleSheet(f"font-size:10px;color:{C['overlay1']};"); l.addWidget(b)
        w._v = v; return w

    def _sv(self, w, val): w._v.setText(str(val))

    def _connect(self):
        self.b_load.clicked.connect(self._load); self.b_analyze.clicked.connect(self._analyze)
        self.b_process.clicked.connect(self._process); self.b_cancel.clicked.connect(self._cancel)
        self.b_save.clicked.connect(self._save); self.slider.valueChanged.connect(self._scrub)
        self.bsrt.clicked.connect(lambda: self._export('srt')); self.btxt.clicked.connect(lambda: self._export('txt'))
        self.bjsn.clicked.connect(lambda: self._export('json')); self.bcpy.clicked.connect(self._copy)

    def _on_be(self, i): self.stack.setCurrentIndex(i); self.badge.setText(BACKENDS[i])

    def _load(self):
        p, _ = QFileDialog.getOpenFileName(self, "Select Video", "", "Video (*.mp4 *.mov *.avi *.mkv *.webm);;All (*)")
        if not p: return
        try:
            self.video_path = p; self.results = []; self.segments = []; self.tbl.setRowCount(0); self.txte.clear(); self._exp(False)
            cap = cv2.VideoCapture(p)
            if not cap.isOpened(): self._log("❌ Can't open"); return
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0; frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)); dur = frames/fps; cap.release()
            self.video_info = {'fps':fps,'frames':frames,'w':w,'h':h,'dur':dur}
            self.slider.setMaximum(max(0,frames-1)); self.slider.setValue(0); self.d_lbl.setText(self._ft(dur))
            self._sv(self.sf,f"{frames:,}"); self._sv(self.sfps,f"{fps:.1f}"); self._sv(self.sres,f"{w}x{h}"); self._sv(self.sseg,"—"); self._sv(self.smo,"—")
            self.b_analyze.setEnabled(True); self.b_process.setEnabled(True)
            self.statusBar().showMessage(f"Loaded: {os.path.basename(p)}")
            self._log(f"📂 {os.path.basename(p)} — {w}x{h} @ {fps:.1f}fps — {frames:,} frames — {self._ft(dur)}")
            self._lf(0)
        except Exception as e: self._log(f"❌ {e}")

    def _lf(self, n):
        if not self.video_path: return
        if self._fw and self._fw.isRunning(): return
        self._fw = FrameWorker(self.video_path, n)
        self._fw.frame_ready.connect(self._of); self._fw.start()

    def _of(self, img, ts, info):
        self.preview.set_frame(img); self.t_lbl.setText(self._ft(ts))
        self._sv(self.smo, f"{info.get('open_ratio',0):.2f}")

    def _scrub(self, v): self._lf(v)

    def _analyze(self):
        if not self.video_path: return
        self.b_analyze.setEnabled(False); self.b_process.setEnabled(False); self.prog.setValue(0)
        self._log("🔍 Analyzing..."); self._sw = SegmentWorker(self.video_path)
        self._sw.progress.connect(self.prog.setValue); self._sw.log.connect(self._log)
        self._sw.finished.connect(self._os)
        self._sw.error.connect(lambda m: (self._log(f"❌ {m}"), self.b_analyze.setEnabled(True), self.b_process.setEnabled(True)))
        self._sw.start()

    def _os(self, segs):
        self.segments = segs; self._sv(self.sseg, len(segs))
        self.b_analyze.setEnabled(True); self.b_process.setEnabled(True); self.prog.setValue(100)
        for i,(s,e) in enumerate(segs): self._log(f"   [{i+1}] {self._ft(s)} → {self._ft(e)} ({e-s:.1f}s)")
        Toast(self, f"  ✅  {len(segs)} segments  ", C['green'])

    def _process(self):
        if not self.video_path: return
        be = self._get_be()
        if not be: return
        self.b_process.setEnabled(False); self.b_analyze.setEnabled(False); self.b_cancel.setEnabled(True)
        self.prog.setValue(0); self.results=[]; self.tbl.setRowCount(0); self.txte.clear(); self._exp(False)
        segs = self.segments if (self.chk_seg.isChecked() and len(self.segments)>1) else None
        self._log(f"🧠 Lip reading via {BACKENDS[self.be_combo.currentIndex()]}...")
        self._pw = ProcessingWorker(self.video_path, be, segs)
        self._pw.progress.connect(self.prog.setValue); self._pw.log.connect(self._log)
        self._pw.segment_result.connect(self._or); self._pw.finished.connect(self._od)
        self._pw.error.connect(self._oe); self._pw.start()

    def _cancel(self):
        if self._pw: self._pw.cancel(); self._log("⏹ Cancelling...")
        self.b_cancel.setEnabled(False)

    def _get_be(self):
        i = self.be_combo.currentIndex()
        if i == 0: return HuggingFaceSpaceBackend(self.hf_url.text().strip())
        if i == 1: return LocalAutoAVSRBackend()
        if i == 2:
            t = self.rep_tok.text().strip()
            if not t: Toast(self,"  ⚠️  Set token in Settings  ",C['peach']); return None
            return ReplicateBackend(t)
        u = self.ep_url.text().strip()
        if not u: Toast(self,"  ⚠️  Set URL in Settings  ",C['peach']); return None
        return DirectAPIBackend(u, self.ep_key.text().strip())

    def _or(self, r):
        row = self.tbl.rowCount(); self.tbl.insertRow(row)
        self.tbl.setItem(row,0,QTableWidgetItem(f"{self._ft(r['start'])} → {self._ft(r['end'])}"))
        self.tbl.setItem(row,1,QTableWidgetItem(f"{r['end']-r['start']:.1f}s"))
        self.tbl.setItem(row,2,QTableWidgetItem(r['text'])); self.tbl.scrollToBottom()

    def _od(self, res):
        self.results = res; self.b_process.setEnabled(True); self.b_analyze.setEnabled(True); self.b_cancel.setEnabled(False); self._exp(True)
        full = ' '.join(r['text'] for r in res if r['text']); self.txte.setPlainText(full)
        self.statusBar().showMessage(f"Done — {len(res)} seg(s), {len(full.split())} words")
        Toast(self, f"  ✅  {len(res)} segments transcribed  ", C['green'])

    def _oe(self, msg):
        self._log(f"❌ {msg}"); self.b_process.setEnabled(True); self.b_analyze.setEnabled(True); self.b_cancel.setEnabled(False)
        Toast(self, f"  ❌  {msg[:80]}  ", C['red'])

    def _export(self, fmt):
        if not self.results: return
        base = Path(self.video_path).stem if self.video_path else "lipsight"
        p, _ = QFileDialog.getSaveFileName(self, f"Export", f"{base}_lipsight.{fmt}",
            {"srt":"SRT (*.srt)","txt":"Text (*.txt)","json":"JSON (*.json)"}.get(fmt,"*"))
        if not p: return
        try:
            {'srt':export_srt,'txt':export_txt,'json':export_json}[fmt](self.results, p)
            self._log(f"💾 {p}"); Toast(self, "  💾  Exported  ", C['green'])
        except Exception as e: self._log(f"❌ {e}"); Toast(self, "  ❌  Failed  ", C['red'])

    def _copy(self):
        t = self.txte.toPlainText()
        if t: QApplication.clipboard().setText(t); Toast(self, "  📋  Copied  ", C['green'])

    def _exp(self, on):
        for b in [self.bsrt, self.btxt, self.bjsn, self.bcpy]: b.setEnabled(on)

    def _save(self):
        self.cfg.update({
            'backend_index': self.be_combo.currentIndex(),
            'hf_space_url': self.hf_url.text().strip(),
            'replicate_api_token': self.rep_tok.text().strip(),
            'custom_endpoint': self.ep_url.text().strip(),
            'custom_endpoint_key': self.ep_key.text().strip(),
            'auto_segment': self.chk_seg.isChecked(),
        })
        save_config(self.cfg); Toast(self, "  ✅  Saved  ", C['green']); self._log("💾 Settings saved")

    def _pre_dl(self):
        self._log("📥 Pre-downloading local model..."); self.b_dl.setEnabled(False); self.b_dl.setText("⏳ Downloading...")
        class W(QThread):
            log=pyqtSignal(str); done=pyqtSignal(bool,str)
            def run(s):
                try: LocalAutoAVSRBackend()._ensure_setup(s.log.emit); s.done.emit(True,"")
                except Exception as e: s.done.emit(False,str(e))
        w = W(); w.log.connect(self._log)
        def fin(ok,msg):
            self.b_dl.setEnabled(True)
            if ok: self.b_dl.setText("✅  Model Ready"); Toast(self,"  ✅  Ready  ",C['green'])
            else: self.b_dl.setText("📥  Pre-Download Model"); self._log(f"❌ {msg}"); Toast(self,f"  ❌  {msg[:60]}  ",C['red'])
        w.done.connect(fin); w.start(); self._dlw = w

    def _log(self, msg): self.logw.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {msg}")

    @staticmethod
    def _ft(s): m=int(s)//60; sec=s-m*60; return f"{m:02d}:{sec:06.3f}"


# ── Entry ───────────────────────────────────────────────────────────────────
def main():
    import traceback as _tb
    def _exc(t,v,tb):
        msg=''.join(_tb.format_exception(t,v,tb))
        f=os.path.join(get_config_dir(),'crash.log')
        try:
            with open(f,'w') as fh: fh.write(msg)
        except: pass
        print(f"\n{'='*60}\n{APP_NAME} Crash\n{'='*60}\n{msg}")
        if sys.platform=='win32':
            try: import ctypes; ctypes.windll.user32.MessageBoxW(0,f"Log: {f}\n\n{msg[:500]}",f"{APP_NAME} Error",0x10)
            except: pass
        sys.__excepthook__(t,v,tb)
    sys.excepthook = _exc

    app = QApplication(sys.argv)

    branding_icon = QIcon(str(_branding_icon_path()))

    app.setWindowIcon(branding_icon)
    app.setStyle("Fusion"); app.setStyleSheet(DARK_STYLE)
    font = app.font(); font.setFamily("Segoe UI"); font.setPointSize(10); app.setFont(font)
    w = LipSightWindow(); w.show()
    w.setWindowIcon(branding_icon)
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
