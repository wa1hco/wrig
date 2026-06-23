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

WSJTX keeps two separate per-rig folders, and WRIG touches both. **This split is
the single most important thing to understand:**

| What | WSJTX path for `--rig-name flexa-ft8` | WRIG's job |
|------|----------------------------------------|------------|
| **Config** (`wsjtx.ini`) | Linux/Mac: `~/.config/WSJT-X - flexa-ft8/`<br>Windows: `%LOCALAPPDATA%\WSJT-X - flexa-ft8\` | Link the folder to the WRIG instance dir |
| **Log / data** (`wsjtx_log.adi`, `ALL.TXT`) | Linux/Mac: `~/.local/share/WSJT-X - flexa-ft8/`<br>Windows: `%LOCALAPPDATA%\WSJT-X - flexa-ft8\` *(same folder as config)* | Link `wsjtx_log.adi` to the shared NAS log |

On **Linux/Mac** config and log are two *different* folders; on **Windows** they
are the *same* folder. That is why the shared-log link does **not** sit next to
`wsjtx.ini` on Linux.

### Instance directories (config)

Each instance gets its own config directory under `~/.config/wrig/instances/<rig-name>/`.
WRIG points WSJTX's config path at it with a symlink (Linux/Mac) or directory
junction (Windows):

```
Linux/Mac:  ~/.config/WSJT-X - flexa-ft8       →  ~/.config/wrig/instances/flexa-ft8/
Windows:    %LOCALAPPDATA%\WSJT-X - flexa-ft8   →  ...\wrig\instances\flexa-ft8\
```

WSJTX finds its config normally via `--rig-name flexa-ft8`; it just happens to
land in the WRIG-managed directory.

### Shared log (one file on the NAS)

There is exactly **one** `wsjtx_log.adi`, and it lives on your TrueNAS share.
Every instance — on every PC, Windows or Linux — points its WSJTX log at that
one file, so "worked before" colouring and dupe checking are shared across all
rigs and machines.

WRIG places the symlink in **WSJTX's log directory** (the right column above),
not in the config dir:

```
Linux/Mac:  ~/.local/share/WSJT-X - flexa-ft8/wsjtx_log.adi  →  <shared_log_dir>/wsjtx_log.adi
Windows:    %LOCALAPPDATA%\WSJT-X - flexa-ft8\wsjtx_log.adi   →  <shared_log_dir>\wsjtx_log.adi
```

`<shared_log_dir>` is set once per machine in `machine.ini` (see
[Machine Configuration](#machine-configuration)). All instances append to the
same ADI file regardless of band or mode; WSJTX's own file locking prevents
corruption during simultaneous writes (rare in multi-band SO2R operation anyway).

If WRIG finds a **real** (non-symlink) `wsjtx_log.adi` already in a log dir, it
renames it to `wsjtx_log.adi.local-backup` before linking — it never deletes a
local log that might hold un-merged QSOs.

### Instance config: seeding and templates

When you create an instance, WRIG fills in `wsjtx.ini` from the first source
that applies:

1. **Import** — if a WSJTX config dir already exists for that rig name, WRIG
   adopts it in place and links it.
2. **Seed from an existing profile** *(default)* — copy a known-good `wsjtx.ini`
   (your base `WSJT-X/wsjtx.ini`, an unmanaged `WSJT-X - <rig>` profile, or
   another WRIG instance) and **keep everything** — colours, logging, operator
   checkboxes, MyCall/MyGrid — while **clearing only the radio/audio/CAT/PTT
   keys**, so you pick the rig and sound device for this instance. `Rig name=`
   is then set to match.
3. **Template** — if no profile is found, copy the best match from
   `~/.config/wrig/templates/` (order below).
4. **Minimal stub** — if there is no template either, write a 4-line placeholder.

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
`~/.config/WSJT-X - <rig-name>` (Linux/Mac) or `%LOCALAPPDATA%\WSJT-X - <rig-name>`
(Windows). If one exists when you run `wrig create <rig-name>`, WRIG imports that
configuration instead of creating a fresh instance.

## Commands

```
wrig create <rig-name> [--force]
    Create a new instance. If an existing WSJT-X config directory already
    exists for that rig name, WRIG imports it. Otherwise it fills in wsjtx.ini
    by seeding from an existing profile (clearing radio/audio), or falls back to
    a template, then a minimal stub. Either way it patches Rig name and links
    wsjtx_log.adi (in WSJTX's log dir) to the shared NAS log.

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
    Re-create the shared-log symlink in WSJTX's log dir (useful after remounting
    the share, or to repair an instance whose log link was misplaced).

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
`%APPDATA%\wrig\machine.ini` (Windows). Edit it once per machine.

