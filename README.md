# WRIG — WSJTX rig-name Manager

Create and launch multiple WSJTX instances, each with its own config directory and
a shared log file on a TrueNAS (or any network) share.

## Quick Start

### Linux / macOS

```bash
cd ~/ham/wrig
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
wrig config               # see paths, edit machine.ini
wrig create flexa-ft8     # create first instance
wrig start flexa-ft8      # launch it
```

If `wrig` is not yet on your PATH, use the CLI directly: `python3 -m wrig.cli config`

If your Python is externally managed by the OS (Debian/Ubuntu PEP 668), the `venv` workflow above is the reliable install path.

### Windows

A venv is not required — install directly:

```powershell
cd $HOME\Documents\wrig
pip install -e .
wrig config               # see paths, edit machine.ini
wrig create flexa-ft8     # create first instance
wrig start flexa-ft8      # launch it
```

If `wrig` is not yet on your PATH, use the CLI directly: `python -m wrig.cli config`

> If you just ran `pip install -e .`, open a **new** PowerShell window so the updated PATH takes effect before calling `wrig`.

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

### How WSJTX itself stores per-rig files

`wsjtx --rig-name NAME` is a **built-in WSJTX feature**: WSJTX appends ` - NAME`
to its own config and data locations. Config and data are **separate**, and on
Linux they are even different *kinds* of object:

| | Linux/Mac *(verified)* | Windows *(to be confirmed — see [Verifying on Windows](#verifying-wsjtx-paths-on-windows))* |
|---|---|---|
| **Settings** | a flat **file** `~/.config/WSJT-X - NAME.ini` | a flat `.ini` under `%LOCALAPPDATA%` |
| **Data + log** | a **directory** `~/.local/share/WSJT-X - NAME/`<br>(`wsjtx_log.adi`, `ALL.TXT`, `save/`, …) | `%LOCALAPPDATA%\WSJT-X - NAME\` |

(Without `--rig-name` it's plain `~/.config/WSJT-X.ini` + `~/.local/share/WSJT-X/`.)
The per-rig separation is WSJTX's doing — WRIG does not create it.

### What WRIG manages

WRIG launches `wsjtx --rig-name <rig-name>` and adds the things WSJTX doesn't do
itself:

- **Shared log** — the main feature (below).
- **Registry** of known instances, an interactive **picker**, and shell
  **completion**.

### Shared log (one file on the NAS)

There is exactly **one** `wsjtx_log.adi`, and it lives on your TrueNAS share.
WRIG places a symlink in **WSJTX's log directory** (the data dir above) pointing
at it, so "worked before" colouring and dupe checking are shared across all rigs
and every PC:

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

### ⚠️ Config seeding — under review

WRIG *also* creates an instance dir under `~/.config/wrig/instances/<rig-name>/`,
a directory symlink `~/.config/WSJT-X - <rig-name>` → that dir, and seeds a
`wsjtx.ini` there (copy an existing profile, clear radio/audio, patch `Rig name`).

**On Linux this does not affect WSJTX's configuration:** WSJTX reads the flat
file `~/.config/WSJT-X - NAME.ini` (see table above) and ignores both the
directory symlink and the seeded `wsjtx.ini`. The per-rig config you get comes
from WSJTX's native `--rig-name`, not from this layer. The seeding/redirect
mechanism is being reworked to target the flat `.ini` directly (or be removed);
the Windows config path is being confirmed first. **The shared-log feature above
is unaffected and works.**

## Commands

```
wrig create <rig-name> [--force]
    Register a new instance and link wsjtx_log.adi (in WSJTX's log dir) to the
    shared NAS log. It also seeds an instance-dir wsjtx.ini, but note: WSJTX
    reads its own flat WSJT-X - <name>.ini, so that seeding currently does not
    configure WSJTX (see "Config seeding — under review").

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
shared_log_dir = /media/share/WRIG/
```

Windows (UNC path to the NAS):
```ini
[machine]
wsjtx_binary   = C:\WSJT\bin\wsjtx.exe
shared_log_dir = \\192.168.1.5\share\WRIG
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

### Verifying WSJTX paths on Windows

The Linux paths above are confirmed; the Windows config path/filename still needs
checking on a real Windows box. Run these in `cmd` after launching a rig at least
once (`wsjtx --rig-name TEST`), and see [`WINDOWS_HANDOFF.md`](WINDOWS_HANDOFF.md)
for the full investigation + shared-log test checklist:

```cmd
dir "%LOCALAPPDATA%" | findstr /i WSJT
dir "%LOCALAPPDATA%\WSJT-X*"
dir "%APPDATA%" | findstr /i WSJT
where /r "%LOCALAPPDATA%" wsjtx_log.adi
```

This tells us whether WSJTX uses a flat `WSJT-X - TEST.ini`, a nested
`WSJT-X\...`, or a per-rig folder — which decides how the config layer is reworked.

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

A venv is not required on Windows — install directly:

```powershell
git clone https://github.com/yourname/wrig.git
cd wrig
pip install -e .
```

If `wrig` is not available immediately, open a new PowerShell window (to refresh PATH), or use:

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
# --- What WSJTX actually reads/writes (created by WSJTX via --rig-name) ---
~/.config/WSJT-X - flexa-ft8.ini                 ← CONFIG (flat file; WSJTX owns it)
~/.local/share/WSJT-X - flexa-ft8/               ← DATA dir (WSJTX owns it)
  wsjtx_log.adi  →  <shared_log_dir>/wsjtx_log.adi   ← shared-log symlink (placed by wrig)
  ALL.TXT, save/, db.sqlite, ...                     ← stays local

# The one shared log on the NAS:
<shared_log_dir>/wsjtx_log.adi

# --- WRIG's own files ---
~/.config/wrig/
  machine.ini              ← edit once per machine
  registry.json            ← list of known instances (auto-managed)
  instances/<rig-name>/
    wsjtx.ini              ← seeded by wrig, but WSJTX ignores it (see
                             "Config seeding — under review")

# A directory symlink wrig creates that WSJTX does NOT use on Linux:
~/.config/WSJT-X - flexa-ft8   →  ~/.config/wrig/instances/flexa-ft8/   (inert)
```

On **Windows** there is no `~/.local/share` split: config and data both sit under
`%LOCALAPPDATA%`. The exact config filename is still being confirmed — see
[Verifying WSJTX paths on Windows](#verifying-wsjtx-paths-on-windows).
