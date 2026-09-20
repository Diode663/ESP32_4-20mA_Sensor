import ngs
from start import MODEL
from recover import run
def curve(temp, lim):
    ngs.circ(f"""limiter
V24 p24 0 24
{lim}
Vload loopv 0 0
{MODEL}
.options temp={temp}
.end""")
    ngs.cmd("dc vload 0 23.5 23.5")
    i = ngs.vec("vload#branch")
    return [x*1e3 for x in i]
def FIX(r16): return f"""R16 p24 sns {r16}
Q1 loopv drv sns MMBT5401
Q2 drv fb p24 MMBT5401
R17 drv 0 47k
R18 sns fb 1k"""
for r16 in (20, 18, 16):
    print(f"\nPROPOSED: R19 removed (no foldback), R16 = {r16} ohm")
    print("  temp   current limit   Q1 dissipation into a dead short")
    for t in (-20, 25, 60, 85):
        i0, i1 = curve(t, FIX(r16))
        print(f"  {t:4d}C     {i0:6.1f} mA      {i0*24/1000:5.2f} W")
print("\nPROPOSED (R16=18): recovery after short, lift-off 8 V / 12 V, demand 22 mA")
for vmin in (8, 12):
    for t in (0, 25, 50, 70, 85):
        v, i = run(t, 22, vmin, FIX(18))
        print(f"  liftoff {vmin:2d}V  {t:3d}C -> {v:5.1f} V {i:5.1f} mA {'OK' if abs(i-22)<0.3 else 'STUCK'}")
