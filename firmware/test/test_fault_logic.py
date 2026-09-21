#!/usr/bin/env python3
"""
Truth-table test for the loop fault classifier and the calibration maths.

Why this exists: the classifier is an eleven-state precedence ladder living in
a C++ lambda inside the ESPHome package. `esphome compile` proves it is valid
C++; nothing proves it is the *right* C++. Until a board exists this is the
only way to execute the decision table at all.

The thresholds are READ FROM THE YAML rather than copied, so editing a
substitution can never silently desynchronise the test from the firmware.
The ladder below mirrors the lambda; keep them in step by hand.

    python firmware/test/test_fault_logic.py
"""
import math
import pathlib
import re
import sys

PKG = pathlib.Path(__file__).resolve().parents[1] / "package" / "esp32-4to20ma-board.yaml"

OK, UNDER, OVER, FAIL_LO, FAIL_HI, SUPPLY, SHORT, OFF, NODATA, OPEN, REVERSED = range(11)
NAMES = {
    OK: "OK", UNDER: "Under-range", OVER: "Over-range",
    FAIL_LO: "Fault: low (NAMUR)", FAIL_HI: "Fault: high (NAMUR)",
    SUPPLY: "Fault: supply low", SHORT: "Fault: field short",
    OFF: "Loop power off", NODATA: "Fault: no sensor data",
    OPEN: "Fault: open circuit", REVERSED: "Fault: reversed polarity",
}


def load_subs():
    """Pull the substitutions block out of the package."""
    text = PKG.read_text(encoding="utf-8")
    block = text.split("substitutions:", 1)[1].split("\n# =====", 1)[0]
    subs = {}
    for k, v in re.findall(r'^\s{2}(\w+):\s*"([^"]*)"', block, re.M):
        try:
            subs[k] = float(v)
        except ValueError:
            subs[k] = v
    return subs


S = load_subs()


def classify(i, v, powered=True, stale=False):
    """Mirror of the classification ladder in the package's interval lambda."""
    if not powered:
        return OFF
    if stale or (i is None or math.isnan(i)) or (v is None or math.isnan(v)):
        return NODATA
    if v < S["loop_v_short"]:
        return SHORT
    if i < -S["open_circuit_ma"]:
        return REVERSED
    if i < S["open_circuit_ma"]:
        return OPEN
    if v < S["loop_v_low"]:
        return SUPPLY
    if i > S["ne43_fail_high"]:
        return FAIL_HI
    if i < S["ne43_fail_low"]:
        return FAIL_LO
    if i > S["ne43_over"]:
        return OVER
    if i < S["ne43_under"]:
        return UNDER
    return OK


def calibrate(raw, lo, hi):
    """Mirror of the two-point lambda on loop_current_raw."""
    if not math.isfinite(lo) or not math.isfinite(hi) or abs(hi - lo) < 1e-6:
        return raw
    return S["cal_ref_low"] + (raw - lo) * (S["cal_ref_high"] - S["cal_ref_low"]) / (hi - lo)


NOM = 22.8          # healthy loop voltage with current flowing
CASES = [
    # (name,                     i,     v,     powered, stale, expected)
    ("mid-scale 12 mA",          12.0,  NOM,   True,  False, OK),
    ("exactly 4 mA",              4.0,  NOM,   True,  False, OK),
    ("exactly 20 mA",            20.0,  NOM,   True,  False, OK),
    ("3.9 mA, inside NE43 range", 3.9,  NOM,   True,  False, OK),
    ("20.4 mA, inside range",    20.4,  NOM,   True,  False, OK),
    ("3.7 mA under-range",        3.7,  NOM,   True,  False, UNDER),
    ("20.7 mA over-range",       20.7,  NOM,   True,  False, OVER),
    ("3.5 mA NAMUR fail low",     3.5,  NOM,   True,  False, FAIL_LO),
    ("22 mA NAMUR fail high",    22.0,  NOM,   True,  False, FAIL_HI),
    ("ADC pegged at ceiling",    24.67, NOM,   True,  False, FAIL_HI),
    ("open circuit",              0.0,  24.0,  True,  False, OPEN),
    ("leakage only",              0.05, 24.0,  True,  False, OPEN),
    ("reversed sourcing xmtr",   -8.0,  24.0,  True,  False, REVERSED),
    ("supply sagging",           12.0,  15.0,  True,  False, SUPPLY),
    ("hard short",               24.67,  0.5,  True,  False, SHORT),
    ("short beats everything",   -8.0,   0.5,  True,  False, SHORT),
    ("power off",                 0.0,   0.0,  False, False, OFF),
    ("power off beats short",    24.67,  0.5,  False, False, OFF),
    ("stale: INA226 silent",     12.0,  NOM,   True,  True,  NODATA),
    ("stale beats a good read",  12.0,  NOM,   True,  True,  NODATA),
    ("NaN current",              math.nan, NOM, True, False, NODATA),
    ("NaN voltage",              12.0,  math.nan, True, False, NODATA),
]

USABLE = {OK, UNDER, OVER}


def main():
    print(f"thresholds from {PKG.name}: "
          f"fail_low={S['ne43_fail_low']} under={S['ne43_under']} "
          f"over={S['ne43_over']} fail_high={S['ne43_fail_high']} "
          f"v_low={S['loop_v_low']} v_short={S['loop_v_short']} "
          f"open={S['open_circuit_ma']}\n")

    fails = 0
    for name, i, v, powered, stale, want in CASES:
        got = classify(i, v, powered, stale)
        ok = got == want
        fails += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<28} -> {NAMES[got]}"
              + ("" if ok else f"   EXPECTED {NAMES[want]}"))

    # Every state must be reachable, or the ladder has an unreachable branch.
    print()
    reached = {classify(i, v, p, s) for _, i, v, p, s, _ in CASES}
    missing = set(NAMES) - reached
    print(f"  {'PASS' if not missing else 'FAIL'}  every state reachable"
          + ("" if not missing else f"   NEVER REACHED: {[NAMES[m] for m in missing]}"))
    fails += bool(missing)

    # A reading may only be published when the state is one of the usable three.
    bad = [(i, v) for i in (-5, 0, 3.5, 3.7, 4, 12, 20, 20.7, 22, 24.67)
           for v in (0.5, 15, NOM)
           if (classify(i, v) in USABLE) != (classify(i, v) <= OVER)]
    print(f"  {'PASS' if not bad else 'FAIL'}  usable-state set matches 'code <= 2'")
    fails += bool(bad)

    # Calibration: identity, a real correction, and the degenerate guard.
    print()
    checks = [
        ("identity", calibrate(12.0, 4.0, 20.0), 12.0),
        ("gain+offset", calibrate(12.0, 4.0123, 19.9871), 12.0003),
        ("captures 4 mA back", calibrate(4.0123, 4.0123, 19.9871), 4.0),
        ("captures 20 mA back", calibrate(19.9871, 4.0123, 19.9871), 20.0),
        ("degenerate pair falls back to raw", calibrate(12.0, 4.0, 4.0), 12.0),
        ("NaN calibration falls back to raw", calibrate(12.0, math.nan, 20.0), 12.0),
    ]
    for name, got, want in checks:
        ok = abs(got - want) < 1e-3
        fails += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  calibration {name:<34} {got:.4f}"
              + ("" if ok else f"   EXPECTED {want:.4f}"))

    print()
    if fails:
        print(f"{fails} FAILED")
        return 1
    print(f"all {len(CASES) + len(checks) + 2} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
