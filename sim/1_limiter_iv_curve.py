import ngs
MODEL = """.MODEL MMBT5401 PNP (IS=21.48f XTI=3 EG=1.11 VAF=100 BF=132.1 ISE=21.48f NE=1.375 IKF=.1848 NK=.5 XTB=1.5 BR=3.661 ISC=0 NC=2 IKR=0 RC=1.6 CJC=17.63p MJC=.5312 VJC=.75 FC=.5 CJE=73.39p MJE=.3777 VJE=.75 TR=1.476n TF=641.9p)"""
def curve(temp, v24=24.0, r18="1k", r19="43k"):
    ngs.circ(f"""limiter
V24 p24 0 {v24}
R16 p24 sns 20
Q1 loopv drv sns MMBT5401
Q2 drv fb p24 MMBT5401
R17 drv 0 47k
R18 sns fb {r18}
R19 fb loopv {r19}
Vload loopv 0 0
{MODEL}
.options temp={temp}
.end""")
    ngs.cmd("dc vload 0 24 0.5")

    v = ngs.vec("loopv"); i = ngs.vec("vload#branch")
    return v, [x*1e3 for x in i]
res = {}
for t in (-20, 25, 50, 70, 85):
    v, i = curve(t); res[t] = i
print("Vout   " + "".join(f"{t:>8}C" for t in res))
for k in range(0, len(v), 2):
    print(f"{v[k]:5.1f}  " + "".join(f"{res[t][k]:9.2f}" for t in res))
