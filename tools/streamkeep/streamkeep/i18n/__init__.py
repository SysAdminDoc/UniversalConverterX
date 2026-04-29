"""Internationalization infrastructure (F74).

Provides ``install_translator(lang)`` which loads a ``.qm`` file and
installs it into the running QApplication. Untranslated strings fall
through to English.

Available languages are discovered by scanning this directory for ``.qm``
files. The ``translations/`` subdirectory holds ``.ts`` source files for
Qt Linguist.

Usage::

    from streamkeep.i18n import install_translator, available_languages
    install_translator("es")   # Spanish
    print(available_languages())  # ["en", "es", "de", ...]
"""

import os
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QLocale, QTranslator

_I18N_DIR = Path(__file__).parent
_translator = None


def available_languages():
    """Return list of available language codes (from .qm files + 'en')."""
    langs = ["en"]
    for f in _I18N_DIR.glob("*.qm"):
        code = f.stem  # e.g., "streamkeep_es.qm" -> "streamkeep_es"
        # Extract language code after last underscore
        parts = code.rsplit("_", 1)
        if len(parts) == 2 and len(parts[1]) in (2, 5):
            if parts[1] not in langs:
                langs.append(parts[1])
    return sorted(langs)


def install_translator(lang, app=None):
    """Install a QTranslator for *lang* (e.g., 'es', 'de', 'ja').

    Returns True if a translation was loaded, False otherwise.
    'en' is the built-in fallback — always returns True.
    """
    global _translator
    if app is None:
        app = QCoreApplication.instance()
    if app is None:
        return False

    # Remove previous translator
    if _translator is not None:
        app.removeTranslator(_translator)
        _translator = None

    if lang == "en" or not lang:
        return True  # English is the source language, no translation needed

    # Try to load the .qm file
    translator = QTranslator(app)
    qm_path = str(_I18N_DIR / f"streamkeep_{lang}.qm")
    if os.path.isfile(qm_path) and translator.load(qm_path):
        app.installTranslator(translator)
        _translator = translator
        return True

    # Try system locale fallback
    if translator.load(QLocale(lang), "streamkeep", "_", str(_I18N_DIR)):
        app.installTranslator(translator)
        _translator = translator
        return True

    return False


def current_language():
    """Return the currently installed language code, or 'en'."""
    if _translator is None:
        return "en"
    return "translated"  # Can't easily extract the code from QTranslator
