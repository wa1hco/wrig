"""
wrig/instance.py — Create, delete, and manage WSJTX instance directories.

Instance directory layout:
  <instances_dir>/<rig_name>/
    wsjtx.ini          ← copied from best-match template, rig-name patched
    wsjtx_log.adi      ← symlink (Linux/Mac) or junction (Windows) → shared log
    wsjtx_log.lck      ← not touched; WSJTX manages this itself

Template selection (best match wins):
  templates/<radio>-<band>-<mode>.ini   exact match
  templates/<radio>-<mode>.ini          radio + mode
  templates/<radio>.ini                 radio only
  templates/default.ini                 fallback
"""

import configparser
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .config import get_instances_dir, get_shared_log_dir, templates_dir, is_windows
from .launcher import (ensure_wsjtx_config_link, find_existing_wsjtx_config_path,
                       wsjtx_config_path_for)
from .registry import (parse_rig_name, register_instance, unregister_instance,
                        instance_exists, get_instance)


LOG_FILENAME = "wsjtx_log.adi"


# ---------------------------------------------------------------------------
# Template selection
# ---------------------------------------------------------------------------

def find_best_template(rig_name: str) -> Optional[Path]:
    """Return path to best-matching template ini, or None if none found."""
    radio, band, mode = parse_rig_name(rig_name)
    tdir = templates_dir()

    candidates = []
    if band:
        candidates.append(tdir / f"{radio}-{band}-{mode}.ini")
        candidates.append(tdir / f"{radio}-{band}.ini")
    candidates.append(tdir / f"{radio}-{mode}.ini")
    candidates.append(tdir / f"{radio}.ini")
    candidates.append(tdir / "default.ini")

    for c in candidates:
        if c.exists():
            return c
    return None


# ---------------------------------------------------------------------------
# INI patching
# ---------------------------------------------------------------------------

