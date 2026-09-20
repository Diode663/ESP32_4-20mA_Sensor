# ESP32 4-20 mA Sensor Board — Second-Pass Design Review

**Date:** 2026-09-20 · **Reviewed:** Rev F as on disk (46 footprints, placed, unrouted) · **Resolved in:** Rev G
**Scope:** an independent pass over the whole design. The first review
(`Design_Review_2026-09-20.md`) was read only to avoid repeating it; its
conclusions were not taken as given.

## Resolution — Rev G, same day

Everything below was fixed except **M-1 (shunt grade), which the designer
accepted**: 0.8 % of reading over a 40 °C swing is within what this board is
for. If that changes, the fix is a drop-in 0805.

| # | Status | What was done |
|---|---|---|
| C-1 | **Fixed** | R19 removed, R16 → 18 Ω (`C138043`), Q1 → BCP53-16 SOT-223 (`C148109`). Simulated with worst-case hFE and D4 in circuit: 35 / 33 / 30 / 27 mA at −20 / 25 / 60 / 85 °C, 22.8 V at J2 at 20 mA (`sim/6_rev_g_limiter.py`) |
| H-1 | **Fixed** | D4 1N4148W (`C81598`) in series after Q1; D3 → SMAJ28A (`C353458`). Reverse current into the rail is zero out to 46 V |
| H-2 | **Fixed** | D3 re-referenced to GND; new D5 SMAJ12A (`C113957`) from `LOOP_RTN` to GND. Each within 6 mm of its terminal pin |
| M-1 | **Accepted** | No change, by decision |
| M-2 | **Fixed** | U3 turned so IN+/IN− face the shunt, as TI's Figure 30. C8 is now 1.5 mm from VS and 2.2 mm from GND (was 8.0 mm, wrong side); C9 1.8 mm from the input pins |
| M-3 | **Fixed** | Boost laid out as the MT3608 datasheet's Figure 3. Switched-current loop 26 → 19 mm round, 28 → 19 mm²; C11's ground 9.7 → 3.8 mm from U5's. The SMA diode's own length is now what sets it — a SOD-123 Schottky would shrink it further, not done |
| M-4 | **Fixed** | `pcblib.sync_footprints()` swaps a footprint whose ID no longer matches its symbol and can prune orphans; `Board.drc()` runs with `--schematic-parity`. Both the project and skill copies. Parity is clean |
| L-1 | **Fixed** | Title block Rev G, 2026-09-20; stale docstring corrected |
| L-2 | **Fixed** | Soft-start load switch Q3/Q4/R21/R22/C12. VBUS sees 1.0 µF at attach, down from 26.8. My first version (Miller capacitor) failed in simulation and was replaced — see `sim/7_usb_inrush.py` |
| L-3 | **Fixed** | Top M2 holes moved to y = 16.8 mm: 19 mm from the antenna, 1.8 mm clear of the button pads for a 4.6 mm standoff |
| L-4 | **Fixed** | L1 → 22 µH `FNR4030S220MT` (`C167883`), same footprint, Isat 1.2 A |
| L-5 | **Fixed** | J2 is 3-pin. (First as a pluggable `C8412`; replaced the same day by the one-piece push-in block below, which also changed the pin order) |
| L-6 | **Documented** | Two-point calibration and the loop-voltage validity check are firmware requirements, stated at the top of the README |

**Found on the way**, all fixed:

- The SMA and FNR4030 footprints drew their courtyards round the body and left
  the pads outside. A courtyard-legal layout put two TVS diodes dead against a
  test pad and DRC reported `shorting_items`. Both courtyards now enclose the
  pads.
- `schlib` mis-ordered properties when flattening a symbol that `extends`
  another and adds fields its parent lacks (`Transistor_FET:AO3401A`), failing
  the native-format check. Fixed in both copies.
- `tidy_references` treated only pads and silk as obstacles, so it printed
  R12's designator in the middle of the SOT-223. It now avoids other parts'
  courtyards and searches upright text and further out.

