"""Rev G limiter as built: R16 18R, no foldback, series blocking diode D4, and a
worst-case-gain pass transistor (BCP53-16 hFE min 100)."""
import ngs
from start import MODEL
PASS = MODEL.replace("MMBT5401", "BCP53LOW").replace("BF=132.1", "BF=100")
D4 = ".model D1N4148 D(IS=2.52n RS=.568 N=1.752 BV=100 IBV=100u CJO=4p TT=20n)"
def net(temp, tail):
    return f"""rev g
V24 p24 0 24
R16 p24 sns 18
Q1 pass drv sns BCP53LOW
Q2 drv fb p24 MMBT5401
R17 drv 0 47k
R18 sns fb 1k
D4 pass loopv D1N4148
{tail}
{MODEL}
{PASS}
{D4}
.options temp={temp}
.end"""
print(" temp   limit into short   V at J2 @ 4 mA   @ 20 mA   @ 24 mA")
for t in (-20, 25, 60, 85):
    ngs.circ(net(t, "Vload loopv 0 0")); ngs.cmd("op")
    ilim = ngs.vec("vload#branch")[0] * 1e3
    vs = []
    for i in (4, 20, 24):
        ngs.circ(net(t, f"Iload loopv 0 {i}m")); ngs.cmd("op"); vs.append(ngs.vec("loopv")[0])
    print(f" {t:4d}C      {ilim:5.1f} mA          {vs[0]:5.2f} V     {vs[1]:5.2f} V   {vs[2]:5.2f} V")
print("\nLOOP_V forced above the rail (the H-1 case): current pushed back into +24V")
ngs.circ(net(25, "Vf loopv 0 24")); ngs.cmd("dc vf 24 46 11")
for v, i in zip(ngs.vec("loopv"), ngs.vec("v24#branch")):
    print(f"   {v:4.0f} V -> {i*1e6:8.3f} uA")
