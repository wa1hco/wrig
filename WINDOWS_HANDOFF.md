# WRIG — Windows handoff / test plan

Note for a Claude Code session (or human) running on the **Windows** PC. The
development and all verification so far happened on **Linux**; the items below
are the parts that can only be confirmed on Windows.

Read this top to bottom, run the steps, and **record the actual output** (paste
it back, or append it under "Results" at the bottom and commit). Don't guess —
the whole point is to replace assumptions with observed Windows behaviour.

---

## Background — what is known vs. unknown

WRIG runs multiple WSJTX instances via WSJTX's built-in `wsjtx --rig-name NAME`,
and links each instance's `wsjtx_log.adi` to **one shared log on the TrueNAS**
(`\\192.168.1.5\share`) so "worked before" colouring is shared across all rigs
and PCs.

**Verified on Linux:**
- WSJTX config is a **flat file** `~/.config/WSJT-X - NAME.ini`.
- WSJTX data/log is a **directory** `~/.local/share/WSJT-X - NAME/` (holds
  `wsjtx_log.adi`, `ALL.TXT`, `save/`).
- WRIG's shared-log symlink in the **data dir** works.
- WRIG's config-dir symlink + seeded instance `wsjtx.ini` are **ignored** by
  WSJTX (it reads the flat `.ini`). This config layer is **under review** — do
  not trust it to configure WSJTX.

**Unknown on Windows (your job to confirm):**
1. Where exactly WSJTX stores config for `--rig-name NAME` — flat
   `%LOCALAPPDATA%\WSJT-X - NAME.ini`? nested `%LOCALAPPDATA%\WSJT-X\...`? a
   per-rig folder? This decides how the config layer gets reworked.
2. Whether the shared-log symlink to the NAS can be created and resolves.

---

## Part A — Investigate WSJTX's Windows config/data paths

Run in `cmd` (not PowerShell, so `%VAR%` expands), **after** launching a rig at
least once so WSJTX has written its files:

```cmd
wsjtx --rig-name TEST            REM launch once, change a setting, close it

dir "%LOCALAPPDATA%" | findstr /i WSJT
dir "%LOCALAPPDATA%\WSJT-X*" /a
dir "%APPDATA%" | findstr /i WSJT
where /r "%LOCALAPPDATA%" wsjtx_log.adi
where /r "%LOCALAPPDATA%" "WSJT-X - TEST*"
```

**What to capture:**
- The exact name of the config object for `TEST`: a file `WSJT-X - TEST.ini`, a
  folder `WSJT-X - TEST\`, or something nested. Paste the `dir` output.
- The exact path of `wsjtx_log.adi` (which folder WSJTX logs into).
- Whether config and log/data are the **same** folder or different.

---

## Part B — Test the shared log to the NAS

**One-time machine setup:**
1. Turn on **Developer Mode**: Settings → Privacy & security → For developers
   → Developer Mode = On. (Lets WRIG create symlinks without admin.)
2. On the NAS, make a dedicated folder (e.g. `\\192.168.1.5\share\wrig`) and
   move the existing `wsjtx_log.adi` into it (preserves QSO history).
3. Map it to a drive:
   ```cmd
   net use W: \\192.168.1.5\share\wrig /persistent:yes
   ```
4. Install + configure WRIG:
   ```cmd
   pip install -e .
   wrig config
   ```
   Edit `%APPDATA%\wrig\machine.ini` → `shared_log_dir = W:\` and set
   `wsjtx_binary` to the real `wsjtx.exe` path.

**Test:**
5. `wrig create wintest` then `wrig relink wintest`.
6. Find where WSJTX logs for `wintest` (from Part A), then check that
   `wsjtx_log.adi` there is a symlink to the NAS:
   ```cmd
   dir <that folder>\wsjtx_log.adi          REM expect <SYMLINK> → W:\wsjtx_log.adi
   fsutil reparsepoint query "<that folder>\wsjtx_log.adi"
   ```
   - If WRIG printed a manual `mklink` command instead of creating it →
     Developer Mode is off, or the drive isn't reachable.
7. Launch `wrig start wintest`, log a test QSO, confirm it lands in
   `W:\wsjtx_log.adi`, and that a second rig shows it as "worked before".

**Gotchas to watch (Windows symlink → network target):**
- A junction (`mklink /J`) CANNOT point at a network drive — WRIG must use a
  symbolic link. That needs Developer Mode (or admin).
- The path may chain junction (config dir → instance dir) → symlink
  (`wsjtx_log.adi` → NAS). If colouring works but logging doesn't (or vice
  versa), suspect that two-hop chain.
- These PCs are not hardened, so default L2R symlink evaluation should be fine.

---

## Part C — Report back / next actions

Append findings under "Results" and commit, or paste them into the chat. Then
the config layer can be reworked correctly:
- If Windows also uses a **flat `.ini`** → make seeding write the flat
  `WSJT-X - NAME.ini` on both platforms and drop the inert directory symlink.
- If Windows uses a **folder** → the two platforms differ and the config layer
  needs per-platform handling (or drop config management, keep log + launcher).

## Results

### Part A — WSJTX Windows config/data layout (CONFIRMED, 2026-06-23)

Observed on the Windows PC (user wa1hco), inspecting `%LOCALAPPDATA%` directly
(no relaunch needed — existing profiles were already present):

```
%LOCALAPPDATA% = C:\Users\wa1hc\AppData\Local

