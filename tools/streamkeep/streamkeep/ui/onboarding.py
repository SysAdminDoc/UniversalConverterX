"""First-run onboarding wizard — polished multi-step setup for new users."""

import subprocess

from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QStackedWidget, QVBoxLayout, QWidget,
)

from ..paths import _CREATE_NO_WINDOW
from ..utils import default_output_dir
from .widgets import (
    make_dialog_hero,
    make_dialog_section,
    make_status_banner,
    update_status_banner,
)


class OnboardingWizard(QDialog):
    """Multi-step first-run setup wizard."""

    _STEP_TITLES = [
        "Welcome",
        "Save location",
        "Appearance",
        "Ready to go",
    ]

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to StreamKeep")
        self.setFixedSize(640, 500)
        self.setModal(True)
        self._config = config or {}
        self._output_dir = str(default_output_dir())
        self._theme = "dark"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 18)
        layout.setSpacing(12)

        hero, _, _, self._hero_badge = make_dialog_hero(
            "Set up StreamKeep in a minute",
            "Pick where recordings go, choose how the app should look, "
            "and confirm the essentials before you start downloading.",
            eyebrow="FIRST RUN",
            badge_text="4-step setup",
        )
        layout.addWidget(hero)

        step_row = QHBoxLayout()
        step_row.setContentsMargins(2, 0, 2, 0)
        step_row.setSpacing(8)
        self._step_label = QLabel("")
        self._step_label.setObjectName("fieldLabel")
        step_row.addWidget(self._step_label)
        step_row.addStretch(1)
        self._step_meta = QLabel("")
        self._step_meta.setObjectName("fieldHint")
        step_row.addWidget(self._step_meta)
        layout.addLayout(step_row)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)

        self._stack.addWidget(self._page_welcome())
        self._stack.addWidget(self._page_output())
        self._stack.addWidget(self._page_theme())
        self._stack.addWidget(self._page_done())

        nav = QHBoxLayout()
        nav.setSpacing(8)
        self._skip_btn = QPushButton("Skip setup")
        self._skip_btn.setObjectName("ghost")
        self._skip_btn.clicked.connect(self._skip_all)
        nav.addWidget(self._skip_btn)
        nav.addStretch(1)
        self._back_btn = QPushButton("Back")
        self._back_btn.setObjectName("secondary")
        self._back_btn.clicked.connect(self._go_back)
        nav.addWidget(self._back_btn)
        self._next_btn = QPushButton("Continue")
        self._next_btn.setObjectName("primary")
        self._next_btn.clicked.connect(self._go_next)
        nav.addWidget(self._next_btn)
        layout.addLayout(nav)

        self._check_ffmpeg()
        self._update_summary()
        self._update_nav()

    def _page_welcome(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        section, content = make_dialog_section(
            "System readiness",
            "StreamKeep works best with ffmpeg available in PATH. "
            "If it is missing, the app can still open but downloads will not start yet.",
        )
        self._ffmpeg_banner, self._ffmpeg_title, self._ffmpeg_body = make_status_banner()
        content.addWidget(self._ffmpeg_banner)

        checklist, checklist_content = make_dialog_section(
            "What this setup covers",
            "These defaults can all be changed later in Settings.",
        )
        for line in [
            "Choose a default recording folder.",
            "Pick dark, light, or follow-system appearance.",
            "Start with safe, clean defaults and skip the rest for now.",
        ]:
            item = QLabel(f"• {line}")
            item.setObjectName("sectionBody")
            item.setWordWrap(True)
            checklist_content.addWidget(item)

        outer.addWidget(section)
        outer.addWidget(checklist)
        outer.addStretch(1)
        return page

    def _page_output(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        section, content = make_dialog_section(
            "Default recording folder",
            "This becomes the starting point for downloads, monitoring, and saved metadata.",
        )
        self._output_banner, self._output_title, self._output_body = make_status_banner()
        content.addWidget(self._output_banner)

        browse_row = QHBoxLayout()
        browse_row.setSpacing(8)
        browse_btn = QPushButton("Choose folder…")
        browse_btn.setObjectName("primary")
        browse_btn.clicked.connect(self._browse_output)
        browse_row.addWidget(browse_btn)
        reset_btn = QPushButton("Use recommended folder")
        reset_btn.setObjectName("secondary")
        reset_btn.clicked.connect(self._reset_output)
        browse_row.addWidget(reset_btn)
        browse_row.addStretch(1)
        content.addLayout(browse_row)

        note = QLabel(
            "Tip: keeping recordings under one root makes storage cleanup, "
            "history, and auto-record profiles much easier to manage."
        )
        note.setObjectName("fieldHint")
        note.setWordWrap(True)
        content.addWidget(note)

        outer.addWidget(section)
        outer.addStretch(1)
        return page

    def _page_theme(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        section, content = make_dialog_section(
            "Appearance",
            "Choose the default look for the app. You can switch themes any time without restarting.",
        )
        self._theme_banner, self._theme_title, self._theme_body = make_status_banner()
        content.addWidget(self._theme_banner)

        self._dark_radio = QRadioButton("Dark — richer contrast and a focused, cinematic workspace")
        self._dark_radio.setChecked(True)
        self._light_radio = QRadioButton("Light — brighter surfaces and cleaner daytime readability")
        self._system_radio = QRadioButton("Follow system — stay in sync with your OS preference")
        for radio in (self._dark_radio, self._light_radio, self._system_radio):
            radio.toggled.connect(self._update_summary)
            content.addWidget(radio)

        outer.addWidget(section)
        outer.addStretch(1)
        return page

    def _page_done(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        section, content = make_dialog_section(
            "Ready to start",
            "You can paste a stream URL right away, or set up monitor profiles for automatic recording later.",
        )
        self._done_banner, self._done_title, self._done_body = make_status_banner()
        content.addWidget(self._done_banner)

        next_steps = QLabel(
            "Good next steps:\n"
            "• Paste a URL in Download to test your setup.\n"
            "• Open Monitor to track channels automatically.\n"
            "• Visit Settings if you want cookies, proxies, or file templates."
        )
        next_steps.setObjectName("sectionBody")
        next_steps.setWordWrap(True)
        content.addWidget(next_steps)

        outer.addWidget(section)
        outer.addStretch(1)
        return page

    def _check_ffmpeg(self):
        message = (
            "ffmpeg was found. Downloads, trimming, and verification are ready to use."
        )
        tone = "success"
        title = "System tools look good"
        try:
            r = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                timeout=5,
                creationflags=_CREATE_NO_WINDOW,
            )
            if r.returncode != 0:
                raise OSError("ffmpeg returned a non-zero exit code")
        except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired):
            tone = "warning"
            title = "ffmpeg is still missing"
            message = (
                "Install ffmpeg and add it to PATH before starting downloads. "
                "You can finish setup now and fix this later from Settings."
            )
        update_status_banner(
            self._ffmpeg_banner,
            self._ffmpeg_title,
            self._ffmpeg_body,
            title=title,
            body=message,
            tone=tone,
        )

    def _browse_output(self):
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Select output folder",
            self._output_dir,
        )
        if chosen:
            self._output_dir = chosen
            self._update_summary()

    def _reset_output(self):
        self._output_dir = str(default_output_dir())
        self._update_summary()

    def _update_summary(self):
        if self._light_radio.isChecked() if hasattr(self, "_light_radio") else False:
            self._theme = "light"
            theme_title = "Light theme selected"
            theme_body = "Bright surfaces with softer contrast for daytime use."
        elif self._system_radio.isChecked() if hasattr(self, "_system_radio") else False:
            self._theme = "system"
            theme_title = "Following system theme"
            theme_body = "StreamKeep will follow your OS appearance preference."
        else:
            self._theme = "dark"
            theme_title = "Dark theme selected"
            theme_body = "A calmer, higher-contrast workspace tuned for media-heavy workflows."

        if hasattr(self, "_output_banner"):
            update_status_banner(
                self._output_banner,
                self._output_title,
                self._output_body,
                title="Recordings will be saved here",
                body=self._output_dir,
                tone="info",
            )
        if hasattr(self, "_theme_banner"):
            update_status_banner(
                self._theme_banner,
                self._theme_title,
                self._theme_body,
                title=theme_title,
                body=theme_body,
                tone="info",
            )
        if hasattr(self, "_done_banner"):
            update_status_banner(
                self._done_banner,
                self._done_title,
                self._done_body,
                title="Setup summary",
                body=f"Theme: {self._theme} • Output folder: {self._output_dir}",
                tone="success",
            )

    def _update_nav(self):
        idx = self._stack.currentIndex()
        total = self._stack.count()
        self._step_label.setText(f"Step {idx + 1} of {total}")
        self._step_meta.setText(self._STEP_TITLES[idx])
        self._back_btn.setEnabled(idx > 0)
        self._next_btn.setText("Finish setup" if idx == total - 1 else "Continue")
        self._hero_badge.setText(f"{idx + 1}/{total}")
        self._hero_badge.setVisible(True)

    def _go_next(self):
        idx = self._stack.currentIndex()
        if idx >= self._stack.count() - 1:
            self._finish()
            return
        self._stack.setCurrentIndex(idx + 1)
        self._update_summary()
        self._update_nav()

    def _go_back(self):
        idx = self._stack.currentIndex()
        if idx <= 0:
            return
        self._stack.setCurrentIndex(idx - 1)
        self._update_nav()

    def _skip_all(self):
        self._config["first_run_complete"] = True
        self.accept()

    def _finish(self):
        self._config["output_dir"] = self._output_dir
        self._config["theme"] = self._theme
        self._config["first_run_complete"] = True
        self.accept()

    @property
    def chosen_theme(self):
        return self._theme

    @property
    def chosen_output_dir(self):
        return self._output_dir