def patch_wsjtx_ini(ini_path: Path, rig_name: str, band: str, mode: str) -> None:
    """
    Patch a wsjtx.ini file in-place:
      - Sets [Configuration] → Rig name = <rig_name>
      - Optionally sets Band and Mode if not already set
    
    WSJTX uses a non-standard INI format (no section for top-level keys),
    so we use configparser with a DEFAULT section trick, then write back
    preserving structure as much as possible.
    """
    # WSJTX ini files use a [Configuration] section with many keys.
    # We read as text and do targeted line replacement to avoid
    # configparser reformatting the entire file.
    text = ini_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    
    in_config_section = False
    rig_name_set = False
    new_lines = []

    for line in lines:
        stripped = line.strip()
        
        # Track which section we're in
        if stripped.startswith("["):
            in_config_section = stripped.lower() == "[configuration]"
        
        if in_config_section and stripped.lower().startswith("rig name="):
            line = f"Rig name={rig_name}\n"
            rig_name_set = True
        
        new_lines.append(line)

    # If [Configuration] section exists but had no Rig name key, insert it
    if not rig_name_set:
        final_lines = []
        in_config_section = False
        inserted = False
        for line in new_lines:
            final_lines.append(line)
            if line.strip().lower() == "[configuration]" and not inserted:
                final_lines.append(f"Rig name={rig_name}\n")
                inserted = True
        new_lines = final_lines

    # If there was no [Configuration] section at all, append one
    if not any("[configuration]" in l.lower() for l in new_lines):
        new_lines.append("\n[Configuration]\n")
        new_lines.append(f"Rig name={rig_name}\n")

    ini_path.write_text("".join(new_lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Shared log link
# ---------------------------------------------------------------------------

def create_log_link(instance_dir: Path, rig_name: str) -> None:
    """
    Create a link in the instance directory pointing to the shared log file.

    Linux/Mac: symlink  instance_dir/wsjtx_log.adi → shared_log_dir/wsjtx_log.adi
    Windows:   hardlink (works across same volume) or symlink if Developer Mode on.
               Falls back to copying the file if neither is available.

    The shared log file is created (empty ADI) if it doesn't exist yet.
    """
    shared_dir = get_shared_log_dir()
    shared_log = shared_dir / LOG_FILENAME
    link_path = instance_dir / LOG_FILENAME

    # Ensure shared log directory and file exist
    try:
        shared_dir.mkdir(parents=True, exist_ok=True)
        if not shared_log.exists():
            shared_log.write_text("")
            print(f"[wrig] Created shared log file: {shared_log}")
    except OSError as e:
        print(f"[wrig] WARNING: Could not access shared log dir {shared_dir}: {e}")
        print(f"[wrig]   Instance will use a local log. Mount the share and re-run 'wrig relink {rig_name}' to fix.")
        return

    # Remove existing link/file at destination
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()

    if is_windows():
        _create_windows_link(link_path, shared_log)
    else:
        link_path.symlink_to(shared_log)
        print(f"[wrig] Symlink: {link_path} → {shared_log}")


def _create_windows_link(link_path: Path, target: Path) -> None:
    """
    Windows link strategy:
    1. Try symlink (works if Developer Mode or running as admin)
    2. Fall back to hardlink (works if on same volume — unlikely for SMB)
    3. Fall back to writing a .lnk-style redirect text file + warning
    """
    try:
        link_path.symlink_to(target)
        print(f"[wrig] Symlink: {link_path} → {target}")
        return
    except (OSError, NotImplementedError):
        pass

    try:
        os.link(str(target), str(link_path))
        print(f"[wrig] Hardlink: {link_path} → {target}")
        return
    except OSError:
        pass

    # Last resort: write a redirect file and warn
    redirect_file = link_path.with_suffix(".adi.wrig_redirect")
    redirect_file.write_text(str(target))
    print(f"[wrig] WARNING: Could not create symlink or hardlink on Windows.")
    print(f"[wrig]   To enable symlinks: Settings → Developer Mode → ON")
    print(f"[wrig]   Redirect marker written to: {redirect_file}")
    print(f"[wrig]   Manually set the WSJTX log path to: {target}")


# ---------------------------------------------------------------------------
# Create instance
# ---------------------------------------------------------------------------

def _import_existing_wsjtx_config(rig_name: str, instance_dir: Path) -> bool:
    wsjtx_path = find_existing_wsjtx_config_path(rig_name)
    if not wsjtx_path:
        return False

    print(f"[wrig] Found existing WSJT-X config at: {wsjtx_path}")
    print(f"[wrig] Importing it into managed instance dir: {instance_dir}")

    instance_dir.mkdir(parents=True, exist_ok=True)

    for item in wsjtx_path.iterdir():
        if item.name == LOG_FILENAME:
            continue
        target = instance_dir / item.name
        if target.exists():
            continue
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)

    try:
        shutil.rmtree(wsjtx_path)
    except OSError as e:
        print(f"[wrig] WARNING: could not remove original WSJT-X config dir: {e}")
        return False

    if not ensure_wsjtx_config_link(rig_name, instance_dir, config_path=wsjtx_path):
        print(f"[wrig] WARNING: could not link WSJT-X config path for import.")
        return False

    print(f"[wrig] Replaced original config dir with link: {wsjtx_path} → {instance_dir}")
    return True


def create_instance(rig_name: str, force: bool = False) -> bool:
    """
    Create a new WSJTX instance directory for the given rig name.

    Returns True on success, False if it already exists (unless force=True).
    """
    # Normalize user input: allow passing the full WSJT-X folder name
    # e.g. 'WSJT-X - IC7300' or just 'IC7300'. Strip the prefix if present.
    if rig_name.startswith("WSJT-X - "):
        rig_name = rig_name[len("WSJT-X - "):]

    if instance_exists(rig_name) and not force:
        print(f"[wrig] Instance '{rig_name}' already exists. Use --force to recreate.")
        return False

    radio, band, mode = parse_rig_name(rig_name)
    inst_dir = get_instances_dir() / rig_name

    existing_imported = _import_existing_wsjtx_config(rig_name, inst_dir)

    if not existing_imported:
        inst_dir.mkdir(parents=True, exist_ok=True)

        # --- Find and copy template ---
        template = find_best_template(rig_name)
        ini_dest = inst_dir / "wsjtx.ini"

        if template:
            shutil.copy2(str(template), str(ini_dest))
            print(f"[wrig] Copied template: {template.name} → {ini_dest}")
        else:
            # Write a minimal stub wsjtx.ini
            ini_dest.write_text(_minimal_wsjtx_ini(rig_name))
            print(f"[wrig] No template found — created minimal wsjtx.ini")
            print(f"[wrig]   Add a template to: {templates_dir()}")

        # --- Patch rig name into ini ---
        patch_wsjtx_ini(ini_dest, rig_name, band, mode)
    else:
        ini_dest = inst_dir / "wsjtx.ini"
        if not ini_dest.exists():
            ini_dest.write_text(_minimal_wsjtx_ini(rig_name))
        patch_wsjtx_ini(ini_dest, rig_name, band, mode)

    # --- Create shared log link ---
    create_log_link(inst_dir, rig_name)

    # --- Register ---
    template_name = "imported" if existing_imported else (template.stem if template else "minimal")
    register_instance(rig_name, template_name, radio, band, mode, inst_dir)

    print(f"[wrig] Instance created: {rig_name}")
    print(f"[wrig]   Config dir: {inst_dir}")
    print(f"[wrig]   Radio={radio}  Band={band or '(unset)'}  Mode={mode or '(unset)'}")
    return True


def _minimal_wsjtx_ini(rig_name: str) -> str:
    return f"""\
[Configuration]
Rig name={rig_name}
SaveDirectory=
AzimuthDegrees=0
"""


# ---------------------------------------------------------------------------
# Delete instance
# ---------------------------------------------------------------------------

def delete_instance(rig_name: str, remove_files: bool = False) -> bool:
    """
    Remove an instance from the registry.
    If remove_files=True, also deletes the instance config directory.
    Never touches the shared log file.
    """
    info = get_instance(rig_name)
    if not info:
        print(f"[wrig] Instance '{rig_name}' not found.")
        return False

    if remove_files:
        inst_dir = Path(info["instance_dir"])
        if inst_dir.exists():
            # Safety: don't delete symlink target, only the link itself
            log_link = inst_dir / LOG_FILENAME
            if log_link.is_symlink():
                log_link.unlink()
            shutil.rmtree(str(inst_dir), ignore_errors=True)
            print(f"[wrig] Deleted config dir: {inst_dir}")

    unregister_instance(rig_name)
    print(f"[wrig] Instance '{rig_name}' removed from registry.")
    return True


# ---------------------------------------------------------------------------
# Relink — fix broken log symlink
# ---------------------------------------------------------------------------

def relink_instance(rig_name: str) -> bool:
    """Re-create the shared log symlink for an existing instance."""
    info = get_instance(rig_name)
    if not info:
        print(f"[wrig] Instance '{rig_name}' not found.")
        return False
    inst_dir = Path(info["instance_dir"])
    create_log_link(inst_dir, rig_name)
    return True