**Verified end state:** 28 nets / 35 no-connects exact match, ERC 0 errors,
0 wire crossings, 0 text problems, native format matches KiCad's own save;
schematic parity clean, placement DRC 5 (all deliberate silk-at-edge) + 5
library-internal, no overlaps, placement deterministic across runs; BOM 34
lines / 47 placements.

**Two part changes requested after the review, same day:**

- **U1 → ESP32-S3-WROOM-1U-N4** (`C2980296`), U.FL connector. The board was
  deliberately left untouched so the PCB-antenna module can be refitted: the
  two modules share one land pattern in Espressif's datasheet, so the new
  footprint reuses the existing pads and origin exactly. Reverting is one line.
  The radio now depends on the pigtail and antenna in `bom/non-bom-items.csv`.
- **J2 → KEFA KF250NH-5.0-3P** (`C976567`), a one-piece push-in spring
  terminal. Footprint, symbol and 3D model came from LCSC/EasyEDA and were
  checked against KEFA's drawing before use. Pinout is now **1 = GND,
  2 = mA in, 3 = +24 V out**, left to right looking into the wire entry, which
  keeps +24 V under the limiter and GND beside D5 with nothing crossing behind
  the block. The mating plug is no longer needed. Push-in is for solid or
  ferruled wire; bare stranded needs the button held while inserting.

State after both: 28 nets exact, ERC 0 errors, parity clean, placement DRC 4
(all silk-at-edge) + 5 library-internal, BOM 34 lines / 47 placements.

**Still open — all of it routing:** no copper, so EMC and thermal remain
provisional. When routing: pour `LOOP_C` around Q1's tab and stitch it through;
ground pour on both layers, stitched round the boost; keep the pour back from
the top edge; run IN+/IN− as a pair from R12's pads.

---

## The review as written (Rev F)

**Verdict: do not route yet.** Two circuit changes (C-1, H-1) alter the parts
list and the placement, so routing now would be routing the wrong board.

| # | Severity | Finding | Evidence |
|---|---|---|---|
| C-1 | **Critical** | Foldback limiter can lock a transmitter at ~9 V and report a plausible but wrong current | ngspice |
| H-1 | **High** | A surge on `LOOP_V` goes backwards through Q1 into the 24 V rail; D3 never gets to clamp | datasheet + ngspice |
| H-2 | Medium-High | `LOOP_RTN` has no clamp to ground; a common-mode surge reaches the INA226 inputs through 10 Ω | circuit analysis |
| M-1 | Medium | Shunt is 1 % / ±200 ppm/°C — it, not the INA226, sets the accuracy | LCSC parametrics |
| M-2 | Medium | INA226 bypass cap `C8` is 8 mm from the VS pin, on the wrong side of the chip | measured from board |
| M-3 | Medium | Boost hot loop encloses 28 mm²; SW pin has only 5.5 V of headroom | measured + datasheet |
| M-4 | Medium | Board carries 1.5 mm test pads; schematic and docs say 1.0 mm | `kicad-cli pcb drc --schematic-parity` |
| L-1…L-6 | Low | Stale title block, USB inrush capacitance, metal screws by the antenna, inductor value, 2-wire-only terminal, calibration | see below |

---

## C-1. The foldback limiter locks up into a constant-current load

A foldback limiter and a 4-20 mA transmitter are a bad pairing, for a textbook
reason: foldback assumes the load draws *less* as the voltage falls. A loop
transmitter draws the *same* current at any voltage above its lift-off, and
when starved it saturates and takes everything on offer. So the two curves can
cross twice — once at the proper operating point near 23 V, and once part-way
down the foldback slope — and the lower crossing is stable.

What the limiter can actually deliver (`sim/1_limiter_iv_curve.py`):

