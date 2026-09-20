#!/usr/bin/env python3
"""Route the ESP32-S3 4-20 mA board (2 layers) and pour ground.

    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" route_board.py
    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" route_board.py --autoroute

A hybrid. The nets where geometry IS the design are scripted here and never
handed to an autorouter:

  * the MT3608 boost -- input loop, switch node, output loop and their ground
    returns (datasheet Figure 3),
  * the INA226 Kelvin taps off the shunt (datasheet Figure 30),
  * the USB-C fan-out, the ESD clamp and the pair up to the module,
  * the power trunks, the 24 V loop path and Q1's copper,
  * every ground via and both ground pours.

Everything else (I2C, EN, IO0, MT_EN, the load-switch gate network, the LED,
the pull-up branches) is Freerouting's, run with --autoroute. Its result is
kept in routing/autoroute.json and replayed on every ordinary run, so the
board is reproducible without Java and without re-rolling the autorouter.

Idempotent: every track, via and copper zone is removed and redrawn. The
script checks that each pad it starts or ends on is where it expects and
stops if not -- move a part in place_components.py and its route here has to
follow. If a part that only the autorouter touches moves, run --autoroute.

Coordinates are board mm, origin top-left, Y down. The drawing, autorouter and
reporting machinery is routelib.py (from the kicad-pcb-placement skill); this
file is only this board's copper.
"""
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from routelib import Router, F, B      # noqa: E402

NAME = "esp32-4to20ma-board"
W, H = 40.0, 61.0

r = Router(__file__, NAME, size=(W, H))
pad, track, via, zone, zone_connection = r.pad, r.track, r.via, r.zone, r.zone_connection


# ---------------------------------------------------------------------------
# USB-C entry: fan-out, ESD clamp, CC pulldowns, VBUS
# ---------------------------------------------------------------------------
P, N = "/USB_P", "/USB_N"


def route_usb():
    """J1's pads read N P N P (B7 A6 A7 B6). The OUTER two are the main path:
    D- on the west, D+ on the east, which is the order D1 (turned 180) and the
    module's pins 13/14 both want, so the pair never crosses itself. The inner
    two are the flip-side duplicates: A6 joins D+ on the top layer, A7 joins
    D- by the only bottom strap in the pair, 2.7 mm long."""
    yp = 53.59
    b7, a6 = pad("J1", "B7", (10.75, yp), N), pad("J1", "A6", (11.25, yp), P)
    a7, b6 = pad("J1", "A7", (11.75, yp), N), pad("J1", "B6", (12.25, yp), P)
    d4, d6 = pad("D1", 4, (10.55, 48.65), N), pad("D1", 6, (12.45, 48.65), P)
    d3, d1 = pad("D1", 3, (10.55, 46.35), N), pad("D1", 1, (12.45, 46.35), P)
    w = 0.2                                        # 0.3 mm pads on a 0.5 mm pitch
    # D-: B7 straight up into the clamp, through it (flow-through), out the top
    track(N, [b7, (10.75, 52.1), (10.55, 51.9), d4, d3], w)
    nb = via(N, (10.55, 49.95))
    na = via(N, (11.80, 52.30))
    track(N, [a7, (11.75, 52.8), na], w)
    track(N, [na, (10.55, 51.05), nb], w, B)
    # D+: B6 up the east column; A6 crosses over A7's via on the top layer
    track(P, [b6, (12.25, 52.95), (12.45, 52.75), d6, d1], w)
    track(P, [a6, (11.25, 51.8), (11.45, 51.6), (12.45, 51.6)], w)

    # coupled pair, centre line x = 13.0, from above the clamp to the module
    uw, ug = 0.25, 0.20
    xn, xp = 13.0 - (uw + ug) / 2, 13.0 + (uw + ug) / 2
    u13, u14 = pad("U1", 13, (13.10, 16.24), N), pad("U1", 14, (13.10, 17.51), P)
    track(P, [d1, (12.45, 45.3), (xp, 45.3 - (xp - 12.45)), (xp, u14[1])], uw)
    yn = 44.7 - (xn - 10.55)
    track(N, [d3, (10.55, 44.7), (xn, yn), (xn, 19.0), (11.95, 19.0 - (xn - 11.95)),
              (11.95, 16.64), (12.35, 16.24), u13], uw)


