# ESP32 4-20mA ESPHome Sensor Board

Single-channel industrial 4-20mA current-loop reader, USB-C powered, built for ESPHome.

## Rev G at a glance (2026-09-20)

Rev G is the result of a second, independent design review
(`docs/Design_Review_2026-09-20_second_pass.md`). Every circuit change below
was simulated first; the decks are in `sim/` and run on KiCad's own bundled
ngspice.

| Change | Why |
|---|---|
| Limiter is now **constant-current**: R19 removed, R16 18 ohm, Q1 -> BCP53-16 (SOT-223) | Rev F's foldback could park a transmitter at ~9 V / 14 mA after a short or a hot-plug and report that as the reading |
| **D4** (1N4148W) in series after Q1 | a surge on `LOOP_V` drove Q1 backwards into the 24 V rail from ~25 V, long before the TVS conducted |
| **D3 -> SMAJ28A to GND**, new **D5** SMAJ12A from `LOOP_RTN` to GND | one TVS across the pair handled only differential surges; common-mode went through the shunt into the INA226 |
| **Soft-start load switch** Q3/Q4/R21/R22/C12 ahead of the boost | VBUS saw ~27 uF at attach against USB's 10 uF limit; it now sees 1 uF, and `MT_EN` low truly disconnects the loop supply |
| **J2 is 3-pin**: GND, mA in, +24 V out | a 3-wire or self-powered (sourcing) transmitter could not be connected at all |
| **J2 is a one-piece push-in block**, KEFA KF250NH-5.0-3P (`C976567`) | no separate plug to order or lose; solid and ferruled wire pushes straight in, the orange button releases it or opens it for bare stranded wire |
| **U1 is the ESP32-S3-WROOM-1U-N4** (`C2980296`): U.FL connector, external antenna | antenna goes on the enclosure, not inside it. **The board is unchanged** - see below |
| L1 4.7 -> **22 uH** | a quarter of the ripple current at this light load |
| Boost and INA226 re-placed to their **datasheet layout figures** | switched-current loop 28 -> 19 mm^2 with C11's ground 3.8 mm from U5's (was 9.7); C8 1.5 mm from VS (was 8.0, on the wrong side of the chip) |
| Top M2 holes moved from the corners to y = 16.8 mm | they were level with the antenna, 9.6 mm from the module |
| `pcblib`: swaps changed footprints, DRC runs with `--schematic-parity` | the board had kept 1.5 mm test pads the schematic dropped for 1.0 mm, and nothing could see it |

