#!/usr/bin/env python3
"""gridroute -- this board's own grid router.

Written for this board, in the way Anthropic's 2026-11 electronics post
describes: the critical nets are drawn by hand (route_board.py), and what is
left is searched on a grid, one net at a time, with rip-up and retry, by a
router small enough to read. It replaces Freerouting for those nets;
Freerouting stays available as a cross-check (route_board.py --autoroute).

What it is
  * A 0.1 mm grid over the board, two layers. A cell is open to a net when a
    track of that net's width, centred there, clears every other net's
    copper, every hole and the board edge by the netclass clearance. The test
    is analytic (point to rectangle / segment / circle), not a bitmap, so a
    track on the grid is clear by construction; KiCad's DRC is still the judge.
  * A* over (cell, layer, heading). Headings are the eight 45 degree
    directions; a 45 degree turn costs a little, a 90 degree turn a lot, and
    anything sharper is not allowed, so paths come out as a human would draw
    them. A via costs VIA mm of track.
  * Cost is length times a per-cell multiplier. The bottom layer is the
    ground plane, so it costs BOTTOM times the top; `regions` raise the price
    of places that should stay clear (under the radio module, under the USB
    pair, under the boost converter). `shy` keeps named nets further from
    named aggressors (I2C away from the switch node).
  * Multi-pin nets grow as a tree: everything already joined is the source,
    the nearest island is the target, and a new branch may tee into any
    copper of its own net.
  * Rip-up and retry. A net that cannot get through is re-searched with the
    other grid-routed nets made passable at a price; whatever it crossed is
    ripped up, the stuck net goes first and the ripped ones are routed again.
    After everything is in, each net in turn is ripped up and re-routed
    against the others until no pass improves the total.

What it is not: a general autorouter. No differential pairs, no length
tuning, no push-and-shove, two layers only. Those nets are scripted.

Coordinates are board mm, origin top-left, Y down, as in routelib.
"""
import fnmatch
import heapq
import json
import math
import os
import time

import numpy as np
import pcbnew

mm = pcbnew.ToMM
SQ2 = math.sqrt(2.0)
DX = (1, 1, 0, -1, -1, -1, 0, 1)
DY = (0, 1, 1, 1, 0, -1, -1, -1)


class Shape:
    __slots__ = ("kind", "g", "net", "layers", "src", "tag")

    def __init__(self, kind, g, net, layers, src, tag=None):
        self.kind, self.g, self.net, self.layers, self.src, self.tag = kind, g, net, layers, src, tag

    def bbox(self):
        k, g = self.kind, self.g
        if k == "rect":
            return g
        if k == "circ":
            return (g[0] - g[2], g[1] - g[2], g[0] + g[2], g[1] + g[2])
        hw = g[4]
        return (min(g[0], g[2]) - hw, min(g[1], g[3]) - hw, max(g[0], g[2]) + hw, max(g[1], g[3]) + hw)