def route_cc_vbus():
    yp = 53.59
    a5, b5 = pad("J1", "A5", (10.25, yp), "/CC1"), pad("J1", "B5", (13.25, yp), "/CC2")
    r7, r8 = pad("R7", 1, (9.80, 51.51), "/CC1"), pad("R8", 1, (13.20, 51.51), "/CC2")
    track("/CC1", [a5, (10.25, 52.9), (9.80, 52.45), r7], 0.2)
    track("/CC2", [b5, (13.25, 52.2), r8], 0.2)
    for ref, x in (("R7", 9.80), ("R8", 13.20)):
        g = pad(ref, 2, (x, 50.49), "GND")
        track("GND", [g, via("GND", (x, 49.60))], 0.3)
    # J1's two ground signal pins are boxed in by their neighbours, so the pour
    # reaches each with one spoke at best: tie each to the shell stake beside it
    for num, x, xs in (("A1B12", 8.30, 7.45), ("B1A12", 14.70, 15.55)):
        g = pad("J1", num, (x, yp), "GND")
        track("GND", [g, (xs, yp)], 0.3)
        zone_connection("J1", num, pcbnew.ZONE_CONNECTION_FULL)
    # the clamp's ground pin, boxed in by the pair: its own via
    track("GND", [pad("D1", 2, (11.50, 46.35), "GND"), via("GND", (11.50, 45.20))], 0.3)

    # VBUS. The receptacle's two VBUS pins are only joined inside a plug, so the
    # board joins them: one bottom link under the clamp, which also feeds D1.5.
    vl, vr = pad("J1", "A4B9", (9.10, yp), "+5V"), pad("J1", "B4A9", (13.90, yp), "+5V")
    d5 = pad("D1", 5, (11.50, 48.65), "+5V")
    yl = 47.50
    jl, jm, jr = via("+5V", (9.10, yl), 0.8, 0.4), via("+5V", (11.50, yl)), via("+5V", (13.90, yl), 0.8, 0.4)
    track("+5V", [d5, jm], 0.3)
    track("+5V", [jl, jr], 0.5, B)
    track("+5V", [vl, (9.10, 49.0)], 0.3)
    track("+5V", [vr, (13.90, 49.0)], 0.3)
    # west trunk: straight up to the LDO, both of its +5V pins and C6
    u41, u43 = pad("U4", 1, (7.05, 33.30), "+5V"), pad("U4", 3, (8.95, 33.30), "+5V")
    c6 = pad("C6", 1, (4.50, 32.48), "+5V")
    track("+5V", [(9.10, 49.0), (9.10, 35.05), (8.95, 34.9), u43], 0.5)
    track("+5V", [(8.95, 34.9), (7.05, 34.9), u41], 0.5)
    track("+5V", [(7.05, 34.9), (4.50, 34.9), c6], 0.4)
    # east trunk: up to the load switch
    q32 = pad("Q3", 2, (17.91, 33.85), "+5V")
    c12, r21 = pad("C12", 1, (15.37, 33.25), "+5V"), pad("R21", 1, (15.34, 32.10), "+5V")
    track("+5V", [(13.90, 49.0), (13.90, 47.0), (14.60, 46.3), (14.60, 35.0), (15.30, 34.3),
                  (17.46, 34.3), q32], 0.5)
    track("+5V", [(15.37, 34.3), c12, r21], 0.3)


