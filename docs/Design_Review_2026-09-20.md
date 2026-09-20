# ESP32 4-20 mA Sensor Board — Design Review

**Project:** esp32-4to20ma-board (KiCad 10.0, single A2 sheet, 2-layer PCB, placed but unrouted)
**Date:** 2026-09-20
**Revision reviewed:** Rev E — adds the foldback current limiter, moves the INA226 bus tap to the field side, applies JLCPCB fabrication rules
**Analyzers run:** `analyze_schematic.py`, `analyze_pcb.py --full`, `cross_analysis.py`, `analyze_emc.py`, `analyze_thermal.py`, `lifecycle_audit.py`, `summarize_findings.py` (run folder `analysis/2026-09-20_1224`)

---

## Update — 2026-09-20, later the same day

Three of the five blockers below have been closed. The findings are left in
place, annotated, so the reasoning stays readable rather than being edited out
of history.

| Was | Now |
|---|---|
| **H-1** INA226 VBUS over-voltage | **FIXED** — `R20`, 10 kΩ 0402 (`C25744`, same part as R1/R11, so no new BOM line) in series from `LOOP_V` to `U3` pin 8. New net `INA_VBUS`. Placed at (31.00, 44.00) mm |
| **F-4 / UC-002** VBUS ESD unconfirmed | **RESOLVED — false positive, datasheet-verified.** See the corrected entry below |
| **FD-001** no fiducials | **FIXED** — `FID1`/`FID2`/`FID3` at (4, 7), (36, 7), (36, 54) mm |
| **M-1** Q1 thermal margin | **closed — risk accepted by the designer**, 2026-09-20 |
| **TE-001** no test points | **DONE** — TP1-TP5 on `LOOP_V`, `LOOP_RTN`, `+24V`, `+3V3`, `MT_EN` |
| **GP-002 / VS-001** no ground plane, no stitching | still open — resolve at routing |
| **J1 hole clearance** | **closed** — board rule relaxed 0.25 → 0.20 mm, JLCPCB's own published NPTH-to-track minimum. See below |

Netlist re-verified after the change: 24 nets, 35 no-connects, exact match to
the specification. DRC is now **7 placement-level** and **7 library-internal**,
with 101 unconnected items pending routing. Five of the seven are the
deliberate `silk_edge_clearance` warnings on J1 and U1. The other two —
`C8`/`R18` at 0.11 mm and `C9`/`R13` clipped by a mask opening — are
reference-designator artefacts, cosmetic, and **not** attributable to R20,
whose own designator is pinned by hand and clear. I could not originally claim
they pre-dated this change, because `pcblib`'s `tidy_references` was not
idempotent. **That has since been fixed** — it ordered parts by a bounding box
that included the reference text, and since every 0402 has the same extent the
tie fell through to KiCad's footprint write order, which changes on every save.
It now sorts on pads/silk/courtyard only, with the reference as tie-break.
Three consecutive runs now give byte-identical designator positions, and the
placement DRC count is a stable 7.

Test points (TE-001) **have since been added** — see below.

### Test points added, same day

Five 1.0 mm bare pads, each within a few mm of the net it probes so the stub
stays short on a two-layer board:

| Ref | Net | Position (mm) | Sits by |
|---|---|---|---|
| TP1 | `LOOP_V` | 24.00, 46.75 | between U3 and the TVS |
| TP2 | `LOOP_RTN` | 22.00, 50.25 | the clear area west of the TVS |
| TP3 | `+24V` | 21.00, 34.00 | the boost output cap |
| TP4 | `+3V3` | 11.50, 35.00 | the LDO output, beside C7 |
| TP5 | `MT_EN` | 20.00, 26.50 | under R15's pull-up |

They carry `in_bom=False`, so the BOM stays at **30 order lines** against 41
placements. 1.5 mm pads were tried first and rejected: the extra courtyard
pushed TP1 and TP2 out of the pockets beside the parts they probe.

