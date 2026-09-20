#!/usr/bin/env python3
"""Regenerate bom/bom.csv from the schematic.

    python bom_report.py

The schematic is the source of truth, so this exports the BOM with KiCad's
own exporter rather than re-reading generate_schematic.py's PARTS table --
that way the CSV cannot drift from the sheet the way the hand-maintained one
did (it still listed the 4.02 ohm shunt after the part changed).

Two things happen on top of the raw export:

* Lines are regrouped by **LCSC part number**, because that is the ordering
  key. KiCad groups by value, which splits SW1 (RESET) and SW2 (BOOT) into
  two lines even though they are one part number.
* The user-managed columns -- LC_Stock, Chosen_Distributor, Validated,
  Notes -- are carried over from the existing CSV, matched on LCSC, so
  re-running never discards work done in the spreadsheet.
"""
import csv
import io
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCH = os.path.join(HERE, "esp32-4to20ma-board.kicad_sch")
OUT = os.path.join(HERE, "bom", "bom.csv")
CLI = os.environ.get("KICAD_CLI", r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")

COLUMNS = ["Reference", "Qty", "Value", "Footprint", "MPN", "Manufacturer",
           "LCSC", "LC_Stock", "Chosen_Distributor", "Datasheet", "Validated",
           "DNP", "Notes"]
#: columns the spreadsheet owns; this script never overwrites them
KEEP = ["LC_Stock", "Chosen_Distributor", "Validated", "Notes"]


def natural(ref):
    """Sort R9 before R10, and keep like prefixes together."""
    head = ref.rstrip("0123456789")
    tail = ref[len(head):]
    return (head, int(tail) if tail else 0)


def export_raw():
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    subprocess.run(
        [CLI, "sch", "export", "bom", "-o", path,
         "--fields", "Reference,QUANTITY,Value,Footprint,MPN,Manufacturer,LCSC,DNP",
         "--labels", "Reference,Qty,Value,Footprint,MPN,Manufacturer,LCSC,DNP",
         "--group-by", "Value,Footprint,MPN",
         "--sort-field", "Reference", "--ref-delimiter", ",", SCH],
        capture_output=True, check=True)
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    os.remove(path)
    return rows


def load_existing():
    """{LCSC: {column: value}} for the columns the spreadsheet owns."""
    if not os.path.exists(OUT):
        return {}
    with io.open(OUT, encoding="utf-8-sig", newline="") as f:
        return {r.get("LCSC", ""): {k: r.get(k, "") for k in KEEP}
                for r in csv.DictReader(f) if r.get("LCSC")}


def main():
    raw = export_raw()
    kept = load_existing()

    merged = {}
    for r in raw:
        lcsc = (r.get("LCSC") or "").strip()
        key = lcsc or "%s|%s" % (r.get("MPN"), r.get("Value"))
        m = merged.setdefault(key, {
            "refs": [], "values": [], "LCSC": lcsc,
            "MPN": r.get("MPN", ""), "Manufacturer": r.get("Manufacturer", ""),
            "Footprint": r.get("Footprint", ""), "DNP": r.get("DNP", "")})
        m["refs"] += [x for x in r["Reference"].split(",") if x]
        if r.get("Value") and r["Value"] not in m["values"]:
            m["values"].append(r["Value"])

    out = []
    for m in sorted(merged.values(), key=lambda m: natural(sorted(m["refs"], key=natural)[0])):
        refs = sorted(set(m["refs"]), key=natural)
        # the package is what a human checks against the board; the library
        # prefix is noise in a spreadsheet
        fp = m["Footprint"].split(":")[-1]
        for tag in ("R_", "C_", "L_", "LED_"):
            if fp.startswith(tag):
                fp = fp[len(tag):].split("_")[0]
                break
        row = {c: "" for c in COLUMNS}
        row.update({
            "Reference": ",".join(refs),
            "Qty": str(len(refs)),
            "Value": "/".join(m["values"]),
            "Footprint": fp,
            "MPN": m["MPN"],
            "Manufacturer": m["Manufacturer"],
            "LCSC": m["LCSC"],
            "Datasheet": ("https://www.lcsc.com/product-detail/%s.html" % m["LCSC"]
                          if m["LCSC"] else ""),
            "DNP": m["DNP"],
        })
        row.update(kept.get(m["LCSC"], {}))
        out.append(row)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(out)

    placements = sum(int(r["Qty"]) for r in out)
    print("wrote %s" % OUT)
    print("  %d order lines, %d placements" % (len(out), placements))
    carried = sum(1 for r in out if any(r[k] for k in KEEP))
    if carried:
        print("  carried spreadsheet columns forward on %d line(s)" % carried)
    blank = [r["Reference"] for r in out if not r["LCSC"]]
    if blank:
        print("  NO LCSC PART NUMBER: " + ", ".join(blank))


if __name__ == "__main__":
    main()