# ---------------------------------------------------------------------------
# 3.3 V: LDO output, its capacitor, the trunk up the west side
# ---------------------------------------------------------------------------
def route_3v3():
    u45 = pad("U4", 5, (7.05, 30.70), "+3V3")
    c7, tp4 = pad("C7", 1, (11.50, 32.78), "+3V3"), pad("TP4", 1, (11.50, 35.00), "+3V3")
    track("+3V3", [u45, (7.05, 29.4), (10.30, 29.4), (10.30, 32.78), c7, tp4], 0.5)
    c2, r5 = pad("C2", 1, (8.35, 8.80), "+3V3"), pad("R5", 1, (8.99, 14.90), "+3V3")
    r1, c3 = pad("R1", 1, (8.99, 4.30), "+3V3"), pad("C3", 1, (9.02, 2.30), "+3V3")
    track("+3V3", [(7.05, 29.4), (8.00, 28.45), (8.00, 9.5), c2], 0.5)
    track("+3V3", [(8.00, 14.90), r5], 0.3)
    track("+3V3", [c2, (8.00, 8.1), (8.00, 3.0), (8.70, 2.30), c3], 0.4)
    track("+3V3", [(8.00, 4.80), (8.50, 4.30), r1], 0.3)


# ---------------------------------------------------------------------------
# MT3608 boost (datasheet Figure 3)
# ---------------------------------------------------------------------------
def route_boost():
    u = {n: pad("U5", n) for n in range(1, 7)}
    pad("U5", 2, (28.00, 33.15), "GND")
    l1, l2 = pad("L1", 1, (22.20, 32.40), "/VIN_SW"), pad("L1", 2, (25.20, 32.40), "/MT_SW")
    c10v, c10g = pad("C10", 1, (31.20, 29.03), "/VIN_SW"), pad("C10", 2, (31.20, 31.97), "GND")
    c11v, c11g = pad("C11", 1, (29.40, 39.62), "+24V"), pad("C11", 2, (29.40, 36.67), "GND")
    d2a, d2k = pad("D2", 2, (26.00, 35.95), "/MT_SW"), pad("D2", 1, (26.00, 40.35), "+24V")
    q33 = pad("Q3", 3, (19.79, 32.90), "/VIN_SW")
    # input: load switch -> inductor, and along the top of L1 to IN, EN and CIN
    track("/VIN_SW", [q33, (21.4, 32.90)], 0.6)
    track("/VIN_SW", [(22.20, 30.8), (22.20, 29.5), (30.0, 29.5)], 0.6)
    track("/VIN_SW", [(28.00, 29.5), u[5]], 0.45)
    track("/VIN_SW", [(28.95, 29.5), u[4]], 0.45)
    # switch node: as small as the three pads allow
    track("/MT_SW", [(25.6, 33.15), u[1]], 0.5)
    track("/MT_SW", [(25.5, 33.8), (25.5, 35.4)], 1.0)
    # output: rectifier -> COUT -> test point
    track("+24V", [(26.0, 39.75), (29.4, 39.75)], 0.8)
    track("+24V", [d2k, pad("TP3", 1, (23.20, 40.40), "+24V")], 0.4)
    # grounds. CIN returns UNDER the IC to pin 2 (Figure 3); COUT returns to the
    # same pin down the east side of the rectifier. Two vias on that path and
    # one at each capacitor tie the loop to the bottom plane.
    track("GND", [(30.0, 32.0), (28.00, 32.0), u[2]], 0.5)
    track("GND", [u[2], (28.00, 35.6), (28.5, 36.3), (28.9, 36.5)], 0.6)
    for xy in ((28.00, 34.5), (28.00, 35.45), (29.30, 32.0)):
        via("GND", xy)
    track("GND", [(32.3, 31.97), via("GND", (33.10, 31.97))], 0.5)
    # feedback: 1 mm from pin 3 to the divider node, and the divider's two ends
    r11f, r11g = pad("R11", 1, (29.79, 34.00), "/MT_FB"), pad("R11", 2, (30.81, 34.00), "GND")
    r10f, r10v = pad("R10", 2, (29.79, 35.20), "/MT_FB"), pad("R10", 1, (30.81, 35.20), "+24V")
    track("/MT_FB", [u[3], (28.95, 33.85), (29.10, 34.00), r11f, r10f], 0.2)
    track("GND", [r11g, (30.81, 32.3)], 0.3)
    # +24V east to the limiter, top layer all the way
    q22, r16 = pad("Q2", 2, (36.64, 34.05), "+24V"), pad("R16", 1, (38.60, 32.89), "+24V")
    track("+24V", [(30.6, 39.62), (31.50, 39.62), (31.50, 34.4), (31.85, 34.05), q22], 0.4)
    track("+24V", [r10v, (31.50, 35.20)], 0.3)
    track("+24V", [q22, (36.64, 33.45), (37.20, 32.89), r16], 0.3)