| `LOOP_V` | −20 °C | 25 °C | 50 °C | 70 °C | 85 °C |
|---|---|---|---|---|---|
| 0 V (short) | 8.2 mA | 4.0 mA | 1.6 mA | **0** | **0** |
| 8 V | 17.0 | 13.0 | 10.6 | 8.7 | 7.3 |
| 12 V | 21.4 | 17.4 | 15.1 | 13.2 | 11.8 |
| 23 V | 32.6 | 29.3 | 27.1 | 25.3 | 24.0 |

The short-circuit current is `(Vbe − 24 V × 1/44) / 20 Ω` — the small difference
of two ~0.6 V numbers, one of which moves −2 mV/°C. It is 4 mA at 25 °C and
**zero from about 65 °C up** (the 0.55 mA left is R19's own divider current;
Q1 is fully off).

The consequence, short removed or a discharged transmitter plugged into a live
J2, rail already at 24 V (`sim/recover.py`, lift-off 8 V):

| Process demand | 0 °C | 25 °C | 50 °C | 70 °C |
|---|---|---|---|---|
| 4–8 mA | ok | ok | ok | ok |
| 12 mA | ok | ok | **8.6 V / 11.3 mA** | **8.5 V / 9.3 mA** |
| 16 mA | ok | **8.7 V / 13.8 mA** | stuck | stuck |
| 20–22 mA | **8.9 V / 16.2 mA** | **8.7 V / 13.8 mA** | stuck | stuck |

The board then reports 13.8 mA while the process is at 20 mA. Nothing looks
broken. For a measuring instrument that is the worst available failure mode.
Cases near the boundary (for example 12 V lift-off, 20 mA, 25 °C) went either
way between runs — on real hardware those will be decided by part tolerance.

Cold power-up is fine (`sim/start.py`): `LOOP_V` tracks the rail up and Vce
never gets large. That is why the first review's "doubles as a soft start"
reads as true — it only examined that case. The model is also generous: it
gives the transmitter zero current below lift-off. Real ones draw quiescent
current there, which makes this worse.

**Fix (recommended) — constant-current limit, bigger pass transistor:**

| Change | From | To |
|---|---|---|
| `R19` | 43 k | **remove** (this is the foldback) |
| `R16` | 20 Ω | **18 Ω** — holds ≥ 27 mA at 85 °C so a 24 mA over-range still reads |
| `Q1` | MMBT5401, SOT-23, 0.3 W | **BCP53-16, SOT-223, 1.5 W** — LCSC `C148109`, 91 k in stock. Pinout 1 = B, 2/4 = C, 3 = E |
| `R18` | 1 k | keep — it now just limits Q2's base current |

Simulated (`sim/3_proposed_fix.py`): limit 37 / 33 / 30 / 27 mA at
−20 / 25 / 60 / 85 °C, recovery correct at every temperature and lift-off
tested. A dead short costs Q1 0.66–0.89 W, which is what the SOT-223 is for —
give its tab a few cm² of copper. This also retires M-1 from the first review
on its merits rather than by acceptance.

There is no way to keep the SOT-23: any limiter that delivers 22 mA at a 10 V
output must drop 14 V × 22 mA ≈ 0.3 W in the pass device at that point.

**Firmware, do this regardless:** the INA226 already reads `LOOP_V`. If it is
below ~20 V while the current is above 3.5 mA, the reading is invalid — flag
it. On Rev F boards that is also the recovery: pulse `MT_EN` low for ~0.5 s and
the loop restarts cleanly (`sim/5_firmware_recovery.py`, all four cases
recover). With the hardware fix, the same check becomes a short-circuit alarm,
and dropping `MT_EN` during a short cuts Q1 to 4.6 V × 33 mA = 0.15 W.

---

## H-1. Surge on `LOOP_V` goes backwards through Q1; D3 never clamps

D3 (SMAJ36A) starts conducting at 40 V. But `LOOP_V` is Q1's collector, and a
PNP's collector-base junction is a diode: once `LOOP_V` passes ~25 V it
forward-biases, lifts the base, and at about 7 V of reverse bias Q1's
emitter-base junction avalanches (V(BR)EBO is 5 V minimum). From there the
surge has a path into the +24 V rail through nothing but R16's 20 Ω.