class GridRouter:
    BOTTOM = 2.5        # the bottom layer is the ground plane: a mm there costs this many top mm
    VIA = 8.0           # a via costs this many mm of top track
    TURN = (0.0, 0.12, 1.5)     # straight on, 45 degrees, 90 degrees
    NEAR = 0.20         # mm beyond the clearance in which a track pays NEAR_COST
    NEAR_COST = 1.4
    RIP = 25.0          # price multiplier for passing through another grid-routed net when stuck
    GREED = 1.1         # weight on the distance-to-go estimate: >1 searches less, settles for a little more

    def __init__(self, board, pro_path=None, origin=(100.0, 50.0), size=(40.0, 61.0), pitch=0.1,
                 edge=0.5, hole_clearance=0.2, margin=0.02, corner=1.0,
                 via=(0.6, 0.3), regions=(), shy=(), novia=(), quiet=False):
        self.board, self.ox, self.oy = board, origin[0], origin[1]
        self.w, self.h, self.p = size[0], size[1], pitch
        self.nx, self.ny = int(round(self.w / pitch)) + 1, int(round(self.h / pitch)) + 1
        self.n = self.nx * self.ny
        self.edge, self.hole_cl, self.margin, self.corner = edge, hole_clearance, margin, corner
        self.via_d, self.via_drill = via
        self.regions, self.shy, self.novia, self.quiet = list(regions), list(shy), list(novia), quiet
        self.X, self.Y = np.meshgrid(np.arange(self.nx) * pitch, np.arange(self.ny) * pitch)
        self.shapes = []
        self.classes, self.patterns = {"Default": 0.2}, []
        if pro_path and os.path.exists(pro_path):
            ns = json.load(open(pro_path, encoding="utf-8")).get("net_settings", {})
            self.classes = {c["name"]: c.get("clearance", 0.2) for c in ns.get("classes", [])}
            self.patterns = [(p["pattern"], p["netclass"]) for p in ns.get("netclass_patterns", [])]
        self._clcache = {}
        self.expanded = 0
        self._read()

    # ------------------------------------------------------------------ board
    def say(self, *a):
        if not self.quiet:
            print(*a, flush=True)

    def net_clearance(self, net):
        if net not in self._clcache:
            c = self.classes.get("Default", 0.2)
            for pat, cls in self.patterns:
                if net and fnmatch.fnmatchcase(net, pat):
                    c = self.classes.get(cls, c)
            self._clcache[net] = c
        return self._clcache[net]

    def clearance(self, a, b):
        return max(self.net_clearance(a), self.net_clearance(b))

    def _read(self):
        b, ox, oy = self.board, self.ox, self.oy
        F, Bc = pcbnew.F_Cu, pcbnew.B_Cu
        for fp in b.GetFootprints():
            fid = fp.GetReference().startswith("FID")
            for p in fp.Pads():
                bb = p.GetBoundingBox()
                x0, y0, x1, y1 = mm(bb.GetLeft()) - ox, mm(bb.GetTop()) - oy, mm(bb.GetRight()) - ox, mm(bb.GetBottom()) - oy
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                layers = tuple(l for l, k in ((0, F), (1, Bc)) if p.IsOnLayer(k))
                hole = mm(p.GetDrillSize().x)
                tag = (fp.GetReference(), p.GetNumber(), cx, cy)
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    self.shapes.append(Shape("circ", (cx, cy, hole / 2), None, (0, 1), "hole", tag))
                    continue
                if fid:        # keep tracks out of the fiducial's mask opening too
                    self.shapes.append(Shape("circ", (cx, cy, 1.1), None, (0,), "hole", tag))
                    continue
                net = p.GetNetname() or "~nc-%s-%s" % (fp.GetReference(), p.GetNumber())
                if p.GetShape() == pcbnew.PAD_SHAPE_CIRCLE:
                    self.shapes.append(Shape("circ", (cx, cy, (x1 - x0) / 2), net, layers, "pad", tag))
                else:
                    self.shapes.append(Shape("rect", (x0, y0, x1, y1), net, layers, "pad", tag))
        for t in b.GetTracks():
            net = t.GetNetname()
            if t.GetClass() == "PCB_VIA":
                q = t.GetPosition()
                self.shapes.append(Shape("circ", (mm(q.x) - ox, mm(q.y) - oy, mm(t.GetWidth(F)) / 2), net, (0, 1), "via"))
            else:
                a, e = t.GetStart(), t.GetEnd()
                self.shapes.append(Shape("seg", (mm(a.x) - ox, mm(a.y) - oy, mm(e.x) - ox, mm(e.y) - oy, mm(t.GetWidth()) / 2),
                                         net, (0 if t.GetLayer() == F else 1,), "track"))
        for i in range(b.GetAreaCount()):
            z = b.GetArea(i)
            if z.GetIsRuleArea() or z.GetNetname() == "GND":
                continue
            bb = z.GetBoundingBox()
            self.shapes.append(Shape("rect", (mm(bb.GetLeft()) - ox, mm(bb.GetTop()) - oy, mm(bb.GetRight()) - ox, mm(bb.GetBottom()) - oy),
                                     z.GetNetname(), (0 if z.GetLayer() == F else 1,), "zone"))

    # --------------------------------------------------------------- geometry
    def _window(self, s, d):
        x0, y0, x1, y1 = s.bbox()
        p = self.p
        ix0, ix1 = max(0, int(math.floor((x0 - d) / p))), min(self.nx, int(math.ceil((x1 + d) / p)) + 1)
        iy0, iy1 = max(0, int(math.floor((y0 - d) / p))), min(self.ny, int(math.ceil((y1 + d) / p)) + 1)
        return ix0, ix1, iy0, iy1

    def _dist(self, s, win):
        """Distance from each cell centre in the window to the shape's copper edge (<= 0 inside)."""
        ix0, ix1, iy0, iy1 = win
        X, Y = self.X[iy0:iy1, ix0:ix1], self.Y[iy0:iy1, ix0:ix1]
        g = s.g
        if s.kind == "rect":
            dx = np.maximum(np.maximum(g[0] - X, X - g[2]), 0.0)
            dy = np.maximum(np.maximum(g[1] - Y, Y - g[3]), 0.0)
            out = np.hypot(dx, dy)
            inside = (dx == 0) & (dy == 0)
            if inside.any():        # signed inside, so "inside copper" can be asked with a margin
                depth = np.minimum(np.minimum(X - g[0], g[2] - X), np.minimum(Y - g[1], g[3] - Y))
                out = np.where(inside, -depth, out)
            return out
        if s.kind == "circ":
            return np.hypot(X - g[0], Y - g[1]) - g[2]
        ax, ay, bx, by, hw = g
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy
        if L2 == 0:
            return np.hypot(X - ax, Y - ay) - hw
        u = np.clip(((X - ax) * vx + (Y - ay) * vy) / L2, 0.0, 1.0)
        return np.hypot(X - (ax + u * vx), Y - (ay + u * vy)) - hw

    def blocked(self, net, hw, skip_routed=False, only=None):
        """bool [2, ny, nx]: True where a track of half-width hw on `net` may not be centred."""
        B = np.zeros((2, self.ny, self.nx), bool)
        lim = self.edge + hw
        k = int(math.ceil(lim / self.p - 1e-9))
        if only is None:
            B[:, :k, :] = True
            B[:, -k:, :] = True
            B[:, :, :k] = True
            B[:, :, -k:] = True
            r = self.corner        # rounded board corners
            for cx, cy in ((r, r), (self.w - r, r), (r, self.h - r), (self.w - r, self.h - r)):
                sx = self.X < r if cx == r else self.X > self.w - r
                sy = self.Y < r if cy == r else self.Y > self.h - r
                B[:, (sx & sy) & (np.hypot(self.X - cx, self.Y - cy) > r - lim)] = True
        for s in self.shapes:
            if s.net == net:
                continue
            if skip_routed and s.src == "route":
                continue
            if only is not None and not only(s):
                continue
            d = hw + self.margin + (self.hole_cl if s.src == "hole" else self.clearance(net, s.net))
            for a, agg, more in self.shy:
                if fnmatch.fnmatchcase(net, a) and s.net and fnmatch.fnmatchcase(s.net, agg):
                    d += more
            win = self._window(s, d)
            if win[0] >= win[1] or win[2] >= win[3]:
                continue
            m = self._dist(s, win) < d
            for L in s.layers:
                B[L, win[2]:win[3], win[0]:win[1]] |= m
        return B

    def via_ok(self, net):
        """bool [ny, nx]: a via of this net may be centred here."""
        r = self.via_d / 2
        bad = self.blocked(net, r).any(axis=0)
        for s in self.shapes:            # never in a pad (any net), and holes keep their distance from each other
            if s.src == "pad":
                d = r + 0.05
            elif s.src == "via":
                d = r + 0.25
            else:
                continue
            win = self._window(s, d)
            bad[win[2]:win[3], win[0]:win[1]] |= self._dist(s, win) < d
        for x0, y0, x1, y1 in self.novia:
            bad[max(0, int(y0 / self.p)):int(y1 / self.p) + 1, max(0, int(x0 / self.p)):int(x1 / self.p) + 1] = True
        return ~bad

    def cost_map(self, net, hw, B):
        C = np.ones((2, self.ny, self.nx), np.float32)
        C[1] *= self.BOTTOM
        for reg in self.regions:
            layer, x0, y0, x1, y1, mult = reg[:6]
            nets = reg[6] if len(reg) > 6 else None
            if nets and not any(fnmatch.fnmatchcase(net, n) for n in nets):
                continue
            ix0, ix1 = max(0, int(x0 / self.p)), min(self.nx, int(x1 / self.p) + 1)
            iy0, iy1 = max(0, int(y0 / self.p)), min(self.ny, int(y1 / self.p) + 1)
            for L in ((0, 1) if layer is None else (layer,)):
                C[L, iy0:iy1, ix0:ix1] *= mult
        near = self._near(net, hw)
        C[near & ~B] *= self.NEAR_COST
        return C

    def _near(self, net, hw):
        save = self.margin
        self.margin = save + self.NEAR
        try:
            return self.blocked(net, hw)
        finally:
            self.margin = save

    # ------------------------------------------------------------ connectivity
    def components(self, net):
        """Islands of this net's copper: [{cells: {flat index: snap point}, bbox}], largest first."""
        mine = [s for s in self.shapes if s.net == net]
        label = np.full((2, self.ny, self.nx), -1, np.int32)
        parent = list(range(len(mine)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        cells = []
        for i, s in enumerate(mine):
            win = self._window(s, 0.0)
            inside = self._dist(s, win) <= 1e-6
            got = []
            for L in s.layers:
                sub = label[L, win[2]:win[3], win[0]:win[1]]
                for j in np.unique(sub[inside]):
                    if j >= 0:
                        parent[find(int(j))] = find(i)
                sub[inside] = i
                ys, xs = np.nonzero(inside)
                got.append((L, ys + win[2], xs + win[0]))
            cells.append(got)
        groups = {}
        for i, s in enumerate(mine):
            groups.setdefault(find(i), []).append(i)
        out = []
        for root, members in groups.items():
            cmap = {}
            for i in members:
                s = mine[i]
                for L, ys, xs in cells[i]:
                    for y, x in zip(ys.tolist(), xs.tolist()):
                        cmap[(L * self.ny + y) * self.nx + x] = i
            if not cmap:
                # copper too thin to cover a cell centre: use the nearest cell to each shape's middle
                for i in members:
                    bb = mine[i].bbox()
                    x, y = int(round((bb[0] + bb[2]) / 2 / self.p)), int(round((bb[1] + bb[3]) / 2 / self.p))
                    for L in mine[i].layers:
                        cmap[(L * self.ny + y) * self.nx + x] = i
            xs = [k % self.nx for k in cmap]
            ys = [(k // self.nx) % self.ny for k in cmap]
            out.append({"cells": cmap, "shapes": mine, "bbox": (min(xs), min(ys), max(xs), max(ys)),
                        "members": members})
        out.sort(key=lambda c: -len(c["cells"]))
        return out

    def _snap(self, shape, x, y):
        """The point on a shape's own centre that a track ending at (x, y) inside it should run on to."""
        g = shape.g
        if shape.kind == "rect":
            return ((g[0] + g[2]) / 2, (g[1] + g[3]) / 2)
        if shape.kind == "circ":
            return (g[0], g[1])
        ax, ay, bx, by, _hw = g
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy
        u = 0.0 if L2 == 0 else min(1.0, max(0.0, ((x - ax) * vx + (y - ay) * vy) / L2))
        return (ax + u * vx, ay + u * vy)

    # ------------------------------------------------------------------ search
    def _astar(self, blk, cost, viaok, sources, targets, tb):
        """A* over cells. Each cell keeps its cheapest arrival and the heading
        it arrived on, which is what the turn costs are charged against: nine
        times fewer states than searching (cell, heading), and the improvement
        passes in route_all() take up what that approximation leaves. The
        heuristic is weighted (GREED) for the same reason."""
        nx, ny, n, p = self.nx, self.ny, self.n, self.p
        tx0, ty0, tx1, ty1 = tb
        TURN, VIA, GREED = self.TURN, self.VIA, self.GREED
        STEP = tuple(p * (SQ2 if (DX[d] and DY[d]) else 1.0) for d in range(8))
        OFF = tuple(DY[d] * nx + DX[d] for d in range(8))
        INF = 1e18
        g = [INF] * (2 * n)
        head = bytearray(b"") * (2 * n)
        parent = [-1] * (2 * n)
        done = bytearray(2 * n)
        heap = []
        push, pop = heapq.heappush, heapq.heappop
        for idx in sources:
            g[idx] = 0.0
            rem = idx % n
            x, y = rem % nx, rem // nx
            dx = tx0 - x if x < tx0 else (x - tx1 if x > tx1 else 0)
            dy = ty0 - y if y < ty0 else (y - ty1 if y > ty1 else 0)
            push(heap, (GREED * p * ((dx + 0.41421356 * dy) if dx > dy else (dy + 0.41421356 * dx)), idx))
        expanded = 0
        while heap:
            _f, idx = pop(heap)
            if done[idx]:
                continue
            done[idx] = 1
            if idx in targets:
                total = g[idx]
                path = [idx]
                while parent[idx] >= 0:
                    idx = parent[idx]
                    path.append(idx)
                self.expanded += expanded
                return path[::-1], total
            expanded += 1
            gc = g[idx]
            d = head[idx]
            L, rem = divmod(idx, n)
            y, x = divmod(rem, nx)
            for nd in range(8):
                if d != 8:
                    df = nd - d
                    if df < 0:
                        df = -df
                    if df > 4:
                        df = 8 - df
                    if df > 2:
                        continue
                    tp = TURN[df]
                else:
                    tp = 0.0
                x2, y2 = x + DX[nd], y + DY[nd]
                if x2 < 0 or y2 < 0 or x2 >= nx or y2 >= ny:
                    continue
                nidx = idx + OFF[nd]
                if blk[nidx] or done[nidx]:
                    continue
                ng = gc + STEP[nd] * cost[nidx] + tp
                if ng < g[nidx]:
                    g[nidx] = ng
                    head[nidx] = nd
                    parent[nidx] = idx
                    dx = tx0 - x2 if x2 < tx0 else (x2 - tx1 if x2 > tx1 else 0)
                    dy = ty0 - y2 if y2 < ty0 else (y2 - ty1 if y2 > ty1 else 0)
                    push(heap, (ng + GREED * p * ((dx + 0.41421356 * dy) if dx > dy else (dy + 0.41421356 * dx)), nidx))
            if viaok[rem]:
                oidx = (1 - L) * n + rem
                if not blk[oidx] and not done[oidx]:
                    ng = gc + VIA
                    if ng < g[oidx]:
                        g[oidx] = ng
                        head[oidx] = 8
                        parent[oidx] = idx
                        dx = tx0 - x if x < tx0 else (x - tx1 if x > tx1 else 0)
                        dy = ty0 - y if y < ty0 else (y - ty1 if y > ty1 else 0)
                        push(heap, (ng + GREED * p * ((dx + 0.41421356 * dy) if dx > dy else (dy + 0.41421356 * dx)), oidx))
        self.expanded += expanded
        return None, None

    def _xy(self, idx):
        L, rem = divmod(idx, self.n)
        y, x = divmod(rem, self.nx)
        return L, round(x * self.p, 4), round(y * self.p, 4)

    def _emit(self, net, width, path, src_comp, dst_comp):
        """Turn a cell path into segment and via shapes, run on to the centres of what it joins."""
        pts = [self._xy(i) for i in path]
        s0 = src_comp["shapes"][src_comp["cells"][path[0]]]
        s1 = dst_comp["shapes"][dst_comp["cells"][path[-1]]]
        runs, cur = [], [pts[0]]
        vias = []
        for a, b in zip(pts, pts[1:]):
            if a[0] != b[0]:
                runs.append(cur)
                vias.append((a[1], a[2]))
                cur = [b]
            else:
                cur.append(b)
        runs.append(cur)
        new = []
        for n_run, run in enumerate(runs):
            L = run[0][0]
            line = [(q[1], q[2]) for q in run]
            if n_run == 0:
                sp = self._snap(s0, *line[0])
                if sp != line[0] and L in s0.layers:
                    line.insert(0, (round(sp[0], 4), round(sp[1], 4)))
            if n_run == len(runs) - 1:
                ep = self._snap(s1, *line[-1])
                if ep != line[-1] and L in s1.layers:
                    line.append((round(ep[0], 4), round(ep[1], 4)))
            # drop collinear middles
            out = [line[0]]
            for q in line[1:]:
                if len(out) >= 2:
                    (ax, ay), (bx, by) = out[-2], out[-1]
                    if abs((bx - ax) * (q[1] - by) - (by - ay) * (q[0] - bx)) < 1e-9 and \
                            (bx - ax) * (q[0] - bx) + (by - ay) * (q[1] - by) > 0:
                        out[-1] = q
                        continue
                if q != out[-1]:
                    out.append(q)
            for a, b in zip(out, out[1:]):
                new.append(Shape("seg", (a[0], a[1], b[0], b[1], width / 2), net, (L,), "route", net))
        for x, y in vias:
            new.append(Shape("circ", (x, y, self.via_d / 2), net, (0, 1), "route", net))
        return new

    # ------------------------------------------------------------------ routing
    def route_net(self, net, width, rip=False):
        """Join every island of `net`. Returns (ok, cost, crossed nets when rip=True)."""
        hw = width / 2
        total, crossed = 0.0, set()
        for _ in range(64):
            comps = self.components(net)
            if len(comps) <= 1:
                return True, total, crossed
            B = self.blocked(net, hw, skip_routed=rip)
            C = self.cost_map(net, hw, B)
            owner = None
            if rip:
                # other grid-routed nets are passable at a price; remember whose copper it was
                owner = np.full((2, self.ny, self.nx), -1, np.int16)
                names = sorted({s.net for s in self.shapes if s.src == "route" and s.net != net})
                for i, other in enumerate(names):
                    m = self.blocked(net, hw, only=lambda s, o=other: s.src == "route" and s.net == o)
                    owner[m & (owner < 0)] = i
                C[owner >= 0] *= self.RIP
            V = self.via_ok(net)
            if rip:
                V &= ~(owner >= 0).any(axis=0)
            blk = bytearray(B.reshape(-1).tobytes())
            cost = C.reshape(-1).tolist()
            viaok = bytearray(V.reshape(-1).tobytes())
            root = comps[0]
            sources = [k for k in root["cells"] if not blk[k]]
            best = None
            # nearest island first, judged by bounding boxes
            rb = root["bbox"]

            def gap(c):
                b = c["bbox"]
                return max(b[0] - rb[2], rb[0] - b[2], 0) + max(b[1] - rb[3], rb[1] - b[3], 0)
            for dst in sorted(comps[1:], key=gap)[:1]:
                targets = {k for k in dst["cells"] if not blk[k]}
                if not sources or not targets:
                    continue
                path, pc = self._astar(blk, cost, viaok, sources, targets, dst["bbox"])
                if path and (best is None or pc < best[1]):
                    best = (path, pc, dst)
            if best is None:
                return False, total, crossed
            path, pc, dst = best
            if rip:
                flat = owner.reshape(-1)
                crossed |= {names[int(flat[k])] for k in path if flat[k] >= 0}
            self.shapes += self._emit(net, width, path, root, dst)
            total += pc
        return False, total, crossed

    def rip_up(self, net):
        self.shapes = [s for s in self.shapes if not (s.src == "route" and s.net == net)]

    def route_all(self, nets, passes=3):
        """nets: [(name, width)] in priority order. Returns {net: cost} and the list of failures."""
        width = dict(nets)
        order = [n for n, _ in nets]
        cost, failed = {}, []
        queue = list(order)
        guard = 0
        while queue and guard < 6 * len(order):
            guard += 1
            net = queue.pop(0)
            self.rip_up(net)
            t0 = time.time()
            ok, c, _ = self.route_net(net, width[net])
            if ok:
                cost[net] = c
                self.say("   %-10s routed, cost %6.1f, %.1f s" % (net, c, time.time() - t0))
                continue
            # stuck: find out what is in the way, take it out, go first
            self.rip_up(net)
            ok, c, crossed = self.route_net(net, width[net], rip=True)
            self.rip_up(net)
            if not ok or not crossed:
                failed.append(net)
                self.say("   %-10s no way through, even over the other routed nets" % net)
                continue
            self.say("   %-10s stuck; ripping up %s and going first" % (net, ", ".join(sorted(crossed))))
            for o in crossed:
                self.rip_up(o)
                cost.pop(o, None)
            ok, c, _ = self.route_net(net, width[net])
            if ok:
                cost[net] = c
            else:
                self.rip_up(net)
                failed.append(net)
            queue = [o for o in order if o in crossed and o not in queue] + queue
        # improvement: each net again, against all the others, searched exactly
        self.GREED = 1.0
        for n_pass in range(passes):
            better = 0
            for net in order:
                if net not in cost:
                    continue
                keep = [s for s in self.shapes if s.src == "route" and s.net == net]
                self.rip_up(net)
                ok, c, _ = self.route_net(net, width[net])
                if ok and c < cost[net] - 1e-6:
                    better += 1
                    cost[net] = c
                else:
                    self.rip_up(net)
                    self.shapes += keep
            self.say("   improvement pass %d: %d net(s) shortened" % (n_pass + 1, better))
            if not better:
                break
        return cost, failed

    # ------------------------------------------------------------------ output
    def items(self):
        """Grid-routed copper as routelib replay records."""
        out = []
        for s in self.shapes:
            if s.src != "route":
                continue
            if s.kind == "circ":
                out.append({"via": True, "net": s.net, "x": s.g[0], "y": s.g[1], "d": self.via_d, "drill": self.via_drill})
            else:
                out.append({"net": s.net, "layer": "F" if s.layers[0] == 0 else "B", "x1": s.g[0], "y1": s.g[1],
                            "x2": s.g[2], "y2": s.g[3], "w": round(s.g[4] * 2, 3)})
        return out

    def stats(self):
        st = {}
        for s in self.shapes:
            if s.src != "route":
                continue
            d = st.setdefault(s.net, {"top": 0.0, "bottom": 0.0, "vias": 0})
            if s.kind == "circ":
                d["vias"] += 1
            else:
                d["top" if s.layers[0] == 0 else "bottom"] += math.hypot(s.g[2] - s.g[0], s.g[3] - s.g[1])
        return st