`shared_log_dir` is the **directory that holds the single shared `wsjtx_log.adi`**
on your NAS — the same file for every machine, named however that machine reaches
the share.

Linux/Mac (NAS mounted at a local path):
```ini
[machine]
wsjtx_binary   = /usr/bin/wsjtx
shared_log_dir = /mnt/nas/share
```

Windows (UNC path to the NAS):
```ini
[machine]
wsjtx_binary   = C:\WSJT\bin\wsjtx.exe
shared_log_dir = \\192.168.1.5\share
```

### Reaching the NAS on Windows: UNC vs mapped drive

WRIG links each instance's `wsjtx_log.adi` to `<shared_log_dir>\wsjtx_log.adi`.
That link is a **symbolic link** (the only link type that can cross to a network
share — junctions and hardlinks cannot). Two things matter:

- **Creating** the symlink needs the symlink privilege → turn on **Developer
  Mode** (`Settings → Privacy & security → For developers`). Then WRIG creates
  it without running as administrator.
- **The target** can be written two ways, with a trade-off:

| `shared_log_dir` | Pros | Watch out for |
|------------------|------|----------------|
| **UNC** `\\192.168.1.5\share` | Clean, self-describing, nothing to mount | No stored credentials (fine for an open/guest share; otherwise first access can be "access denied"); resolving a local→remote symlink relies on Windows' default L2R evaluation, which some locked-down machines disable |
| **Mapped drive** `Z:\` (mapped to that UNC, persistent) | Authenticates once, reconnects at logon, sidesteps the L2R caveat | One extra setup step per machine: `net use Z: \\192.168.1.5\share /persistent:yes` |

UNC is the simplest to explain and works on a typical open TrueNAS share. If the
share needs credentials or the PC restricts remote symlink evaluation, prefer a
persistent mapped drive. Either way it is just the `shared_log_dir` string —
switch any time by editing `machine.ini` and re-running `wrig relink <rig>`.

### Recommended setup: a dedicated NAS folder + mapped drive

Give the shared log its own folder on the NAS rather than dropping it in a
general share, and map just that folder:

1. On the NAS, create a folder, e.g. `\\192.168.1.5\share\wrig\`.
2. Move your existing `wsjtx_log.adi` into it (keeps your QSO history).
3. **Windows** — map it to a drive and point `machine.ini` at the drive:
   ```
   net use W: \\192.168.1.5\share\wrig /persistent:yes
   ```
   ```ini
   shared_log_dir = W:\
   ```
4. **Linux/Mac** — mount/point at the same folder, e.g. `shared_log_dir = /mnt/wrig`.

Keep that folder **lean — just the shared log** (optionally a `backups/` subdir;
one shared file is a single point of failure, so periodic copies are cheap
insurance). Do **not** put per-machine files there: `machine.ini`, `registry.json`,
per-rig `wsjtx.ini`, and `ALL.TXT` all stay local to each PC.

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

**Windows note on links:** WRIG points WSJTX's config path at the instance dir
with a **directory junction** — that works without admin rights. The shared-log
link is a **symbolic link** to the NAS, which junctions/hardlinks cannot do, so
enable **Developer Mode** (`Settings → Privacy & security → For developers`) once;
WRIG then creates it without administrator rights. See
[Reaching the NAS on Windows](#reaching-the-nas-on-windows-unc-vs-mapped-drive)
for the UNC-vs-mapped-drive trade-off. If link creation fails, WRIG warns and
prints the manual `mklink` command to run from an elevated prompt.

### macOS

Same as Linux. Not tested — patches welcome.

## File Layout (Linux/Mac)

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
      wsjtx.ini            ← seeded/templated, rig-name patched (CONFIG only)
    flexb-msk144/
      wsjtx.ini
    ...

# CONFIG: WSJTX's config lookup path → WRIG instance dir (symlink by wrig)
~/.config/WSJT-X - flexa-ft8         →  ~/.config/wrig/instances/flexa-ft8/

# LOG: WSJTX's data/log dir holds the shared-log symlink (placed by wrig)
~/.local/share/WSJT-X - flexa-ft8/wsjtx_log.adi  →  <shared_log_dir>/wsjtx_log.adi
~/.local/share/WSJT-X - flexb-msk144/wsjtx_log.adi  →  <shared_log_dir>/wsjtx_log.adi

# The one shared log on the NAS:
<shared_log_dir>/wsjtx_log.adi
```

On **Windows** there is no `~/.local/share` split: config and log share
`%LOCALAPPDATA%\WSJT-X - <rig>\`, which WRIG junctions to the instance dir, so
`wsjtx.ini` and the `wsjtx_log.adi` symlink both land there.
