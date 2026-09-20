#!/usr/bin/env python3
"""Checks the drawn schematic against the intended netlist.

The sheets are hand-laid-out geometry, so a mistyped coordinate can silently
merge two nets or leave a pin floating. Rather than trust the layout, this
exports the netlist with kicad-cli -- KiCad's own connectivity engine, the same
one the PCB uses -- and diffs it against NETS in generate_schematic.py.

Nets are compared by their *set of pins*, not by name, because KiCad may pick a
different name for a net than we did (for example a power symbol's name wins
over a local label). A rename is reported as informational; a different pin
grouping is an error.
"""
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_schematic import NETS, NO_CONNECT, PARTS  # noqa: E402

PROJDIR = os.path.dirname(os.path.abspath(__file__))
KICAD_CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
ROOT_SCH = os.path.join(PROJDIR, "esp32-4to20ma-board.kicad_sch")


def export_netlist(out_path):
    r = subprocess.run(
        [KICAD_CLI, "sch", "export", "netlist", "--format", "kicadxml",
         "-o", out_path, ROOT_SCH],
        capture_output=True, text=True)
    if r.returncode != 0:
        print("kicad-cli netlist export FAILED")
        print(r.stdout)
        print(r.stderr)
        sys.exit(2)
    return out_path


def parse_netlist(path):
    """-> {net_name: frozenset((ref, pin))}"""
    root = ET.parse(path).getroot()
    nets = {}
    for net in root.iter("net"):
        name = net.get("name")
        pins = set()
        for node in net.findall("node"):
            pins.add((node.get("ref"), node.get("pin")))
        nets[name] = pins
    return nets


def strip_path(name):
    """KiCad prefixes sheet-local net names with the sheet path."""
    return name.rsplit("/", 1)[-1]


def main():
    out = os.path.join(PROJDIR, "netlist_check.xml")
    export_netlist(out)
    actual = parse_netlist(out)
    os.remove(out)

    expected = {n: set(map(tuple, pins)) for n, pins in NETS.items()}

    # Power-symbol references (#PWR***) and PWR_FLAG nodes are drawing
    # artefacts, not real connections -- drop them before comparing.
    actual = {n: {p for p in pins if not p[0].startswith("#")}
              for n, pins in actual.items()}
    actual = {n: pins for n, pins in actual.items() if pins}

    # KiCad emits a single-pin "unconnected-(...)" net for every no-connect
    # flag. Check that set matches NO_CONNECT exactly, then set them aside.
    nc_drawn = {p for n, pins in actual.items()
                if n.startswith("unconnected-") for p in pins}
    actual = {n: pins for n, pins in actual.items()
              if not n.startswith("unconnected-")}
    nc_want = set(map(tuple, NO_CONNECT))
    nc_errors = []
    if nc_drawn - nc_want:
        nc_errors.append(f"pins left unconnected but not marked NC: "
                         f"{sorted(nc_drawn - nc_want)}")
    if nc_want - nc_drawn:
        nc_errors.append(f"pins marked NC but wired to something: "
                         f"{sorted(nc_want - nc_drawn)}")

    by_pins_actual = {frozenset(v): strip_path(k) for k, v in actual.items()}
    by_pins_expected = {frozenset(v): k for k, v in expected.items()}

    errors = list(nc_errors)
    renames = []

    for pins, want_name in by_pins_expected.items():
        if pins in by_pins_actual:
            got = by_pins_actual[pins]
            if got != want_name:
                renames.append(f"{want_name} -> drawn as {got}")
            continue
        # find whatever the drawn schematic did with these pins
        touching = {strip_path(n) for n, ps in actual.items() if ps & pins}
        errors.append(
            f"net {want_name}: expected pins {sorted(pins)}\n"
            f"    but those pins land in drawn net(s) "
            f"{sorted(touching) or ['<nothing>']}")
        for n in sorted(touching):
            got = {p for k, ps in actual.items() if strip_path(k) == n for p in ps}
            extra = got - pins
            missing = pins - got
            if extra:
                errors.append(f"      {n} also contains {sorted(extra)}")
            if missing:
                errors.append(f"      {n} is missing {sorted(missing)}")

    for pins, got_name in by_pins_actual.items():
        if pins not in by_pins_expected:
            if not any(pins & e for e in by_pins_expected):
                errors.append(f"unexpected net {got_name}: {sorted(pins)}")

    # Every component in the BOM must actually appear.
    seen_refs = {r for pins in actual.values() for r, _ in pins}
    nc_refs = {r for r, _ in NO_CONNECT}
    for ref in PARTS:
        if ref not in seen_refs and ref not in nc_refs:
            errors.append(f"component {ref} has no connections at all")

    print(f"Nets drawn: {len(actual)}   expected: {len(expected)}")
    if renames:
        print("\nNet renames (same pins, different name -- usually fine):")
        for r in renames:
            print("  ", r)
    if errors:
        print("\nNETLIST MISMATCH:")
        for e in errors:
            print("  " + e)
        sys.exit(1)
    print("\nNetlist matches the specification exactly.")


if __name__ == "__main__":
    main()
