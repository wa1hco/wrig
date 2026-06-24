"""
wrig/instance.py — Create, delete, and manage WSJTX rig instances.

Model: "seed once, then step away." WSJTX owns its own per-rig config via
`--rig-name` (it reads WSJT-X - <rig>.ini natively). WRIG does NOT redirect that
config; at create time it seeds WSJTX's real config file from an existing
profile, then leaves WSJTX to manage it. WRIG's lasting job is the shared log.

create_instance(<rig>):
  - config file = launcher.wsjtx_config_file_for(<rig>)
      Linux/Mac: ~/.config/WSJT-X - <rig>.ini            (flat file)
      Windows:   %LOCALAPPDATA%\\WSJT-X - <rig>\\WSJT-X - <rig>.ini
  - if it already exists -> adopt it (don't clobber unless --force)
  - else seed: copy an existing profile, clear radio/audio, patch Rig name;
    fall back to a curated template, then a minimal stub.
  - link wsjtx_log.adi (in WSJTX's log dir) to the one shared NAS log.

Seed source order (find_base_wsjtx_ini): default WSJTX profile -> first existing
per-rig profile.

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

from .config import get_shared_log_dir, templates_dir, is_windows
from .launcher import (wsjtx_config_file_for, wsjtx_base_config_file,
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
      - Sets [Configuration] -> Rig name = <rig_name>
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
    Return an existing WSJTX config .ini to seed a new rig from, or None.

    Priority:
      1) The default WSJTX profile's config (no --rig-name).
      2) The first existing per-rig profile (excluding exclude_rig).

    Paths are resolved per platform by the launcher (flat file on Linux/Mac,
    file-inside-folder on Windows).
    """
    base = wsjtx_base_config_file()
    if base.is_file():
        return base

    exclude = exclude_rig.strip().lower()
    for name, ini in sorted(find_existing_wsjtx_configs().items()):
        if exclude and name == exclude:
            continue
        if ini.is_file():
            return ini

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

def _backup_aside(path: Path, suffix: str) -> Path:
    """
    Rename `path` aside, appending `suffix` (uniquified with a counter if needed),
    so it is never lost when we replace it. Returns the backup path.
    """
    backup = path.with_name(path.name + suffix)
    counter = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}{suffix}{counter}")
        counter += 1
    path.rename(backup)
    return backup


def _backup_local_log(log_path: Path) -> Path:
    """Back up a real (non-symlink) local log before replacing it with a symlink."""
    return _backup_aside(log_path, ".local-backup")


def create_log_link(rig_name: str) -> None:
    """
    Point this rig's WSJT-X log at the single shared log on the NAS.

    WSJT-X writes wsjtx_log.adi into its data/log dir, so the symlink must live
    there (see wsjtx_log_dir_for):
      Linux/Mac: $XDG_DATA_HOME/WSJT-X - <rig>/wsjtx_log.adi -> shared
      Windows:   %LOCALAPPDATA%\\WSJT-X - <rig>\\wsjtx_log.adi -> shared

    The shared log file is created (empty ADI) if it doesn't exist yet. A
    pre-existing *real* local log is backed up, never silently deleted.
    """
    shared_dir = get_shared_log_dir()
    shared_log = shared_dir / LOG_FILENAME

    log_dir = wsjtx_log_dir_for(rig_name)
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
        print(f"[wrig]   Backed it up to {backup} - merge into the shared log if it has QSOs")

    if is_windows():
        _create_windows_link(link_path, shared_log)
    else:
        link_path.symlink_to(shared_log)
        print(f"[wrig] Symlink: {link_path} -> {shared_log}")


def _create_windows_link(link_path: Path, target: Path) -> None:
    """
    Windows link strategy:
    1. Try symlink (works if Developer Mode or running as admin)
    2. Fall back to hardlink (works if on same volume — unlikely for SMB)
    3. Fall back to writing a .lnk-style redirect text file + warning
    """
    try:
        link_path.symlink_to(target)
        print(f"[wrig] Symlink: {link_path} -> {target}")
        return
    except (OSError, NotImplementedError):
        pass

    try:
        os.link(str(target), str(link_path))
        print(f"[wrig] Hardlink: {link_path} -> {target}")
        return
    except OSError:
        pass

    # Last resort: write a redirect file and warn
    redirect_file = link_path.with_suffix(".adi.wrig_redirect")
    redirect_file.write_text(str(target))
    print(f"[wrig] WARNING: Could not create symlink or hardlink on Windows.")
    print(f"[wrig]   To enable symlinks: Settings -> Developer Mode -> ON")
    print(f"[wrig]   Redirect marker written to: {redirect_file}")
    print(f"[wrig]   Manually set the WSJTX log path to: {target}")


