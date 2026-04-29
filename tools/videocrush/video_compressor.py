#!/usr/bin/env python3
"""
VideoCrush v0.1.0 — Professional Video Compressor
Target-size video compression with 2-pass encoding via FFmpeg.
"""

import sys, os, subprocess, json, time, re, shutil, math
from pathlib import Path


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


# ── Bootstrap ──────────────────────────────────────────────────────────────────
def _bootstrap():
    if sys.version_info < (3, 8):
        print("Python 3.8+ required"); sys.exit(1)
    required = ['PyQt6']
    for pkg in required:
        mod = pkg.split('[')[0].replace('-', '_').lower()
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

_bootstrap()

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QProgressBar, QComboBox,
    QDoubleSpinBox, QSpinBox, QGroupBox, QGridLayout, QTextEdit,
    QSplitter, QFrame, QSizePolicy, QCheckBox, QLineEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QProcess
from PyQt6.QtGui import QFont, QIcon, QColor, QPalette, QDragEnterEvent, QDropEvent

# ── Version ────────────────────────────────────────────────────────────────────
VERSION = "0.1.0"

# ── Constants ──────────────────────────────────────────────────────────────────
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg', '.ts', '.vob', '.3gp'}
AUDIO_CODECS = {'aac': 'aac', 'opus': 'libopus', 'copy': 'copy', 'none': 'an'}
VIDEO_CODECS = {'H.264 (libx264)': 'libx264', 'H.265 (libx265)': 'libx265', 'VP9': 'libvpx-vp9', 'AV1 (SVT)': 'libsvtav1'}
OUTPUT_FORMATS = {'mp4': '.mp4', 'mkv': '.mkv', 'webm': '.webm'}
PRESETS = {'ultrafast': 'ultrafast', 'superfast': 'superfast', 'veryfast': 'veryfast',
           'faster': 'faster', 'fast': 'fast', 'medium': 'medium',
           'slow': 'slow', 'slower': 'slower', 'veryslow': 'veryslow'}

# ── Dark Theme ─────────────────────────────────────────────────────────────────
DARK_STYLE = """
QMainWindow, QWidget { background-color: #1e1e2e; color: #cdd6f4; font-family: 'Segoe UI', sans-serif; }
QGroupBox {
    border: 1px solid #45475a; border-radius: 10px;
    margin-top: 1.2em; padding: 14px 10px 10px 10px; color: #cdd6f4;
    font-weight: bold; font-size: 13px;
}
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 8px; color: #89b4fa; }
QPushButton {
    background-color: #89b4fa; color: #1e1e2e; border: none;
    padding: 9px 20px; border-radius: 7px; font-weight: bold; font-size: 13px;
}
QPushButton:hover { background-color: #74c7ec; }
QPushButton:pressed { background-color: #89dceb; }
QPushButton:disabled { background-color: #45475a; color: #6c7086; }
QPushButton#dangerBtn { background-color: #f38ba8; }
QPushButton#dangerBtn:hover { background-color: #eba0ac; }
QPushButton#secondaryBtn { background-color: #313244; color: #cdd6f4; border: 1px solid #45475a; }
QPushButton#secondaryBtn:hover { background-color: #45475a; }
QLineEdit, QDoubleSpinBox, QSpinBox {
    background-color: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 6px; padding: 7px 10px;
    selection-background-color: #89b4fa; selection-color: #1e1e2e; font-size: 13px;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus { border-color: #89b4fa; }
QComboBox {
    background-color: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 6px; padding: 7px 10px; font-size: 13px;
}
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: none; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #cdd6f4; }
QComboBox QAbstractItemView {
    background-color: #1e1e2e; color: #cdd6f4;
    border: 1px solid #45475a; selection-background-color: #89b4fa; selection-color: #1e1e2e;
    outline: none;
}
QProgressBar {
    background-color: #313244; border: none; border-radius: 6px;
    text-align: center; color: #cdd6f4; font-weight: bold; min-height: 22px;
}
QProgressBar::chunk { background-color: #89b4fa; border-radius: 6px; }
QTextEdit {
    background-color: #11111b; color: #a6adc8; border: 1px solid #313244;
    border-radius: 8px; padding: 8px; font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px; selection-background-color: #89b4fa; selection-color: #1e1e2e;
}
QLabel { color: #cdd6f4; }
QLabel#dimLabel { color: #6c7086; font-size: 12px; }
QLabel#accentLabel { color: #89b4fa; font-weight: bold; }
QLabel#titleLabel { font-size: 22px; font-weight: bold; color: #cdd6f4; }
QLabel#subtitleLabel { font-size: 12px; color: #6c7086; }
QLabel#fileInfoLabel {
    background-color: #181825; border: 1px solid #313244; border-radius: 8px;
    padding: 12px; font-size: 13px; color: #bac2de;
}
QCheckBox { color: #cdd6f4; spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px; border: 2px solid #45475a; background: #313244; }
QCheckBox::indicator:checked { background-color: #89b4fa; border-color: #89b4fa; }
QSplitter::handle { background-color: #313244; height: 2px; }
QFrame#dropFrame {
    background-color: #181825; border: 2px dashed #45475a; border-radius: 12px;
    min-height: 100px;
}
QFrame#dropFrame:hover { border-color: #89b4fa; }
"""