**One cosmetic cost, stated plainly:** TP2's designator grazes J2's and R13's
silkscreen by 0.07-0.09 mm. That corner of the board holds the shunt, the
Kelvin taps, the TVS and the terminal, and it has room for the pad but not for
a third designator. Silk-on-silk is a printing nicety, not an electrical or
assembly problem, and the alternative — moving TP2 into open copper 7 mm away
— would have cost a real stub trace on a dense two-layer board. Placement DRC
is therefore **6** — down from 7 — and library-internal DRC is **5**.

TP2 was first placed in that pocket and moved out to (22.00, 50.25). Two
reasons: its designator had nowhere readable to go, printing on top of R13's,
and a probe wedged 0.6 mm from the terminal block risks shorting to J2. The
stub out to it carries no current, so the only cost is a little copper. R13's
designator is pinned by hand at (33.90, 50.41), 1.6 mm from its own pad, which
freed the contested gap for D3 and also cleared a `silk_over_copper` on C9.

---

### Found while checking the render, same day

Reviewing the 3D render turned up a defect none of the analyzers, DRC or the
netlist diff could see, because all of them work from the 2D layers:

**J2's footprint had a 5.00 mm pad pitch on a 5.08 mm part.** `C8445` is
`WJ2EDGVC-5.08-02P`; LCSC's parametrics state `P=5.08mm`. The pads sat at
±2.50 mm instead of ±2.54 mm — 0.08 mm narrow across the pair. With a 1.70 mm
drill it would still have assembled, which is precisely why nothing flagged it.
Fixed to ±2.54 mm.

