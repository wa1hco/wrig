# Bug report: SmartSDR-M per-slice TX power/ALC meter ("red bar") renders on the wrong slice

## Summary

On a FLEX-8600M with two slices (A and B), the front-panel **slice TX indicator
(red "TX" on the slice flag) correctly tracks the transmit slice**, but the
**per-slice TX power/ALC meter bar does not** — it stays anchored on slice B
even while slice A is the slice that is keyed and emitting RF.

This reproduces **with native front-panel keying** (SmartSDR-M's own MOX/TX, FM
mode) — i.e. with no third-party software involved — and also when the transmit
slice is switched by a bound client via the command API. The actual RF and the
radio's command-API state are **correct** in every case; this is purely a
front-panel **display/meter-routing** defect. The misplaced meter makes it look
as though slice B is transmitting while slice A is keyed.

## Environment

- Radio: **FLEX-8600M**, serial `3025-1213-8601-2077`, nickname "Flex1"
- Firmware / SmartSDR-M version: **4.2.20.41343**
- Discovery protocol version: `3.1.0.4`; command-API connect banner: `V1.4.0.0`
- Multiflex: `licensed_clients=2`, one in use (SmartSDR-M front panel)
- Two slices in use (A and B), both 6 m, mode DIGU
- Transmit modulation source: DAX (`transmit dax=1`)
- Third-party bound clients: two helper processes per slice (CAT + DAX),
  based on the kc2g-flex-tools FlexLib. They do **not** create their own GUI
  client — each connects, finds the SmartSDR-M client by station name, issues
  `client bind client_id=<uuid>`, then controls one slice.
- Single transmitter (as expected); TX is handed between slices by setting
  `slice <n> tx=1`, which clears `tx` on the other slice.

## Configuration

- Slice A: `index_letter=A`, `dax=1`
- Slice B: `index_letter=B`, `dax=2`
- DAX TX bound to channel 1 / slice A (`dax audio set 1 slice=A tx=1`);
  channel 2 / slice B has TX disabled (`tx=0`).
- Two WSJT-X instances, each keying its own slice over Hamlib-net → CAT helper
  → `slice <n> tx=1` + `xmit 1`.

## Steps to reproduce

### Minimal repro — native front panel only, no third-party software

1. On a FLEX-8600M (front-panel SmartSDR-M), create two slices A and B (FM mode,
   different frequencies).
2. Make slice A the transmit slice and key it from the front panel (MOX/TX).
3. Watch the two slice flags while transmitting.

Result: the red "TX" flag indicator is on slice A (correct), but the per-slice
power/ALC meter bar is shown on slice **B**.

### Second path — transmit slice switched by a bound client

1. With SmartSDR-M running, create two slices A and B.
2. From a second client, `client bind` to the SmartSDR-M client and control its
   slices (no separate GUI client is created).
3. Key slice A by setting `slice A tx=1` then `xmit 1` (e.g. WSJT-X Tune). Unkey.
4. Key slice B the same way (`slice B tx=1` / `xmit 1`). Unkey.
5. Alternate A and B and watch the front-panel slice flags — same misplaced
   meter.

## Expected behavior

The per-slice TX power/ALC meter bar should appear on whichever slice currently
has `tx=1` (the live transmit slice) — i.e. it should track the transmit slice
exactly as the red "TX" flag indicator already does.

## Actual behavior

- The red **"TX" flag indicator** correctly moves to the slice being keyed
  (A when slice A is keyed, B when slice B is keyed). ✅
- The red **power/ALC meter bar** stays on **slice B** even while slice A is the
  one transmitting. ❌
- RF output, spectrum energy, and dial frequency are all correctly on the keyed
  slice. The defect is confined to the meter rendering.
- Reproduces independent of **keying path** (native front-panel MOX/TX *and*
  bound-client `slice tx=1`) and independent of **mode** (observed in FM and in
  DIGU). This indicates the meter mis-routing is in SmartSDR-M itself, not in any
  third-party tooling or DAX/digital-mode path.
- **Persists across a full radio reboot** (power-cycle of the FLEX-8600M). The
  defect is present from a cold boot — it is not stale/corrupt persistent state.

## Evidence (command-API state captured live during keying)

Passive capture from a read-only API client subscribed to `slice`, `tx`, and
`interlock`. Two consecutive tunes, slice B then slice A:

```
# WSJTX-B Tune — transmitter correctly on slice B
slice 0 (A) tx=0
slice 1 (B) tx=1
slice 1 RF_frequency=50.260000        (B tune freq)
interlock state=TRANSMITTING tx_client_handle=0x13FA80F0 source=SW

# WSJTX-A Tune — transmitter correctly on slice A
slice 1 (B) tx=0
slice 0 (A) tx=1
slice 0 RF_frequency=50.312000        (A TX-offset freq)
interlock state=TRANSMITTING tx_client_handle=0x13FA80F0 source=SW
```

During the slice-A tune above, the API state is unambiguous — `slice A tx=1`,
`slice B tx=0`, only slice A's frequency shifts for TX — yet the front-panel
power/ALC meter bar was displayed on slice **B**.

## Ruled out (so the meter placement is not explained by any of these)

- **Active slice:** forcing `slice A active=1` (so A is both active and tx) did
  not move the meter off B.
- **`tx` flag:** `tx=1` was on A while the meter showed on B.
- **Stale DAX-TX binding:** explicitly clearing `dax audio set 2 slice=B tx=0`
  did not move the meter off B.
- The meter does not track the transmit slice, the active slice, the DAX-TX
  channel binding, or actual RF.

## Impact / severity

Cosmetic but **misleading and safety-relevant**: an operator reading the front
panel sees the power meter on the non-transmitting slice and reasonably
concludes the wrong slice is keyed. In a dual-slice / dual-application setup
(e.g. two WSJT-X instances) this is actively confusing. No effect on emitted RF.

## Suggested area to investigate

The front-panel per-slice TX power/ALC meter appears to bind to a
slice/panadapter once (e.g. at slice creation or first TX) and never re-route to
the slice that is actually transmitting. The red "TX" flag indicator already
uses the correct, live source of truth (the `tx` slice); the power/ALC meter
should use the same. Because it reproduces with native front-panel keying, the
fix is in SmartSDR-M's meter-to-slice association, not in the command API.
