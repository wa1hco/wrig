r"""
wrig/launcher.py — Start and stop WSJTX instances.

WSJTX is launched with:
  wsjtx --rig-name <rig_name>

WSJTX's `--rig-name <rig>` is its own feature: it derives two per-rig locations
from the rig name. Config and data are SEPARATE, and differ by platform:
  CONFIG (settings .ini):
    Linux/Mac:  ~/.config/WSJT-X - <rig>.ini            (a flat FILE)
    Windows:    %LOCALAPPDATA%\WSJT-X - <rig>\WSJT-X - <rig>.ini   (file in a folder)
  LOG/DATA (wsjtx_log.adi, ALL.TXT):
    Linux/Mac:  ~/.local/share/WSJT-X - <rig>/          (separate dir)
    Windows:    %LOCALAPPDATA%\WSJT-X - <rig>\           (same folder as config)

WRIG does NOT redirect WSJTX's config (no symlink/junction). It seeds WSJTX's
real config file once at create time (see instance.create_instance) and links
wsjtx_log.adi in the log dir to the shared NAS log (see wsjtx_log_dir_for and
instance.create_log_link). Path helpers here name those real locations:
wsjtx_config_file_for() and wsjtx_log_dir_for().
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

from .config import get_wsjtx_binary, is_windows, is_mac
from .registry import get_instance, list_instances


# ---------------------------------------------------------------------------
# WSJTX per-rig config / log paths (WSJTX's own --rig-name layout)
# ---------------------------------------------------------------------------

def wsjtx_config_roots() -> list[Path]:
    """Config roots WSJTX may use, primary first.

    Windows: %LOCALAPPDATA% (where WSJTX actually stores per-rig config), with
    %APPDATA% kept only as a fallback for discovering legacy/misplaced configs.
    """
    if is_windows():
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        roots = [local]
        if roaming != local:
            roots.append(roaming)
        return roots
    else:
        roots = [Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))]
        roots.append(Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")))
        return roots


def _wsjtx_ini_for_profile(profile: str) -> Path:
    """
    Real .ini path for a WSJTX profile basename (e.g. 'WSJT-X' for the default
    profile, or 'WSJT-X - FlexA' for `--rig-name FlexA`).

    Windows:   <root>/<profile>/<profile>.ini   (a folder containing the .ini)
    Linux/Mac: <root>/<profile>.ini             (a flat file)

    <root> is the primary config root (Windows %LOCALAPPDATA%, Linux ~/.config).
    """
    root = wsjtx_config_roots()[0]
    if is_windows():
        return root / profile / f"{profile}.ini"
    return root / f"{profile}.ini"


def wsjtx_config_file_for(rig_name: str) -> Path:
    """The .ini file WSJTX reads/writes for `--rig-name <rig_name>`."""
    return _wsjtx_ini_for_profile(f"WSJT-X - {rig_name}")


def wsjtx_base_config_file() -> Path:
    """The default (no `--rig-name`) WSJTX config .ini."""
    return _wsjtx_ini_for_profile("WSJT-X")


def wsjtx_log_dir_for(rig_name: str) -> Path:
    """
    Directory where WSJTX writes wsjtx_log.adi for `--rig-name <rig_name>` — i.e.
    where the shared-log symlink must live.

    Windows:   the per-rig folder %LOCALAPPDATA%\\WSJT-X - <rig>\\  (config + data)
    Linux/Mac: the DATA dir  $XDG_DATA_HOME/WSJT-X - <rig>/  (separate from config)
    """
    if is_windows():
        return wsjtx_config_roots()[0] / f"WSJT-X - {rig_name}"
    data_root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return data_root / f"WSJT-X - {rig_name}"


def find_existing_wsjtx_configs() -> dict[str, Path]:
    """
    Discover unmanaged WSJTX rig profiles → the path of their config .ini.
    Key is the lowercased rig name (the part after 'WSJT-X - ').

    Windows:   folders  <root>/WSJT-X - <name>/   holding  WSJT-X - <name>.ini
    Linux/Mac: flat files  <root>/WSJT-X - <name>.ini
    """
    found: dict[str, Path] = {}
    prefix = "WSJT-X - "
    root = wsjtx_config_roots()[0]
    if not root.exists():
        return found

    for item in sorted(root.iterdir()):
        if not item.name.startswith(prefix):
            continue
        if is_windows():
            if item.is_dir() and not item.is_symlink():
                ini = item / f"{item.name}.ini"
                name = item.name[len(prefix):].strip().lower()
                if name and ini.is_file():
                    found.setdefault(name, ini)
        else:
            if item.is_file() and item.name.endswith(".ini"):
                name = item.name[len(prefix):-len(".ini")].strip().lower()
                if name:
                    found.setdefault(name, item)
    return found


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

def start_instance(rig_name: str, dry_run: bool = False) -> bool:
    """
    Launch WSJTX for the given rig name.
    """
    info = get_instance(rig_name)
    if not info:
        print(f"[wrig] Unknown instance '{rig_name}'. Run: wrig create {rig_name}")
        return False

    # WSJTX owns its own per-rig config (it reads WSJT-X - <rig>.ini natively via
    # --rig-name); WRIG seeded it at create time and otherwise stays out of the
    # way. The shared-log link is placed at create/relink time. Just launch.
    # If the log link ever breaks (e.g. after remounting the share), run:
    #   wrig relink <rig>
    binary = get_wsjtx_binary()
    if not Path(binary).exists() and not _in_path(binary):
        print(f"[wrig] WSJTX binary not found: {binary}")
        print(f"[wrig]   Edit: {_machine_config_hint()}")
        return False

    cmd = [binary, "--rig-name", rig_name]
    print(f"[wrig] Launching: {' '.join(cmd)}")

    if dry_run:
        print("[wrig] (dry-run - not actually launching)")
        return True

    if is_windows():
        # Detached process on Windows
        subprocess.Popen(
            cmd,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    else:
        subprocess.Popen(cmd, start_new_session=True, close_fds=True)

    return True


def _in_path(binary: str) -> bool:
    import shutil
    return shutil.which(binary) is not None


def _machine_config_hint() -> str:
    from .config import machine_config_path
    return str(machine_config_path())