`sim/4_reverse_conduction.py`: 40 mA reverse at 28 V, 100 mA at 32 V, then
amps — all before D3 reaches breakdown. What takes the surge instead:

- **Q1's emitter-base junction** in avalanche, which permanently degrades hFE
  even when it survives;
- **C11 and the rail** — ~5 µF effective at 24 V bias, pumped upward, with
  **U5's SW pin rated 30 V absolute maximum** (MT3608 datasheet) sitting one
  Schottky drop away.

Removing R19 for C-1 closes the other reverse path (`LOOP_V` → R19 → Q2's
collector-base → rail).

**Fix:** a series diode, anode at Q1's collector, cathode to `LOOP_V`.
**1N4148W**, SOD-123, LCSC `C81598`, JLCPCB basic, 75 V reverse. It carries at
most the 37 mA limit and costs ~0.7 V, leaving ~22.6 V at the terminal —
still far above any transmitter's lift-off plus cable drop. Not an SS34: a
40 V Schottky would see 58 − 24 = 34 V in reverse at D3's clamp, too close.

Worth doing at the same time: **D3 → SMAJ28A** (`C353458`; 28 V stand-off
against a 24.7 V worst-case rail, clamps at 45 V instead of 58 V). That is
kinder to the transmitter, which is typically rated 30–36 V, and to U3's bus
pin.

## H-2. `LOOP_RTN` has no clamp to ground

D3 sits *across* the terminal, so it handles differential surges only. A
common-mode surge — both field wires lifted against board ground, the usual
case on a long cable — returns through `LOOP_RTN` → R12 → GND. The INA226
inputs see `I × 3.32 Ω` through only 10 Ω: 12 A is enough to pass their 40 V
absolute maximum, and R12 is an 0805.

**Fix:** re-reference D3 from `LOOP_V` to **GND**, and add a second TVS from
`LOOP_RTN` to GND — **SMAJ12A** (`C113957`), which clamps under 20 V and at
80 mV of normal bias leaks nanoamps, so it costs no accuracy. Bonus: D3's
leakage currently flows through the shunt and is measured as loop current;
referenced to ground it no longer is.

Severity depends on where this gets installed. On a bench with a metre of
cable, low. On a plant floor, high. The first review calls the board
"industrial", so I have rated it for that.

---

## M-1. The shunt sets the accuracy, and it is the wrong grade

`R12` (`C3013220`) is thick film, **±1 %, ±200 ppm/°C**. The INA226 it feeds
is 0.1 % with 10 µV offset. A one-point calibration removes the 1 %; nothing
removes the drift — 40 °C of enclosure swing is **0.8 % of reading**, roughly
eight times everything else in the chain combined.

**Fix:** thin film, 0.1 %, ≤ 25 ppm/°C, same 0805 footprint. 3.3 Ω is a
standard value and moves full scale from 24.67 to 24.82 mA. I could not
confirm a specific in-stock LCSC number — the parametric search was returning
errors — so this one needs sourcing by hand.

## M-2. C8 is not decoupling U3

U3 is rotated 180°, so VS (pin 6) and GND (pin 7) are on its **south** side at
(26.05, 46.66) and (26.55, 46.66). C8 is at (31.5, 40.4): north-east of the
chip, **8.0 mm** from the pin it serves. It wants to be within ~2 mm, west of
pins 6/7 — about where TP1 is now. TP1 can move; C8 cannot.

## M-3. Boost hot loop

The loop that carries the switched current — U5.SW → D2 → C11 → GND → U5.GND —
measures **26 mm around and 28 mm² enclosed**; C11's ground pad is 9.7 mm from
U5's. With SW at 24.5 V against a **30 V absolute maximum**, ringing has 5.5 V
of headroom, and loop inductance is what sets the ringing. It is also 10 mm
from a part resolving 2.5 µV, on two layers.

