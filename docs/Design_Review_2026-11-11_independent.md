# ESP32 4-20 mA Sensor Board — independent review of Rev G

2026-11-11, on branch `claude/rev-h-review`. Rev G as ordered is untouched on `main`.

Done fresh from the netlist, the datasheets and the routed board, without leaning on the two
earlier reviews; afterwards compared with them, so each item says whether it is new. Nothing
here was measured on hardware.

## Findings

| # | Severity | Finding | New? | Evidence |
|---|---|---|---|---|
| 1 | Medium-high | **A surge on the mA-in wire goes through the shunt before D5 clamps.** D5 (SMAJ12A) does not conduct until 13–14 V, and the 3.32 Ω shunt sits in parallel with it: 0.5 kV / 12 A line-to-ground puts 5.2 A, 91 W peak for 30 µs into an 0805 rated 0.125 W; 1 kV puts 6.5 A, 139 W. Typical 0805 thick film is good for roughly 30–50 W at that width. The part at risk is the one that sets the accuracy, and a damaged shunt usually drifts rather than opens. | New. D5 was added in the second review; that review did not look at what the shunt sees. | `ngspice`, 8/20 µs source, TVS fitted to datasheet points |
| 2 | Medium | **24 V applied straight to the mA-in pin destroys the input.** 24 V across 3.32 Ω is 7 A, and it is above D5's stand-off. A wiring mistake with a separately powered transmitter does this. Industrial inputs survive it; this one has nothing in series. | New | circuit |
| 3 | Medium | **The loop supply is on by default.** R15 pulls MT_EN up, so the 24 V rail is live through reset, boot, flashing and any firmware hang, and the only protection against a shorted loop in that time is Q1 dissipating 0.85 W continuously (accepted earlier as marginal at high ambient). A pull-down would make the firmware's 3 s cut-off the normal case, not the only case. | New framing; Q1's dissipation itself was accepted before | netlist |
| 4 | Medium | **Module supply is routed badly.** U1 pin 2 is fed through a via under the module, 7 mm of bottom track and a second via; C3 (100 nF) hangs off the far end, 10 mm and two vias from the pin, though it sits 4 mm from it. The module has its own decoupling, so this probably works; it is not what Espressif asks for. | New. Autorouter output nobody looked at | board |
| 5 | Medium | **No legend on the board at all.** The silkscreen has designators only: nothing says which J2 position is GND, mA in or +24 V, which button is RESET, what the test pads are, or the board's name and revision. | New | board file: no text items |
| 6 | Low | Boost start-up was simulated as capacitors only. MT3608 starts switching at about 2 V on a rail that Q3 is still ramping; expect a brief hiccup, not damage. Scope VIN_SW at first enable. | New | reasoning; no MT3608 model |
| 7 | Low | The "1 µF at attach" claim counts only what is directly on VBUS. The LDO passes charge on to 32 µF at 3.3 V (about 106 µC against USB's 50 µC). Every ESP32 dev board does the same. | Corrects the second review | arithmetic |
| 8 | Low | D2 (SS34, SMA) is far larger than a 35 mA load needs; its capacitance costs roughly 0.1 W at 1.2 MHz and its length sets the hot loop. A SOD-123 40 V Schottky would do. | Noted before, not done | datasheet |
| 9 | Info | LDO at continuous Wi-Fi transmit (0.5 W in SOT-25) runs hot; fine at ESPHome duty. | New | datasheet |

### Checked and found sound

- Current limiter dynamics, which had only ever been simulated at DC: hard short while running
  20 mA peaks at 0.4 A for 0.4 µs and settles to 33–34 mA with no ringing (hFE 100–250);
  charging 10 nF–100 µF and limiting into 100 Ω through 10 µH–1 mH of cable show no oscillation.
- Pin numbers against datasheets for every IC, transistor and diode; pad order of every
  project-library footprint; USB D+/D−; strapping pins; INA226 common-mode range, address and
  bus-pin protection; D4 blocking; load-switch gate drive.
- Leakage paths around the shunt: none that the two-point calibration does not remove.

## For the Rev G boards on order

Nothing stops them being used. Two hand reworks are worth doing before field use:

1. D5 → SMAJ5.0A (same SMA footprint, e.g. LCSC `C113952`): the shunt then sees 18–23 W, inside
   its pulse rating. Check the reading at 4 mA afterwards; a 5 V TVS leaks more than a 12 V one.
2. Lift R15 and fit it from Q4 gate to source (pins 1–2, adjacent) so the loop supply defaults off.

At bring-up: scope VIN_SW at enable (6); watch for brown-out resets during Wi-Fi transmit (4);
label J2 by hand (5).

## Routing with this board's own router

`gridroute.py` (about 500 lines) replaces Freerouting for the ten nets that are not scripted:
a 0.1 mm grid, analytic clearance, A* with 45° headings, tree growth for multi-pin nets,
rip-up and retry, several net orders tried and the cheapest kept. KiCad's DRC found no
clearance error in anything it produced.

| | Rev G (Freerouting) | Own router, same pin map | Own router, I2C/MT_EN pins swapped |
|---|---|---|---|
| Signal vias | 7 | 13 | 13 |
| Track on the bottom (ground) layer, these nets | 59 mm | 24 mm | 21 mm |
| +3V3 on the bottom | 39 mm, 15 mm of it under the module | 10.5 mm | 11 mm |
| Module supply | 2 vias, C3 off the path | top layer through C3, no via | same |
| DRC | 4 + 5 | 4 + 5 | 4 + 5 |
| Bottom ground | one piece | one piece | one piece |

- The pin swap (SDA to GPIO10, MT_EN to GPIO11) was tried properly — schematic, placement,
  firmware pin names — and is **not worth it**: 3 mm less bottom track for a firmware fork
  between Rev G and Rev H. It is not on the branch.
- What forces the remaining hops is placement, not routing: the USB pair and the +5V feed to Q3
  run north–south and cut the board in two, and 3V3 and I2C have to get across. Fewer vias needs
  parts moved, not a better router.

## Schematic drawing

Measured on the Rev G sheet: 52 parts on A2; **20 connections inside a block made by label
instead of wire** (boost 4 nets, limiter 3, loop measurement 3, USB 4); block area would fit A3.
The limiter was the worst: six parts, three of them joined only by name.

On the branch the limiter and the boost converter are redrawn as a person would — one rail left
to right, every connection a wire, names only naming nets. Same netlist, zero crossings, label
joins 20 → 11. The rest of the sheet is as it was.
