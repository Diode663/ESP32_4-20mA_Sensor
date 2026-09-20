#!/usr/bin/env python3
"""Component placement for the ESP32 4-20 mA board -- placement only, no routing.

Run with KiCad's own Python, which is where pcbnew lives:

    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" place_components.py

RE-RUNNING RESETS EVERY FOOTPRINT POSITION. If you have moved parts or
routed anything in KiCad, do not run this: pcblib notices the file changed,
backs it up to .pcbgen-backup/ and stops. Port the changes into PLACEMENT
below, then run with --force.

Rev G -- portrait, antenna overhanging
--------------------------------------
The board is portrait with both connectors on the bottom edge, four M2
mounting holes, and the ESP32 module's antenna cantilevered off the top
edge. Espressif's best case for a module antenna is no PCB under it at all,
which is what the overhang buys: the board stops level with the start of the
module's pad rows and the antenna hangs in free air.

That leaves the module mechanically exposed -- soldered on three edges with
~6.5 mm unsupported. The enclosure needs clearance around it and must not
press on it.

Module pad geometry, measured from the footprint (local mm from its centre):
    left flank  x -8.90, pins 1..14, y -8.95 .. +7.56, 1.27 pitch
    bottom edge y +8.95, pins 15..26
    right flank x +8.90, pins 27..40
So 3V3 (2) and EN (3) come out top-left, SDA (12) and USB D-/D+ (13/14)
bottom-left, SCL (17) and the loop-enable IO10 (18) on the bottom edge, and
IO0 (27) lower-right. The support parts follow those pins.

What this script does
---------------------
1. Reloads every footprint from its library, so .kicad_mod fixes reach the
   board (KiCad keeps its own copy of each one).
2. Draws the outline with 1 mm rounded corners and puts the drill/place
   origin on the top-left corner.
3. Places every footprint from PLACEMENT, all on the top layer.
4. Adds four M2 clearance holes, three fiducials and the antenna keep-outs.
5. Re-links footprints to their schematic symbols by UUID and assigns pad
   nets from KiCad's own netlist export.
6. Tidies the reference designators at 0.15 mm stroke (JLCPCB minimum).
7. Checks geometry, saves, runs DRC, reports critical net spans, renders.

Coordinates are board-relative millimetres: origin at the top-left corner,
Y down, rotation in degrees counter-clockwise.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pcblib import Board

W, H = 40.0, 61.0                  # board size, mm -- portrait

#: ref -> (x, y, rotation degrees). All top layer.
PLACEMENT = {
    # --- MCU: top of the board, antenna hanging off the top edge ----------
    # U1's centre sits 9.95 mm below the edge, so its local y -9.95 lands on
    # it: 6.5 mm of antenna overhangs and the pad rows start 1.0 mm inside.
    "U1":   (22.00, 9.95, 0),
    "C3":   (9.50, 2.30, 0),       # 100 nF at pin 2 (3V3), y 2.27
    "R1":   (9.50, 4.30, 0),       # EN pull-up at pin 3, y 3.54
    "C1":   (9.50, 6.30, 0),       # EN RC cap
    "C2":   (9.30, 8.80, 0),       # 22 uF bulk, below the HF parts
    "R5":   (9.50, 14.90, 0),      # SDA pull-up at pin 12, y 14.97

    # --- Buttons below the module, pull-ups in the gap between them -------
    "SW1":  (10.50, 23.65, 0),     # RESET -> EN, up the left side
    "SW2":  (29.50, 23.65, 0),     # BOOT  -> IO0 (pin 27, lower right)
    "R15":  (20.00, 21.00, 0),     # MT_EN pull-up directly under pin 18: its track drops straight in
    "R6":   (20.00, 23.50, 0),     # SCL pull-up below it, reached from the SCL run that passes on its way to U3

    # --- 3.3 V LDO: left, between the USB 5 V and its loads ---------------
    "U4":   (8.00, 32.00, 0),      # AP2112K
    "C6":   (4.50, 32.00, 90),     # LDO input
    "C7":   (11.50, 32.00, 90),    # LDO output

    # --- Soft-start load switch: where +5V arrives, feeding the boost -----
    # Kept right of x = 14.4 so the USB pair has a clear run up the left.
    "Q3":   (18.85, 32.90, 0),     # P-FET: S/G on the left, D straight at L1
    "R21":  (15.85, 32.10, 0),     # gate pull-up, gate pad toward Q3
    "C12":  (15.85, 33.25, 0),     # gate-source cap, stacked under R21
    "R22":  (15.85, 30.95, 180),   # gate pull-down, gate pad toward Q3
    "Q4":   (17.60, 28.60, 180),   # N-FET: G toward TP5 / MT_EN, D at R22

    # --- 24 V boost, laid out as the MT3608 datasheet's Figure 3 ----------
    # (rotated to this footprint's pin order: 1-2-3 along the bottom, SW left).
    #   L   beside the SW pin              -> the SW node is a 2 mm stub
    #   D   leaves the SW node, COUT beside it and antiparallel, so its ground
    #       pad lands 3 mm from the GND pin -> the switched-current loop closes
    #       in a few mm (was 26 mm round / 28 mm^2)
    #   CIN at the IN pin, grounded back under the IC to pin 2
    #   FB divider on the far side of the IC from the SW node
    "U5":   (28.00, 32.00, 0),
    "L1":   (23.70, 32.40, 0),     # pad 2 (SW) 2 mm from U5 pin 1
    "D2":   (26.00, 38.15, 90),    # anode up at the SW node, cathode down
    "C11":  (29.40, 38.15, 90),    # +24V down beside D2's cathode, GND up at U5
    "C10":  (31.20, 30.50, 270),   # VIN_SW up at IN/EN, GND down
    "R11":  (30.30, 34.00, 0),     # FB-to-GND, 1 mm from pin 3; its GND pad runs straight up to C10
    "R10":  (30.30, 35.20, 180),   # +24V-to-FB, FB pad under R11 FB pad; moved beside U5 so +24V can pass east to the limiter on the top layer

    # --- Current limiter: right edge, between the rail and the terminal ---
    "R16":  (38.60, 33.40, 270),   # sense: +24V up, LOOP_SNS down
    "R18":  (38.60, 35.95, 270),   # LOOP_SNS up beside R16, LOOP_FB down at Q2.B
    "Q2":   (35.70, 35.00, 180),   # E up at +24V, B at R18, C left toward Q1.B
    "R17":  (33.00, 37.20, 90),    # base bias: LOOP_DRV down toward Q1.B
    # SOT-223 turned so the tab (collector, the heat path) is up in open
    # copper and the three leads face the terminal. 0.85 W in a dead short:
    # pour LOOP_C generously around the tab and stitch it to the bottom layer.
    "Q1":   (35.80, 42.80, 90),
    "D4":   (36.90, 49.00, 180),   # anode under Q1's collector lead, K on to J2

    # --- Loop sense, laid out as the INA226 datasheet's Figure 30 ---------
    # U3 is turned so IN+/IN- leave on the side facing the shunt and meet the
    # filter and the Kelvin taps in a straight line; the bypass sits directly
    # at VS/GND (it was 8 mm away, on the wrong side of the chip).
    "U3":   (20.50, 44.50, 270),   # right flank, top to bottom: IN+ IN- VBUS GND VS
    "C9":   (24.40, 43.40, 270),   # across IN+/IN-; 0.1 mm up so the VBUS tap clears its lower pad
    "R13":  (26.40, 43.10, 180),   # IN+ tap  -> R12's LOOP_RTN pad
    "R14":  (26.40, 44.40, 180),   # IN- tap  -> R12's GND pad
    "R12":  (30.00, 43.75, 270),   # shunt, LOOP_RTN up, GND down. The taps carry no
                                   # current, so 3 mm of Kelvin trace costs nothing
                                   # and leaves room to label R13/R14
    "C8":   (23.10, 46.70, 0),     # bypass: +3V3 pad under VS, GND pad beside it
    "R20":  (26.40, 45.80, 180),   # bus-pin series limit

    # --- Field protection: one TVS per wire, each within 6 mm of its pin ---
    "D3":   (30.10, 48.80, 180),   # LOOP_V  -> GND, cathode toward J2 pin 1
    "D5":   (21.00, 48.80, 180),   # LOOP_RTN -> GND, cathode toward J2 pin 2

    # --- USB input and ESD: bottom left, short hop up to pins 13/14 -------
    "J1":   (11.50, 55.97, 0),     # mouth flush with the bottom edge; 0.5 mm left of
                                   # Rev F to clear the wider 3-pin terminal's outline
    "D1":   (11.50, 47.50, 180),   # ESD clamp, flow-through. Turned 180 so D- is on the west: the pair then
                                   # reaches U1 pins 13/14 from the south-west with no crossing. 1.5 mm further
                                   # up than before, which is the room the connector fan-out needs.
    "R7":   (9.80, 51.00, 90),     # CC pulldowns in the lanes between VBUS and the pair, 2 mm from their pins
    "R8":   (13.20, 51.00, 90),
    "R9":   (3.80, 45.50, 90),     # LED resistor
    "LED1": (3.80, 52.00, 90),     # power LED on the left edge, clear of J1

    # --- Bring-up test points (1.0 mm bare pads) ---------------------------
    "TP4":  (11.50, 35.00, 0),     # +3V3, at the LDO output beside C7
    "TP5":  (21.20, 26.00, 0),     # MT_EN, below R15's pull-up
    "TP3":  (23.20, 40.40, 0),     # +24V, beside D2's cathode
    "TP1":  (37.00, 51.60, 0),     # LOOP_V, below D4
    "TP2":  (25.55, 48.80, 0),     # LOOP_RTN, in the gap the return runs up

    # --- Field terminal: bottom right, one-piece push-in block -------------
    # Wire entry faces the bottom edge, its face 0.3 mm inside it. Left to
    # right looking in: 1 = GND, 2 = mA in, 3 = +24 V out -- +24 V under the
    # limiter, GND beside D5's anode, so nothing crosses behind the block.
    "J2":   (25.50, 55.00, 0),
}

#: Optical alignment targets, in an L so the assembler cannot mount the
#: board rotated. 4 mm in from the edges, which is the closest JLCPCB will
#: read (they ask for 3.85 mm) and as far apart as the parts allow.
FIDUCIALS = [(4.00, 7.00), (36.00, 7.00), (36.00, 54.00)]

#: M2 clearance holes. The bottom pair sit 3.5 mm in from the corners, by the
#: connectors, where the plugging forces are. The top pair used to be in the
#: corners too, level with the antenna and 9.6 mm from the module; Espressif
#: asks for ~15 mm clear of metal, so they are down beside the buttons now,
#: 19 mm from the nearest corner of the antenna, and high enough that a 4.6 mm
#: metal standoff clears the button pads (EN and IO0) by 1.5 mm.
HOLES = [(3.50, 16.80), (W - 3.50, 16.80), (3.50, H - 3.50), (W - 3.50, H - 3.50)]
HOLE_DRILL = 2.20

# No antenna keep-out: the overhang already removes the PCB from under the
# antenna, which is what a keep-out would have been for. Corner keep-outs
# beside it were tried and only fought with C3, which has to sit at the
# module's 3V3 pin. At routing time, keep the ground pour back from the top
# edge instead.
KEEPOUTS = {}

#: Designators placed by hand: ref -> (x, y, text angle). The lower-right corner
#: holds the limiter, the sense network, two TVS diodes and the terminal, and
#: tidy_references() has no clear spot beside most of them. Each of these was
#: checked against DRC rather than by eye.
REF_PINS = {
    "R12": (31.55, 43.75, 90),     # upright, between the shunt and Q1
    "C11": (29.40, 41.35, 0),      # the strip between C11 and the shunt
    "R13": (26.40, 41.95, 0),      # above it
    "R14": (28.30, 44.50, 90),     # upright, in the column between taps and shunt
    "R20": (24.75, 45.50, 90),     # upright, left of it
    "TP2": (25.55, 47.30, 0),
    "C8":  (18.20, 46.55, 0),      # the only clear spot in the 1.1 mm strip above D5
    "C9":  (24.40, 41.95, 0),
    "Q1":  (34.60, 37.75, 0),      # the strip above its tab, not under D4
    "D5":  (16.45, 49.90, 0),
    "R22": (13.50, 30.95, 0),      # the load-switch stack reads down its left side
    "R21": (13.50, 32.10, 0),
    "C12": (13.50, 33.25, 0),
    "D4":  (34.05, 49.00, 90),
    "R17": (31.85, 37.60, 90),
    "R18": (37.20, 37.55, 0),
    "R11": (32.70, 34.60, 0),      # east of the divider, over the masked +24V track
    "R10": (32.70, 35.72, 0),
}

# Nets whose length this layout is supposed to be protecting.
CRITICAL = ["/MT_SW", "/VIN_SW", "/INA_INP", "/INA_INN", "/LOOP_RTN", "/LOOP_C",
            "/USB_P", "/USB_N", "/I2C_SDA", "/I2C_SCL"]

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    b = Board(__file__, "esp32-4to20ma-board", size=(W, H))
    b.sync_footprints(prune=True)  # the schematic is the source of truth: add, swap, remove
    b.refresh_footprints()         # pick up library fixes before anything else
    b.outline(radius=1.0)
    b.place_all(PLACEMENT)
    for name, poly in KEEPOUTS.items():
        b.keepout(name, poly)
    for x, y in HOLES:
        b.hole(x, y, HOLE_DRILL)
    for x, y in FIDUCIALS:
        b.fiducial(x, y)
    b.link_schematic()             # symbol UUIDs and pad nets
    b.tidy_references()
    for ref, (x, y, angle) in REF_PINS.items():
        t = b.fps[ref].Reference()
        t.SetTextAngleDegrees(angle)
        t.SetPosition(b.pt(x, y))
    b.check()                      # aborts on overlaps and unplaced parts
    b.save(force="--force" in sys.argv)
    b.drc()
    b.report_nets(CRITICAL)
    b.render(os.path.join(HERE, "render"))


if __name__ == "__main__":
    main()
