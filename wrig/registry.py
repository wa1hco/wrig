"""
wrig/registry.py — JSON registry of known WRIG instances.

Schema:
{
  "flexa-ft8": {
    "created": "2026-06-22T10:00:00",
    "template_used": "seeded",
    "radio": "flexa",
    "band": "",
    "mode": "ft8",
    "config_file": "/home/jeff/.config/WSJT-X - flexa-ft8.ini"
  },
  ...
}

config_file is informational (WSJTX's real per-rig config); WRIG recomputes the
config/log paths from the rig name on demand, so a stale value here is harmless.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import registry_path


def _load() -> dict:
    p = registry_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    registry_path().write_text(json.dumps(data, indent=2))


def list_instances() -> dict:
    return _load()


def get_instance(rig_name: str) -> Optional[dict]:
    return _load().get(rig_name)


def instance_exists(rig_name: str) -> bool:
    return rig_name in _load()


def register_instance(rig_name: str, template_used: str, radio: str, band: str,
                      mode: str, config_file: Path) -> None:
    data = _load()
    data[rig_name] = {
        "created": datetime.now(timezone.utc).isoformat(),
        "template_used": template_used,
        "radio": radio,
        "band": band,
        "mode": mode,
        "config_file": str(config_file),
    }
    _save(data)


def unregister_instance(rig_name: str) -> bool:
    data = _load()
    if rig_name not in data:
        return False
    del data[rig_name]
    _save(data)
    return True


def parse_rig_name(rig_name: str) -> tuple[str, str, str]:
    """
    Parse a rig name into (radio, band, mode).

    Naming convention:  <radio>[-<band>]-<mode>
    Examples:
      flexa-ft8        → radio=flexa,  band='',  mode=ft8
      flexb-msk144     → radio=flexb,  band='',  mode=msk144
      ic7300-2m-ft8    → radio=ic7300, band=2m,  mode=ft8
      ic9700-70cm-ft8  → radio=ic9700, band=70cm,mode=ft8

    Rules:
    - Last segment is always the mode.
    - If there are 3+ segments, the middle one is the band.
    - The first segment(s) are the radio name.

    This is heuristic — any string is a valid rig name, the parse
    is only used for template selection and ini patching.
    """
    KNOWN_BANDS = {"160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m",
                   "12m", "10m", "6m", "4m", "2m", "1.25m", "70cm", "33cm",
                   "23cm", "13cm"}
    KNOWN_MODES = {"ft8", "ft4", "msk144", "jt65", "jt9", "wspr", "q65",
                   "js8", "fst4", "fst4w"}

    parts = rig_name.lower().split("-")
    if len(parts) == 1:
        return rig_name, "", ""

    mode = parts[-1] if parts[-1] in KNOWN_MODES else parts[-1]
    rest = parts[:-1]

    band = ""
    if len(rest) >= 2 and rest[-1] in KNOWN_BANDS:
        band = rest[-1]
        radio = "-".join(rest[:-1])
    else:
        radio = "-".join(rest)

    return radio, band, mode