**State:** 28 nets / 35 no-connects match the specification exactly, ERC 0
errors, schematic parity clean, placement DRC 4 (all deliberate silk-at-edge)
+ 5 library-internal, 52 parts + 4 holes + 3 fiducials, BOM 34 lines / 47
placements. **Placed and routed** - 0 unconnected, DRC unchanged at 4 + 5; see
[Routing](#routing).

**Firmware:** `firmware/` holds the ESPHome configuration, and both of the
things this board's firmware had to do are done there:

1. A reading is published as *unknown*, not as a plausible number, whenever
   the loop is not trustworthy - including `LOOP_V` below 20 V with current
   flowing. On a sustained short (`LOOP_V` < 3 V) it drops `MT_EN`, which now
   removes the supply entirely, retries three times and then latches off.
2. Two-point calibration at 4 mA and 20 mA, captured from Home Assistant with
   a reference source and stored in flash. R12's 1 % tolerance and 200 ppm/°C
   drift and R20's fixed gain error all come out together; one point cannot
   remove them.

The firmware is a reusable ESPHome package, pulled by URL, so another board
built from this design tracks the same definition.

It also classifies faults to NAMUR NE43 and detects a backwards-wired sourcing
transmitter, which reads as negative current through the shunt. Validated on
ESPHome 2026.9.0: config clean, and it compiles to 47 % of the N4's
application partition. See `firmware/README.md`.

### Going back to the PCB-antenna module

The -1U was swapped in **without touching the board**, deliberately. Espressif's
datasheet gives the -1 and the -1U one land pattern (Figures 10 and 11 carry
identical dimensions; the -1 only adds the antenna area), so the new footprint
`WIFIM-SMD_ESP32-S3-WROOM-1U` copies the old one's 61 pads and its origin
unchanged and differs only in body outline and 3D model. The outline, the
6.5 mm the antenna would overhang, the keep-clear at the top edge and the
lowered top mounting holes are all still laid out for the -1.

To revert, change one line in `generate_schematic.py` (the old line is kept
there as a comment) and re-run both generators. No copper moves.

With the -1U fitted the radio has **no antenna of its own**: the U.FL pigtail
and antenna in `bom/non-bom-items.csv` are required, and the connector is
U.FL / IPEX generation 1 - the smaller Gen 3/4 (MHF3/MHF4) plugs do not mate.

## Calibration

**Do this before you trust a reading.** R12 is a 1 % shunt with 200 ppm/°C
drift, and R20 adds a fixed 1.19 % gain error to the voltage reading. A single
point cannot remove both a gain and an offset error, which is why there are
two. The firmware ships with the identity calibration, so an uncalibrated
board is out by whatever its own components happen to be.

You need a loop calibrator, or any adjustable current source you trust to
better than the accuracy you want out of the board.

1. Wire the calibrator into **J2 pins 3 and 2** as if it were a 2-wire
   transmitter — the board supplies the 24 V and the calibrator sinks the
   current. An active source works too: push into pin 2, return on pin 1, and
   turn *Loop power* off first so the two supplies do not fight.
2. Set **4.000 mA**. Watch the `Loop current (raw)` entity and wait for it to
   settle — the median filter takes about 3 s, so give it ten.
3. Press **Calibrate: capture 4 mA**.
4. Set **20.000 mA**, wait again, press **Calibrate: capture 20 mA**.
5. Read the **Calibration** entity. It reports the pair you captured together
   with the resulting gain and offset, for example
   `4mA=4.0123  20mA=19.9871  gain=1.00212  offset=-0.0208 mA`.
   A gain more than a couple of percent from 1.000 means something is wrong —
   check the shunt and the wiring rather than accepting it.

A capture is **refused** if the raw reading is more than 2 mA away from the
reference it claims to be, and the log says so. That is deliberate: it stops a
mistimed press silently destroying the calibration.

The result is written to flash and survives reboots and OTA updates.
**Calibrate: reset to factory** puts back the values compiled into the YAML.

Recalibrate if the board's ambient temperature changes substantially: the
shunt's 200 ppm/°C over a 40 °C swing is 0.8 % of reading, about 0.13 mA
across the span. Full procedure and the entity list are in
[`firmware/README.md`](firmware/README.md).

## Project files

```
esp32-4to20ma-board.kicad_pro     Project file
esp32-4to20ma-board.kicad_sch     The schematic — one A2 sheet (generated)
schematic.pdf                     PDF of the schematic
esp32-4to20ma-board.kicad_pcb     Board, 40x61mm portrait — placed and routed
setup_fab.py                      Stackup, netclasses, board rules, .kicad_dru (run before routing)
route_board.py                    Routes the board: scripted critical nets + replayed autoroute + pours
routelib.py                       Routing library (from the kicad-pcb-placement skill): drawing, the
                                  Freerouting hand-off, replay, DRC and pour reports
routing/autoroute.json            Freerouting's result, replayed by route_board.py
routing/drc.json                  The last full DRC report
build_package.py                  Builds fab/: gerbers zip, BOM, CPL, order notes (DRC-gated)
jlc_cpl.py, jlc_rotations.json    CPL exporter and this board's sourced rotation corrections
jlc_compare.py                    Derives those corrections from JLCPCB's own footprints
fab/                              The JLCPCB upload, regenerated by build_package.py
place_components.py               Places every part; the source of truth for the layout
pcblib.py                         PCB builder (from the kicad-pcb-placement skill)
.pcbgen-backup/                   Backups of the board and of the original footprints
sym-lib-table / fp-lib-table      Project-local + KiCad-standard library references
libraries/                        Project-local symbols, footprints, 3D models from LCSC
datasheets/manifest.json          Which manufacturer datasheet was read for each
                                  IC, and where to get it — the PDFs themselves
                                  are copyrighted and not in this repository
firmware/                         ESPHome configuration — a shared package plus
                                  a thin per-device file. See firmware/README.md
bom/bom.csv                       BOM with LCSC part numbers, for JLCPCB turnkey
bom/non-bom-items.csv             Parts to order that aren't on the board
bom_report.py                     Regenerates bom/bom.csv from the schematic
docs/Design_Review_2026-09-20.md  Design review (schematic + placement, pre-fab)
docs/Design_Review_2026-09-20_second_pass.md   Second, independent review - what Rev G fixes
sim/                              ngspice decks for the limiter, surge path and USB inrush
analysis/                         Analyzer JSON per run, tracked by manifest.json
generate_schematic.py             Generates the schematic — the source of truth
schlib.py                         Schematic builder (from the kicad-schematic-layout skill)
.schgen-backup/                   Automatic backups of any sheet the generator overwrote
verify_schematic.py               Diffs KiCad's extracted netlist against the spec
netlist_report.py                 Regenerates netlist_report.txt
netlist_report.txt                Pin-level connectivity listing for rework
erc_report.txt                    Verification output (0 errors)
render/pcb_top.png                3D top view, written by place_components.py
render/pcb_angled.png             3D angled view
render/pcb_bottom.png             3D bottom view
render/copper_top.svg, copper_bottom.svg   The copper layers as drawn
render/pcb.svg                    Vector top view
render/pcb_top_pad_overlay.png    The top view with the real pad rectangles drawn
                                  over it — how the J2 pitch error and the three
                                  misplaced 3D models were caught
```


## Schematic organisation

The schematic is **one A2 sheet**. At 47 parts plus five test points the design still isn't complex
enough to justify hierarchy, which would only add page-flipping. The sheet has
four sections, tiled in signal-flow order:

```
USB-C INPUT & ESD   ->   3.3 V REGULATOR & LED   ->   ESP32-S3 MODULE
24 V BOOST CONVERTER   ->   LOOP CURRENT LIMITER   ->   LOOP TERMINAL & MEASUREMENT
TEST POINTS, sheet notes
```

One block per **circuit**, seven in all (it was twelve). The boost converter is
one block with its load switch, input and output in it, not three; the module is
one block with its reset, boot, pull-ups, decoupling and strapping notes, not
"module" and "support circuitry". Reference sheets for these parts are drawn the
same way - Adafruit's ESP32-S3 Feather divides its sheet into "POWER AND
FILTERING", "USB TO SERIAL CONVERTER", "LIPO CHARGING" and so on, with the module
and everything that serves it in one region.

Drawing conventions throughout:

- **Flow and orientation:** signals flow left to right; supplies come in from
  the top and grounds leave at the bottom.
- **Power rails:** `GND`, `+3V3`, `+5V` and `+24V` are drawn as power-port
  symbols, not text labels.
- **Links between sections:** the sections connect by net label — `USB_P` and
  `USB_N` from USB-C to the ESP32-S3, and `I2C_SDA` and `I2C_SCL` from the
  ESP32-S3 to the INA226.
- **Wires vs labels:** components are wired with real wires and junctions.
  Short labelled stubs are used only where a wire would cross another net: the
  USB-C flip pairing, the CC pulldowns, the MT3608's FB/SW pins and the INA226
  sense lines. There are no wire crossings on the sheet.
- **Blocks and notes:** each circuit is drawn inside `s.block_start(title)` /
  `s.block_end()`, with its design calculations as notes *inside* the block.
  No rectangle is typed by hand: `schlib` derives each outline from what is in
  the block (parts, field text, labels, notes, measured at KiCad's own glyph
  widths) plus 5 mm, and `arrange()` flows the blocks across the page in the
  order they are declared. `check_text()` then reads KiCad's render and fails
  on any string or part body within 0.8 mm of an outline. Run against the old
  hand-boxed sheet that check reports about a hundred such faults (`I2C_SCL`
  on the module box's edge, the strapping notes across another, `+24V` on the
  limiter's top line); on this sheet, none.

### Regenerating

`generate_schematic.py` is the source of truth. Edit it rather than the
`.kicad_sch` file, which gets regenerated:

```bash
python3 generate_schematic.py && python3 netlist_report.py
```

The generator re-checks the geometry and verifies the drawn netlist against its
`NETS` spec, using KiCad's own netlister. It also runs ERC, then a text check.
The text check reads KiCad's rendered SVG and flags any reference, value,
label or note that is drawn sideways, lies on a wire, or overlaps a part.

If the sheet was changed in KiCad since the last run, the generator refuses to
overwrite it. It backs the file up to `.schgen-backup/` first; port your edits
into the script, then rerun with `--force`.

### PCB after the switch to one sheet

Footprints are linked to schematic symbols by the symbols' sheet path, and
flattening the hierarchy changed every path. Update the PCB like this:

1. Run **Tools → Update PCB from Schematic**.
2. Tick **"Re-link footprints to schematic symbols based on their reference
   designators"**. All references are unchanged, so every footprint re-links.
3. Expect local net names to change prefix, e.g. `/USB-C Input…/CC1` → `/CC1`.
   The board has almost no routing yet, so nothing is lost.

From now on, UUIDs are deterministic, so regenerating won't break the links
again.

## Routing

The board is **routed**: 0 unconnected items, DRC at the same 4 + 5 it had as a
bare placement (four deliberate silk-at-edge warnings, five inside library
footprints), schematic parity clean. Two scripts, run in this order after
`place_components.py`:

```bash
"C:\Program Files\KiCad\10.0\bin\python.exe" setup_fab.py
"C:\Program Files\KiCad\10.0\bin\python.exe" route_board.py
```

`setup_fab.py` writes the JLCPCB 2-layer stackup (JLC0216A, 1.6 mm), the
netclasses (`USB` 0.25/0.20 mm pair, `POWER` 0.4 mm, `LOOP` 0.3 mm with 0.25 mm
clearance, `GND`) and a three-rule `.kicad_dru`. The board constraints are the
ones in *Fabrication rules* below, unchanged.

`route_board.py` is a **hybrid**. It removes every track, via and copper zone
and redraws them, so it is safe to run again after any placement change - and
it **discards hand edits to tracks**; change the script, or stop using it.

| Scripted (255 segments and vias) | Why it is not left to an autorouter |
|---|---|
| MT3608 boost | Figure 3: CIN returns to pin 2 *under* the IC, COUT returns down the east side of D2, the switch node is two stubs under 2 mm, FB is 1 mm from pin 3 to the divider |
| INA226 taps | Figure 30: the two taps enter the shunt pads on their inner faces as a pair; load current enters and leaves on the outer faces. R14.1 is on GND by name only, so the pour is kept off it - it sees the shunt pad and nothing else |
| USB-C fan-out, D1, the pair | see below |
| +5V, +3V3 and +24V trunks, the 24 V loop | widths, and the one place each may change layer |
| Q1's copper | tab and pin 2 are one area top and bottom (40 + 45 mm2), six vias under the body |
| every ground via, both pours | the bottom pour is **one unbroken piece** of 2179 mm2 |

Freerouting 2.4.1 does the rest - EN, IO0, MT_EN, I2C, the load-switch gate
network, the LED and the +3V3 branches: 113 segments, 7 vias. It runs only with
`route_board.py --autoroute`; its result is stored in `routing/autoroute.json`
and replayed on every ordinary run, so the board is reproducible (two runs give
byte-identical tracks) without Java and without re-rolling the autorouter. Run
`--autoroute` again if a part that only it touches moves. Runs differ: each one is
judged by KiCad's own DRC on a trial board and repeated (up to three times) until
nothing is left open, and `FREEROUTING_BEST_OF=3` keeps the best of three. Look at
the result either way - one re-roll here passed DRC with the bottom ground in two
pieces. It expects
`~/tools/freerouting/` (or `FREEROUTING_HOME`) to hold `freerouting-2.4.1.jar` and a Java
25 runtime; it runs headless, with the fan-out stage and telemetry off.

Three things about KiCad 10 + Freerouting 2.4.1 that cost time and are handled
in `routelib.py`: KiCad exports existing tracks as `(type route)`, which an
autorouter may rip up, so the DSN is patched to `(type protect)`; KiCad's
`ImportSpecctraSES` then refuses the session file, so the script reads the SES
itself and takes only unprotected items on nets it did not route; and
Freerouting does not count a track that ends inside a pad, off its centre, as
connected, so whatever it adds to a fully scripted net is dropped as a duplicate.

**USB.** J1's D+/D- pads read N P N P. The *outer* two (B7, B6) are the main
path - D- west, D+ east - which is the order both D1 (turned 180 degrees) and
module pins 13/14 want, so the pair never crosses itself. A6 joins D+ on the top
layer; A7 joins D- by the only bottom strap in the pair, 2.9 mm. The two VBUS
pins are joined on the board by a 4.8 mm bottom link under D1, which also feeds
D1's pin 5 (a receptacle's VBUS pins are only joined inside a plug). The pair
is 39.6 / 43.8 mm including those stubs; at the S3's 12 Mbit/s full speed the
4 mm difference is about 25 ps against an 83 ns bit.

**Where the bottom ground is cut**, all of it: the two USB-entry links above,
one SDA hop of 9.8 mm that passes under the pair at 45 degrees, +3V3 to the
pull-ups and U3 (39 mm in two runs, about 1 mA), and LOOP_V's sense tap to R20
(10.5 mm). Nothing crosses under the boost converter.

**Placement changes routing asked for** (all in `place_components.py`): D1
turned 180 degrees and moved up 1.5 mm; R7 and R8 moved into the lanes between
VBUS and the pair, 2 mm from their pins; R10/R11 moved beside U5, which lets
+24V reach the limiter on the top layer; C9 up 0.1 mm; R6 and R15 swapped so
each pull-up sits under its own pin (before that, MT_EN took a 25 mm detour
under the module).

Still open after routing: nothing has been measured. EMC and Q1's temperature
are as designed, not as tested.

## Fabrication package (JLCPCB)

```bash
"C:\Program Files\KiCad\10.0\bin\python.exe" build_package.py
```

writes `fab/`: `esp32-4to20ma-board_gerbers.zip` (9 layers + separate PTH and NPTH drill
files + drill maps), `_bom.csv` (34 lines, 47 parts), `_cpl.csv` (47 placements) and
`ORDER_NOTES.txt`. It refuses to build unless DRC is clean apart from the two accepted
errors inside J1's library footprint, the BOM is read from the board so it is exactly
what is placed, and the build stops if BOM and CPL designators differ or the board
disagrees with `bom/bom.csv`.

Three things to know before ordering:

- **Standard PCBA, not Economic.** JLCPCB lists the ESP32-S3-WROOM-1U-N4 (`C2980296`)
  as "PCBA Type: Standard Only". J2 is the one through-hole part; it is "Economic and
  Standard", wave-soldered, and rides along.
- **Rotations were derived, not guessed.** `jlc_compare.py` fetches JLCPCB's own
  footprint for each part's LCSC number and matches it to the board's, pad number to
  pad number. Every project-library footprint is already at JLCPCB's zero with zero
  origin offset. Only the four stock-KiCad transistor footprints differ - Q1 (SOT-223)
  and Q2, Q3, Q4 (SOT-23) need +180 - and those are in `jlc_rotations.json`, each with
  its evidence. None of it has been seen in JLCPCB's placement preview yet:
  `ORDER_NOTES.txt` says what each part should look like there. LED1's polarity rests on
  pad 1 being the cathode in their footprint (its silk says so; their symbol could not
  be fetched to confirm) - a reversed LED only stays dark.
- **All 34 lines were in stock at LCSC on 2026-09-20**, thinnest: U1 1,702, J2 1,990,
  R12 4,810, C10/C11 8,605. Nine manufacturer names in the BOM were wrong (the Samsung
  capacitors were listed as CCTC, the FOJAN resistors as Uniroyal, LED1 as
  "Nichia-compatible" - it is Nationstar) and were corrected in `generate_schematic.py`;
  every MPN and LCSC number was already right.

## PCB placement

Components are placed on a **40 × 61 mm** two-layer board,
portrait, with 1 mm rounded corners, by `place_components.py` on top of
`pcblib.py`. Run it with KiCad's Python:

```bash
"C:\Program Files\KiCad\10.0\bin\python.exe" place_components.py
```

**Re-running resets every part to the table.** Once you start adjusting
placement by hand, editing the `PLACEMENT` table is the only safe way to
change it. `pcblib` enforces this: it hashes the board each time it writes,
and if the file has changed since, it backs it up to `.pcbgen-backup/` and
refuses. Port your changes into the table, then run with `--force`.

Each run also:

- imports any footprint the schematic has and the board lacks, and reloads
  every footprint from its library, so schematic and `.kicad_mod` changes
  both reach the board without a trip through the KiCad GUI;
- re-links every footprint to its schematic symbol by UUID and assigns pad
  nets from KiCad's own netlist, so the ratsnest is right immediately and
  *Update PCB from Schematic* finds nothing to change;
- puts each reference designator where it clears pads, silkscreen, its
  neighbours and the board edge, at 0.15 mm stroke (JLCPCB's minimum);
- checks courtyard overlaps, **pad-to-pad gaps between different parts**,
  off-board parts and keep-out intrusions before saving, and aborts rather
  than writing a broken board. The pad-gap check matters: 8 of these 52
  footprints draw their courtyard around the body and leave the pads
  outside it (SW1 by 2.66 mm), so courtyard clearance flatters them. It
  caught the buttons sitting 0.35 mm from the module's pad row and the CC
  resistors 0.21 mm from J1 — both legal for DRC, both far too tight;
- runs DRC and **splits it in two** — placement problems, which are yours to
  fix, and problems inside a single library footprint, which moving parts
  cannot fix. Expect **4** and **5** respectively, 0 unconnected items, and
  `schematic parity: clean`. (Run it after moving a part and it will report
  shorts until `route_board.py` has been run again - the old tracks are still
  where the part used to be);
- prints the span of the critical nets, so the claims below are measurable
  rather than asserted;
- writes `render/pcb_top.png`, `render/pcb_angled.png` and `render/pcb.svg`.

All 5 placement-level warnings are `silk_edge_clearance`, on J1 where the
USB-C shell meets the board edge and on U1 where the module crosses the top
edge to overhang it - both deliberate.

`tidy_references` orders parts by `_part_extent()` (pads, silkscreen and
courtyard, deliberately blind to the text) with a natural sort on the
reference as tie-break, so repeated runs give byte-identical designator
positions. In Rev G it also searches further: the same eight spots with the
text turned upright, then both again up to 2 mm out, and it treats other
parts' courtyards as obstacles - pads and silk alone left the middle of the
SOT-223 looking like free board, and it put R12's designator there.

That still cannot solve the lower-right corner, which holds the limiter, the
sense network, two TVS diodes and the terminal. `REF_PINS` in
`place_components.py` places 18 designators by hand, each checked against DRC.

Five test points (`TP1`-`TP5`, 1.0 mm bare pads) sit on `LOOP_V`, `LOOP_RTN`,
`+24V`, `+3V3` and `MT_EN`. They are real schematic symbols - that is the only
way they get a net - but carry `in_bom=False`. Until Rev G the *board* still
held 1.5 mm pads: `pcblib` never propagated a footprint changed in the
schematic. It does now, and `Board.drc()` runs with `--schematic-parity`.

Four M2 holes: the bottom pair 3.5 mm in from the corners beside the
connectors, the top pair at y = 16.8 mm beside the buttons - 19 mm from the
antenna (Espressif asks for ~15 mm clear of metal) and 1.8 mm clear of the
button pads for a 4.6 mm standoff.

Three fiducials (`FID1`/`FID2`/`FID3`, 1 mm copper in a 2 mm mask opening)
sit at (4, 7), (36, 7) and (36, 54) mm — an L, 4 mm in from the edges, which
clears JLCPCB's 3.85 mm minimum. They are board-only footprints: no schematic
symbol, excluded from the BOM and from the placement file, so they cannot
become orphan designators in a PCBA upload.

`pcblib.py` is the shared library from the `kicad-pcb-placement` skill; it is
copied in so the project stays self-contained.

### Why the board is this shape

**Portrait, 40 × 61 mm.** About the minimum for this part set. The
measured extents are 2.40 mm of margin left and right — set by the M2
mounting holes, not by any component — J1's shell flush with the bottom edge,
and C3 1.80 mm from the top. Width is pinned by the bottom edge: J2's
courtyard is 12 mm wide (it includes the mating plug), J1's is about 10, and
the two corner mounting holes take 6 mm between them. Height is pinned by the
vertical stack: module 19 mm, buttons 7, boost 14, sense chain 10, connectors
10. The extra 1 mm over the first attempt buys ~1 mm of clearance either side
of the buttons.

**The antenna overhangs the top edge.** The board stops level with the start
of the module's pad rows, so 6.5 mm of antenna hangs in free air —
Espressif's best case, and better than any keep-out on a populated board. The
module is then soldered on three edges with that 6.5 mm unsupported, so the
enclosure needs clearance around it and must not press on it. There is no
antenna keep-out zone any more: the overhang replaced it. At routing time,
keep the ground pour back from the top edge.

**Both connectors are on the bottom edge**, as asked. Note that J2 is a
*vertical* plug-in header — the mating plug drops in from above — so its
position at the edge is for cable dressing, not because it needs edge access.

| Area | What's there | Why |
|---|---|---|
| Top, antenna overhanging | ESP32-S3 module, centred | No PCB under the antenna at all |
| Upper left | C3 at pin 2 (3V3), R1/C1 at EN, C2 bulk, R5 at pin 12 | The module's 3V3, EN and SDA pins are all on the left flank; each part sits level with the pin it serves |
| Below the module | RESET and BOOT buttons, R6 and R15 in the gap between them | SCL (17) and the loop enable IO10 (18) come out of the module's bottom edge, right where their pull-ups sit |
| Left, middle | AP2112K LDO + C6/C7 | Between its 5 V source at the bottom and its 3.3 V loads above |
| Right, middle | MT3608 boost: C10, L1, U5, D2, C11 in one tight loop, FB divider by the FB pin | Per the MT3608 datasheet, and the furthest point on the board from the antenna |
| Right, lower | INA226, shunt R12, R13/R14 tapping its two ends, C9 | Kelvin sense per the INA226 datasheet; U3 faces the shunt with its inputs and the MCU with its I²C |
| Bottom left | USB-C, D1 ESD clamp directly above it, CC pulldowns either side, LED on the left edge | D+/D− run connector → clamp → module with nothing in the way |
| Bottom right | 4-20 mA terminal J2, TVS D3 just above it aligned with its pins | Field wiring lands at the edge and is clamped immediately |

Measured after placement:

| Net | Span | Comment |
|---|---|---|
| `/MT_SW` | 5.45 mm | the boost switching node — the one that matters |
| `/LOOP_RTN` | 9.68 mm | terminal to shunt |
| Kelvin taps | 1.69 mm | R13 and R14 each sit against the shunt pad they measure |
| `/USB_P` / `/USB_N` | 35–36 mm | the cost of portrait: connector at the bottom, module at the top. Fine for the S3's 12 Mbps full-speed USB, but route them as a pair over unbroken ground |
| `/I2C_SDA` / `/I2C_SCL` | 28–35 mm | 400 kHz, length is irrelevant |

### Loop short-circuit protection

A boost converter cannot disconnect its output: `Vin -> L1 -> D2 -> Vout` is a
DC path that conducts with U5 disabled. Shorting Loop+ to Loop- therefore fed
~1.35 A from the 5 V rail straight through the shunt, destroying R12 (about
6 W in an 0805) and browning out the board.

The fix is a series element, which costs only compliance voltage, never
accuracy, because the transmitter regulates the loop current:

| | |
|---|---|
| Q1 | PNP pass element, **BCP53-16 in SOT-223** (80 V, 1.5 W) |
| R16 | 18 ohm sense; Q2 steals Q1's base drive once the drop across it reaches a Vbe |
| R18 | 1 k in Q2's base - limits its base current, nothing more |
| R17 | 47 k base bias, ~0.5 mA; BCP53-16 hFE >= 100 turns that into 50 mA |
| D4 | 1N4148W in series after Q1: blocks `LOOP_V` from driving Q1 backwards |

`Ilim = Vbe(Q2) / R16`: **35 / 33 / 30 / 27 mA at -20 / 25 / 60 / 85 C**
(`sim/6_rev_g_limiter.py`), so a 24 mA over-range reads at any temperature.
R16 + Q1 + D4 cost 1.2 V: **22.8 V at J2 with 20 mA flowing**.

**It is deliberately not a foldback limiter, and Rev F's was a mistake.** A
2-wire transmitter is a constant-current load: it draws the same current at
any voltage above its lift-off, so its load line can cross a foldback curve
twice, and the lower crossing is stable. After a short was cleared, or a
transmitter was plugged into a live J2, Rev F could sit at ~9 V / 14 mA
indefinitely with the process at 20 mA - and report 14 mA
(`sim/recover.py`). Its short-circuit current was also the small difference of
two ~0.6 V terms and fell to zero by ~65 C. Cold power-up happened to work,
which is why it looked fine.

The price is dissipation: a dead short puts the whole rail across Q1,
24 V x 35 mA = **0.85 W**. That is what the SOT-223 is for - pour `LOOP_C`
generously around the tab and stitch it to the bottom layer. Firmware should
also drop `MT_EN` on a sustained short; with the Rev G load switch that
removes the supply entirely rather than leaving 4.6 V behind.

### Field protection

Each field wire has its own TVS **to ground**, within 6 mm of its terminal
pin: D3 (SMAJ28A, clamps at 45 V) on `LOOP_V`, D5 (SMAJ12A, clamps under
20 V) on `LOOP_RTN`. Rev F had one SMAJ36A *across* the pair, which did
nothing for a common-mode surge: that returned through R12, and the INA226's
inputs saw `I x 3.32 ohm` through only 10 ohm. D5 sits at 80 mV in normal
operation and leaks nanoamps, so it costs no accuracy; and D3's leakage no
longer flows through the shunt.

D4 matters as much as the TVS. `LOOP_V` was Q1's collector, and a PNP's
collector-base junction is a diode: from ~25 V it conducted backwards, the
emitter-base junction avalanched at ~7 V of reverse bias, and the surge went
into the 24 V rail through R16 - toward U5's SW pin, rated 30 V absolute - all
before the old 36 V TVS reached breakdown (`sim/4_reverse_conduction.py`).
With D4 the reverse current is zero to beyond D3's clamp. It is a 1N4148W
rather than a Schottky because it sees the clamp minus the rail in reverse.

### Soft-start load switch

Q3 (AO3401A) sits between VBUS and everything the boost hangs on it: C10, and
C11 through L1/D2. Q4 (2N7002) turns it on from `MT_EN`; U5's own EN now rides
on its switched input. C12 is gate-to-**source** on purpose - a gate-to-drain
(Miller) capacitor was tried first and fails at hot-plug, because with the
drain at 0 V it drags the gate low as VBUS steps up and turns Q3 hard on for
the very edge it is meant to soften. Simulated (`sim/7_usb_inrush.py`): VBUS
sees **1.0 uF at attach, down from 26.8 uF** (USB allows 10), then a 0.33 A
peak 4 ms later as the boost input charges.

The INA226's VBUS tap moved to the **field side** of the limiter, so a short
shows up twice over: the current reads saturated (anything past 24.67 mA) and
the loop voltage collapses. Firmware can tell a shorted field pair from an
open one.

### J1's hole clearance, and why the rule moved

All four `hole_clearance` errors were inside J1's own footprint — its two
0.70 mm NPTH locating pegs against its own pads, nothing to do with placement.
JLCPCB publishes **0.20 mm** NPTH-to-track for 2-layer boards; this project was
running a stricter 0.25 mm, so half the errors existed only because of our own
rule. `min_hole_clearance` is now 0.20 mm and the count drops to two.

The two that remain (0.1812 mm, 0.019 mm inside JLCPCB's limit) are an
**accepted deviation**: they are on the *duplicated* GND pads — A1/B12 and
B1/A12 are the same nets on both sides of the receptacle — so a drill breakout
into one would not open the connection. If JLCPCB objects at DFM review, the
fallback is to trim those two pads by ~0.07 mm, which costs about 6 % of their
solder area and clears even the old rule.

### Fabrication rules (JLCPCB, 2-layer)

Board Setup now carries JLCPCB's published capabilities. Where the board was
already stricter it was left alone — being tighter than the fab is a design
choice, being looser is a defect:

| Rule | Was | Now | JLCPCB |
|---|---|---|---|
| Minimum clearance | **0.0 (off)** | 0.127 | 0.127 |
| Silkscreen line width (default) | 0.10 | 0.15 | 0.15 |
| Silkscreen text thickness (default) | 0.10 | 0.15 | 0.15 |
| Track width | 0.153 | 0.153 | 0.127 |
| Via diameter / annular ring | 0.5 / 0.13 | unchanged | 0.45 / 0.125 |
| Through-hole diameter | 0.3 | unchanged | 0.2 |
| Copper to board edge | 0.5 | unchanged | 0.3 required, 0.5 recommended |

The important one is **minimum clearance, which was 0.0** — DRC had no global
spacing floor at all, only the netclasses' own 0.2 mm. The track and via size
menus were empty and are now populated with 0.25/0.4/0.6/0.8 mm tracks and
0.6/0.3, 0.8/0.4 vias, all above JLCPCB's floor.

JLCPCB does not publish a hole-to-copper figure, so `min_hole_clearance`
stays at the widely cited 0.25 mm — which is what J1's four remaining errors
are measured against. See below.

### Library-footprint fixes

The EasyEDA-sourced footprints in `libraries/esp32-4to20ma-board.pretty/`
had three real problems. All three are now fixed; the originals are in
`.pcbgen-backup/footprints-*/`.

| Part | Was | Now | Why |
|---|---|---|---|
| U1 | 12 thermal vias in the ground pad, unnumbered, 0.25 mm drill, 0.075 mm ring, paste over an open hole | pad `41`, 0.30 mm drill, 0.60 mm pad (0.15 mm ring), no paste, mask opening on the front only | Unnumbered meant they carried no net, so they grounded nothing *and* read as a foreign net inside the pad they sit in — that alone was 24 clearance errors. The drill and ring were below the board minimums. Paste over an open hole wicks solder away from the joint; tenting the back stops it running through |
| J1 | two 0.7 mm locating pegs defined as plated holes with pad = drill, so no copper ring at all | `np_thru_hole` | They are mechanical locating posts, not connections |
| J2 | 3D model pointed at `WJ5.08-LI`, a different part | KiCad's `PhoenixContact_MSTBVA_2,5_2-G-5,08_1x02_Vertical` | Cosmetic. A stand-in of the same class, pitch and pin count — its body renders a little larger than the real WJ2EDGVC, which is 9.5 × 5.6 mm |

That took the footprint-level DRC count from **59 to 7**, and the board from
96 unconnected items to 88 (the 12 vias now join GND).

**A fourth problem, found on 2026-09-20 by looking at the 3D render:**

| Part | Was | Now | Why |
|---|---|---|---|
| J2 | pads at ±2.50 mm — a **5.00 mm pitch** | ±2.54 mm, **5.08 mm** | `C8445` is `WJ2EDGVC-5.08-02P`; LCSC's own parametrics say `P=5.08mm`. The footprint was 0.08 mm narrow across the pair. With a 1.70 mm drill and ~1.0 mm pins it would still have assembled, so DRC and the netlist never saw it — but it was wrong, and it is the kind of error that only shows up when a part will not seat |
| D2 / D3 / D5 (SMA) | courtyard ±2.16 × ±1.30 mm, drawn round the body — the 2 × 2 mm pads at ±2.2 stuck 1 mm out of it | ±3.45 × ±1.55 mm, pads + 0.25 | Rev G. With the pads outside the courtyard, a layout that was courtyard-legal put two SMAs dead against a test pad: DRC reported `shorting_items`. |
| L1 (FNR4030) | courtyard ±2.00 mm square; pads reach ±2.30 | ±2.55 × ±2.25 mm | Rev G, same cause. |
| J2 (3-pin) | — did not exist | `CONN-TH_WJ2EDGVC-5.08-3P` | Rev G. Derived from the corrected 2-pin footprint: same profile, one more 5.08 mm position, body 17.2 mm. LCSC `C8412`. **Superseded the same day by the KF250NH below; the footprint is kept in the library, unused.** |
| J2 (KF250NH-5.0-3P) | — new | `CONN-TH_KF250NH-5.0-3P`, with symbol and STEP/WRL model | From LCSC/EasyEDA (`C976567`) via `easyeda2kicad`. Checked against KEFA's drawing before use, because the last EasyEDA terminal footprint had the wrong pitch: 5.00 mm pitch, 14.1 × 10.0 mm body, pins 5.70 mm from the wire-entry face, Ø1.5 drill against Ø1.4 +0.1 — all correct. Symbol pins changed from *unspecified* to *passive*. |
| U1 (WROOM-1U) | — new | `WIFIM-SMD_ESP32-S3-WROOM-1U` | The **existing** footprint's 61 pads and origin copied unchanged, with the 19.2 mm body outline and the -1U 3D model from EasyEDA (`C2980296`). EasyEDA's own -1U footprint was *not* used: its pad centres sit 0.15 mm further in than the verified pattern already on the board. Model offset 0.54 mm, checked in the render. |

**And three 3D models were misplaced** — cosmetic for fabrication, since gerbers,
drill, paste and CPL all come from the 2D layers, but they make the render
useless for judging mechanical fit, which is exactly what a render is for:

| Part | Offset added | Why |
|---|---|---|
| U1 | `0, 3.700, 0` | The model is centred on its own body; the footprint origin is at the centre of the **pad array**, and the module's 6.5 mm antenna end carries no pads. The body was drawn 3.7 mm down the board |
| J1 | `0, -1.190, 0` | Same class of problem — the USB-C shell is not centred on the pad array |
| J2 | `-2.540, 0, 0` | The Phoenix stand-in's origin is on **pin 1**, not between the pins, so the body sat one half-pitch to the right |

Verified by measuring the rendered bodies against the footprints' silkscreen
outlines: all three now agree to within 0.2 mm. `render/pcb_top_pad_overlay.png`
is the render with the real pad rectangles drawn on top, which is how the
mismatch was confirmed rather than eyeballed.

`place_components.py` calls `refresh_footprints()` before placing, so
library fixes reach the board — KiCad stores its own copy of every
footprint, and editing a `.kicad_mod` alone changes nothing.

**Still open, both judgement calls rather than mistakes:**

- **4 × `hole_clearance` on J1.** The two NPTH locating pegs sit 0.18 mm and
  0.22 mm from the neighbouring USB-C pads, against a `min_hole_clearance`
  of 0.25 mm in Board Setup. That is the connector's real geometry, not an
  error — the part is simply dense. Check what your fab actually allows for
  a non-plated hole next to copper; if it is 0.15 mm, relax the rule rather
  than shaving the pads.
- **3 × `silk_over_copper`** on J1, SW1 and SW2, where each footprint's own
  outline crosses its own pads. Cosmetic; fabs clip silkscreen at the mask
  automatically.

**Not a footprint problem, but worth noting:** J2 is the *board-side header*
only. The mating plug — the screw-terminal half the field wires land in — is
a separate part and is not in the BOM. It is a vertical part: the plug drops
in from above, so nothing about it requires the board edge.

### Why it's no longer hierarchical

Rev B used a root block diagram plus four sub-sheets. The old sheets are in
`.schgen-backup/flatten-*/` and in KiCad's Local History.

## Design summary

- **MCU**: ESP32-S3-WROOM-1U-N4 (4MB flash, U.FL connector for an external antenna), dual-core LX7, Wi-Fi/BLE, **native USB** — no USB-UART bridge chip.
- **Power in**: USB-C receptacle, data+power (no PD negotiation — plain 5V/500mA sink). CC1/CC2 have 5.1kΩ pulldowns per USB-C spec. USBLC6-2SC6 ESD-protects the D+/D- lines, wired straight through to the S3's native USB pins (IO19/IO20).
- **Programming**: no bridge chip, no auto-reset transistors. Per Espressif's own ESP32-S3-WROOM-1 reference design, the chip's internal USB-Serial/JTAG Controller peripheral handles esptool's reset/bootloader-entry handshake directly over the native USB connection — GPIO0's default strapping (internal weak pull-up) plus GPIO46's default strapping (internal weak pull-down) already satisfy the "Joint Download Boot" condition, so esptool can flash and open a console with zero external reset circuitry. SW1 (RESET, EN→GND) and SW2 (BOOT, GPIO0→GND) are kept as manual fallback buttons, matching Espressif's reference.
- **3.3V rail**: AP2112K-3.3 LDO (600mA), powers the ESP32-S3 and INA226.
- **24V loop supply**: MT3608 boost converter, 5V→24V, fed through a soft-start load switch (Q3/Q4) and feeding the field terminal through a **constant-current limiter** (Q1/Q2, R16-R18, D4). `MT_EN` is held high by R15 (100k to 3.3V) and pulled low by IO10; it gates the load switch, so firmware can remove loop power entirely or power-cycle a stuck transmitter. L1 is 22µH. Feedback divider R10=390kΩ/R11=10kΩ gives exactly 0.6V×(1+39) = **24.00V**. Rated for far more than the 30mA the loop needs — this is the same MT3608 topology recommended in its own datasheet, just very lightly loaded here.
- **Current sensing**: INA226 (I2C, 16-bit, TI). Low-side shunt R12 = 3.32Ω 1% between the loop-return terminal and GND. The INA226's shunt input is fixed at ±81.92mV with no PGA, so the shunt alone sets the ceiling: 3.32Ω puts full scale at **24.67mA**, which reads a sensor driving 23.5mA over-range instead of clipping. 24mA gives 79.7mV (97% of range) and the 2.5µV LSB works out at 0.75µA — about 21,200 counts across the 4-20mA span, far beyond any transmitter's accuracy. (Rev C used 4.02Ω, which clipped at 20.4mA.) 10Ω series filter resistors (R13/R14) + a 100nF cap across the sense lines follow the INA226 datasheet's own recommended input-protection network (fig. 21) for exposed field wiring. INA226's VBUS pin reads the loop supply voltage as a diagnostic, tapped downstream of the limiter through **R20, a 10kΩ series resistor**: D3 clamps as high as 58.1V at its rated surge current, well past the INA226's 40V absolute maximum, and the pin is rated for only ±5mA. R20 holds the worst case to 1.8mA. It costs 1.19% of gain against the 830kΩ input impedance, which firmware corrects and which does not touch the current measurement.
- **Field wiring**: 3-position one-piece push-in spring terminal, 5.00mm pitch (KEFA KF250NH-5.0-3P, 16–20 AWG) — **1 = GND, 2 = mA in, 3 = +24V out**, numbered left to right looking into the wire entry. A 2-wire transmitter goes on 3-2; a self-powered (sourcing) output on 2-1; a 3-wire sensor uses all three, within the ~30mA limit. Each field wire has its own TVS to ground (SMAJ28A / SMAJ12A).
- **I2C**: GPIO8 (SDA) / GPIO9 (SCL), 4.7kΩ pull-ups — the conventional default I2C pins on ESP32-S3 boards.

## Why these specific parts

Every non-passive part was picked from real LCSC/JLCPCB stock and its **actual manufacturer datasheet was read** (not just the LCSC listing) to get the pinout and application values right — see `datasheets/`. In particular:
- ESP32-S3-WROOM-1's pinout, strapping-pin table, USB_D+/D- pin assignment (IO20/IO19), and Espressif's own peripheral reference schematic (section 6, which explicitly omits any external reset circuitry for the native-USB path) came straight from Espressif's datasheet.
- MT3608's feedback equation, recommended inductor/cap values, and diode rating came from the Aerosemi datasheet.
- INA226's shunt-sensing topology, pin functions, and input-filtering recommendation came from the TI datasheet.

## Why we switched from ESP32-WROOM-32E + CH340C

The board originally used a classic ESP32-WROOM-32E with a CH340C USB-UART bridge for flashing. We switched to a native-USB ESP32-S3 module after comparing both approaches:
- **Fewer parts, similar cost**: dropping CH340C + its 2 bypass caps + both 2N7002 auto-reset transistors + their 2 gate resistors (8 parts total) more than offsets the S3 module's slightly higher unit price — net BOM cost actually went *down* slightly.
- **Better dev experience**: native USB gives real USB-JTAG hardware debugging (impossible on the bridge-chip design without an external JTAG probe) and a driverless CDC-ACM console on modern OSes.
- **Trade-off accepted**: losing CH340C as a "sacrificial" USB layer — if the S3's native USB pins are ever ESD-damaged, both flashing and the wired console go down together, versus the old design where a blown bridge chip only killed flashing (OTA over Wi-Fi still worked). Given this board lives on a bench/in an enclosure rather than a harsh field environment, that trade-off was judged acceptable.

## Verification performed

- **Netlist equivalence**: `verify_schematic.py` exports the netlist with
  `kicad-cli` — KiCad's own connectivity engine, the same one the PCB uses — and
  diffs it against the `NETS` specification in `generate_schematic.py`, matching
  nets by their *set of pins*. All 28 nets and all 35 no-connects match exactly
  (the five test points included).
  This is what catches a mistyped coordinate silently shorting two nets.
- `kicad-cli sch erc` → **0 errors, 59 warnings**: 58 are the "Unspecified" pin
  electrical type carried by EasyEDA-converted symbols (cosmetic — the symbols
  simply don't declare input/output/power roles) and 1 is the expected
  cached-symbol-vs-library sync notice. Report in `erc_report.txt`.
- **Geometry guards** in `schlib.py` run on every build and fail the generate if
  any pin, wire end or label misses the 1.27 mm connection grid, or if a wire end
  connects to nothing. Both classes of defect are invisible to a netlist diff.
- Rotation handling was verified empirically against KiCad rather than assumed:
  placing a `Device:R` at each of 0/90/180/270 and reading back which pin landed
  where (rot 0 → pin 1 up, 90 → left, 180 → down, 270 → right).
- `kicad-happy` schematic analyzer: 33 components / 25 unique parts, zero missing MPNs.
- `kicad-cli pcb drc` on the (currently empty) board outline → 0 violations.

## Known limitations / things to look at before ordering

- **Two nets were renamed** when the rails became power symbols: `VUSB_5V` → `+5V`
  and `LOOP_24V` → `+24V`. The board currently has footprints placed but almost no
  routing, so just run **Tools → Update PCB from Schematic** and KiCad will carry the
  new names over; footprint associations are preserved by the stable UUIDs.
- **The board is routed but nothing has been built or measured.** See [Routing](#routing). The USB pair is coupled but not impedance-controlled: on a 1.6 mm two-layer board 90 Ω needs a coplanar geometry, and at USB Full-Speed (12 Mbps) over 40 mm it does not matter.
- INA226's Alert pin is left unconnected — intentional (the datasheet explicitly allows floating it when the alert function isn't used), but wire it to a spare GPIO if you want threshold interrupts later.
- GPIO3 (JTAG-source strapping pin) is left unconnected. The datasheet notes it has no internal pull resistor and should ideally be actively driven, but since this board doesn't break out a JTAG header, an undefined JTAG-source selection at boot has no functional effect — only relevant if you later add a JTAG connector.
- ~~No dedicated VBUS transient suppressor~~ — **this was wrong, and the datasheet says so.** ST's USBLC6-2 lists "Protects VBUS" in its features and specifies `VBR`, the breakdown voltage between VBUS and GND, at 6V minimum at 1mA: there is a zener inside the part between pin 5 and ground, and D1 pin 5 is on `+5V`. VBUS is protected. (The board's ESD analyzer flags this too, as `UC-002`; it is a false positive.)
- Only 1 channel, per the current 24V/30mA supply budget. See the earlier discussion if you want to scale to multiple loop-powered channels — the 24V rail current draw scales roughly linearly per channel.

## Ordering

`bom/bom.csv` is generated from the schematic by `bom_report.py` — run it after
any part change rather than editing the CSV's first seven columns by hand:

```bash
python bom_report.py
```

It regroups by LCSC number (the ordering key, so SW1 and SW2 merge into one
line despite having different values) and carries the spreadsheet's own
columns — LC_Stock, Chosen_Distributor, Validated, Notes — forward on each
re-run.

**Cost: about USD 7.20 per board** in components at LCSC's single-unit prices
on 2026-09-20 (Rev F was 6.31; the Rev G circuit changes add about 0.24, the -1U module 0.26 and the push-in terminal 0.37), 47 placements over 34
order lines. The module is about 61% of that ($4.41) and the INA226 another
12% ($0.79). Sixteen of the 34 lines are JLCPCB *extended* parts, so turnkey
assembly adds roughly $48 of one-off setup fees on top. Of the Rev G
additions, the 1N4148W, AO3401A and 2N7002 are basic; the BCP53-16, both TVS
diodes, the 18 ohm, the 22 uH and the 3-pin socket are extended. PCB, stencil
and M2 hardware are not included.

`bom/bom.csv` has every part's LCSC number, ready for JLCPCB's BOM/CPL turnkey flow once the PCB is routed and gerbers/CPL are exported (the `jlcpcb` skill covers that step). Anything that has to be ordered but isn't on the board lives in `bom/non-bom-items.csv`, hand-maintained since none of it is derivable from the schematic. Today that is the **U.FL pigtail and 2.4 GHz antenna** the -1U module needs - it has no antenna of its own. (Rev F and early Rev G also needed a mating plug for the pluggable terminal; the one-piece push-in block does not.) Candidates to add when you get to ordering: M2 screws and standoffs for the four mounting holes, a USB-C cable, and a stencil.

## Licence

Copyright Diode663 2026.

**Hardware** (the KiCad project, schematic, board, the project's own symbols and footprints,
fabrication outputs and documentation): this source describes Open Hardware and is licensed under
the CERN-OHL-P v2. You may redistribute and modify this source and make products using it under
the terms of the CERN-OHL-P v2 (<https://ohwr.org/cern_ohl_p_v2.txt>), a copy of which is in
[`LICENSE`](LICENSE). This source is distributed WITHOUT ANY EXPRESS OR IMPLIED WARRANTY,
INCLUDING OF MERCHANTABILITY, SATISFACTORY QUALITY AND FITNESS FOR A PARTICULAR PURPOSE. Please
see the CERN-OHL-P v2 for applicable conditions.

**Software** (every `*.py` file, and the ESPHome configuration in `firmware/`): MIT, see
[`LICENSE-MIT`](LICENSE-MIT). `schlib.py` and `pcblib.py` are copied in from
[kicad-claude-skills](https://github.com/Diode663/kicad-claude-skills) so the project stays
self-contained; they are MIT there too.

**Not covered by either licence** — third-party material, included for convenience and owned by
its respective rights holders:

- Footprints and 3D models obtained from LCSC / EasyEDA with `easyeda2kicad`: everything in
  `libraries/esp32-4to20ma-board.3dshapes/`, and in `libraries/esp32-4to20ma-board.pretty/` the
  `CONN-TH_KF250NH-5.0-3P`, `CONN-TH_WJ2EDGVC-5.08-2P`, `IND-SMD_L4.0-W4.0_FNR40XXS`,
  `MSOP-10_L3.0-W3.0-P0.50-LS5.0-BL`, `SMA_L4.3-W2.6-LS5.2-RD`, `SOT-23-6_L2.9-W1.6-P0.95-LS2.8-BL`,
  `SOT-25-5_L2.9-W1.6-P0.95-LS2.8-BL`, `SW-SMD_4P-L6.0-W6.0-P4.50-LS9.0_H5.0`,
  `USB-C-SMD_TYPE-C-16PIN-2MD-073` and `WIFIM-SMD_ESP32-S3-WROOM-1-N8` footprints. Several carry
  project corrections — pitch, courtyards, pad numbering and 3D offsets — which are documented in
  the library-footprint table above; `CONN-TH_WJ2EDGVC-5.08-3P` and `WIFIM-SMD_ESP32-S3-WROOM-1U`
  are derived from them.
- Manufacturer datasheets are **not** in this repository. `datasheets/manifest.json` records which
  ones were read and where they came from; fetch them from the manufacturers or LCSC.
- Part numbers, stock figures and prices in `bom/` are LCSC's.

Nothing here is affiliated with or endorsed by Espressif, Texas Instruments, Aerosemi, KEFA,
LCSC or JLCPCB.