# ---------------------------------------------------------------------------
# Current limiter and the 24 V loop
# ---------------------------------------------------------------------------
def route_loop():
    r162, r181 = pad("R16", 2, (38.60, 33.91), "/LOOP_SNS"), pad("R18", 1, (38.60, 35.44), "/LOOP_SNS")
    r182, q21 = pad("R18", 2, (38.60, 36.46), "/LOOP_FB"), pad("Q2", 1, (36.64, 35.95), "/LOOP_FB")
    q23, r171 = pad("Q2", 3, (34.76, 35.00), "/LOOP_DRV"), pad("R17", 1, (33.00, 37.71), "/LOOP_DRV")
    q11 = pad("Q1", 1, (33.50, 45.95), "/LOOP_DRV")
    q12, q14 = pad("Q1", 2, (35.80, 45.95), "/LOOP_C"), pad("Q1", 4, (35.80, 39.65), "/LOOP_C")
    q13 = pad("Q1", 3, (38.10, 45.95), "/LOOP_SNS")
    track("/LOOP_SNS", [r162, r181, (38.97, 35.44), (39.32, 35.79), (39.32, 45.23), (38.6, 45.95), q13], 0.3)
    track("/LOOP_FB", [r182, (37.6, 36.46), (37.2, 36.06), q21], 0.25)
    track("/LOOP_DRV", [q23, (34.3, 35.0), (33.85, 35.45), (33.85, 37.3), (33.44, 37.71), r171,
                        (33.0, 44.6), (33.5, 45.1), q11], 0.25)
    track("GND", [pad("R17", 2, (33.00, 36.69), "GND"), via("GND", (32.30, 36.2))], 0.3)
    # Q1: tab and pin 2 are one copper area, top and bottom, tied by six vias
    # under the body. 0.84 W worst case (a dead short until firmware drops MT_EN).
    track("/LOOP_C", [q14, q12], 1.5)
    d42, d41 = pad("D4", 2, (35.25, 49.00), "/LOOP_C"), pad("D4", 1, (38.55, 49.00), "/LOOP_V")
    track("/LOOP_C", [q12, (35.80, 47.6), (35.45, 47.95), (35.45, 48.6)], 0.5)
    for x in (34.6, 35.8, 37.0):
        for y in (41.8, 43.4):
            via("/LOOP_C", (x, y))
    # LOOP_V: blocking diode -> round the south of D4 -> TVS, test point, terminal
    d31, j23 = pad("D3", 1, (32.30, 48.80), "/LOOP_V"), pad("J2", 3, (30.50, 55.00), "/LOOP_V")
    tp1 = pad("TP1", 1, (37.00, 51.60), "/LOOP_V")
    track("/LOOP_V", [d41, (38.55, 50.0), (38.15, 50.4), (32.70, 50.4), (32.30, 50.0), d31], 0.5)
    track("/LOOP_V", [(37.00, 50.4), tp1], 0.4)
    track("/LOOP_V", [(32.30, 50.4), (30.50, 52.2), j23], 0.5)
    # LOOP_RTN: terminal -> test point and TVS -> east, then up to the shunt's
    # OUTER edge, so load current never shares copper with the Kelvin taps
    j22, tp2 = pad("J2", 2, (25.50, 55.00), "/LOOP_RTN"), pad("TP2", 1, (25.55, 48.80), "/LOOP_RTN")
    d51, r121 = pad("D5", 1, (23.20, 48.80), "/LOOP_RTN"), pad("R12", 1, (30.00, 42.84), "/LOOP_RTN")
    track("/LOOP_RTN", [j22, (25.50, 49.2), tp2, d51], 0.5)
    track("/LOOP_RTN", [tp2, (25.55, 47.35), (25.95, 46.95), (30.90, 46.95), (31.30, 46.55),
                        (31.30, 43.2), (30.95, 42.84), (30.3, 42.84)], 0.4)
    # the shunt's ground end and both TVS grounds go straight down to the plane
    r122 = pad("R12", 2, (30.00, 44.66), "GND")
    for x in (29.6, 30.4):
        track("GND", [(x, 45.0), via("GND", (x, 45.95))], 0.5)
    for ref, x in (("D3", 27.90), ("D5", 18.80)):
        g = pad(ref, 2, (x, 48.80), "GND")
        for dx in (-0.7, 0.7):
            track("GND", [(x + dx, 49.6), via("GND", (x + dx, 50.45))], 0.5)
    track("GND", [(18.80, 49.6), (18.80, 51.4), (20.50, 53.1), pad("J2", 1, (20.50, 55.00), "GND")], 0.8)


