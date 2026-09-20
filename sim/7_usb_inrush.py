"""USB plug-in inrush. Rev F hangs C10 + C11 (through L1/D2) straight on VBUS.
Rev G puts them behind Q3. C12 is gate-to-SOURCE on purpose: a gate-to-drain
(Miller) capacitor was tried first and fails at hot-plug -- with the drain at 0 V it
drags the gate low as VBUS steps up and turns Q3 hard on for the very edge it is
meant to soften (99 uC at attach instead of 5)."""
import ngs
COMMON = """
.model DSCH D(IS=1u RS=0.05 N=1.05)
.model PFET PMOS(LEVEL=1 VTO=-0.9 KP=8 LAMBDA=0.01)
.model NFET NMOS(LEVEL=1 VTO=1.6 KP=0.3)
"""
def run(title, body):
    ngs.circ(f"""{title}
* host: 5 V behind 0.25 ohm of port + cable, plugged in at t = 1 ms
Vbus src 0 PWL(0 0 1m 0 1.01m 5)
Rcab src p5 0.25
C6 p5 0 1u
{body}
{COMMON}
.end""")
    ngs.cmd("tran 5u 120m")
    t = ngs.vec("time"); i = ngs.vec("vbus#branch"); v = ngs.vec("sw")
    # Charge taken in the first 200 us is the capacitance VBUS actually sees at
    # attach -- the quantity USB limits to 10 uF (50 uC at 5 V).
    q = sum(-(i[k] + i[k-1]) / 2 * (t[k] - t[k-1]) for k in range(1, len(t)) if 1e-3 <= t[k] <= 1.2e-3)
    later = max(-x for x, tt in zip(i, t) if tt > 1.2e-3)
    t90 = next((tt for tt, vv in zip(t, v) if vv > 4.5), None)
    print(f"{title:26s} attach charge {q*1e6:6.1f} uC = {q/5*1e6:5.1f} uF seen by VBUS | peak afterwards {later*1e3:5.0f} mA | boost input up after {(t90 - 1e-3) * 1e3:5.1f} ms")
run("Rev F (direct)", """Rj p5 sw 1m
C10 sw 0 10u
L1 sw lx 22u
D2 lx out DSCH
C11 out 0 10u""")
run("Rev G (Q3, C12 gate-source)", """M3 sw g p5 p5 PFET
R21 p5 g 390k
C12 p5 g 100n
R22 g q4d 100k
* MT_EN follows +3V3, which the LDO brings up ~1 ms after VBUS
Ven en 0 PWL(0 0 2m 0 2.2m 3.3)
M4 q4d en 0 0 NFET
C10 sw 0 10u
L1 sw lx 22u
D2 lx out DSCH
C11 out 0 10u""")
