import ngs
from start import MODEL
from recover import ASIS
def run(temp, iset, vmin):
    ngs.circ(f"""firmware recovery: stuck loop, then MT_EN pulsed low (rail falls to 5 V - D2 = 4.6 V)
V24 p24 0 PWL(0 24 300m 24 310m 4.6 600m 4.6 610m 24)
{ASIS}
S1 loopv 0 ctl 0 SW1
Vctl ctl 0 PWL(0 1 50m 1 50.01m 0)
.model SW1 SW(Ron=0.1 Roff=100Meg Vt=0.5)
Ctx loopv rtn 100n
Btx loopv rtn I = min({iset}m, max(0, (V(loopv,rtn)-{vmin})/50))
R12 rtn 0 3.32
{MODEL}
.options temp={temp}
.end""")
    ngs.cmd("tran 100u 900m")
    t = ngs.vec("time"); r = ngs.vec("rtn"); v = ngs.vec("loopv")
    at = lambda s: min(range(len(t)), key=lambda k: abs(t[k]-s))
    a, b = at(0.29), at(0.89)
    return (v[a], r[a]/3.32e-3), (v[b], r[b]/3.32e-3)
for temp in (25, 60):
    for vmin in (8, 12):
        (v0, i0), (v1, i1) = run(temp, 20, vmin)
        print(f"{temp}C lift-off {vmin:2d} V, demand 20 mA: stuck at {v0:4.1f} V {i0:4.1f} mA  -> after MT_EN pulse {v1:4.1f} V {i1:4.1f} mA")
