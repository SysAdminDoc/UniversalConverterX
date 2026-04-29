"""PyInstaller runtime hook — calls multiprocessing.freeze_support() at the
earliest possible point so no worker process ever re-launches the GUI.

Belt-and-braces with the same call at the top of vertigo.py: runtime
hooks execute before any user code, including before the entry script
starts. Without this, any library that uses multiprocessing on Windows
(mediapipe is the usual culprit) will spawn a second Vertigo.exe for
every worker.
"""

import multiprocessing
multiprocessing.freeze_support()
