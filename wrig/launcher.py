r"""
wrig/launcher.py — Start and stop WSJTX instances.

WSJTX is launched with:
  wsjtx --rig-name <rig_name>

WSJTX keeps TWO per-rig locations, derived from the rig name (its own feature):
  CONFIG (settings):
    Linux/Mac:  ~/.config/WSJT-X - <rig_name>.ini   (a FLAT FILE, verified)
    Windows:    a flat .ini under %LOCALAPPDATA%     (exact name TBD on Windows)
  LOG/DATA (wsjtx_log.adi, ALL.TXT):
    Linux/Mac:  ~/.local/share/WSJT-X - <rig_name>/  (DIRECTORY; separate from config)
    Windows:    %LOCALAPPDATA%\WSJT-X - <rig_name>\

The shared LOG link is placed in WSJTX's log/data dir (see wsjtx_log_dir_for()
and instance.create_log_link()) — this works.

KNOWN ISSUE (under review): the *_config_link helpers below create a directory
symlink/junction at WSJTX's config path → our instance dir. On Linux WSJTX reads
the flat ~/.config/WSJT-X - <rig>.ini and IGNORES that directory, so the config
redirect (and instance-dir wsjtx.ini seeding) has no effect. To actually seed
config, WRIG would write the flat .ini directly. Pending confirmation of the
Windows config path before reworking. See WINDOWS_HANDOFF.md.
"""

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .config import get_wsjtx_binary, get_instances_dir, is_windows, is_mac
from .registry import get_instance, list_instances


# ---------------------------------------------------------------------------
# WSJTX expected config path
# ---------------------------------------------------------------------------

def wsjtx_config_roots() -> list[Path]:
    """Return the known root directories WSJT-X may use for per-instance config."""
    if is_windows():
        # WSJT-X stores per-rig config under %LOCALAPPDATA% (AppData\Local),
        # NOT %APPDATA% (Roaming). Local must come first: it's both where
        # WSJT-X actually reads and where our junction must be placed.
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        roots = [local]
        if roaming != local:
            roots.append(roaming)  # fallback for discovery of legacy/misplaced configs
        return roots
    else:
        roots = [Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))]
        roots.append(Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")))
        return roots


def wsjtx_config_paths_for(rig_name: str) -> list[Path]:
    return [root / f"WSJT-X - {rig_name}" for root in wsjtx_config_roots()]


def wsjtx_config_path_for(rig_name: str) -> Path:
    """
    Return the preferred path where WSJTX expects to find its config for this rig name.
    This is where we need to place a symlink → our instance dir.
    """
    return wsjtx_config_paths_for(rig_name)[0]


def wsjtx_log_dir_for(rig_name: str, instance_dir: Path) -> Path:
    """
    Return the directory where WSJT-X actually writes wsjtx_log.adi for this
    --rig-name instance. This is where the shared-log symlink must live.

    Windows:   config and log share one dir (%LOCALAPPDATA%\\WSJT-X - <rig>), and
               WRIG junctions that dir to instance_dir, so the log lands in
               instance_dir — return it directly.
    Linux/Mac: WSJT-X writes the log to its DATA dir
               ($XDG_DATA_HOME/WSJT-X - <rig>), which is SEPARATE from the
               config dir WRIG links. The symlink must go there, not in the
               config-side instance dir.
    """
    if is_windows():
        return instance_dir
    data_root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return data_root / f"WSJT-X - {rig_name}"


def find_existing_wsjtx_config_path(rig_name: str) -> Optional[Path]:
    """Return the first existing WSJT-X config path for the given rig name."""
    for path in wsjtx_config_paths_for(rig_name):
        if path.exists() and path.is_dir():
            return path
    return None


def find_existing_wsjtx_configs() -> dict[str, Path]:
    """Discover existing WSJT-X config directories across known roots.
    Excludes symlinks (which are already managed by WRIG).
    """
    found = {}
    for root in wsjtx_config_roots():
        if not root.exists():
            continue
        for item in root.iterdir():
            if item.is_dir() and item.name.startswith("WSJT-X - "):
                # Skip symlinks (already managed by WRIG)
                if item.is_symlink():
                    continue
                name = item.name[len("WSJT-X - "):].lower().strip()
                if name and name not in found:
                    found[name] = item
    return found


def ensure_wsjtx_config_link(rig_name: str, instance_dir: Path, config_path: Optional[Path] = None) -> bool:
    """
    Ensure WSJTX's expected config path points to our instance dir.
    Returns True if link is good, False if it could not be created.
    """
    wsjtx_path = config_path if config_path else wsjtx_config_path_for(rig_name)

    # Already correct symlink?
    if wsjtx_path.is_symlink():
        if wsjtx_path.resolve() == instance_dir.resolve():
            return True
        else:
            wsjtx_path.unlink()  # stale link, replace it

    # Already exists as a real directory (e.g. WSJTX created it)
    if wsjtx_path.exists() and not wsjtx_path.is_symlink():
        # Don't overwrite a real directory — the user may have data there
        print(f"[wrig] WARNING: {wsjtx_path} exists as a real directory.")
        print(f"[wrig]   Move or rename it, then run: wrig relink {rig_name}")
        return False

    wsjtx_path.parent.mkdir(parents=True, exist_ok=True)

    if is_windows():
        return _create_windows_dir_link(wsjtx_path, instance_dir)
    else:
        wsjtx_path.symlink_to(instance_dir)
        return True


def _create_windows_dir_link(link_path: Path, target: Path) -> bool:
    """Create a directory junction on Windows (no admin required)."""
    try:
        # Directory junctions work without admin on Windows
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"[wrig] Junction: {link_path} -> {target}")
            return True
        else:
            print(f"[wrig] WARNING: mklink /J failed: {result.stderr.strip()}")
    except Exception as e:
        print(f"[wrig] WARNING: Could not create junction: {e}")

    # Fallback: try symlink (requires Developer Mode)
    try:
        link_path.symlink_to(target, target_is_directory=True)
        print(f"[wrig] Dir symlink: {link_path} -> {target}")
        return True
    except OSError:
        pass

    print(f"[wrig] MANUAL STEP REQUIRED on Windows:")
    print(f"[wrig]   Run as admin:  mklink /J \"{link_path}\" \"{target}\"")
    print(f"[wrig]   Then re-run:   wrig start {link_path.name.replace('WSJT-X - ', '')}")
    return False


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

    instance_dir = Path(info["instance_dir"])
    if not instance_dir.exists():
        print(f"[wrig] Instance dir missing: {instance_dir}")
        print(f"[wrig]   Run: wrig create {rig_name} --force  to recreate it")
        return False

    # Ensure WSJTX config symlink is in place
    ensure_wsjtx_config_link(rig_name, instance_dir)

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
