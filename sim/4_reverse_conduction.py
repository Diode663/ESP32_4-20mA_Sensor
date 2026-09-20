import ngs
from start import MODEL
# Gummel-Poon has no E-B breakdown, so add it explicitly: MMBT5401 V(BR)EBO = 5 V min,
# ~7 V typical. Diode anode = emitter, cathode = base; BV conducts base -> emitter.
ngs.circ(f"""LOOP_V driven above the 24 V rail (surge before D3 conducts, or a mis-wired external supply)
V24 p24 0 24
R16 p24 sns 20
Q1 loopv drv sns MMBT5401
DQ1EB sns drv DEB
Q2 drv fb p24 MMBT5401
DQ2EB p24 fb DEB
R17 drv 0 47k
R18 sns fb 1k
R19 fb loopv 43k
Vf loopv 0 24
.model DEB D(IS=1e-18 BV=7 IBV=1u RS=2)
{MODEL}
.end""")
ngs.cmd("dc vf 24 58 2")
v = ngs.vec("loopv"); i = ngs.vec("vf#branch"); ir = ngs.vec("v24#branch")
print(" LOOP_V   current INTO Q1 collector (reverse)   pushed back into +24V rail")
for a, b, c in zip(v, i, ir):
    print(f"  {a:4.0f} V        {-b*1e3:8.1f} mA                      {c*1e3:8.1f} mA")