# ── FFmpeg Utilities ───────────────────────────────────────────────────────────
def find_ffmpeg():
    """Locate ffmpeg binary."""
    for name in ['ffmpeg', 'ffmpeg.exe']:
        path = shutil.which(name)
        if path:
            return path
    common = [
        r'C:\ffmpeg\bin\ffmpeg.exe',
        r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
        '/usr/bin/ffmpeg', '/usr/local/bin/ffmpeg',
    ]
    for p in common:
        if os.path.isfile(p):
            return p
    return None

def find_ffprobe():
    """Locate ffprobe binary."""
    for name in ['ffprobe', 'ffprobe.exe']:
        path = shutil.which(name)
        if path:
            return path
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        probe = os.path.join(os.path.dirname(ffmpeg), 'ffprobe' + ('.exe' if sys.platform == 'win32' else ''))
        if os.path.isfile(probe):
            return probe
    return None

def probe_video(filepath):
    """Get video metadata via ffprobe."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None
    cmd = [
        ffprobe, '-v', 'quiet', '-print_format', 'json',
        '-show_format', '-show_streams', filepath
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        return json.loads(result.stdout)
    except Exception:
        return None

def format_size(bytes_val):
    """Format bytes to human-readable string."""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024**2:
        return f"{bytes_val/1024:.1f} KB"
    elif bytes_val < 1024**3:
        return f"{bytes_val/1024**2:.1f} MB"
    else:
        return f"{bytes_val/1024**3:.2f} GB"

def format_duration(seconds):
    """Format seconds to HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

