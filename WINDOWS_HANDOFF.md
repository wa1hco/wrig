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

_(fill in: paste the Part A `dir` output, the Part B symlink check, and whether
the shared log worked end-to-end)_
