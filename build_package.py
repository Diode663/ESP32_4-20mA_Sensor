#!/usr/bin/env python3
"""Build the JLCPCB turnkey package into fab/:

    fab/gerbers/*            gerbers + Excellon drill (PTH and NPTH separate) + drill maps
    fab/<name>_gerbers.zip   the file to upload
    fab/<name>_bom.csv       Comment, Designator, Footprint, LCSC Part #, MPN, Manufacturer, Quantity
    fab/<name>_cpl.csv       placement file (from jlc_cpl.py + jlc_rotations.json)
    fab/ORDER_NOTES.txt      the options to pick on JLCPCB's order form, and what to look at

    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" build_package.py

It refuses to build unless KiCad's DRC is clean: nothing unconnected, schematic
parity zero, and no error other than the two this project has accepted and
documented (README, "J1's hole clearance"): J1's own locating pegs sit 0.18 mm
from its own ground pads, inside the library footprint, where moving parts
cannot fix it. Anything else stops the build.

Gerbers, drill and placement all use the drill/place origin pcblib sets at the
board's top-left corner, so they line up. The BOM is read from the BOARD's
footprint fields, not from bom/bom.csv, so it is exactly what is placed; the two
are cross-checked, and the build stops if the BOM and CPL designators differ
(JLCPCB rejects that upload) or if the board disagrees with bom/bom.csv.
"""
import collections
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "esp32-4to20ma-board"
CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
PCB = os.path.join(HERE, NAME + ".kicad_pcb")
FAB = os.path.join(HERE, "fab")
GER = os.path.join(FAB, "gerbers")
LAYERS = "F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"

ORDER_NOTES = """JLCPCB order settings for esp32-4to20ma-board (Rev G, 2026-09-20)

PCB
  Layers 2, 40 x 61 mm, thickness 1.6 mm, outer copper 1 oz, FR-4 (stackup JLC0216A).
  Surface finish: LeadFree HASL is fine; nothing finer than 0.5 mm pitch (U3, MSOP-10).
  Via covering: tented. Smallest via 0.6 mm / 0.3 mm hole, smallest track 0.2 mm,
  smallest clearance 0.15 mm (USB fan-out), copper to edge 0.5 mm: all in the
  no-surcharge tier.
  Impedance control: NO. Two layers, and the USB is full speed (12 Mbit/s).
  Remove order number: optional; no "JLCJLCJLCJLC" location is drawn on this board.
  The ESP32 module's footprint reaches 0.19 mm past the TOP board edge and J1's and
  J2's bodies reach the BOTTOM edge: intentional, say so if their engineer asks.

PCB assembly
  PCBA type: STANDARD, not Economic. U1 (ESP32-S3-WROOM-1U-N4, C2980296) is listed
  "PCBA Type: Standard Only" in JLCPCB's parts library (checked 2026-09-20). J2
  (KF250NH-5.0-3P, C976567) is "Economic and Standard", assembly type "Wave Soldering":
  it is the one through-hole part and rides along in a Standard order.
  Side: top only. Tooling holes: added by JLCPCB. Fiducials FID1-FID3 are on the board.
  Files: *_bom.csv and *_cpl.csv from this folder.
  Not populated by design, in neither file: H1-H4 (holes), FID1-3, TP1-TP5 (pads).

  Placement corrections (jlc_rotations.json, each with its evidence): every polarised
  part was compared pad by pad with JLCPCB's own footprint for its LCSC number. The
  project-library parts are already at JLCPCB's zero. Only the four stock-KiCad
  transistor footprints needed a correction: Q1 (SOT-223), Q2 Q3 Q4 (SOT-23), +180.
  NONE of this has been seen in their preview yet. LOOK AT THESE after uploading the CPL:
    Q1         tab (the wide pin) toward the TOP of the board, its three pins toward the bottom
    Q2 Q4      the single pin (collector / drain) on the LEFT, the pair on the right
    Q3         the single pin (drain) on the RIGHT, the pair on the left
    D2         cathode band at the BOTTOM (pad 1, the +24V end, beside C11)
    D3 D5 D4   cathode band on the RIGHT (pad 1: LOOP_V on D3 and D4, LOOP_RTN on D5)
    LED1       cathode toward the BOTTOM edge. Its polarity rests on pad 1 = cathode in their
               LED0805-RD footprint (its closed silk end is on the pad-1 side, as in KiCad's);
               their symbol could not be fetched to confirm. A reversed LED only stays dark.
    U1         module's RF can over the board, U.FL connector at the top-right corner
    U3 U4 U5 D1  pin-1 dot on the silkscreen mark
    J1         contacts on the pads, opening toward the bottom edge
    J2         wire entries toward the bottom edge, orange buttons behind them

Also order (bom/non-bom-items.csv): a U.FL / IPEX Gen 1 pigtail and a 2.4 GHz antenna.
The -1U module has no antenna of its own.

First board bring-up
  Before plugging a sensor in: +5V, +3V3 at TP4, then MT_EN high and +24V at TP3.
  Short LOOP_V (TP1) to LOOP_RTN (TP2) through a meter: expect about 33 mA, and the
  firmware should drop MT_EN within its timeout. Q1 runs warm in that test (0.85 W).
  Two-point calibration at 4 and 20 mA (firmware/README.md).
"""