# ── Compression Worker ─────────────────────────────────────────────────────────
class CompressionWorker(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    status = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, input_path, output_path, target_mb, video_codec, audio_codec,
                 preset, resolution, audio_bitrate, parent=None):
        super().__init__(parent)
        self.input_path = input_path
        self.output_path = output_path
        self.target_mb = target_mb
        self.video_codec = video_codec
        self.audio_codec = audio_codec
        self.preset = preset
        self.resolution = resolution
        self.audio_bitrate = audio_bitrate
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            ffmpeg = find_ffmpeg()
            if not ffmpeg:
                self.error.emit("FFmpeg not found. Please install FFmpeg and ensure it's in your PATH.")
                return

            # Probe input
            info = probe_video(self.input_path)
            if not info:
                self.error.emit("Could not read video file metadata.")
                return

            duration = float(info['format'].get('duration', 0))
            if duration <= 0:
                self.error.emit("Could not determine video duration.")
                return

            # Calculate target bitrate
            target_bits = self.target_mb * 8 * 1024 * 1024
            audio_kbps = self.audio_bitrate if self.audio_codec not in ('copy', 'an') else 0

            # If copying audio, estimate its bitrate from source
            if self.audio_codec == 'copy':
                for stream in info.get('streams', []):
                    if stream.get('codec_type') == 'audio':
                        audio_kbps = int(stream.get('bit_rate', 128000)) // 1000
                        break

            audio_bits = audio_kbps * 1000 * duration
            video_bits = target_bits - audio_bits
            if video_bits <= 0:
                self.error.emit("Target file size is too small for the given audio settings. Increase target size or lower audio bitrate.")
                return

            video_kbps = int(video_bits / duration / 1000)
            if video_kbps < 50:
                self.error.emit(f"Calculated video bitrate ({video_kbps} kbps) is too low for usable quality. Increase target size.")
                return

            self.log.emit(f"📐 Duration: {format_duration(duration)}")
            self.log.emit(f"🎯 Target: {self.target_mb:.1f} MB")
            self.log.emit(f"🎬 Video bitrate: {video_kbps} kbps")
            if audio_kbps > 0:
                self.log.emit(f"🔊 Audio bitrate: {audio_kbps} kbps")
            self.log.emit("")

            # Build ffmpeg command components
            vf_filters = []
            if self.resolution and self.resolution != 'Original':
                h = int(self.resolution.replace('p', ''))
                vf_filters.append(f"scale=-2:{h}")

            vf_arg = ','.join(vf_filters) if vf_filters else None

            # Common args
            codec_name = self.video_codec
            is_vp9 = codec_name == 'libvpx-vp9'
            is_av1 = codec_name == 'libsvtav1'

            # ── Pass 1 ──
            self.status.emit("Pass 1/2 — Analyzing...")
            self.log.emit("═══ Pass 1 / 2 ═══")

            pass1_cmd = [ffmpeg, '-y', '-i', self.input_path]

            if vf_arg:
                pass1_cmd += ['-vf', vf_arg]

            pass1_cmd += ['-c:v', codec_name, '-b:v', f'{video_kbps}k']

            null_out = 'NUL' if sys.platform == 'win32' else '/dev/null'

            if is_vp9:
                pass1_cmd += ['-pass', '1', '-passlogfile', os.path.join(os.path.dirname(self.output_path), 'ffmpeg2pass'),
                              '-speed', '4', '-an', '-f', 'webm', null_out]
            elif is_av1:
                # SVT-AV1 doesn't support 2-pass well via ffmpeg; use single pass CRF constrained
                pass
            else:
                if self.preset and not is_av1:
                    pass1_cmd += ['-preset', self.preset]
                pass1_cmd += ['-pass', '1', '-passlogfile', os.path.join(os.path.dirname(self.output_path), 'ffmpeg2pass'),
                              '-an', '-f', 'null', null_out]

            if not is_av1:
                self.log.emit(f"  > {' '.join(os.path.basename(c) if i == 0 else c for i, c in enumerate(pass1_cmd))}")
                self._run_ffmpeg(pass1_cmd, duration, pass_num=1)

                if self._cancelled:
                    self.log.emit("\n⛔ Cancelled.")
                    self.status.emit("Cancelled")
                    return

            # ── Pass 2 ──
            self.status.emit("Pass 2/2 — Encoding...")
            self.log.emit("\n═══ Pass 2 / 2 ═══")
            self.progress.emit(0)

            pass2_cmd = [ffmpeg, '-y', '-i', self.input_path]

            if vf_arg:
                pass2_cmd += ['-vf', vf_arg]

            pass2_cmd += ['-c:v', codec_name, '-b:v', f'{video_kbps}k']

            if is_vp9:
                pass2_cmd += ['-pass', '2', '-passlogfile', os.path.join(os.path.dirname(self.output_path), 'ffmpeg2pass'),
                              '-speed', '2']
            elif is_av1:
                pass2_cmd += ['-svtav1-params', f'tbr={video_kbps}']
            else:
                if self.preset:
                    pass2_cmd += ['-preset', self.preset]
                pass2_cmd += ['-pass', '2', '-passlogfile', os.path.join(os.path.dirname(self.output_path), 'ffmpeg2pass')]

            # Audio
            if self.audio_codec == 'an':
                pass2_cmd += ['-an']
            elif self.audio_codec == 'copy':
                pass2_cmd += ['-c:a', 'copy']
            else:
                pass2_cmd += ['-c:a', self.audio_codec, '-b:a', f'{self.audio_bitrate}k']

            pass2_cmd += ['-movflags', '+faststart', self.output_path]

            self.log.emit(f"  > {' '.join(os.path.basename(c) if i == 0 else c for i, c in enumerate(pass2_cmd))}")
            self._run_ffmpeg(pass2_cmd, duration, pass_num=2)

            if self._cancelled:
                self.log.emit("\n⛔ Cancelled.")
                self.status.emit("Cancelled")
                if os.path.exists(self.output_path):
                    os.remove(self.output_path)
                return

            # Report results
            if os.path.exists(self.output_path):
                out_size = os.path.getsize(self.output_path)
                in_size = os.path.getsize(self.input_path)
                ratio = (1 - out_size / in_size) * 100 if in_size > 0 else 0
                self.log.emit(f"\n✅ Compression complete!")
                self.log.emit(f"   Input:  {format_size(in_size)}")
                self.log.emit(f"   Output: {format_size(out_size)}")
                self.log.emit(f"   Saved:  {ratio:.1f}%")
                self.finished.emit({'output': self.output_path, 'size': out_size, 'ratio': ratio})
            else:
                self.error.emit("Output file was not created. Check the log for errors.")

            # Cleanup pass log files
            passlog_base = os.path.join(os.path.dirname(self.output_path), 'ffmpeg2pass')
            for suffix in ['', '-0.log', '-0.log.mbtree', '.log', '.log.mbtree']:
                p = passlog_base + suffix
                if os.path.exists(p):
                    try: os.remove(p)
                    except: pass

        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")

    def _run_ffmpeg(self, cmd, duration, pass_num):
        """Execute ffmpeg and parse progress."""
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        proc = subprocess.Popen(
            cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
            universal_newlines=False, creationflags=creation_flags
        )

        buffer = b''
        while True:
            if self._cancelled:
                proc.terminate()
                proc.wait()
                return

            chunk = proc.stderr.read(256)
            if not chunk:
                break
            buffer += chunk

            # Parse progress from ffmpeg stderr
            lines = buffer.split(b'\r')
            buffer = lines[-1]
            for line in lines[:-1]:
                text = line.decode('utf-8', errors='replace').strip()
                time_match = re.search(r'time=(\d+):(\d+):(\d+)\.(\d+)', text)
                if time_match:
                    h, m, s, _ = time_match.groups()
                    current = int(h) * 3600 + int(m) * 60 + int(s)
                    pct = min(int(current / duration * 100), 100) if duration > 0 else 0
                    self.progress.emit(pct)

                # Log errors
                if any(kw in text.lower() for kw in ['error', 'invalid', 'failed', 'unknown']):
                    self.log.emit(f"  ⚠ {text}")

        proc.wait()
        if proc.returncode != 0 and not self._cancelled:
            remaining = buffer.decode('utf-8', errors='replace').strip()
            if remaining:
                self.log.emit(f"  ⚠ {remaining[-500:]}")
        self.progress.emit(100)