Three 3D models were also misplaced — **cosmetic for fabrication**, since
gerbers, drill, paste and the CPL all derive from the 2D layers, but disabling
for mechanical and enclosure work: U1 by 3.70 mm in Y (the footprint origin is
the centre of the pad array, not of the module body, because the antenna end
carries no pads), J1 by 1.19 mm in Y, and J2 by 2.54 mm in X (the Phoenix
stand-in's origin is on pin 1). All three now agree with their silkscreen
outlines to within 0.2 mm, verified by measuring the rendered bodies rather
than by eye.

**The copper was checked and is correct.** U1's pads match Espressif's land
pattern (1.27 mm pitch, three rows, 19.3 × 19.1 mm extent) and J1's match the
16-pin USB-C 2MD pattern (0.5 mm pitch, ±3.2 mm outer pads).
`render/pcb_top_pad_overlay.png` shows the render with the real pad rectangles
drawn over it.

---

## Overview

Single-channel industrial 4-20 mA current-loop reader. USB-C in, AP2112K LDO for
3.3 V, MT3608 boost for the 24 V loop supply, foldback current limiter feeding a
pluggable field terminal, low-side shunt read by an INA226 over I²C, ESP32-S3
module with the antenna cantilevered off the board edge.

40 components, 31 unique parts, 58 nets, 40 × 61 mm two-layer board. 44
footprints on the PCB — the four extra are NPTH mounting holes, which have no
schematic symbol by design.

**Bottom line:** the design is internally clean — 0 ERC errors, the drawn netlist
matches its maintained specification exactly, 100 % MPN coverage, and every IC
pinout I could check against a manufacturer PDF is correct. One finding is worth
fixing before fabrication: the INA226's bus-voltage pin sits on the field side of
the terminal with no series resistance, where the TVS can clamp above the pin's
absolute maximum. A second is a thermal margin that disappears at the top of the
temperature range. Neither is a show-stopper, and both have cheap fixes.

The board is **not ready to fabricate**, but only because it is not routed —
there is no copper, no ground plane and no stitching yet. Those are the next
step, not defects.

---

## Critical Findings

### H-1. The INA226's VBUS pin can be driven past its absolute maximum by the TVS

**Severity: HIGH — FIXED 2026-09-20. Evidence: datasheet-verified.**

> **Resolved.** `R20` (10 kΩ, 0402, `C25744`) now sits between `LOOP_V` and
> `U3` pin 8, creating the net `INA_VBUS`. The analysis below is the reasoning
> that led to it, kept as written.

`U3` pin 8 (VBUS) connects directly to `LOOP_V`, the field-side node, with no
series resistance. That node is clamped by `D3` (SMAJ36A).

| Quantity | Value | Source |
|---|---|---|
| INA226 V_VBUS absolute maximum | **−0.3 V to 40 V** | INA226 datasheet §6.1 Absolute Maximum Ratings |
| INA226 input current into any pin | **±5 mA** | same table |
| SMAJ36A breakdown voltage V_BR | **40 V minimum** | SMAJ36A datasheet (Littelfuse / Bourns) |
| SMAJ36A clamping voltage V_C | **58.1 V at I_PP 6.9 A**, 10/1000 µs | same |

So the TVS only *begins* conducting at the INA226's absolute maximum, and under
a real surge it holds the node as high as 58 V — about 18 V beyond the rating,
with nothing to limit the current into the pin's internal clamp.

Note this is a **pre-existing topology issue, not something Rev E introduced**.
Before the limiter, `+24V` *was* the field node, so pin 8 had the same exposure.
Moving the tap to `LOOP_V` kept it.

The differential inputs are already protected: `R13`/`R14` (10 Ω) are the series
elements TI's own input-protection network calls for. VBUS simply never got the
same treatment.

**Fix:** a series resistor from `LOOP_V` to `U3` pin 8. 10 kΩ limits the clamp
current to (58.1 − 40)/10 k ≈ **1.8 mA**, inside the ±5 mA pin rating. The cost
is a gain error on the bus reading: VBUS input impedance is **830 kΩ**
(datasheet §6.5), so 10 kΩ in series is a **1.19 %** error. That reading is a
diagnostic, not the measurement, and the error is a fixed scalar you can
calibrate out in firmware.

### M-1. Q1 has almost no thermal margin during a sustained short at high ambient

> **Closed 2026-09-20 — risk accepted by the designer.** No change made. The
> analysis below stands as written; it is recorded here so the decision is
> traceable rather than forgotten. If the enclosure is later specified above
> ~60 °C ambient, re-open it.

**Severity: MEDIUM. Evidence: datasheet-verified figures, hand calculation.**

The foldback holds a dead short at ~5 mA with ~23.9 V across `Q1`, so it
dissipates **≈ 0.128 W** continuously for as long as the fault persists.

| Quantity | Value | Source |
|---|---|---|
| P_D at 25 °C (LCSC C8326, JSCJ) | 300 mW | LCSC listing for C8326 |
| P_D at 25 °C (onsemi MMBT5401) | 350 mW | onsemi MMBT5401 datasheet |
| Derating | 2.8 mW/°C | onsemi datasheet |

At 25 °C ambient, 0.128 W is a comfortable 43 % of the JSCJ part's rating. At
**85 °C ambient the derated rating is ~132 mW**, and 128 mW is **97 % of it** —
no margin, in the one condition (a shorted field pair, indefinitely) that the
circuit exists to survive.

**Fix, pick one:**
- Tighten the foldback — raising `R18` from 1 k to 1.2 k drops the short-circuit
  current to ~3 mA and the dissipation to ~0.07 W, at the cost of a lower
  start-up current into a capacitive transmitter.
- Move `Q1` to SOT-89 (e.g. a BCP-series PNP), roughly 500 mW–1 W.
- Accept it, and state a maximum ambient in the product documentation.

The choice depends on the enclosure's internal temperature, which I do not know.

---

## Component Summary

| Metric | Value |
|---|---|
| Components (schematic) | 40 |
| Unique parts | 31 |
| Nets | 58 |
| Components missing an MPN | **0** |
| PCB footprints | 44 (40 parts + 4 NPTH mounting holes) |
| SMD / THT | 39 / 1 (J2, the pluggable terminal) |
| Board | 40 × 61 mm, 2 layers |

100 % MPN and LCSC coverage — the sourcing gate (SS-001/002) does not fire.

---

## Power Tree

```
USB-C VBUS (5 V)
├── AP2112K (U4) ──> +3V3 ──> ESP32-S3 (U1), INA226 VS (U3), pull-ups
└── MT3608 boost (U5) ──> +24V ──> foldback limiter (R16/Q1/Q2/R17/R18/R19)
                                    └── LOOP_V ──> J2 field terminal, D3 TVS,
                                                   INA226 VBUS monitor
```

Rails detected and voltages resolved: `+24V` 24.0 V, `+5V` 5.0 V, `+3V3` 3.3 V,
`GND`. The analyzer's estimated +5 V load is 240 mA (U4 only); it does not model
the boost's input draw, so treat that as a floor, not a budget.

**Boost output, datasheet-verified:** MT3608 FB = 0.588 / **0.600** / 0.612 V
(datasheet electrical characteristics). With R10/R11 = 390 k/10 k,
V_out = 0.6 × (1 + 39) = **24.00 V** nominal, ±2 % from FB tolerance alone,
before resistor tolerance. Confirmed by the analyzer's own divider detection
(VD-DET, R10/R11).

---

## Analyzer Verification

### Component count
Schematic 40 / PCB 44. **Match**, once the four NPTH mounting holes — which are
board-only by construction and carry no symbol — are accounted for. `pcblib`
marks them excluded from BOM and position files, so they do not appear as
schematic-parity errors.

### Component pinout verification

Verified against manufacturer PDFs, not KiCad library symbols:

| Ref | Part | Pins checked | Source | Status |
|---|---|---|---|---|
| U5 | MT3608 | SW=1, GND=2, FB=3, EN=4, VIN=5, NC=6 | MT3608 datasheet, pin-description table | **Datasheet-verified — matches** |
| U3 | INA226 | A1=1, A0=2, Alert=3, SDA=4, SCL=5, VS=6, GND=7, VBUS=8, IN−=9, IN+=10 | INA226 datasheet, pinout diagram | **Datasheet-verified — matches** |
| Q1, Q2 | MMBT5401 SOT-23 | **1 = Base, 2 = Emitter, 3 = Collector** | onsemi MMBT5401 datasheet, "1-Base, 2-Emitter, 3-Collector" | **Datasheet-verified — matches `Q_PNP_BEC`** |
| U1 | ESP32-S3-WROOM-1 | 3V3=2, EN=3, IO8=12, IO19=13, IO20=14, IO9=17, IO10=18, IO0=27, GND=1/40/41 | Espressif datasheet (on disk) + footprint pad measurement | Datasheet-verified |
| U4 | AP2112K-3.3 | 5-pin SOT-25 | Datasheet on disk | Datasheet-verified |
| D1, D2, D3, J1, J2, SW1/2, L1, LED1 | — | — | No datasheet obtainable | **Unverified — see Review Limits** |

The transistor check matters most here. The skill's guidance is explicit that
SOT-23 BJTs exist in at least six pinout variants and that checking a symbol
against the `.kicad_sym` file is circular. I had originally confirmed `Q_PNP_BEC`
by noting that KiCad's own `MMBT3906` symbol extends it — that is a library
cross-check, not a datasheet check. The onsemi PDF settles it independently.

### Net tracing

All four new limiter nets traced end to end against the raw schematic and
confirmed against the netlist the generator verifies on every run:

| Net | Pins | Correct? |
|---|---|---|
| `+24V` | D2.1, C11.1, R10.1, R16.1, Q2.2 (emitter) | Yes — rail stops at the limiter |
| `LOOP_SNS` | R16.2, Q1.2 (emitter), R18.1 | Yes — sense node |
| `LOOP_DRV` | Q1.1 (base), Q2.3 (collector), R17.1 | Yes — Q2 steals base drive |
| `LOOP_FB` | Q2.1 (base), R18.2, R19.1 | Yes — foldback divider tap |
| `LOOP_V` | Q1.3 (collector), R19.2, J2.1, D3.1, U3.8 | Yes — field side |

`d.verify(NETS, NO_CONNECT)` compares KiCad's own extracted netlist against the
maintained specification by pin set on every generator run, and reports
"netlist matches the specification exactly" (23 nets drawn, 23 expected).

### PCB verification
Board outline 40.0 × 61.0 mm confirmed against the raw `.kicad_pcb`. Zero
courtyard overlaps; minimum pad-to-pad gap between different parts ≥ 0.5 mm
(checked by `pcblib.check()`, which measures pads rather than courtyards because
11 of the 40 footprints have pads outside their own courtyard). No
schematic-parity findings.

### Gerber verification
Not applicable — no fabrication outputs exist yet.

---

## Signal Analysis Review

### Current sense — the core of the instrument

**Shunt sizing, datasheet-verified.** INA226 shunt input range is
**−81.9175 to +81.92 mV** (datasheet §6.5), fixed, with no PGA. The shunt alone
sets the measurement ceiling:

- R12 = 3.32 Ω → full scale **24.67 mA**
- At 24 mA: 79.7 mV, 97 % of range
- 2.5 µV LSB → **0.75 µA** resolution, ~21 200 counts across 4–20 mA

This correctly accommodates a sensor driving 23.5 mA over-range, which the
previous 4.02 Ω shunt (20.4 mA ceiling) would have clipped.

**Kelvin connection.** R13/R14 tap the shunt's own pads at 1.69 mm — measured
from the placed board, not asserted. R13/R14 (10 Ω) plus C9 (100 nF) form the
differential input filter TI's datasheet recommends for exposed field wiring.

**Common-mode.** Low-side sensing puts the INA226's inputs at ~80 mV, far inside
the −0.3 V to 40 V pin rating.

### Foldback current limiter

`Itrip = (0.65 − Vce × f) / R16`, with `f = R18/(R18+R19) = 1 k/44 k = 0.0227`:

| Condition | Vce | Limit | Q1 dissipation |
|---|---|---|---|
| Running | ~0.2 V | 32 mA | negligible |
| Hard short | ~23.9 V | 5 mA | 0.128 W — see M-1 |

Design intent is sound: the limit rises with output voltage, so the foldback
doubles as a soft start rather than latching a transmitter off. Compliance cost
is ~0.7 V (0.43 V across R16 plus Q1 saturation), leaving 23.3 V at the terminal
against sensors specified to 20 V.

**This circuit exists for a real reason** worth restating: a boost converter
cannot disconnect its output. `Vin → L1 → D2 → Vout` conducts with U5 disabled,
so before Rev E a shorted field pair drove ~1.35 A from the 5 V rail through the
shunt — roughly 6 W in an 0805. Disabling the boost in firmware does not fix
that; only a series element does.

### Protection devices
`D1` USBLC6-2SC6 on the USB data lines (PD-DET, "esd_ic"). `D3` SMAJ36A across
the field terminal. See F-4 in False Positives for the VBUS ESD question.

### RC filters
`R1`/`C1` at 15.92 Hz — the ESP32-S3 reset RC, ~10 ms rise on EN. Correct by
intent.

### Simulation verification
**Not performed.** `ngspice`, `ltspice` and `xyce` are all absent from this
machine, so the `spice` skill has no simulator to drive. The divider and filter
values above were checked arithmetically against datasheet reference voltages
instead. This is a real gap: SPICE is what catches value-computation errors that
static analysis misses.

---

## Power Analysis

Decoupling detected on `+5V` and `+3V3` (DC-DET, DO-DET). The module's HF cap
`C3` sits at U1 pin 2 and the bulk `C2` below it; `C8` bypasses the INA226 at
VS. No IC power pin reaches its rail only through a capacitor (no PP-001).

No rail-source findings (RS-001/002/003) — every rail has a declared source.

---

## PCB Layout Analysis

The board is **placed but unrouted**: 0 tracks, 0 vias, 0 zones, 0 copper layers
in use. Everything below is placement-stage only.

**Placement quality**, measured rather than asserted:

| Net | Span | Comment |
|---|---|---|
| `/MT_SW` | 5.45 mm | Boost switching node — the one that matters for EMI |
| Kelvin taps | 1.69 mm | R13/R14 against the shunt pads they measure |
| `/LOOP_RTN` | 9.68 mm | Terminal to shunt |
| `/USB_DP` / `/USB_DM` | 35–37 mm | The cost of portrait layout; fine for 12 Mbps full-speed USB, but route as a close pair over unbroken ground |
| `/I2C_SDA` / `/I2C_SCL` | 25–32 mm | 400 kHz, length irrelevant |

**Antenna.** The ESP32-S3 module's antenna cantilevers 6.5 mm off the top edge,
so there is no PCB under it at all — Espressif's best case. PM-002 flags J1 at
0.03 mm from the board edge and the module antenna at the edge; both are
deliberate. Mechanically the module is soldered on three edges with 6.5 mm
unsupported, so the enclosure must not press on it.

**DFM.** JLCPCB standard tier, **0 violations**, board 40 × 61 mm.

**Fabrication rules.** Board Setup now carries JLCPCB's 2-layer capabilities.
The significant find during this revision: `min_clearance` was **0.0** — DRC had
no global spacing floor at all, only the netclasses' own 0.2 mm. Now 0.127 mm.
Silkscreen line width and text thickness were 0.10 mm against JLCPCB's 0.15 mm
minimum. Rules already stricter than the fab (track 0.153, via 0.5/0.13, hole
0.3, edge 0.5) were deliberately left alone.

---

## Thermal Analysis

`analyze_thermal.py` ran and returned **0 findings with the score SKIPPED** —
correctly, because thermal modelling needs PCB copper and via data and the board
has neither yet. Re-run it after routing and pouring.

The Q1 calculation in M-1 is a hand calculation from datasheet θ figures, not
analyzer output, and is labelled as such.

The other dissipating parts are undemanding: the shunt burns 1.9 mW at 24 mA;
the LDO drops 1.7 V at up to ~240 mA (≈0.4 W in SOT-25) — that one is worth
re-checking once the copper pour exists, since it is the largest steady
dissipation on the board.

---

## EMC / Cross-Domain Analysis

**Cross-domain (`cross_analysis.py`): 0 findings.** No connector current-capacity
problems, no decoupling-adequacy gaps, no schematic/PCB sync errors.

**EMC risk score 86.5**, 4 findings — all attributable to the unrouted state:

| Rule | Severity | Finding | Assessment |
|---|---|---|---|
| GP-002 | error | No ground plane zones detected | Expected — not routed. **Must be resolved before fab** |
| VS-001 | warning | Via stitching may be insufficient | Expected — no vias yet |
| GP-001 | info | Return path analysis unavailable | Consequence of the above |
| EE-001 | info | Board cavity resonance frequencies | Informational |

The EMC assessment is therefore **provisional**. Re-run it after routing — with
a 24 V switching node and a 2.4 GHz radio on the same board, the ground pour and
stitching around the boost are the decisive factors and none of them exist yet.

---

## Component Lifecycle

Audit **ran but returned no usable data**: 30 components checked, all 30
`unknown`. LCSC is the only distributor configured on this machine and it does
not expose lifecycle status, so every result is `unknown` by construction. No
DigiKey, Mouser or element14 credentials are set.

Temperature audit: 0 of 30 checked against the industrial range, same cause.

**Not a clean bill of health — an absence of data.** For a board intended for
industrial field wiring, the −40/+85 °C coverage of every part is worth
confirming before production, especially the electrolytic-free but
ceramic-heavy power path.

Sourcing risk from the earlier BOM pass still stands: the **ESP32-S3-WROOM-1-N4
is the only line under 5 000 in stock** (4 715). Fine for prototypes, worth
watching for a production run.

---

## Manufacturing / DFM / Testability

| Finding | Severity | Assessment |
|---|---|---|
| FD-001 — no fiducials, 39 SMD components | high | **FIXED 2026-09-20.** Three `Fiducial_1mm_Mask2mm` at (4, 7), (36, 7) and (36, 54) mm — an L configuration, 4 mm in from the edges against JLCPCB's 3.85 mm guidance, and as far apart as the parts allow. Board-only footprints: no schematic symbol, excluded from the BOM and from the position file, so they cannot appear as orphan designators in a PCBA upload |
| TE-001 — test point coverage 0/54 nets | warning | **Real but a judgement call.** At minimum consider pads on `LOOP_V`, `LOOP_RTN`, `+24V`, `+3V3` and `MT_EN` — bring-up on a board with no test points means probing 0402 terminations |
| OR-001 — 11 passives deviate from 90° orientation | info | Placement choice; parts were oriented to face the pins they serve. No assembly impact at this scale |
| TB-001 ×9 — 0402 tombstoning risk "medium" | info | Inherent to 0402 with asymmetric thermal mass; the footprints are symmetric. Accept |
| Unique extended parts | — | 15 of 30 BOM lines are JLCPCB *extended*, none preferred → ~$45 one-off setup fees |

Assembly is single-sided (all 40 parts on top), which keeps it to JLCPCB's
Economic tier apart from the one through-hole part (J2, the terminal block),
which pushes it to Standard.

---

## False Positives / Reviewer Overrides

Findings reviewed and judged benign, kept here so you can see they were
considered:

| Rule | Finding | Why dismissed |
|---|---|---|
| **VM-001** | "Net MT_EN: 5.0 V / 3.3 V domain crossing without level shifter" | **False positive.** The analyzer infers U5's domain from its VIN rail. EN is a logic input: **V_IH 1.5 V min, V_IL 0.4 V max, absolute max 26 V** (MT3608 datasheet). A 3.3 V GPIO drive is well above threshold and far below the limit, and R15 pulls to +3V3 — not +5V — so the ESP32 pin sees nothing above 3.3 V either. Datasheet-verified |
| **PU-001** | "U3 pin Alert missing pull-up resistor" | **False positive.** Alert is an open-drain *output*, deliberately in `NO_CONNECT`. An unused output needs no pull-up |
| **LD-DET** | "LED driver Q2" | **False positive.** Q2 is the limiter's sense transistor. Pattern-matcher overreach |
| **RT-001 ×23** | Unrouted nets | Expected — the board is placed, not routed |
| **VD-004** | "C10 (10 µF/50 V) is over-designed for +5V" | **Deliberate.** C10 and C11 are the same part number so the BOM carries one line instead of two; the 50 V part is required at C11 on the 24 V rail |
| **PM-002** | J1 0.03 mm from board edge; RF module antenna at edge | **Deliberate.** The USB-C opening is flush by design and the antenna overhang is the point |
| **F-4: UC-002** | "No ESD/TVS protection on VBUS at J1" | **False positive — confirmed 2026-09-20 against ST's datasheet** (USBLC6-2, Doc ID 11265 Rev 5). Its feature list opens with "2 data-line protection / Protects VBUS", and Table 2 specifies **V_BR, breakdown voltage between VBUS and GND, 6 V minimum at I_R = 1 mA** — an internal zener from pin 5 to ground. The SOT23-6L pinout is **1 = I/O1, 2 = GND, 3 = I/O2, 4 = I/O2, 5 = VBUS, 6 = I/O1**, which matches D1's wiring exactly (pins 1/6 on `USB_P`, 3/4 on `USB_N`, 5 on `+5V`, 2 on `GND`). My earlier description of it as a "5-line device" was wrong: it protects two data lines *and* VBUS. Caveat: the BOM part is `C2687116`, a second source rather than genuine ST — its LCSC parametrics (5 V standoff, 6 V, SOT-23-6) are consistent, but only the ST part is datasheet-verified |

---

## Not Performed / Review Limits

- **SPICE simulation not performed** — no simulator installed (`ngspice`,
  `ltspice`, `xyce` all absent). Divider and filter values were checked
  arithmetically against datasheet reference voltages instead.
- **Gerber analysis not performed** — no fabrication outputs exist yet.
- **Lifecycle audit produced no usable data** — LCSC-only, which returns
  `unknown` for all statuses. No DigiKey/Mouser/element14 credentials.
- **Thermal analyzer returned SKIPPED** — needs PCB copper and vias, which do
  not exist pre-routing.
- **Datasheet coverage is 4 of 31 unique parts** (ESP32-S3, INA226, AP2112K,
  MT3608), plus MMBT5401, SMAJ36A and — added in the 2026-09-20 update —
  USBLC6-2, obtained from the web during this review.
  An LCSC sync attempt returned no additional datasheet URLs. Pin-level claims
  for **D2, J1, J2, SW1/SW2, L1, LED1** are therefore *unverified* — they
  are inference from the footprint and net names, not datasheet checks.
- **No structured datasheet extraction cache** (`datasheets/extracted/`) — all
  datasheet checks in this review were done by reading the PDFs directly.
- **No deep-review JSON** (`analysis/deep_review.json`) — the per-IC deep pass
  was done inline in this document rather than through the gated pipeline.
- **No previous review delta** — this is the first design review of this board,
  so there is nothing to diff against. Future reviews can diff
  `analysis/2026-09-20_1224`.
- **EMC assessment is provisional** — see above.

---

## Verdict

**Not ready to fabricate — but the gap is routing, not design.**

Blocking, in order:

1. **Route the board**, pour ground on both layers and stitch it, then re-run
   the EMC and thermal analyses. GP-002 and VS-001 resolve here.
2. ~~**H-1 — add a series resistor to the INA226's VBUS pin.**~~ Done: `R20`.
3. ~~**Decide on M-1** — Q1's thermal margin at high ambient.~~ Risk accepted.
4. ~~**Confirm F-4** — whether the USBLC6-2SC6 clamps VBUS.~~ Done: it does.
5. ~~**Add fiducials**; consider test points.~~ Both done.
6. ~~**Decide J1's hole clearance.**~~ Resolved: the rule was the problem, not
   the board. See *J1 hole clearance* below — two 0.1812 mm items remain as a
   documented, accepted deviation.

Then, before ordering: remember J2's mating plug (C71370) is not on the board
and not in the BOM — it is in `bom/non-bom-items.csv`.

---

## J1 hole clearance — resolved 2026-09-20

All four `hole_clearance` errors were **inside J1's own footprint**: its two
0.70 mm NPTH locating pegs against its own signal pads. Not a placement
mistake, and nothing about the layout could fix them.

| Pads | Actual | JLCPCB min (0.20 mm) | Old board rule (0.25 mm) |
|---|---|---|---|
| A4B9 / B4A9 (`+5V`) | 0.2219 mm | passes | failed |
| A1B12 / B1A12 (`GND`) | 0.1812 mm | fails by 0.019 mm | failed |

JLCPCB publishes **0.20 mm NPTH-to-track** for 2-layer boards, so half these
errors existed only because the project's rule was stricter than the fab's.
`min_hole_clearance` is now **0.20 mm** — the fab's real number — and the
count drops from four errors to two.

**The two remaining are an accepted deviation, not an oversight.** They are
0.019 mm inside JLCPCB's limit, on a connector that ships by the million with
this exact land pattern, and — the part that actually matters — the affected
pads are the **duplicated** GND pads: `A1` and `B12` are the same net and so
are `B1` and `A12`, each appearing on both sides of the receptacle. A drill
breakout into one would not open the connection.

Two alternatives were considered and not taken. Shrinking the pegs to 0.60 mm
would clear both, but the connector's post diameter could not be obtained and
0.70 mm suggests ~0.6 mm posts, which would make it an interference fit.
Trimming the two GND pads by ~0.07 mm would clear even the old 0.25 mm rule at
the cost of ~6 % of their solder area; that remains the fallback if JLCPCB
objects at DFM review.

`min_hole_to_hole` was deliberately left at 0.25 mm — it was not implicated.

What is already solid: the netlist matches its specification exactly and is
re-verified on every generator run; every IC pinout that could be checked
against a manufacturer PDF is correct, including the transistor pinout that is
the classic silent killer; the shunt sizing is right for the stated 24 mA
requirement with margin; the current limiter addresses a genuine failure mode
with a correct topology; and placement measurements back the layout claims
rather than asserting them.
