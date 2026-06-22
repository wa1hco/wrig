# WRIG — WSJTX rig-name Manager

Create and launch multiple WSJTX instances, each with its own config directory and
a shared log file on a TrueNAS (or any network) share.

## Quick Start

```bash
cd /home/jeff/ham/wrig
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
wrig config               # see paths, edit machine.ini
wrig create flexa-ft8     # create first instance
wrig start flexa-ft8      # launch it
```

If `wrig` is not yet on your PATH, use the CLI directly:

```bash
python3 -m wrig.cli config
```

If your Python is externally managed by the OS (Debian/Ubuntu PEP 668), the `venv` workflow above is the reliable install path.

## Rig Name Convention

```
<radio>[-<band>]-<mode>
```

| Rig Name         | Radio   | Band | Mode    |
|-----------------|---------|------|---------|
| `flexa-ft8`     | flexa   | —    | ft8     |
| `flexb-msk144`  | flexb   | —    | msk144  |
| `ic7300-2m-ft8` | ic7300  | 2m   | ft8     |
| `ic9700-70cm-q65` | ic9700 | 70cm | q65   |

Any string is a valid rig name — the parsing is only used for template
selection and display.

## How It Works

### Instance directories

Each instance gets its own config directory under `~/.config/wrig/instances/<rig-name>/`.
WRIG creates a symlink (Linux/Mac) or directory junction (Windows) from WSJTX's expected
config path to that directory:

```
~/.config/WSJT-X - flexa-ft8   →   ~/.config/wrig/instances/flexa-ft8/
```

WSJTX finds its config normally via `--rig-name flexa-ft8`; it just happens to
land in the WRIG-managed directory.

### Shared log

`wsjtx_log.adi` inside each instance directory is a symlink pointing to a single
shared log file on your TrueNAS share:

```
~/.config/wrig/instances/flexa-ft8/wsjtx_log.adi
    → /mnt/Users/share/wsjtx_log.adi
```

All instances append to the same ADI file regardless of band or mode.
WSJTX's own locking prevents corruption during simultaneous writes
(which rarely happen in multi-band SO2R operation anyway).

### Template configs

When creating an instance, WRIG copies the best-matching template from
`~/.config/wrig/templates/` and patches the `Rig name=` field:

```
templates/
  flexa.ini          # FlexRadio A — CAT port, audio device, etc.
  flexb.ini          # FlexRadio B
  ic7300.ini         # IC-7300
  ic9700.ini         # IC-9700
  default.ini        # fallback if no match
```

Template selection order for `ic7300-2m-ft8`:
1. `ic7300-2m-ft8.ini`   (exact)
2. `ic7300-2m.ini`
3. `ic7300-ft8.ini`
4. `ic7300.ini`          ← matches here
5. `default.ini`

**Populate your templates by copying your working wsjtx.ini files:**

```bash
cp ~/.config/WSJT-X/wsjtx.ini ~/.config/wrig/templates/flexa.ini
cp ~/.config/WSJT-X\ -\ flex/wsjtx.ini ~/.config/wrig/templates/flexb.ini
```

WRIG also discovers existing WSJT-X config directories under
`~/.config/WSJT-X - <rig-name>` and `~/.local/share/WSJT-X - <rig-name>`.
If you run `wrig create <rig-name>` and an existing WSJT-X directory exists,
WRIG will import that configuration instead of creating a fresh instance.

## Commands

```
wrig create <rig-name> [--force]
    Create a new instance. If an existing WSJT-X config directory already
    exists for that rig name, WRIG will import it and register it. Otherwise
    it copies the best-match template, patches Rig name, and creates the shared
    log symlink.

wrig start [<rig-name-or-prefix>]
    Launch WSJTX. If name is omitted or a prefix, shows an interactive picker.
    Uses fzf if available, otherwise a numbered menu.
    --dry-run   Print the launch command without running it.

wrig list
    Show all registered instances.
    Also discovers existing WSJT-X config directories that are not yet
    registered with WRIG.

wrig delete <rig-name> [--files] [--yes]
    Remove from registry. --files also deletes the config directory.
    Never touches the shared log.

wrig relink <rig-name>
    Re-create the shared log symlink (useful after remounting the share).

wrig config
    Show all WRIG paths and print machine.ini.

wrig completion bash|zsh|fish
    Print a shell completion script.

    bash:   eval "$(wrig completion bash)"    # add to ~/.bashrc
    zsh:    eval "$(wrig completion zsh)"     # add to ~/.zshrc
    fish:   wrig completion fish > ~/.config/fish/completions/wrig.fish
```

## Machine Configuration

On first use, WRIG creates `~/.config/wrig/machine.ini` (Linux/Mac) or
`%APPDATA%\wrig\machine.ini` (Windows). Edit it once per machine:

```ini
[machine]
wsjtx_binary   = /usr/bin/wsjtx
shared_log_dir = /mnt/Users/share
```

Windows example:
```ini
[machine]
wsjtx_binary   = C:\WSJT\bin\wsjtx.exe
shared_log_dir = \\192.168.1.5\Users\share
```

## Installation

### Linux (Ubuntu)

```bash
git clone https://github.com/yourname/wrig.git
cd wrig
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Tab completion (bash):
echo 'eval "$(wrig completion bash)"' >> ~/.bashrc
source ~/.bashrc
```

If `wrig` is not available immediately, use:

```bash
python3 -m wrig.cli --help
```

> On Debian/Ubuntu with an externally managed Python, `pip install --user` may fail.
> Use the `venv` workflow above instead.

### Windows

```powershell
git clone https://github.com/yourname/wrig.git
cd wrig
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

If `wrig` is not available immediately, use:

```powershell
python -m wrig.cli --help
```

**Windows note on symlinks:** WRIG uses directory junctions to point
WSJTX's config path to the WRIG instance directory — these work without
admin rights. For the shared log file symlink, either enable Developer Mode
(`Settings → System → For Developers → Developer Mode`) or, if the TrueNAS
share is on a different volume (it usually is), use a hardlink workaround.
If neither works, WRIG will warn you and print the manual `mklink` command.

### macOS

Same as Linux. Not tested — patches welcome.

## File Layout

```
~/.config/wrig/
  machine.ini              ← edit once per machine
  registry.json            ← list of known instances (auto-managed)
  templates/
    flexa.ini              ← copy your working wsjtx.ini files here
    flexb.ini
    ic7300.ini
    default.ini
  instances/
    flexa-ft8/
      wsjtx.ini            ← copied from template, rig-name patched
      wsjtx_log.adi        ← symlink → /mnt/Users/share/wsjtx_log.adi
    flexb-msk144/
      wsjtx.ini
      wsjtx_log.adi        ← same symlink target
    ...

# WSJTX's own config lookup path (symlink created by wrig):
~/.config/WSJT-X - flexa-ft8   →   ~/.config/wrig/instances/flexa-ft8/

# Shared TrueNAS log:
/mnt/Users/share/wsjtx_log.adi
```
