"""Product identity: the ONLY place to rename the product.

Everything else reads from here: window titles, tray tooltip, mutex and event
names, settings folder, autostart value, the PyInstaller exe name and every
#define of the Inno Setup script (scripts/build.ps1 passes them as /D flags).

To rebrand: change these values, regenerate the icon (scripts/make_icon.py),
rebuild. APP_GUID must stay constant across versions of the same product, or
Windows will treat an upgrade as a second, separate installation.
"""

APP_NAME = "GPU Task Manager"
APP_SLUG = "GPUTaskManager"          # file names, exe name, folders: no spaces
APP_VERSION = "0.1.0"
APP_PUBLISHER = "Francesco Trani"
AUTHOR = "Francesco Trani"
AUTHOR_URL = "https://francescotrani.com"
REPO_URL = "https://github.com/Bottega-Alu/gpu-task-manager"
APP_URL = REPO_URL                    # publisher/support URL in Apps & features and the installer
APP_GUID = "{5E1F7A2C-8B3D-4C6E-9A40-1D2F3B4C5A61}"
COPYRIGHT = "Copyright (c) 2026 Francesco Trani"
LICENSE_NAME = "PolyForm Noncommercial License 1.0.0"

# Measurement engine (MIT): credited in THIRD-PARTY-NOTICES.txt and the licenses folder, as MIT requires.
ENGINE_NAME = "gputaskman"
ENGINE_AUTHOR = "Scott Hanselman"
ENGINE_URL = "https://github.com/shanselman/gputaskman"

EXE_NAME = f"{APP_SLUG}.exe"
MUTEX_NAME = f"Local\\{APP_SLUG}-instance"
SHOW_EVENT_NAME = f"Local\\{APP_SLUG}-show"
RUN_VALUE_NAME = APP_SLUG             # HKCU\...\Run value for start at sign-in
DATA_DIR_NAME = APP_NAME              # %APPDATA%\<this>\settings.json