# ---------------------------------------------------------------------------
# INA226: Kelvin taps, filter, decoupling (datasheet Figure 30)
# ---------------------------------------------------------------------------
def route_sense():
    r131, r132 = pad("R13", 1, (26.91, 43.10), "/LOOP_RTN"), pad("R13", 2, (25.89, 43.10), "/INA_INP")
    r141, r142 = pad("R14", 1, (26.91, 44.40), "GND"), pad("R14", 2, (25.89, 44.40), "/INA_INN")
    c91, c92 = pad("C9", 1, (24.40, 42.92), "/INA_INP"), pad("C9", 2, (24.40, 43.88), "/INA_INN")
    u10, u9 = pad("U3", 10, (22.61, 43.50), "/INA_INP"), pad("U3", 9, (22.61, 44.00), "/INA_INN")
    # taps enter the shunt pads on their INNER faces, as a pair, 1.3 mm apart
    track("/LOOP_RTN", [r131, (29.6, 43.10)], 0.2)
    track("GND", [r141, (29.6, 44.40)], 0.2)
    # R14.1 is on GND by name only: it must see the shunt pad and nothing else,
    # so the pour is kept off it
    zone_connection("R14", 1, pcbnew.ZONE_CONNECTION_NONE)
    track("/INA_INP", [r132, (24.9, 43.10), (24.72, 42.92), c91, (23.85, 42.92), (23.41, 43.36), (23.2, 43.50), u10], 0.2)
    track("/INA_INN", [r142, (25.49, 44.00), (24.52, 44.00), c92, (23.9, 43.88), (23.78, 44.00), u9], 0.2)
    # bus-voltage tap: out of pin 8 under C9, then down to R20 clear of the IN- tap
    u8, r202 = pad("U3", 8, (22.61, 44.50), "/INA_VBUS"), pad("R20", 2, (25.89, 45.80), "/INA_VBUS")
    track("/INA_VBUS", [u8, (24.75, 44.50), (25.35, 45.10), (25.35, 45.55), (25.60, 45.80), r202], 0.2)
    # supply pin and its capacitor; one ground via for pin 7 and the capacitor
    c81, c82 = pad("C8", 1, (22.62, 46.70), "+3V3"), pad("C8", 2, (23.58, 46.70), "GND")
    u6, u7 = pad("U3", 6, (22.61, 45.50), "+3V3"), pad("U3", 7, (22.61, 45.00), "GND")
    track("+3V3", [c81, u6], 0.25)
    g = via("GND", (24.20, 45.50))
    track("GND", [(23.2, 45.00), (23.70, 45.00), g], 0.25)
    track("GND", [c82, (24.20, 46.08), g], 0.25)
    track("GND", [pad("U3", 1, (18.39, 43.50), "GND"), pad("U3", 2, (18.39, 44.00), "GND")], 0.25)
    track("GND", [pad("U3", 1), via("GND", (18.39, 42.55))], 0.25)
    # I2C lands on the west side as a pair: SDA inside, SCL outside, which is the
    # order pins 4 and 5 want. Left to itself the autorouter wraps SCL round the
    # corner first and boxes SDA in. It picks these two stubs up at their top ends.
    u4, u5 = pad("U3", 4, (18.39, 45.00), "/I2C_SDA"), pad("U3", 5, (18.39, 45.50), "/I2C_SCL")
    track("/I2C_SDA", [u4, (17.20, 45.00), (16.75, 44.55), (16.75, 38.0)], 0.2)
    track("/I2C_SCL", [u5, (17.00, 45.50), (16.30, 44.80), (16.30, 38.0)], 0.2)


