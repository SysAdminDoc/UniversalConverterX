"""Shared file-dialog helpers for polished native browsing flows."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QDir, QSettings, QStandardPaths, QUrl
from PyQt6.QtWidgets import QFileDialog, QWidget


VIDEO_FILTER = "Video files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.flv *.ts *.mpg *.mpeg)"
ALL_FILES_FILTER = "All files (*)"
MP4_FILTER = "MP4 video (*.mp4)"

_SETTINGS_ORG = "Vertigo"
_SETTINGS_APP = "Vertigo"
_LAST_IMPORT_DIR_KEY = "paths/last_import_dir"
_LAST_EXPORT_DIR_KEY = "paths/last_export_dir"
_LAST_BATCH_DIR_KEY = "paths/last_batch_dir"


def _settings() -> QSettings:
    return QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def _existing_path(path: str) -> str | None:
    if path and Path(path).exists():
        return path
    return None


def _first_existing_standard_path(
    *locations: QStandardPaths.StandardLocation,
) -> str:
    for location in locations:
        path = QStandardPaths.writableLocation(location)
        if path and Path(path).exists():
            return path
    return QDir.homePath()


def _common_places() -> list[str]:
    seen: set[str] = set()
    places: list[str] = []
    for location in (
        QStandardPaths.StandardLocation.HomeLocation,
        QStandardPaths.StandardLocation.DesktopLocation,
        QStandardPaths.StandardLocation.DownloadLocation,
        QStandardPaths.StandardLocation.DocumentsLocation,
        QStandardPaths.StandardLocation.MoviesLocation,
        QStandardPaths.StandardLocation.PicturesLocation,
    ):
        path = QStandardPaths.writableLocation(location)
        if path and Path(path).exists() and path not in seen:
            places.append(path)
            seen.add(path)
    return places


def _configure_dialog(dialog: QFileDialog, start_dir: str) -> None:
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, False)
    dialog.setViewMode(QFileDialog.ViewMode.Detail)
    dialog.setDirectory(start_dir)
    dialog.setHistory([start_dir])
    dialog.setSidebarUrls([QUrl.fromLocalFile(path) for path in _common_places()])


def _remember_directory(key: str, path: str | Path) -> None:
    folder = Path(path)
    directory = folder if folder.is_dir() else folder.parent
    if directory.exists():
        _settings().setValue(key, str(directory))


def default_import_directory() -> str:
    remembered = _existing_path(_settings().value(_LAST_IMPORT_DIR_KEY, "", type=str))
    if remembered:
        return remembered
    return _first_existing_standard_path(
        QStandardPaths.StandardLocation.MoviesLocation,
        QStandardPaths.StandardLocation.DownloadLocation,
        QStandardPaths.StandardLocation.DesktopLocation,
        QStandardPaths.StandardLocation.DocumentsLocation,
        QStandardPaths.StandardLocation.HomeLocation,
    )


def remember_import_directory(path: str | Path) -> None:
    _remember_directory(_LAST_IMPORT_DIR_KEY, path)


def get_open_video_paths(parent: QWidget | None = None) -> list[str]:
    dialog = QFileDialog(parent, "Import video(s)")
    dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
    dialog.setNameFilters([VIDEO_FILTER, ALL_FILES_FILTER])
    dialog.selectNameFilter(VIDEO_FILTER)
    _configure_dialog(dialog, default_import_directory())

    if dialog.exec() != QFileDialog.DialogCode.Accepted:
        return []
    paths = dialog.selectedFiles()
    if paths:
        remember_import_directory(paths[0])
    return paths


def get_save_video_path(parent: QWidget | None, suggested: Path) -> str:
    initial_dir = _existing_path(str(suggested.parent)) or _existing_path(
        _settings().value(_LAST_EXPORT_DIR_KEY, "", type=str)
    ) or default_import_directory()

    dialog = QFileDialog(parent, "Export vertical", initial_dir)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setFileMode(QFileDialog.FileMode.AnyFile)
    dialog.setNameFilters([MP4_FILTER])
    dialog.selectNameFilter(MP4_FILTER)
    dialog.setDefaultSuffix("mp4")
    _configure_dialog(dialog, initial_dir)
    dialog.selectFile(str(suggested))

    if dialog.exec() != QFileDialog.DialogCode.Accepted:
        return ""
    paths = dialog.selectedFiles()
    if not paths:
        return ""
    _remember_directory(_LAST_EXPORT_DIR_KEY, paths[0])
    return paths[0]


def get_existing_directory(parent: QWidget | None, title: str) -> str:
    initial_dir = _existing_path(_settings().value(_LAST_BATCH_DIR_KEY, "", type=str))
    if not initial_dir:
        initial_dir = _existing_path(_settings().value(_LAST_EXPORT_DIR_KEY, "", type=str))
    if not initial_dir:
        initial_dir = default_import_directory()

    dialog = QFileDialog(parent, title, initial_dir)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
    dialog.setLabelText(QFileDialog.DialogLabel.Accept, "Choose folder")
    _configure_dialog(dialog, initial_dir)

    if dialog.exec() != QFileDialog.DialogCode.Accepted:
        return ""
    paths = dialog.selectedFiles()
    if not paths:
        return ""
    _remember_directory(_LAST_BATCH_DIR_KEY, paths[0])
    return paths[0]
