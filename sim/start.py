import ngs
MODEL = """.MODEL MMBT5401 PNP (IS=21.48f XTI=3 EG=1.11 VAF=100 BF=132.1 ISE=21.48f NE=1.375 IKF=.1848 NK=.5 XTB=1.5 BR=3.661 ISC=0 NC=2 IKR=0 RC=1.6 CJC=17.63p MJC=.5312 VJC=.75 FC=.5 CJE=73.39p MJE=.3777 VJE=.75 TR=1.476n TF=641.9p)"""
def run(temp, iset_ma, vmin, r19="43k", extra=""):
    # transmitter: regulates iset once it has vmin across it; below that it is
    # saturated and takes whatever it can get through 50 ohm.
    ngs.circ(f"""startup
V24 p24 0 PWL(0 0 5m 24)
R16 p24 sns 20
Q1 loopv drv sns MMBT5401
Q2 drv fb p24 MMBT5401
R17 drv 0 47k
R18 sns fb 1k
R19 fb loopv {r19}
{extra}
Ctx loopv rtn 100n
Btx loopv rtn I = min({iset_ma}m, max(0, (V(loopv,rtn)-{vmin})/50))
R12 rtn 0 3.32
{MODEL}
.options temp={temp}
.end""")
    ngs.cmd("tran 50u 200m")
    v = ngs.vec("loopv"); r = ngs.vec("rtn")
    return v[-1], r[-1] / 3.32 * 1e3
if __name__ == "__main__":
  print("transmitter lift-off 10 V (typical 2-wire spec is 8-12 V)")
  print(f"{'demand':>8} | " + " | ".join(f"{t:>4}C: Vloop  Iloop" for t in (0, 25, 50, 70)))
  for iset in (4, 8, 12, 16, 20, 22):
      row = []
      for t in (0, 25, 50, 70):
          v, i = run(t, iset, 10)
          row.append(f"      {v:5.1f}V {i:5.1f}mA{'' if abs(i-iset) < 0.3 else '*'}")
      print(f"{iset:6d}mA | " + " | ".join(row))
  print("* = transmitter starved: loop current is NOT the process value")
