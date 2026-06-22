"""
wrig/config.py — Machine-level configuration for WRIG.

On first run, if no machine config exists, WRIG creates one at:
  Linux/Mac:  ~/.config/wrig/machine.ini
  Windows:    %APPDATA%/wrig/machine.ini

The user edits this file once per machine to set the WSJTX binary path
and the shared log directory on TrueNAS (or wherever).
"""

import configparser
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

def is_windows() -> bool:
    return platform.system() == "Windows"


def is_mac() -> bool:
    return platform.system() == "Darwin"


def is_linux() -> bool:
    return platform.system() == "Linux"


# ---------------------------------------------------------------------------
# Well-known directory roots
# ---------------------------------------------------------------------------

def wrig_config_dir() -> Path:
    """Root directory for all WRIG configuration (machine config + registry + instance dirs)."""
    if is_windows():
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "wrig"
    d.mkdir(parents=True, exist_ok=True)
    return d


def instances_dir() -> Path:
    """Where per-instance config directories live."""
    d = wrig_config_dir() / "instances"
    d.mkdir(parents=True, exist_ok=True)
    return d


def templates_dir() -> Path:
    """Where wsjtx.ini template files live."""
    d = wrig_config_dir() / "templates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def registry_path() -> Path:
    return wrig_config_dir() / "registry.json"


def machine_config_path() -> Path:
    return wrig_config_dir() / "machine.ini"


# ---------------------------------------------------------------------------
# Default WSJTX binary detection
# ---------------------------------------------------------------------------

def _default_wsjtx_binary() -> str:
    if is_windows():
        candidates = [
            r"C:\WSJT\bin\wsjtx.exe",
            r"C:\Program Files\WSJT-X\bin\wsjtx.exe",
            r"C:\Program Files (x86)\WSJT-X\bin\wsjtx.exe",
        ]
        for c in candidates:
            if Path(c).exists():
                return c
        return r"C:\WSJT\bin\wsjtx.exe"  # best guess fallback
    else:
        found = shutil.which("wsjtx")
        return found if found else "/usr/bin/wsjtx"


def _default_log_dir() -> str:
    if is_windows():
        # UNC path — user must edit this
        return r"\\192.168.1.5\Users\share"
    else:
        return "/mnt/Users/share"


# ---------------------------------------------------------------------------
# Machine config read/write
# ---------------------------------------------------------------------------

DEFAULT_MACHINE_CONFIG = """\
# WRIG machine configuration — edit once per machine.
#
# [machine]
#   wsjtx_binary   = full path to wsjtx executable
#   shared_log_dir = directory on TrueNAS (or other share) that holds wsjtx_log.adi
#                    Linux:   /mnt/Users/share
#                    Windows: \\\\192.168.1.5\\Users\\share
#   instances_dir  = (optional) override where instance config dirs are stored

[machine]
wsjtx_binary   = {wsjtx_binary}
shared_log_dir = {shared_log_dir}
"""


def load_machine_config() -> configparser.ConfigParser:
    path = machine_config_path()
    if not path.exists():
        _write_default_machine_config(path)
        print(f"[wrig] Created default machine config: {path}")
        print(f"[wrig] Edit it to set wsjtx_binary and shared_log_dir for this machine.")

    cfg = configparser.ConfigParser()
    cfg.read(str(path))
    return cfg


def _write_default_machine_config(path: Path) -> None:
    content = DEFAULT_MACHINE_CONFIG.format(
        wsjtx_binary=_default_wsjtx_binary(),
        shared_log_dir=_default_log_dir(),
    )
    path.write_text(content)


def get_wsjtx_binary() -> str:
    cfg = load_machine_config()
    return cfg.get("machine", "wsjtx_binary", fallback=_default_wsjtx_binary())


def get_shared_log_dir() -> Path:
    cfg = load_machine_config()
    raw = cfg.get("machine", "shared_log_dir", fallback=_default_log_dir())
    return Path(raw)


def get_instances_dir() -> Path:
    cfg = load_machine_config()
    raw = cfg.get("machine", "instances_dir", fallback=str(instances_dir()))
    d = Path(raw)
    d.mkdir(parents=True, exist_ok=True)
    return d
