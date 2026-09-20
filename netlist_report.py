#!/usr/bin/env python3
"""Writes netlist_report.txt: a pin-level connectivity listing for rework.

Derived from the same PARTS/NETS data the schematic is drawn from, so it
cannot drift from it. Ground connections are listed as just "GND" rather than
enumerating every other pin on the ground net.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_schematic as g  # noqa: E402

GND_NET = "GND"
POWER_NETS = {"GND", "+3V3", "+5V", "+24V"}

_d = g.Design(g.PROJDIR, "esp32-4to20ma-board")
LIB = _d.lib

SECTION_OF = {}
for _fn, _c, _r, _head in g.SECTIONS:
    name = _head.split("  -")[0].strip().title()
    for _s in _fn(_d).symbols:
        if _s["ref"]:
            SECTION_OF[_s["ref"]] = name

PIN_NET = {}
for net, members in g.NETS.items():
    for ref, pin in members:
        PIN_NET[(ref, pin)] = net
NC = set(map(tuple, g.NO_CONNECT))


def pins(ref):
    return LIB.get(g.PARTS[ref][0]).pins(1)


def pin_name(ref, num):
    return LIB.get(g.PARTS[ref][0]).find_pin(num)["name"]


def refkey(r):
    head = r.rstrip("0123456789")
    tail = r[len(head):]
    return (head, int(tail) if tail else 0)


out = []
w = out.append

w("=" * 78)
w("ESP32 4-20 mA ESPHome Sensor Board -- connectivity report")
w("Generated from generate_schematic.py; regenerate with netlist_report.py")
w("=" * 78)

w("")
w("SECTION 1 -- COMPONENTS")
w("")
w(f"{'Ref':6s} {'Schematic block':18s} {'Value':22s} {'LCSC':10s} {'MPN'}")
w("-" * 78)
for ref in sorted(g.PARTS, key=refkey):
    lib_id, value, _fp, lcsc, _mfr, mpn = g.PARTS[ref]
    # test points are bare copper: no LCSC number and nothing to order
    lcsc = lcsc or "--"
    mpn = mpn or "(test point, not in BOM)"
    w(f"{ref:6s} {SECTION_OF.get(ref, '?'):18s} {value:22s} {lcsc:10s} {mpn}")

w("")
w("")
w("SECTION 2 -- PIN CONNECTIONS")
w("")
w("For each pin: the net it sits on, and the other pins on that net.")
w("Pins on GND show only 'GND' -- the full ground membership is in Section 3.")
w("")
for ref in sorted(g.PARTS, key=refkey):
    w(f"--- {ref}  ({g.PARTS[ref][1]})  block: {SECTION_OF.get(ref, '?')}")
    for p in pins(ref):
        num = p["num"]
        net = PIN_NET.get((ref, num))
        if (ref, num) in NC:
            net_s, detail = "(NC)", "-- not connected --"
        elif net == GND_NET:
            net_s, detail = net, ""
        else:
            net_s = net
            detail = ", ".join(f"{r}.{n} ({pin_name(r, n)})"
                               for r, n in g.NETS[net] if (r, n) != (ref, num))
        w(f"   pin {num:<6s} {p['name']:<12s} {net_s:<10s} {detail}")
    w("")

w("")
w("SECTION 3 -- NETS")
w("")
for net in sorted(g.NETS, key=lambda n: (n not in POWER_NETS, n)):
    members = g.NETS[net]
    w(f"{net}  ({len(members)} pins)")
    w("   " + ", ".join(f"{r}.{n}" for r, n in sorted(members, key=lambda m: refkey(m[0]))))
    w("")

w("")
w("SECTION 4 -- NOTES FOR REWORK")
w("")
for line in """
Layout
  One A3 sheet, four blocks in signal-flow order:
    Power Input      USB-C input, ESD clamp, AP2112K 3.3 V LDO, power LED
    Microcontroller  ESP32-S3-WROOM-1-N4, reset/boot buttons, I2C pull-ups
    24 V Loop Supply MT3608 boost, 5 V -> 24 V loop supply
    4-20 Ma Loop     loop terminal, 4.02 ohm shunt, INA226 current monitor

Power rails are power-port symbols (global nets). Blocks connect by net label:
USB_P/USB_N (USB-C -> ESP32-S3) and I2C_SDA/I2C_SCL (ESP32-S3 -> INA226).

Polarity / orientation
  D2  SS34 Schottky: cathode (pin 1) to +24V, anode (pin 2) to the switch node.
  D3  SMAJ36A TVS: cathode (pin 1) to +24V, anode (pin 2) to the loop return.
  LED1 anode (pin 2) from R9, cathode (pin 1) to GND.
  R13 pin 2 is the INA226 side; R14 pin 1 is the ground side.

ESP32-S3 strapping pins -- do not repurpose without checking
  IO0  (pin 27) internal pull-up; SW2 pulls it low for download mode.
  IO46 (pin 16) internal pull-down; must stay low at reset. Left NC.
  IO45 (pin 26) VDD_SPI select; must stay low on the -N4 module. Left NC.
  IO3  (pin 15) no internal pull; JTAG source select only. Left NC.

Calculated values
  R10/R11  MT3608 feedback: Vout = 0.6 x (1 + 390k/10k) = 24.00 V
  R12      shunt: 20 mA x 4.02 ohm = 80.4 mV = 98% of INA226 full scale
  R7/R8    USB-C CC pulldowns, 5.1 k = UFP advertising default current
  R5/R6    I2C pull-ups, 4.7 k for 400 kHz on a short single-target bus
  R9       LED: (3.3 - 1.9) / 330 = 4.2 mA

Two-pin nets (CC1, CC2, LED_A, MT_SW, MT_FB, INA_INP, INA_INN, LOOP_RTN) are
point-to-point and can be rerouted freely. GND, +3V3, +5V and +24V are shared
rails -- check Section 3 before moving anything on them.
""".strip("\n").split("\n"):
    w(line)

path = os.path.join(g.PROJDIR, "netlist_report.txt")
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
print(f"wrote {path} ({len(out)} lines)")
