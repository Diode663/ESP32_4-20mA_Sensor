"""mA-input protection, Rev H: D5 (SMAJ28A) at the pin, F1 (100 mA / 60 V PPTC) in
series, D6 (1N4007W) across the shunt.

Rev G had one SMAJ12A across the input. It does not conduct until 13-14 V, and
the 3.32 ohm shunt is in parallel with it, so a 0.5 kV surge put 5 A and 91 W
peak through an 0805 rated 0.125 W; and 24 V wired to the mA pin put 7 A
through it with nothing in series. Here the shunt only ever sees D6's forward
drop. The price is what D6 leaks at the shunt's 13-80 mV, printed last.

F1's resistance is the unknown: 1.6 ohm (minimum, cold) to 15 ohm (maximum
after a trip), so both ends are run. The element is named Rptc because a
SPICE element whose name starts with F is a current-controlled source.
"""
import ngs

M = """.model DTVS28 D(IS=1n RS=0.6 N=1.5 BV=32.5 IBV=1m)
.model D4007 D(IS=7.02767n RS=0.0341512 N=1.80803 EG=1.11 XTI=5 BV=1000 IBV=5u CJO=10p TT=1u)"""


def net(src, rptc, temp=27):
    return f"""mA input protection, Rev H
{src}
D5 0 lin DTVS28
Rptc lin rtn {rptc}
D6 rtn 0 D4007
R12 rtn 0 3.32
R13 rtn inp 10
C9 inp inn 100n
R14 inn 0 10
{M}
.options temp={temp}
.end"""


print("1) surge 8/20 us on the mA-in pin (IEC 61000-4-5 through 40 ohm)")
for kv, ipk in ((0.5, 12), (1.0, 24)):
    for rp in (1.6, 15):
        ngs.circ(net(f"Isg 0 lin EXP(0 {ipk * 2.05} 0 3.9u 3.9u 14.4u)", rp))
        ngs.cmd("tran 50n 120u 0 50n")
        t, v, vl = ngs.vec("time"), ngs.vec("rtn"), ngs.vec("lin")
        p = [x * x / 3.32 for x in v]
        e = sum((p[k] + p[k - 1]) / 2 * (t[k] - t[k - 1]) for k in range(1, len(t)))
        pf = max((a - b) * (a - b) / rp for a, b in zip(vl, v))
        print(f"   {kv} kV, fuse {rp:4.1f} ohm: pin {max(vl):5.1f} V, shunt node {max(v):4.2f} V -> "
              f"shunt {max(p):5.2f} W peak, {e * 1e6:6.1f} uJ; fuse {max(a - b for a, b in zip(vl, v)):4.1f} V "
              f"across, {pf:5.0f} W peak")

print("2) 24 V supply wired straight to the mA-in pin, before the fuse trips")
for rp in (1.6, 5, 15):
    ngs.circ(net("Vmis lin 0 24", rp))
    ngs.cmd("op")
    v = ngs.vec("rtn")[0]
    i = -ngs.vec("vmis#branch")[0]
    print(f"   fuse {rp:4.1f} ohm: {i:5.2f} A from the supply, shunt node {v:4.2f} V -> shunt "
          f"{v * v / 3.32:4.2f} W, diode {v * (i - v / 3.32):4.1f} W, fuse {i * i * rp:5.0f} W (trips in ms)")

print("3) what the clamp diode steals from the reading")
for temp in (25, 60, 85):
    row = []
    for ma in (4, 12, 20, 24):
        ngs.circ(net(f"Iloop 0 lin {ma}m", 5, temp))
        ngs.cmd("op")
        v = ngs.vec("rtn")[0]
        row.append((ma - v / 3.32 * 1e3) / ma * 1e6)
    print(f"   {temp:3d} C: " + "  ".join(f"{ma} mA: {r:6.1f} ppm" for ma, r in zip((4, 12, 20, 24), row)))
