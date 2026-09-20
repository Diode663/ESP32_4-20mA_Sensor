import ngs, sys
from start import MODEL
def run(temp, iset_ma, vmin, lim):
    ngs.circ(f"""recovery after a field short / hot-plug of a discharged transmitter
V24 p24 0 24
{lim}
* field short held for 50 ms, then removed
S1 loopv 0 ctl 0 SW1
Vctl ctl 0 PWL(0 1 50m 1 50.01m 0)
.model SW1 SW(Ron=0.1 Roff=100Meg Vt=0.5)
Ctx loopv rtn 100n
Btx loopv rtn I = min({iset_ma}m, max(0, (V(loopv,rtn)-{vmin})/50))
R12 rtn 0 3.32
{MODEL}
.options temp={temp}
.end""")
    ngs.cmd("tran 50u 400m")
    v = ngs.vec("loopv"); r = ngs.vec("rtn")
    return v[-1], r[-1] / 3.32 * 1e3
ASIS = """R16 p24 sns 20
Q1 loopv drv sns MMBT5401
Q2 drv fb p24 MMBT5401
R17 drv 0 47k
R18 sns fb 1k
R19 fb loopv 43k"""
if __name__ == "__main__":
    for vmin in (8, 12):
        print(f"\nAS DESIGNED -- short removed at t=50 ms, transmitter lift-off {vmin} V")
        print(f"{'demand':>8} | " + " | ".join(f"{t:>4}C: Vloop   Iloop " for t in (0, 25, 50, 70)))
        for iset in (4, 8, 12, 16, 20, 22):
            row = []
            for t in (0, 25, 50, 70):
                v, i = run(t, iset, vmin, ASIS)
                row.append(f"      {v:5.1f}V {i:5.1f}mA{' ' if abs(i-iset) < 0.3 else '*'}")
            print(f"{iset:6d}mA | " + " | ".join(row))
    print("* = stuck in foldback: the loop current is NOT the process value")