[DIR] C:\Users\wa1hc\AppData\Local\WSJT-X            <- default profile
[DIR] C:\Users\wa1hc\AppData\Local\WSJT-X - FlexA    <- a --rig-name profile

C:\...\WSJT-X\          contains: WSJT-X.ini (124 KB), ALL.TXT, db.sqlite,
                        wsjtx_log.adi (3.2 MB), wsjtx_log_shortcut.adi.lnk,
                        logs\, save\, cty.dat, ...
C:\...\WSJT-X - FlexA\  contains: WSJT-X - FlexA.ini (33 KB), ALL.TXT,
                        db.sqlite, logs\, save\, ...  (no wsjtx_log.adi yet)

No flat "WSJT-X - NAME.ini" files at the LOCALAPPDATA root.
Nothing under %APPDATA% (Roaming).
```

**Answers to the Part A questions:**

1. **Folder, not flat file.** `--rig-name NAME` uses a per-rig **directory**
   `%LOCALAPPDATA%\WSJT-X - NAME\`. This DIFFERS from Linux (flat
   `~/.config/WSJT-X - NAME.ini`).
2. **The .ini lives inside that folder and is named after the folder:**
   `WSJT-X - NAME\WSJT-X - NAME.ini` (default profile: `WSJT-X\WSJT-X.ini`).
   It is **not** named `wsjtx.ini`.
3. **Config and log/data are the SAME folder** on Windows. `wsjtx_log.adi`
   sits next to the `.ini` (observed in the default `WSJT-X\` profile).

### Two Windows bugs this exposes (config layer)

Windows's per-rig folder means WRIG's directory-junction approach *can* work on
Windows (unlike Linux, where the config link is inert) — but the **.ini filename
is wrong on both ends**:

1. **Seeding finds nothing.** `find_base_wsjtx_ini()` looks for `wsjtx.ini`
   inside `WSJT-X\` and `WSJT-X - <name>\`, but the real files are `WSJT-X.ini`
   and `WSJT-X - <name>.ini`. On Windows seeding always misses and falls back to
   template/stub. (wrig/instance.py:140,146,157)
2. **WSJTX ignores WRIG's config.** WRIG writes the instance config as
   `wsjtx.ini` and junctions `%LOCALAPPDATA%\WSJT-X - <rig>` → instance dir, but
   WSJTX reads `WSJT-X - <rig>.ini` from inside that folder — so it ignores
   `wsjtx.ini` and writes its own. (wrig/instance.py:369,396)

**Part C decision:** Windows uses a folder, so the config layer needs
per-platform handling. The fix on Windows is a filename, not a structure:
WRIG must (a) seed by reading `WSJT-X[ - <name>].ini` inside the profile folder,
and (b) write/patch the instance config as `WSJT-X - <rig>.ini` (the name WSJTX
reads from the junctioned folder), not `wsjtx.ini`.

### Part B — shared log to NAS (RUN 2026-06-23, file plumbing PASSES)

Setup used: Developer Mode **ON**; NAS subfolder `\\TRUENAS\share\WRIG` mapped to
`W:` (persistent); `machine.ini` → `shared_log_dir = W:\`,
`wsjtx_binary = C:\WSJT\wsjtx\bin\wsjtx.exe`. The single shared
`W:\wsjtx_log.adi` (3,262,241 bytes) was already in place.

Steps: `wrig create wintest` → `wrig start wintest --dry-run` (creates the config
junction without launching) → inspected the link chain → `wrig delete wintest --files`.

**Results — the two-hop chain works:**
- **Symlink creation** via `Path.symlink_to()` (WRIG's exact call) succeeds with
  Developer Mode on, no admin. Confirmed against a local target and the NAS.
- **Config junction:** `%LOCALAPPDATA%\WSJT-X - wintest` -> `...\wrig\instances\wintest`
  (`LinkType: Junction`). Created by `wrig start`/`ensure_wsjtx_config_link`, **not**
  by `wrig create` — the junction only appears once you start (or relink) the rig.
- **Log symlink (inside instance dir, seen through the junction):**
  `%LOCALAPPDATA%\WSJT-X - wintest\wsjtx_log.adi` -> `W:\wsjtx_log.adi`
  (`LinkType: SymbolicLink`).
- **End-to-end read through junction -> instance dir -> symlink -> W::** returns
  the full **3,262,241 bytes, byte-identical** to a direct UNC read; first line
  `ADIF Export from ADIFMaster v[2.9]`. So the handoff's "two-hop chain" concern
  is fine here with Dev Mode + mapped drive.
  - Gotcha to remember: PowerShell `Get-Item.Length` on the symlink reports `0`
    (reparse-point size), which *looks* like a failure — it isn't; read the bytes
    to verify, don't trust `.Length`.
- **`--files` delete is safe:** removing the instance dir did **not** follow the
  symlink into the NAS — `W:\wsjtx_log.adi` stayed at 3,262,241 bytes. It also
  backs up any *real* local `wsjtx_log.adi` to `*.local-backup` before linking.

**Still not done:** a live `wrig start` that actually launches WSJTX and logs a
real QSO to confirm WSJTX writes through the link (needs the radio). File-level
resolution is proven; only the WSJTX-writes-to-it step is unverified.

### Other Windows bugs found & FIXED this session

3. **Unicode arrow crashed the CLI.** `print(f"... → ...")` raised
   `UnicodeEncodeError` on the cp1252 console and aborted `wrig create`
   mid-run (right after the log symlink was made). Fixed: replaced printed `→`
   with ASCII `->` (and printed `—` with `-`) across the package, and added a
   defensive `sys.stdout/err.reconfigure(errors="backslashreplace")` guard in
   `cli.main()` so a stray non-ASCII char can never hard-crash WRIG again.
4. **`wrig delete --files` leaves a dangling config junction.** It deletes the
   instance dir but not `%LOCALAPPDATA%\WSJT-X - <rig>`, leaving an orphan
   junction that then reappears in `wrig list` as a "discovered" config.
   (Removed manually in this session with `rmdir`.) **TODO:** have delete also
   remove the WSJTX config link.

Also corrected in passing: `machine.ini` `wsjtx_binary` default/path pointed at
`C:\WSJT\bin\wsjtx.exe`; the real binary is `C:\WSJT\wsjtx\bin\wsjtx.exe`.
