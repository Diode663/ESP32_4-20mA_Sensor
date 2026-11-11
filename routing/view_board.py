"""view.py board.kicad_pcb out.png x0 y0 x1 y1 [px_per_mm] [layers=FB] [fills=1]
Draws copper straight from pcbnew: zone fills, tracks, vias, pads, silk, with net labels."""
import sys, hashlib
import pcbnew
from PIL import Image, ImageDraw, ImageFont

pcb, out = sys.argv[1], sys.argv[2]
x0, y0, x1, y1 = map(float, sys.argv[3:7])
K = float(sys.argv[7]) if len(sys.argv) > 7 else 30
LAY = sys.argv[8] if len(sys.argv) > 8 else "FB"
FILLS = (sys.argv[9] if len(sys.argv) > 9 else "1") == "1"
OX, OY = 100.0, 50.0
mm = pcbnew.ToMM
b = pcbnew.LoadBoard(pcb)
im = Image.new("RGB", (int((x1 - x0) * K), int((y1 - y0) * K)), (250, 250, 250))
g = ImageDraw.Draw(im, "RGBA")
f = ImageFont.truetype("arial.ttf", max(9, int(K * 0.32)))
fb = ImageFont.truetype("arialbd.ttf", max(10, int(K * 0.4)))
X = lambda v: (mm(v) - OX - x0) * K
Y = lambda v: (mm(v) - OY - y0) * K


def col(n, a=255):
    if n == "GND":
        return (150, 150, 150, a)
    if not n or n.startswith("unconnected"):
        return (215, 215, 215, a)
    h = hashlib.md5(n.encode()).digest()
    return (60 + h[0] % 170, 60 + h[1] % 170, 60 + h[2] % 170, a)


for gx in range(int(x0), int(x1) + 1):
    g.line([(gx - x0) * K, 0, (gx - x0) * K, im.size[1]], fill=(225, 225, 240) if gx % 5 else (180, 180, 215))
    if gx % (1 if K >= 25 else 5) == 0:
        g.text(((gx - x0) * K + 1, 0), str(gx), fill=(110, 110, 160), font=f)
for gy in range(int(y0), int(y1) + 1):
    g.line([0, (gy - y0) * K, im.size[0], (gy - y0) * K], fill=(225, 225, 240) if gy % 5 else (180, 180, 215))
    if gy % (1 if K >= 25 else 5) == 0:
        g.text((0, (gy - y0) * K + 1), str(gy), fill=(110, 110, 160), font=f)

layers = [(pcbnew.B_Cu, (40, 90, 220)), (pcbnew.F_Cu, (220, 50, 50))]
layers = [l for l in layers if ("B" if l[0] == pcbnew.B_Cu else "F") in LAY]
if FILLS:
    for lay, c in layers:
        for i in range(b.GetAreaCount()):
            z = b.GetArea(i)
            if z.GetIsRuleArea() or z.GetLayer() != lay:
                continue
            ps = z.GetFilledPolysList(lay)
            for k in range(ps.OutlineCount()):
                o = ps.Outline(k)
                pts = [(X(o.CPoint(j).x), Y(o.CPoint(j).y)) for j in range(o.PointCount())]
                if len(pts) > 2:
                    g.polygon(pts, fill=c + (38 if z.GetNetname() == "GND" else 90,), outline=c + (120,))
                for hh in range(ps.HoleCount(k)):
                    h = ps.Hole(k, hh)
                    pts = [(X(h.CPoint(j).x), Y(h.CPoint(j).y)) for j in range(h.PointCount())]
                    if len(pts) > 2:
                        g.polygon(pts, fill=(250, 250, 250, 255), outline=c + (120,))
for lay, c in layers:
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA" or t.GetLayer() != lay:
            continue
        a, e = t.GetStart(), t.GetEnd()
        w = max(1, int(mm(t.GetWidth()) * K))
        g.line([X(a.x), Y(a.y), X(e.x), Y(e.y)], fill=c + (200,), width=w)
        r = w / 2
        for q in (a, e):
            g.ellipse([X(q.x) - r, Y(q.y) - r, X(q.x) + r, Y(q.y) + r], fill=c + (200,))
for fp in b.GetFootprints():
    for it in fp.GraphicalItems():
        if it.GetClass() == "PCB_SHAPE" and b.GetLayerName(it.GetLayer()) in ("F.Silkscreen", "F.Courtyard"):
            cc = (0, 150, 150, 255) if "Silk" in b.GetLayerName(it.GetLayer()) else (190, 140, 255, 255)
            try:
                if it.GetShape() == pcbnew.SHAPE_T_SEGMENT:
                    g.line([X(it.GetStart().x), Y(it.GetStart().y), X(it.GetEnd().x), Y(it.GetEnd().y)], fill=cc, width=1)
                elif it.GetShape() == pcbnew.SHAPE_T_RECT:
                    g.rectangle([X(min(it.GetStart().x, it.GetEnd().x)), Y(min(it.GetStart().y, it.GetEnd().y)),
                                 X(max(it.GetStart().x, it.GetEnd().x)), Y(max(it.GetStart().y, it.GetEnd().y))], outline=cc)
            except Exception:
                pass
    for p in fp.Pads():
        if not (p.IsOnLayer(pcbnew.F_Cu) and "F" in LAY or p.IsOnLayer(pcbnew.B_Cu) and "B" in LAY):
            continue
        bb = p.GetBoundingBox()
        box = [X(bb.GetLeft()), Y(bb.GetTop()), X(bb.GetRight()), Y(bb.GetBottom())]
        g.rectangle(box, fill=col(p.GetNetname(), 235), outline=(0, 0, 0, 255))
        if p.GetDrillSize().x:
            d = mm(p.GetDrillSize().x) * K / 2
            c0 = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            g.ellipse([c0[0] - d, c0[1] - d, c0[0] + d, c0[1] + d], fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        q = t.GetPosition()
        r = mm(t.GetWidth(pcbnew.F_Cu)) * K / 2
        g.ellipse([X(q.x) - r, Y(q.y) - r, X(q.x) + r, Y(q.y) + r], outline=(0, 120, 0, 255), width=max(2, int(K * 0.08)),
                  fill=col(t.GetNetname(), 120))
for d in b.GetDrawings():
    if d.GetClass() == "PCB_SHAPE" and b.GetLayerName(d.GetLayer()) == "Edge.Cuts":
        try:
            g.line([X(d.GetStart().x), Y(d.GetStart().y), X(d.GetEnd().x), Y(d.GetEnd().y)], fill=(0, 0, 0, 255), width=2)
        except Exception:
            pass
if K >= 18:
    for fp in b.GetFootprints():
        bb = fp.GetBoundingBox(False)
        g.text((X(bb.GetLeft()) + 2, Y(bb.GetTop()) - K * 0.45), fp.GetReference(), fill=(0, 0, 200, 255), font=fb)
        if K >= 28:
            for p in fp.Pads():
                n = p.GetNetname()
                if n and not n.startswith("unconnected") and (K >= 45 or n != "GND"):
                    bb = p.GetBoundingBox()
                    g.text((X(bb.GetLeft()) + 1, Y(bb.GetCenter().y) - K * 0.16), p.GetNumber() + ":" + n.lstrip("/"), fill=(0, 0, 0, 255), font=f)
im.save(out)
print(im.size)