# ---------------------------------------------------------------------------
# Ground: vias and pad connections
# ---------------------------------------------------------------------------
def route_ground():
    """One via beside each ground pad that the top pour alone would leave on a
    long or thin path, then stitching so the two pours act as one."""
    todo = [("C7", 2, (11.50, 30.30)), ("U4", 2, (8.00, 34.05)), ("C6", 2, (4.50, 30.60)),
            ("Q4", 2, (19.85, 27.65)), ("C2", 2, (10.25, 10.3)), ("C3", 2, (10.9, 2.30)),
            ("C1", 2, (10.9, 6.30)), ("LED1", 1, (5.2, 52.94))]
    for ref, num, xy in todo:
        p = pad(ref, num, net="GND")
        track("GND", [p, via("GND", xy)], 0.3)
    for xy in [(2.0, 25.0), (2.0, 40.0), (20.0, 58.5), (38.0, 25.0), (38.0, 10.0), (2.0, 10.0),
               (17.8, 38.0), (21.0, 36.5), (27.0, 26.5), (6.0, 40.0), (15.5, 41.0), (12.0, 41.0),
               (34.0, 56.5), (24.0, 23.5), (11.0, 23.7), (34.5, 29.0)]:
        via("GND", xy)


def solid_power_grounds():
    """Loops close through these pads: no thermal spokes on them."""
    for ref, num in (("C10", 2), ("C11", 2), ("U5", 2), ("R12", 2), ("D3", 2), ("D5", 2),
                     ("C7", 2), ("C6", 2), ("Q1", 2), ("Q1", 4), ("D4", 2)):
        zone_connection(ref, num, pcbnew.ZONE_CONNECTION_FULL)
    # the module's centre pad and its thermal holes: solid into both pours
    zone_connection("U1", 41, pcbnew.ZONE_CONNECTION_FULL)


#: Nets this script routes completely. Whatever an autorouter adds to them is
#: dropped: it can only be a duplicate (Freerouting does not count a track that
#: ends inside a pad, off its centre, as connected; KiCad does).
SCRIPTED_NETS = {"GND", "+5V", "+24V", "/VIN_SW", "/MT_SW", "/MT_FB", "/USB_P", "/USB_N", "/CC1", "/CC2",
                 "/LOOP_C", "/LOOP_RTN", "/LOOP_SNS", "/LOOP_FB", "/LOOP_DRV", "/INA_INP", "/INA_INN",
                 "/INA_VBUS"}


def main():
    r.clear()
    solid_power_grounds()
    route_usb()
    route_cc_vbus()
    route_3v3()
    route_boost()
    route_loop()
    route_sense()
    r.check_moved()
    # ground vias and Q1's copper go in BEFORE the autorouter runs, so that it
    # routes round them
    route_ground()
    q1 = [(33.75, 38.2), (38.75, 38.2), (38.75, 47.3), (33.75, 47.3)]
    zone("/LOOP_C", F, "Q1 copper top", q1, 1, 0.25, True)
    zone("/LOOP_C", B, "Q1 copper bottom", q1, 1, 0.25, True)
    zone("GND", F, "GND top")           # present before the export, so the autorouter sees ground as a
    zone("GND", B, "GND bottom")        # plane and leaves it alone; filled after its tracks are in
    r.normalise()
    scripted = r.count()
    if "--autoroute" in sys.argv:
        r.autoroute(SCRIPTED_NETS, passes=int(os.environ.get("FREEROUTING_PASSES", "30")),
                    best_of=int(os.environ.get("FREEROUTING_BEST_OF", "1")))
    auto = r.replay()
    r.fill()
    r.save()
    print("routed: %d scripted + %d autorouted track segments and vias" % (scripted, auto))
    if "--dump" in sys.argv:
        import json
        json.dump(r.snapshot(), open(os.path.join(HERE, "routing", "tracks.json"), "w"))
    r.drc_report()
    r.report(pairs=[("/USB_P", "/USB_N")])


if __name__ == "__main__":
    main()