# ---------------------------------------------------------------------------
# Create instance
# ---------------------------------------------------------------------------

def create_instance(rig_name: str, force: bool = False) -> bool:
    """
    Set up a WSJTX rig instance: seed its config (if new) and link its log to
    the shared NAS log. WSJTX owns the config thereafter.

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
    config_file = wsjtx_config_file_for(rig_name)

    if config_file.exists() and not force:
        # WSJTX already has a config for this rig — adopt it untouched.
        template_name = "existing"
        print(f"[wrig] Using existing WSJTX config: {config_file}")
    else:
        config_file.parent.mkdir(parents=True, exist_ok=True)

        # --force over an existing config: back it up before reseeding.
        if config_file.exists():
            backup = _backup_aside(config_file, ".bak")
            print(f"[wrig] Backed up existing config to {backup}")

        seed_ini = find_base_wsjtx_ini(exclude_rig=rig_name)
        if seed_ini and seed_ini.resolve() != config_file.resolve():
            shutil.copy2(str(seed_ini), str(config_file))
            scrub_radio_audio_settings(config_file)
            template_name = "seeded"
            print(f"[wrig] Seeded config from existing profile: {seed_ini}")
            print(f"[wrig]   -> {config_file} (radio/audio cleared)")
        else:
            template = find_best_template(rig_name)
            if template:
                shutil.copy2(str(template), str(config_file))
                template_name = template.stem
                print(f"[wrig] Seeded config from template: {template.name} -> {config_file}")
            else:
                config_file.write_text(_minimal_wsjtx_ini(rig_name))
                template_name = "minimal"
                print(f"[wrig] No profile or template found - wrote minimal config: {config_file}")
                print(f"[wrig]   Add a template to: {templates_dir()}")

        # Patch rig name into the config (also re-adds Rig name after scrub).
        patch_wsjtx_ini(config_file, rig_name, band, mode)

    # --- Link this rig's log to the shared NAS log ---
    create_log_link(rig_name)

    # --- Register ---
    register_instance(rig_name, template_name, radio, band, mode, config_file)

    print(f"[wrig] Instance ready: {rig_name}")
    print(f"[wrig]   Config: {config_file}")
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
    Unregister an instance. With remove_files=True, also drop this rig's WSJTX
    config .ini and the shared-log symlink. Never touches the shared log target,
    and leaves WSJTX's other data (ALL.TXT, save/) alone.
    """
    info = get_instance(rig_name)
    if not info:
        print(f"[wrig] Instance '{rig_name}' not found.")
        return False

    if remove_files:
        # Remove the shared-log symlink (the link only — never the NAS target).
        log_link = wsjtx_log_dir_for(rig_name) / LOG_FILENAME
        if log_link.is_symlink():
            log_link.unlink()
            print(f"[wrig] Removed log link: {log_link}")

        # Remove this rig's WSJTX config .ini.
        config_file = wsjtx_config_file_for(rig_name)
        if config_file.is_file():
            config_file.unlink()
            print(f"[wrig] Removed config: {config_file}")

    unregister_instance(rig_name)
    print(f"[wrig] Instance '{rig_name}' removed from registry.")
    return True


# ---------------------------------------------------------------------------
# Relink — re-create the shared-log symlink
# ---------------------------------------------------------------------------

def relink_instance(rig_name: str) -> bool:
    """Re-create the shared-log symlink in WSJT-X's log dir (e.g. after the
    share was remounted, or to repair a link placed by an earlier version)."""
    info = get_instance(rig_name)
    if not info:
        print(f"[wrig] Instance '{rig_name}' not found.")
        return False
    create_log_link(rig_name)
    return True
