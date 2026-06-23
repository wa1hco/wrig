"""
wrig/instance.py — Create, delete, and manage WSJTX instance directories.

Instance (CONFIG) directory layout:
  <instances_dir>/<rig_name>/
    wsjtx.ini          ← seeded from an existing profile, else templated/stub;
                         rig-name patched
WSJTX reads config from here via a link from its expected config path.

The shared LOG link is NOT here — WSJTX writes wsjtx_log.adi to its log dir,
which on Linux/Mac is a SEPARATE folder (~/.local/share/WSJT-X - <rig>/) and on
Windows is the same folder as config. create_log_link() places the symlink there
(see launcher.wsjtx_log_dir_for).

wsjtx.ini source order (first that applies): import existing → seed from an
existing profile (clearing radio/audio) → best-match template → minimal stub.

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
                       wsjtx_config_path_for, wsjtx_config_roots,
                       find_existing_wsjtx_configs, wsjtx_log_dir_for)
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


def find_base_wsjtx_ini(exclude_rig: str = "") -> Optional[Path]:
    """
    Return a wsjtx.ini file to seed a new WRIG instance, or None.

    Seed priority:
      1) Base WSJT-X profile:        <config-root>/WSJT-X/wsjtx.ini
      2) First unmanaged rig profile: <config-root>/WSJT-X - <name>/wsjtx.ini
      3) First existing WRIG instance: <instances>/<rig>/wsjtx.ini (excluding exclude_rig)
    """
    for root in wsjtx_config_roots():
        candidate = root / "WSJT-X" / "wsjtx.ini"
        if candidate.is_file():
            return candidate

    discovered = find_existing_wsjtx_configs()
    for _, cfg_dir in sorted(discovered.items()):
        candidate = cfg_dir / "wsjtx.ini"
        if candidate.is_file():
            return candidate

    inst_root = get_instances_dir()
    if inst_root.is_dir():
        for inst_dir in sorted(inst_root.iterdir()):
            if not inst_dir.is_dir():
                continue
            if exclude_rig and inst_dir.name == exclude_rig:
                continue
            candidate = inst_dir / "wsjtx.ini"
            if candidate.is_file():
                return candidate

    return None


def scrub_radio_audio_settings(ini_path: Path) -> None:
    """
    Remove transport-specific keys from the [Configuration] section so a cloned
    profile keeps general defaults but drops stale radio/audio bindings.
    Keys are matched case-insensitively by prefix.
    """
    scrub_prefixes = (
        "rig",
        "cat",
        "ptt",
        "audio",
        "sound",
        "microphone",
        "speaker",
        "input device",
        "output device",
    )

    text = ini_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    in_config_section = False
    filtered = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("["):
            in_config_section = stripped.lower() == "[configuration]"
            filtered.append(line)
            continue

        if in_config_section and "=" in stripped and not stripped.startswith((";", "#")):
            key = stripped.split("=", 1)[0].strip().lower()
            if key.startswith(scrub_prefixes):
                continue

        filtered.append(line)

    ini_path.write_text("".join(filtered), encoding="utf-8")


# ---------------------------------------------------------------------------
# Shared log link
# ---------------------------------------------------------------------------

def _backup_local_log(log_path: Path) -> Path:
    """
    Rename a real (non-symlink) local log aside so it is never lost when we
    replace it with a symlink to the shared log. Returns the backup path.
    """
    backup = log_path.with_name(log_path.name + ".local-backup")
    counter = 1
    while backup.exists():
        backup = log_path.with_name(f"{log_path.name}.local-backup{counter}")
        counter += 1
    log_path.rename(backup)
    return backup


def create_log_link(instance_dir: Path, rig_name: str) -> None:
    """
    Point this instance's WSJT-X log at the single shared log on the NAS.

    WSJT-X writes wsjtx_log.adi into its data/log dir, so the symlink must live
    there (see wsjtx_log_dir_for):
      Linux/Mac: $XDG_DATA_HOME/WSJT-X - <rig>/wsjtx_log.adi → shared
      Windows:   instance_dir\\wsjtx_log.adi → shared  (config == log dir, junctioned)

    The shared log file is created (empty ADI) if it doesn't exist yet. A
    pre-existing *real* local log is backed up, never silently deleted.
    """
    shared_dir = get_shared_log_dir()
    shared_log = shared_dir / LOG_FILENAME

    log_dir = wsjtx_log_dir_for(rig_name, instance_dir)
    link_path = log_dir / LOG_FILENAME

    # Ensure shared log directory and file exist (the NAS is the source of truth)
    try:
        shared_dir.mkdir(parents=True, exist_ok=True)
        if not shared_log.exists():
            shared_log.write_text("")
            print(f"[wrig] Created shared log file: {shared_log}")
    except OSError as e:
        print(f"[wrig] WARNING: Could not access shared log dir {shared_dir}: {e}")
        print(f"[wrig]   Instance will use a local log. Mount the share and re-run 'wrig relink {rig_name}' to fix.")
        return

    # WSJT-X may not have created its log dir yet (Linux/Mac data dir); ensure it.
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"[wrig] WARNING: Could not create WSJT-X log dir {log_dir}: {e}")
        return

    # Replace whatever is at the destination — but never destroy a real local
    # log; a stale symlink is safe to drop, a real file gets backed up first.
    if link_path.is_symlink():
        link_path.unlink()
    elif link_path.exists():
        backup = _backup_local_log(link_path)
        print(f"[wrig] Found a real local log at {link_path}")
        print(f"[wrig]   Backed it up to {backup} — merge into the shared log if it has QSOs")

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

    # Records how the instance config was sourced (for the registry).
    template_name = "imported" if existing_imported else ""

    if not existing_imported:
        inst_dir.mkdir(parents=True, exist_ok=True)
        ini_dest = inst_dir / "wsjtx.ini"

        # --- Prefer seeding from an existing WSJT-X / WRIG profile ---
        seed_ini = find_base_wsjtx_ini(exclude_rig=rig_name)
        if seed_ini:
            shutil.copy2(str(seed_ini), str(ini_dest))
            scrub_radio_audio_settings(ini_dest)
            template_name = "seeded"
            print(f"[wrig] Seeded from existing profile: {seed_ini} → {ini_dest}")
            print(f"[wrig]   Scrubbed radio/audio settings from seeded profile")
        else:
            # --- Fall back to copying a curated template ---
            template = find_best_template(rig_name)
            if template:
                shutil.copy2(str(template), str(ini_dest))
                template_name = template.stem
                print(f"[wrig] Copied template: {template.name} → {ini_dest}")
            else:
                # Write a minimal stub wsjtx.ini
                ini_dest.write_text(_minimal_wsjtx_ini(rig_name))
                template_name = "minimal"
                print(f"[wrig] No template found — created minimal wsjtx.ini")
                print(f"[wrig]   Add a template to: {templates_dir()}")

        # --- Patch rig name into ini (also re-adds Rig name after scrub) ---
        patch_wsjtx_ini(ini_dest, rig_name, band, mode)
    else:
        ini_dest = inst_dir / "wsjtx.ini"
        if not ini_dest.exists():
            ini_dest.write_text(_minimal_wsjtx_ini(rig_name))
        patch_wsjtx_ini(ini_dest, rig_name, band, mode)

    # --- Create shared log link ---
    create_log_link(inst_dir, rig_name)

    # --- Register ---
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
    """Re-create the shared-log symlink in WSJT-X's log dir for an existing instance.

    Also repairs instances whose log link was placed in the wrong directory by
    an earlier version (config dir instead of the data dir WSJT-X logs to).
    """
    info = get_instance(rig_name)
    if not info:
        print(f"[wrig] Instance '{rig_name}' not found.")
        return False
    inst_dir = Path(info["instance_dir"])
    create_log_link(inst_dir, rig_name)
    return True