def run(args):
    r = subprocess.run([CLI] + args, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("kicad-cli %s failed:\n%s%s" % (" ".join(args[:3]), r.stdout, r.stderr))
    return r.stdout


def accepted(v):
    """The two library-internal errors this project has documented and accepted."""
    text = " | ".join(i.get("description", "") for i in v.get("items", []))
    return v.get("type") == "hole_clearance" and "NPTH pad of J1" in text and "of J1" in text.replace("NPTH pad of J1", "")


def gate():
    os.makedirs(os.path.join(HERE, "routing"), exist_ok=True)
    out = os.path.join(HERE, "routing", "drc.json")
    subprocess.run([CLI, "pcb", "drc", "--severity-all", "--schematic-parity", "--format", "json", "-o", out, PCB],
                   capture_output=True, text=True)
    d = json.load(open(out, encoding="utf-8"))
    errs = [v for v in d.get("violations", []) if v["severity"] == "error"]
    real = [v for v in errs if not accepted(v)]
    n = (len(real), len(errs) - len(real), len(d.get("unconnected_items", [])), len(d.get("schematic_parity", [])))
    print("DRC gate: %d error(s) (+%d accepted, inside J1's library footprint), %d unconnected, %d parity" % n)
    for v in real:
        print("   ", v["type"], "|", " | ".join(i["description"][:70] for i in v.get("items", [])))
    if n[0] or n[2] or n[3]:
        raise SystemExit("not building a package from a board that fails DRC")


def natural(ref):
    return (re.sub(r"\d", "", ref), int(re.sub(r"\D", "", ref) or 0))


def bom():
    board = pcbnew.LoadBoard(PCB)
    groups = collections.OrderedDict()
    skipped = []
    for fp in sorted(board.GetFootprints(), key=lambda f: natural(f.GetReference())):
        get = lambda k: fp.GetFieldText(k) if fp.HasField(k) else ""   # noqa: E731
        lcsc = get("LCSC")
        if not lcsc or fp.IsDNP():
            skipped.append(fp.GetReference())
            continue
        # one line per LCSC part: SW1 "RESET" and SW2 "BOOT" are the same switch
        key = (str(fp.GetFPID().GetLibItemName()), lcsc)
        g = groups.setdefault(key, {"refs": [], "values": [], "mpn": get("MPN"), "mfr": get("Manufacturer")})
        g["refs"].append(fp.GetReference())
        if fp.GetValue() not in g["values"]:
            g["values"].append(fp.GetValue())
    path = os.path.join(FAB, NAME + "_bom.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "MPN", "Manufacturer", "Quantity"])
        for (fpname, lcsc), g in groups.items():
            comment = g["values"][0] if len(g["values"]) == 1 else g["mpn"]
            w.writerow([comment, ",".join(g["refs"]), fpname, lcsc, g["mpn"], g["mfr"], len(g["refs"])])
    print("BOM: %d line(s), %d part(s); not in BOM (no LCSC number): %s"
          % (len(groups), sum(len(g["refs"]) for g in groups.values()), ", ".join(skipped)))
    return {r: lcsc for (_f, lcsc), g in groups.items() for r in g["refs"]}


def cross_check(placed):
    """The board must agree with the project's own BOM, designator by designator."""
    src = os.path.join(HERE, "bom", "bom.csv")
    want = {}
    for row in csv.DictReader(open(src, encoding="utf-8")):
        if (row.get("DNP") or "").strip():
            continue
        for ref in row["Reference"].split(","):
            want[ref.strip()] = row["LCSC"].strip()
    diff = sorted(r for r in set(want) | set(placed) if want.get(r) != placed.get(r))
    print("bom/bom.csv vs board: %d designator(s), %s"
          % (len(want), "identical" if not diff else "DIFFERENT: " + ", ".join("%s (bom %s, board %s)" % (r, want.get(r), placed.get(r)) for r in diff)))
    if diff:
        raise SystemExit("the board and bom/bom.csv disagree -- regenerate one of them first")


def main():
    gate()
    if os.path.isdir(FAB):
        shutil.rmtree(FAB)
    os.makedirs(GER)
    run(["pcb", "export", "gerbers", "-o", GER + os.sep, "--layers", LAYERS, "--subtract-soldermask",
         "--use-drill-file-origin", "--check-zones", PCB])
    run(["pcb", "export", "drill", "-o", GER + os.sep, "--format", "excellon", "--drill-origin", "plot",
         "--excellon-units", "mm", "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2", PCB])
    for f in os.listdir(GER):
        if f.endswith(".gbrjob"):
            os.remove(os.path.join(GER, f))
    z = os.path.join(FAB, NAME + "_gerbers.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(os.listdir(GER)):
            zf.write(os.path.join(GER, f), f)
    print("gerbers: %d files -> %s" % (len(os.listdir(GER)), os.path.relpath(z, HERE)))
    placed = bom()
    cross_check(placed)
    r = subprocess.run([sys.executable, os.path.join(HERE, "jlc_cpl.py"), PCB], capture_output=True, text=True)
    print(r.stdout.rstrip())
    if r.returncode:
        raise SystemExit(r.stderr)
    src = os.path.join(HERE, "jlc", NAME + "_cpl.csv")
    dst = os.path.join(FAB, NAME + "_cpl.csv")
    shutil.copy2(src, dst)
    cpl = {row[0] for row in list(csv.reader(open(dst, encoding="utf-8")))[1:]}
    refs = set(placed)
    print("CPL: %d placement(s); in CPL but not BOM: %s; in BOM but not CPL: %s"
          % (len(cpl), sorted(cpl - refs) or "none", sorted(refs - cpl) or "none"))
    if cpl != refs:
        raise SystemExit("BOM and CPL designators differ -- JLCPCB rejects that upload")
    with open(os.path.join(FAB, "ORDER_NOTES.txt"), "w", encoding="utf-8") as f:
        f.write(ORDER_NOTES)
    print("wrote fab/ORDER_NOTES.txt")


if __name__ == "__main__":
    main()
