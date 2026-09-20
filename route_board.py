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

Coordinates are board mm, origin top-left, Y down.
"""
import json
import os
import re
import subprocess
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "esp32-4to20ma-board"
PCB = os.path.join(HERE, NAME + ".kicad_pcb")
AUTO_JSON = os.path.join(HERE, "routing", "autoroute.json")
FREEROUTING = r"C:\Users\diode\tools\freerouting"
KICAD_CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"

OX, OY = 100.0, 50.0
W, H = 40.0, 61.0
F, B = pcbnew.F_Cu, pcbnew.B_Cu
mm = pcbnew.FromMM

board = None
NETS = {}
FPS = {}
MOVED = []           # pads that are not where this script was written for
_REMOVED = []        # pcbnew: a removed item's proxy must never be garbage-collected


def load(path=PCB):
    global board, NETS, FPS
    board = pcbnew.LoadBoard(path)
    NETS = {n.GetNetname(): n for n in board.GetNetInfo().NetsByNetcode().values()}
    FPS = {f.GetReference(): f for f in board.GetFootprints()}


def pt(x, y):
    return pcbnew.VECTOR2I(mm(OX + x), mm(OY + y))


def pad(ref, num, expect=None, net=None):
    """Board-mm centre of a pad. `expect` proves the placement is the one this
    script was written for; `net` proves the netlist is."""
    for p in FPS[ref].Pads():
        if p.GetNumber() == str(num):
            q = p.GetPosition()
            xy = (round(pcbnew.ToMM(q.x) - OX, 3), round(pcbnew.ToMM(q.y) - OY, 3))
            if expect and (abs(xy[0] - expect[0]) > 0.02 or abs(xy[1] - expect[1]) > 0.02):
                MOVED.append("%s.%s is at %s, route_board.py expects %s" % (ref, num, xy, expect))
            if net and p.GetNetname() != net:
                raise SystemExit("%s.%s is on %s, route_board.py expects %s -- netlist changed"
                                 % (ref, num, p.GetNetname(), net))
            return xy
    raise KeyError((ref, num))


def track(net, pts, width, layer=F):
    for a, b in zip(pts, pts[1:]):
        if a == b:
            continue
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pt(*a))
        t.SetEnd(pt(*b))
        t.SetWidth(mm(width))
        t.SetLayer(layer)
        t.SetNet(NETS[net])
        board.Add(t)


def via(net, xy, dia=0.6, drill=0.3):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pt(*xy))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetWidth(mm(dia))
    v.SetDrill(mm(drill))
    v.SetLayerPair(F, B)
    v.SetNet(NETS[net])
    board.Add(v)
    return xy


def clear():
    """Drop every track, via and copper zone. Zones are collected before anything
    is removed, and every removed proxy is kept alive (see _REMOVED)."""
    zones = [board.GetArea(i) for i in range(board.GetAreaCount())]
    doomed = list(board.GetTracks()) + [z for z in zones if not z.GetIsRuleArea()]
    for item in doomed:
        board.Remove(item)
        _REMOVED.append(item)


def zone(net, layer, name, poly=None, priority=0, clearance=0.2, solid=False):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(NETS[net])
    z.SetZoneName(name)
    o = z.Outline()
    o.NewOutline()
    for x, y in (poly or ((0, 0), (W, 0), (W, H), (0, H))):
        o.Append(mm(OX + x), mm(OY + y))
    z.SetLocalClearance(mm(clearance))
    z.SetMinThickness(mm(0.25))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL if solid else pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetThermalReliefGap(mm(0.25))
    z.SetThermalReliefSpokeWidth(mm(0.3))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    z.SetAssignedPriority(priority)
    board.Add(z)
    return z


def zone_connection(ref, num, mode):
    for p in FPS[ref].Pads():
        if p.GetNumber() == str(num):
            p.SetLocalZoneConnection(mode)


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
    track("/LOOP_SNS", [r162, r181, (39.0, 35.44), (39.40, 35.84), (39.40, 45.15), (38.6, 45.95), q13], 0.4)
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
    track("/INA_INN", [r142, (25.0, 44.40), (24.6, 44.0), c92, (23.9, 43.88), (23.78, 44.00), u9], 0.2)
    # supply pin and its capacitor; one ground via for pin 7 and the capacitor
    c81, c82 = pad("C8", 1, (22.62, 46.70), "+3V3"), pad("C8", 2, (23.58, 46.70), "GND")
    u6, u7 = pad("U3", 6, (22.61, 45.50), "+3V3"), pad("U3", 7, (22.61, 45.00), "GND")
    track("+3V3", [c81, u6], 0.25)
    g = via("GND", (24.20, 45.50))
    track("GND", [(23.2, 45.00), (23.70, 45.00), g], 0.25)
    track("GND", [c82, (24.20, 46.08), g], 0.25)
    track("GND", [pad("U3", 1, (18.39, 43.50), "GND"), pad("U3", 2, (18.39, 44.00), "GND")], 0.25)
    track("GND", [(17.8, 43.75), via("GND", (17.10, 43.75))], 0.25)


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
               (17.0, 38.0), (21.0, 36.5), (27.0, 26.5), (6.0, 40.0), (16.5, 41.0), (12.0, 41.0),
               (34.0, 56.5), (24.0, 23.5), (11.0, 23.7), (34.5, 29.0)]:
        via("GND", xy)


def solid_power_grounds():
    """Loops close through these pads: no thermal spokes on them."""
    for ref, num in (("C10", 2), ("C11", 2), ("U5", 2), ("R12", 2), ("D3", 2), ("D5", 2),
                     ("C7", 2), ("C6", 2), ("Q1", 2), ("Q1", 4), ("D4", 2)):
        zone_connection(ref, num, pcbnew.ZONE_CONNECTION_FULL)


# ---------------------------------------------------------------------------
# The autorouted remainder
# ---------------------------------------------------------------------------
#: Nets this script routes completely. Whatever an autorouter adds to them is
#: dropped: it can only be a duplicate (Freerouting does not count a track that
#: ends inside a pad, off its centre, as connected; KiCad does).
SCRIPTED_NETS = {"GND", "+5V", "+24V", "/VIN_SW", "/MT_SW", "/MT_FB", "/USB_P", "/USB_N", "/CC1", "/CC2",
                 "/LOOP_C", "/LOOP_RTN", "/LOOP_SNS", "/LOOP_FB", "/LOOP_DRV", "/INA_INP", "/INA_INN"}


def _sexpr(text):
    """Minimal S-expression reader: nested lists of strings."""
    tok = re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()]+', text)
    stack, cur = [], []
    for t in tok:
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done = cur
            cur = stack.pop()
            cur.append(done)
        else:
            cur.append(t[1:-1] if t.startswith('"') else t)
    return cur[0]


def parse_ses(path):
    """New (unprotected) wires and vias from a Specctra session file, as the
    same plain records snapshot() makes. KiCad's own importer refuses a
    session that carries (type protect), so this reads it directly."""
    root = _sexpr(open(path, encoding="utf-8").read())
    routes = [x for x in root if isinstance(x, list) and x and x[0] == "routes"][0]
    res = [x for x in routes if isinstance(x, list) and x[0] == "resolution"][0]
    per_mm = {"um": 1000.0, "mm": 1.0, "mil": 39.3701, "inch": 0.0393701}[res[1]] * float(res[2])
    net_out = [x for x in routes if isinstance(x, list) and x[0] == "network_out"][0]
    out = []
    for net in (x for x in net_out if isinstance(x, list) and x[0] == "net"):
        name = net[1]
        for item in net[2:]:
            if not isinstance(item, list):
                continue
            if any(isinstance(k, list) and k[:2] == ["type", "protect"] for k in item):
                continue
            if item[0] == "wire":
                path = [k for k in item if isinstance(k, list) and k[0] == "path"][0]
                layer = "F" if path[1] == "top_cu" else "B"
                w = float(path[2]) / per_mm
                xy = [float(v) / per_mm for v in path[3:]]
                pts = [(round(xy[i] - OX, 4), round(-xy[i + 1] - OY, 4)) for i in range(0, len(xy), 2)]
                for a, b in zip(pts, pts[1:]):
                    if a != b:
                        out.append({"net": name, "layer": layer, "x1": a[0], "y1": a[1],
                                    "x2": b[0], "y2": b[1], "w": round(w, 3)})
            elif item[0] == "via":
                m = re.search(r"_(\d+):(\d+)_um", item[1])
                out.append({"via": True, "net": name, "x": round(float(item[2]) / per_mm - OX, 4),
                            "y": round(-float(item[3]) / per_mm - OY, 4),
                            "d": int(m.group(1)) / 1000.0, "drill": int(m.group(2)) / 1000.0})
    return out


def normalise():
    """Make the scripted copper legible to an autorouter, which is stricter
    than KiCad about what counts as connected: split a track wherever another
    track of its net ends on it (a T junction), so every junction is an
    endpoint. Geometry is unchanged."""
    splits = 0
    for _ in range(4):
        tracks = [t for t in board.GetTracks() if t.GetClass() != "PCB_VIA"]
        ends = {}
        for t in board.GetTracks():
            if t.GetClass() == "PCB_VIA":
                ends.setdefault(t.GetNetname(), set()).add((t.GetPosition().x, t.GetPosition().y, None))
            else:
                for q in (t.GetStart(), t.GetEnd()):
                    ends.setdefault(t.GetNetname(), set()).add((q.x, q.y, t.GetLayer()))
        changed = False
        for t in tracks:
            a, b = t.GetStart(), t.GetEnd()
            L2 = float(b.x - a.x) ** 2 + float(b.y - a.y) ** 2
            if L2 == 0:
                continue
            for (x, y, layer) in sorted(ends.get(t.GetNetname(), ()), key=lambda e: (e[0], e[1])):
                if layer is not None and layer != t.GetLayer():
                    continue
                if (x, y) in ((a.x, a.y), (b.x, b.y)):
                    continue
                u = ((x - a.x) * (b.x - a.x) + (y - a.y) * (b.y - a.y)) / L2
                if not 0.0 < u < 1.0:
                    continue
                px, py = a.x + u * (b.x - a.x), a.y + u * (b.y - a.y)
                if (px - x) ** 2 + (py - y) ** 2 > 1000.0 ** 2:       # 1 um
                    continue
                t2 = pcbnew.PCB_TRACK(board)
                t2.SetStart(pcbnew.VECTOR2I(int(x), int(y)))
                t2.SetEnd(b)
                t2.SetWidth(t.GetWidth())
                t2.SetLayer(t.GetLayer())
                t2.SetNet(t.GetNet())
                t.SetEnd(pcbnew.VECTOR2I(int(x), int(y)))
                board.Add(t2)
                splits += 1
                changed = True
                break
        if not changed:
            break
    return splits


def snapshot(bd=None):
    """Every track and via as plain data, for comparison and for replay."""
    out = []
    for t in (bd or board).GetTracks():
        n = t.GetNetname()
        if t.GetClass() == "PCB_VIA":
            q = t.GetPosition()
            out.append({"via": True, "net": n, "x": round(pcbnew.ToMM(q.x) - OX, 4),
                        "y": round(pcbnew.ToMM(q.y) - OY, 4),
                        "d": round(pcbnew.ToMM(t.GetWidth(F)), 3), "drill": round(pcbnew.ToMM(t.GetDrill()), 3)})
        else:
            a, b = t.GetStart(), t.GetEnd()
            out.append({"net": n, "layer": "F" if t.GetLayer() == F else "B",
                        "x1": round(pcbnew.ToMM(a.x) - OX, 4), "y1": round(pcbnew.ToMM(a.y) - OY, 4),
                        "x2": round(pcbnew.ToMM(b.x) - OX, 4), "y2": round(pcbnew.ToMM(b.y) - OY, 4),
                        "w": round(pcbnew.ToMM(t.GetWidth()), 3)})
    return out


def _key(t):
    if t.get("via"):
        return ("v", t["net"], round(t["x"], 2), round(t["y"], 2))
    a, b = (round(t["x1"], 2), round(t["y1"], 2)), (round(t["x2"], 2), round(t["y2"], 2))
    return ("t", t["net"], t["layer"]) + tuple(sorted((a, b)))


def replay_autoroute():
    if not os.path.exists(AUTO_JSON):
        print("no routing/autoroute.json yet -- run with --autoroute")
        return 0
    data = json.load(open(AUTO_JSON, encoding="utf-8"))
    for t in data["items"]:
        if t["net"] not in NETS:
            raise SystemExit("autoroute.json names net %s, which no longer exists -- run --autoroute" % t["net"])
        if t.get("via"):
            via(t["net"], (t["x"], t["y"]), t["d"], t["drill"])
        else:
            track(t["net"], [(t["x1"], t["y1"]), (t["x2"], t["y2"])], t["w"], F if t["layer"] == "F" else B)
    return len(data["items"])


def autoroute(passes):
    """Scripted routes -> Specctra DSN -> Freerouting -> SES -> keep what is new."""
    work = os.path.join(HERE, "routing", "work")
    os.makedirs(work, exist_ok=True)
    tmp = os.path.join(work, NAME + ".kicad_pcb")
    for ext in (".kicad_pro", ".kicad_dru"):
        src = os.path.join(HERE, NAME + ext)
        if os.path.exists(src):
            open(os.path.join(work, NAME + ext), "wb").write(open(src, "rb").read())
    pcbnew.SaveBoard(tmp, board)
    dsn, ses = os.path.join(work, NAME + ".dsn"), os.path.join(work, NAME + ".ses")
    for f in (dsn, ses):
        if os.path.exists(f):
            os.remove(f)
    wb = pcbnew.LoadBoard(tmp)
    if not pcbnew.ExportSpecctraDSN(wb, dsn):
        raise SystemExit("DSN export failed")
    # Two things KiCad's export leaves to us. Existing wiring is written as
    # (type route), which an autorouter may rip up: mark it (type protect).
    # And netclasses come out as "GND,Default", which -inc cannot name.
    text = open(dsn, encoding="utf-8").read()
    text = text.replace("(type route)", "(type protect)").replace(",Default ", " ")
    open(dsn, "w", encoding="utf-8").write(text)
    java = [os.path.join(FREEROUTING, d, "bin", "java.exe") for d in os.listdir(FREEROUTING) if d.startswith("jdk")][0]
    jar = [os.path.join(FREEROUTING, f) for f in os.listdir(FREEROUTING) if f.endswith(".jar")][0]
    # Headless, no SMD fan-out stage (it scatters vias), telemetry off, and its
    # settings file kept in the work folder rather than in the user profile.
    cmd = [java, "-jar", jar, "--gui.enabled=false", "--user_data_path=" + os.path.join(work, "freerouting-user"),
           "--usage_and_diagnostic_data.disable_analytics=true", "--profile.allow_telemetry=false",
           "--router.fanout.enabled=false", "--router.max_passes=%d" % passes,
           "-de", dsn, "-do", ses]
    print("running Freerouting:", " ".join(os.path.basename(c) if os.sep in c else c for c in cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, cwd=work)
    open(os.path.join(work, "freerouting.log"), "w", encoding="utf-8").write(r.stdout + "\n" + r.stderr)
    if not os.path.exists(ses):
        raise SystemExit("Freerouting wrote no session file; see routing/work/freerouting.log")
    new = parse_ses(ses)
    dropped = [t for t in new if t["net"] in SCRIPTED_NETS]
    new = [t for t in new if t["net"] not in SCRIPTED_NETS]
    print("Freerouting added %d items on %d nets (%d more on scripted nets, dropped)"
          % (len(new), len({t["net"] for t in new}), len(dropped)))
    os.makedirs(os.path.dirname(AUTO_JSON), exist_ok=True)
    json.dump({"tool": os.path.basename(jar), "passes": passes, "items": new},
              open(AUTO_JSON, "w", encoding="utf-8"), indent=0)
    return len(new)


# ---------------------------------------------------------------------------
def drc_report():
    out = os.path.join(HERE, "routing", "drc.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run([KICAD_CLI, "pcb", "drc", "--format", "json", "--units", "mm", "--severity-all",
                    "--schematic-parity", "-o", out, PCB], capture_output=True, text=True)
    d = json.load(open(out, encoding="utf-8"))

    def where(it):
        p = it.get("pos", {})
        return "(%.2f, %.2f)" % (p.get("x", 0) - OX, p.get("y", 0) - OY)
    v = d.get("violations", [])
    print("DRC: %d violations, %d unconnected, %d parity" % (len(v), len(d.get("unconnected_items", [])),
                                                             len(d.get("schematic_parity", []))))
    for x in v:
        items = x.get("items", [])
        print("  %-8s %-22s %s  %s" % (x["severity"], x["type"], where(items[0]) if items else "",
                                       " | ".join(i["description"][:60] for i in items)))
    for x in d.get("unconnected_items", []):
        items = x.get("items", [])
        print("  unconnected  %s  %s" % (where(items[0]) if items else "", " | ".join(i["description"][:70] for i in items)))
    return d


def main():
    load()
    clear()
    solid_power_grounds()
    route_usb()
    route_cc_vbus()
    route_3v3()
    route_boost()
    route_loop()
    route_sense()
    if MOVED:
        raise SystemExit("placement changed -- these routes have to follow:\n  " + "\n  ".join(MOVED))
    # ground vias and Q1's copper go in BEFORE the autorouter runs, so that it
    # routes round them; the ground pours go in after it, over whatever is left
    route_ground()
    q1 = [(33.75, 38.2), (38.75, 38.2), (38.75, 47.3), (33.75, 47.3)]
    zone("/LOOP_C", F, "Q1 copper top", q1, 1, 0.25, True)
    zone("/LOOP_C", B, "Q1 copper bottom", q1, 1, 0.25, True)
    zone("GND", F, "GND top")           # present before the export, so the autorouter sees ground as a
    zone("GND", B, "GND bottom")        # plane and leaves it alone; filled after its tracks are in
    normalise()
    scripted = len(list(board.GetTracks()))
    if "--autoroute" in sys.argv:
        autoroute(int(os.environ.get("FREEROUTING_PASSES", "30")))
    auto = replay_autoroute()
    pcbnew.ZONE_FILLER(board).Fill([board.GetArea(i) for i in range(board.GetAreaCount())])
    pcbnew.SaveBoard(PCB, board)
    print("routed: %d scripted + %d autorouted track segments and vias" % (scripted, auto))
    if "--dump" in sys.argv:
        json.dump(snapshot(), open(os.path.join(HERE, "routing", "tracks.json"), "w"))
    drc_report()


if __name__ == "__main__":
    main()