# ── Drop Zone Widget ───────────────────────────────────────────────────────────
class DropZone(QFrame):
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropFrame")
        self.setAcceptDrops(True)
        self.setMinimumHeight(90)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon_label = QLabel("📂")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("font-size: 28px; border: none; background: transparent;")
        layout.addWidget(self.icon_label)

        self.text_label = QLabel("Drag & drop a video file here, or click Browse")
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setObjectName("dimLabel")
        self.text_label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self.text_label)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("QFrame#dropFrame { border-color: #89b4fa; background-color: #1e1e3e; }")

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet("")
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).suffix.lower() in VIDEO_EXTENSIONS:
                self.file_dropped.emit(path)


# ── Main Window ────────────────────────────────────────────────────────────────
class VideoCompressorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"VideoCrush v{VERSION}")
        self.setMinimumSize(780, 720)
        self.resize(820, 780)
        self.input_path = None
        self.video_info = None
        self.worker = None

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(12)

        # ── Header ──
        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel(f"VideoCrush")
        title.setObjectName("titleLabel")
        title_block.addWidget(title)
        subtitle = QLabel(f"v{VERSION}  —  Target-size video compression")
        subtitle.setObjectName("subtitleLabel")
        title_block.addWidget(subtitle)
        header.addLayout(title_block)
        header.addStretch()

        ffmpeg_status = QLabel()
        if find_ffmpeg():
            ffmpeg_status.setText("FFmpeg ready")
            ffmpeg_status.setStyleSheet("color: #a6e3a1; font-size: 12px; font-weight: bold;")
        else:
            ffmpeg_status.setText("FFmpeg not found!")
            ffmpeg_status.setStyleSheet("color: #f38ba8; font-size: 12px; font-weight: bold;")
        header.addWidget(ffmpeg_status)
        main_layout.addLayout(header)

        # ── Input Section ──
        input_group = QGroupBox("Input")
        input_layout = QVBoxLayout(input_group)

        self.drop_zone = DropZone()
        self.drop_zone.file_dropped.connect(self.load_file)
        input_layout.addWidget(self.drop_zone)

        browse_row = QHBoxLayout()
        self.path_label = QLineEdit()
        self.path_label.setPlaceholderText("No file selected...")
        self.path_label.setReadOnly(True)
        browse_row.addWidget(self.path_label, 1)
        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("secondaryBtn")
        browse_btn.setFixedWidth(100)
        browse_btn.clicked.connect(self.browse_file)
        browse_row.addWidget(browse_btn)
        input_layout.addLayout(browse_row)

        self.info_label = QLabel("")
        self.info_label.setObjectName("fileInfoLabel")
        self.info_label.setWordWrap(True)
        self.info_label.setVisible(False)
        input_layout.addWidget(self.info_label)

        main_layout.addWidget(input_group)

        # ── Settings Section ──
        settings_group = QGroupBox("Compression Settings")
        settings_grid = QGridLayout(settings_group)
        settings_grid.setSpacing(10)

        # Target file size
        settings_grid.addWidget(QLabel("Target Size"), 0, 0)
        size_row = QHBoxLayout()
        self.target_size_spin = QDoubleSpinBox()
        self.target_size_spin.setRange(0.5, 10000)
        self.target_size_spin.setValue(25.0)
        self.target_size_spin.setSuffix(" MB")
        self.target_size_spin.setDecimals(1)
        self.target_size_spin.setSingleStep(5)
        size_row.addWidget(self.target_size_spin)

        # Quick size buttons
        for size_label, size_val in [("8 MB", 8), ("25 MB", 25), ("50 MB", 50), ("100 MB", 100)]:
            btn = QPushButton(size_label)
            btn.setObjectName("secondaryBtn")
            btn.setFixedWidth(60)
            btn.clicked.connect(lambda checked, v=size_val: self.target_size_spin.setValue(v))
            size_row.addWidget(btn)
        settings_grid.addLayout(size_row, 0, 1)

        # Video codec
        settings_grid.addWidget(QLabel("Video Codec"), 1, 0)
        self.codec_combo = QComboBox()
        for name in VIDEO_CODECS:
            self.codec_combo.addItem(name, VIDEO_CODECS[name])
        settings_grid.addWidget(self.codec_combo, 1, 1)

        # Preset
        settings_grid.addWidget(QLabel("Encode Preset"), 2, 0)
        self.preset_combo = QComboBox()
        for name in PRESETS:
            self.preset_combo.addItem(name)
        self.preset_combo.setCurrentText('medium')
        settings_grid.addWidget(self.preset_combo, 2, 1)

        # Resolution
        settings_grid.addWidget(QLabel("Resolution"), 3, 0)
        self.res_combo = QComboBox()
        self.res_combo.addItems(['Original', '2160p', '1440p', '1080p', '720p', '480p', '360p'])
        settings_grid.addWidget(self.res_combo, 3, 1)

        # Audio codec
        settings_grid.addWidget(QLabel("Audio"), 4, 0)
        audio_row = QHBoxLayout()
        self.audio_combo = QComboBox()
        self.audio_combo.addItems(['AAC', 'Opus', 'Copy Original', 'No Audio'])
        audio_row.addWidget(self.audio_combo)
        audio_row.addWidget(QLabel("Bitrate:"))
        self.audio_bitrate_spin = QSpinBox()
        self.audio_bitrate_spin.setRange(32, 320)
        self.audio_bitrate_spin.setValue(128)
        self.audio_bitrate_spin.setSuffix(" kbps")
        audio_row.addWidget(self.audio_bitrate_spin)
        settings_grid.addLayout(audio_row, 4, 1)

        # Output format
        settings_grid.addWidget(QLabel("Output Format"), 5, 0)
        self.format_combo = QComboBox()
        for name in OUTPUT_FORMATS:
            self.format_combo.addItem(f".{name}", OUTPUT_FORMATS[name])
        settings_grid.addWidget(self.format_combo, 5, 1)

        main_layout.addWidget(settings_group)

        # ── Progress & Controls ──
        ctrl_group = QGroupBox("Progress")
        ctrl_layout = QVBoxLayout(ctrl_group)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("accentLabel")
        ctrl_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        ctrl_layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        self.compress_btn = QPushButton("🔥 Compress")
        self.compress_btn.setFixedHeight(40)
        self.compress_btn.clicked.connect(self.start_compression)
        btn_row.addWidget(self.compress_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("dangerBtn")
        self.cancel_btn.setFixedHeight(40)
        self.cancel_btn.setFixedWidth(100)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_compression)
        btn_row.addWidget(self.cancel_btn)

        self.open_folder_btn = QPushButton("Open Output Folder")
        self.open_folder_btn.setObjectName("secondaryBtn")
        self.open_folder_btn.setFixedHeight(40)
        self.open_folder_btn.setVisible(False)
        self.open_folder_btn.clicked.connect(self.open_output_folder)
        btn_row.addWidget(self.open_folder_btn)

        ctrl_layout.addLayout(btn_row)
        main_layout.addWidget(ctrl_group)

        # ── Log ──
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(100)
        log_layout.addWidget(self.log_text)
        main_layout.addWidget(log_group)

        self._last_output = None

    def browse_file(self):
        ext_filter = "Video Files (" + " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS)) + ");;All Files (*)"
        path, _ = QFileDialog.getOpenFileName(self, "Select Video File", "", ext_filter)
        if path:
            self.load_file(path)

    def load_file(self, path):
        if not os.path.isfile(path):
            return
        self.input_path = path
        self.path_label.setText(path)
        self.drop_zone.text_label.setText(os.path.basename(path))
        self.drop_zone.icon_label.setText("🎬")

        # Probe video info
        info = probe_video(path)
        self.video_info = info
        file_size = os.path.getsize(path)

        if info:
            duration = float(info['format'].get('duration', 0))
            video_stream = None
            audio_stream = None
            for s in info.get('streams', []):
                if s.get('codec_type') == 'video' and not video_stream:
                    video_stream = s
                elif s.get('codec_type') == 'audio' and not audio_stream:
                    audio_stream = s

            parts = [f"Size: {format_size(file_size)}"]
            if duration > 0:
                parts.append(f"Duration: {format_duration(duration)}")
            if video_stream:
                w = video_stream.get('width', '?')
                h = video_stream.get('height', '?')
                codec = video_stream.get('codec_name', '?')
                fps = video_stream.get('r_frame_rate', '')
                if '/' in str(fps):
                    try:
                        num, den = fps.split('/')
                        fps = f"{int(num)/int(den):.1f}"
                    except:
                        pass
                parts.append(f"Video: {w}x{h}  {codec}  {fps} fps")
            if audio_stream:
                a_codec = audio_stream.get('codec_name', '?')
                a_rate = audio_stream.get('sample_rate', '?')
                a_ch = audio_stream.get('channels', '?')
                parts.append(f"Audio: {a_codec}  {a_rate} Hz  {a_ch}ch")

            bitrate = info['format'].get('bit_rate')
            if bitrate:
                parts.append(f"Bitrate: {int(bitrate)//1000} kbps")

            self.info_label.setText("   |   ".join(parts))
            self.info_label.setVisible(True)

            # Auto-suggest target size (half of original, rounded)
            suggested = max(1, round(file_size / 1024 / 1024 / 2))
            self.target_size_spin.setValue(suggested)
        else:
            self.info_label.setText(f"Size: {format_size(file_size)}  (could not probe details — is FFmpeg installed?)")
            self.info_label.setVisible(True)

    def start_compression(self):
        if not self.input_path:
            self.log_text.append("⚠ No input file selected.")
            return
        if not find_ffmpeg():
            self.log_text.append("⚠ FFmpeg not found. Please install FFmpeg.")
            return

        # Determine output path
        src = Path(self.input_path)
        ext = self.format_combo.currentData()
        out_name = f"{src.stem}_compressed{ext}"
        output_path = str(src.parent / out_name)

        # Get audio codec
        audio_map = {'AAC': 'aac', 'Opus': 'libopus', 'Copy Original': 'copy', 'No Audio': 'an'}
        audio_codec = audio_map.get(self.audio_combo.currentText(), 'aac')

        self.log_text.clear()
        self.log_text.append(f"🚀 Starting compression...")
        self.log_text.append(f"   Input:  {self.input_path}")
        self.log_text.append(f"   Output: {output_path}\n")

        self.progress_bar.setValue(0)
        self.compress_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.open_folder_btn.setVisible(False)

        self.worker = CompressionWorker(
            input_path=self.input_path,
            output_path=output_path,
            target_mb=self.target_size_spin.value(),
            video_codec=self.codec_combo.currentData(),
            audio_codec=audio_codec,
            preset=self.preset_combo.currentText(),
            resolution=self.res_combo.currentText(),
            audio_bitrate=self.audio_bitrate_spin.value()
        )
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.log.connect(self.log_text.append)
        self.worker.status.connect(self.status_label.setText)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def cancel_compression(self):
        if self.worker:
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.status_label.setText("Cancelling...")

    def on_finished(self, result):
        self.compress_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status_label.setText("Done!")
        self.progress_bar.setValue(100)
        self._last_output = result.get('output')
        if self._last_output:
            self.open_folder_btn.setVisible(True)

    def on_error(self, msg):
        self.log_text.append(f"\n❌ Error: {msg}")
        self.status_label.setText("Error")
        self.compress_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    def open_output_folder(self):
        if self._last_output and os.path.exists(self._last_output):
            folder = os.path.dirname(self._last_output)
            if sys.platform == 'win32':
                subprocess.Popen(['explorer', '/select,', self._last_output.replace('/', '\\')])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', '-R', self._last_output])
            else:
                subprocess.Popen(['xdg-open', folder])


# ── Entry Point ────────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    branding_icon = QIcon(str(_branding_icon_path()))
    app.setWindowIcon(branding_icon)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLE)

    # Set dark palette as base
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#1e1e2e"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#cdd6f4"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#313244"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#181825"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#cdd6f4"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#313244"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#cdd6f4"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#89b4fa"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#1e1e2e"))
    app.setPalette(palette)

    window = VideoCompressorWindow()

    window.setWindowIcon(branding_icon)
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
