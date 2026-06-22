"""
wrig/picker.py — Interactive instance picker with prefix filtering.

Used when the user runs `wrig start` with no argument or a partial name.
If fzf is available, uses it for a fuzzy picker.
Otherwise falls back to a numbered menu.
"""

import shutil
import subprocess
import sys
from typing import Optional

from .registry import list_instances


def pick_instance(prefix: str = "") -> Optional[str]:
    """
    Present the user with a list of known instances filtered by prefix.
    Returns the selected rig name, or None if cancelled.
    """
    instances = list_instances()
    names = sorted(instances.keys())

    if prefix:
        filtered = [n for n in names if n.lower().startswith(prefix.lower())]
    else:
        filtered = names

    if not filtered:
        if prefix:
            print(f"[wrig] No instances matching '{prefix}'.")
            print(f"[wrig] Known instances: {', '.join(names) or '(none)'}")
        else:
            print("[wrig] No instances found. Run: wrig create <rig-name>")
        return None

    if len(filtered) == 1:
        return filtered[0]

    # Try fzf first
    if shutil.which("fzf"):
        return _pick_with_fzf(filtered, instances)

    # Fallback: numbered menu
    return _pick_with_menu(filtered, instances)


def _pick_with_fzf(names: list, instances: dict) -> Optional[str]:
    lines = []
    for name in names:
        info = instances[name]
        label = f"{name:<25}  radio={info.get('radio','?')}  band={info.get('band','') or '—'}  mode={info.get('mode','?')}"
        lines.append(label)

    input_text = "\n".join(lines)
    try:
        result = subprocess.run(
            ["fzf", "--prompt", "WSJTX instance> ", "--height", "40%",
             "--layout", "reverse", "--info", "inline"],
            input=input_text, capture_output=True, text=True
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        selected_label = result.stdout.strip()
        # First word is the rig name
        return selected_label.split()[0]
    except Exception:
        return _pick_with_menu(names, instances)


def _pick_with_menu(names: list, instances: dict) -> Optional[str]:
    print("\nAvailable WSJTX instances:")
    print(f"  {'#':<4} {'Rig Name':<25} {'Radio':<10} {'Band':<6} {'Mode'}")
    print(f"  {'-'*4} {'-'*25} {'-'*10} {'-'*6} {'-'*10}")
    for i, name in enumerate(names, 1):
        info = instances[name]
        print(f"  {i:<4} {name:<25} {info.get('radio','?'):<10} "
              f"{info.get('band','') or '—':<6} {info.get('mode','?')}")
    print()
    try:
        choice = input("Enter number (or rig name, or Enter to cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if not choice:
        return None

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(names):
            return names[idx]
        print("[wrig] Invalid number.")
        return None

    # Treat as partial name
    matches = [n for n in names if n.lower().startswith(choice.lower())]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"[wrig] Ambiguous: {', '.join(matches)}")
    else:
        print(f"[wrig] No match for '{choice}'.")
    return None