**Fix:** put C11 directly between D2's cathode and U5 pin 2, so the loop closes
in a few millimetres. C11 and D2 can swap sides: C11 at roughly (31, 37.5),
D2 rotated to land its cathode on it. Then re-run placement DRC.

## M-4. The board has the wrong test-point footprint

`kicad-cli pcb drc --schematic-parity` reports five `footprint_symbol_mismatch`:
the board holds `TestPoint_Pad_D1.5mm`, the schematic `D1.0mm`. The README,
the first review and the comment in `place_components.py` all say 1.5 mm was
rejected. It was rejected in the schematic only.

Cause: `pcblib.sync_footprints()` imports parts the board *lacks*, and
`refresh_footprints()` reloads each by the ID the board *already has*. Nothing
compares the symbol's Footprint field to the board's, so a changed footprint
never propagates. Every clearance quoted for TP1/TP2 was measured with the
larger pad. **Fix:** make `sync_footprints()` replace a footprint whose ID
differs from its symbol's, and add `--schematic-parity` to `Board.drc()` so
this class of error cannot hide again.

---

## Low

- **L-1. The schematic says Rev C, 2026-09-10.** `generate_schematic.py` has
  `REV = "C"`, and its docstring still says "one A3 sheet" and "33 parts". The
  PDF delivered today carries that title block. The design is Rev F, A2, 46
  parts.
- **L-2. ~21 µF on VBUS at plug-in** (C6 + C10, plus C11 through L1/D2, which
  a boost cannot disconnect) against USB's 10 µF limit. Works on every real
  host; not compliant.
- **L-3. Metal M2 hardware level with the antenna.** H1/H2 are 9.6 mm from
  the module's flanks. Espressif asks for ~15 mm clear of metal. Nylon screws
  and standoffs at the top pair, or move them down beside the buttons.
- **L-4. L1 = 4.7 µH is the bottom of the MT3608's 4.7–22 µH range.** At
  0.17 A average input the converter is deep in discontinuous mode with
  ~0.7 A peaks. 22 µH in the same FNR4030 footprint cuts peak current and
  ripple about fourfold — worthwhile next to a µV measurement.
- **L-5. Two-wire sensors only.** J2 has no GND pin, so a 3-wire or
  self-powered (sourcing) 4-20 mA output cannot be connected at all. A 3-pin
  terminal — `LOOP_V`, `LOOP_RTN`, `GND` — adds that for one pin.
- **L-6. Calibrate at two points.** R13/R14 interact with the INA226's input
  bias network, and R20 costs 1.19 % on the bus reading. Both are fixed
  scalars, but this datasheet revision does not give the figure for the first,
  so measure it: 4 mA and 20 mA from a reference source.

## Checked and correct

ESP32-S3 pin assignments (IO8/IO9 I²C, IO19/IO20 USB, IO10 enable, strapping
pins) · INA226 pinout and 0x40 address · MT3608 pinout, 0.6 V reference,
24.00 V divider, 79 % duty against a 90 % limit · AP2112K pinout and output
capacitance · USB-C CC pull-downs · USBLC6 pinout · EN reset RC · netlist
matches the specification exactly (24 nets, 35 no-connects) · ERC 0 errors ·
DRC unchanged at 6 placement + 5 library · `C2913197` really is the -N4.

Analyzer false positives, all three: `PU-001` (Alert is open-drain and
deliberately unused), `UC-002` (USBLC6 pin 5 is on VBUS), `VM-001` (`MT_EN`
is pulled to 3.3 V and the MT3608's EN threshold is 1.5 V — no level shifter
needed).

## Correction to the first review

It states SPICE "was not performed" because no simulator is installed. KiCad
ships ngspice as `bin/ngspice.dll`. `sim/ngs.py` drives it through ctypes;
every simulation cited here is reproducible from `sim/`.

## Not done

No routing exists, so EMC and thermal remain provisional, as before. No gerber
review. Lifecycle data is still unavailable without distributor API keys.
Surge behaviour is analysed and simulated at DC, not against an IEC 61000-4-5
waveform.
