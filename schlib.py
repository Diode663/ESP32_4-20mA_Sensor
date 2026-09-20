#!/usr/bin/env python3
"""schlib -- build professional-looking KiCad schematics from Python.

You describe placements, wires, power ports, labels and notes in sheet
coordinates (mm, Y down); schlib turns that into valid KiCad 9/10 .kicad_sch
files, including hierarchical sheets, and gives you the checks needed to trust
hand-authored geometry:

    Sheet.check()        off-grid points, dangling wire ends, wires through
                         bodies, pins landing mid-wire, crossing count
    Design.verify()      KiCad's own netlist vs. your intended NETS spec
    Design.erc()         ERC summary by category
    Design.render()      SVG + PDF of every page, for looking at the result

Minimal use:

    from schlib import Design
    d = Design(project_dir, "myboard", title="My Board", rev="A")
    s = d.sheet("01-power.kicad_sch", "Power", paper="A5")
    s.place("R1", "Device:R", "10k", 50.8, 50.8)
    s.wire(s.pin("R1", 1), (50.8, 43.18)); s.power("+3V3", 50.8, 43.18)
    s.wire(s.pin("R1", 2), (50.8, 58.42)); s.gnd(50.8, 58.42)
    root = d.root_sheet(title="My Board")
    d.link(s, x=25.4, y=50.8, w=50.8, h=25.4)
    d.write()
    d.verify(NETS, NO_CONNECT)

Geometry conventions (all verified against KiCad, not assumed)
--------------------------------------------------------------
* Library pin `(at x y a)` is the pin's electrical tip; its line runs from
  there toward the body. Local frame is Y-up; the sheet is Y-down.
* Placement angle R is counter-clockwise on screen. Local +Y ends up:
  rot 0 -> up, rot 90 -> left, rot 180 -> down, rot 270 -> right.
* Mirroring: see _transform() -- semantics confirmed by probe_transforms.py.
"""
from __future__ import annotations

import datetime
import difflib
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict

# KiCad 10.0's native schematic format. KiCad 10 opens these files without an
# "older version" prompt and saves them back unchanged; KiCad 9 cannot open
# them. Design.check_native() proves every written sheet matches what KiCad 10
# itself would save, so drift after a KiCad update is caught, not shipped.
SCH_VERSION = "20260306"
GENERATOR_VERSION = "10.0"
# Symbol libraries older than this are converted in memory when loaded (via
# kicad-cli sym upgrade), because schematics embed library symbols verbatim.
LIB_NATIVE_VERSION = 20251024

# The order KiCad 10 saves top-level schematic items in; within a type, items
# are sorted by UUID.
_ITEM_ORDER = ["rectangle", "text", "junction", "no_connect", "wire", "label",
               "global_label", "hierarchical_label", "symbol", "sheet"]

GRID = 1.27               # connection grid, mm (50 mil)
MARGIN = 12.7             # keep-out from the frame, mm
TITLE_BAND = 40.0         # bottom band reserved for the title block, mm

PAPER_SIZES = {
    "A5": (210.0, 148.0), "A4": (297.0, 210.0), "A3": (420.0, 297.0),
    "A2": (594.0, 420.0), "A1": (841.0, 594.0),
    "USLetter": (279.4, 215.9), "USLegal": (355.6, 215.9), "USLedger": (431.8, 279.4),
}
AUTO_PAPER_ORDER = ["A5", "A4", "A3", "A2"]


# ===========================================================================
# Small utilities
# ===========================================================================

_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def sid(*parts):
    """Deterministic UUID from key parts.

    KiCad links PCB footprints to schematic symbols by UUID path. Random UUIDs
    would silently break every board association on each regeneration; stable
    ones also keep the generated files diffable.
    """
    return str(uuid.uuid5(_NS, "|".join(str(p) for p in parts)))


def fmt(n):
    s = f"{float(n):.4f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def q(s):
    """Escape a string for a KiCad s-expression."""
    return str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def on_grid(v, g=GRID):
    return abs(v / g - round(v / g)) < 1e-6


def snap(v, g=GRID):
    return round(round(v / g) * g, 4)


def _same(a, b):
    return abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6


def _on_segment(pt, seg):
    """True if pt lies anywhere on an orthogonal segment, ends included."""
    px, py = pt
    x1, y1, x2, y2 = seg
    if abs(y1 - y2) < 1e-6 and abs(py - y1) < 1e-6:
        return min(x1, x2) - 1e-6 <= px <= max(x1, x2) + 1e-6
    if abs(x1 - x2) < 1e-6 and abs(px - x1) < 1e-6:
        return min(y1, y2) - 1e-6 <= py <= max(y1, y2) + 1e-6
    return False


# ===========================================================================
# Locating KiCad
# ===========================================================================

def find_kicad_cli():
    """kicad-cli path: $KICAD_CLI, PATH, then the usual install locations."""
    env = os.environ.get("KICAD_CLI")
    if env and os.path.exists(env):
        return env
    w = shutil.which("kicad-cli")
    if w:
        return w
    cands = []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            cands += glob.glob(os.path.join(base, "KiCad", "*", "bin", "kicad-cli.exe"))
    elif sys.platform == "darwin":
        cands += ["/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"]
    else:
        cands += ["/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli"]
    cands = [c for c in cands if os.path.exists(c)]

    def ver(p):
        m = re.search(r"KiCad[\\/](\d+(?:\.\d+)?)", p)
        return float(m.group(1)) if m else 0.0
    cands.sort(key=ver, reverse=True)
    if cands:
        return cands[0]
    raise FileNotFoundError("kicad-cli not found; set KICAD_CLI to its path")


def find_symbol_dir(cli=None):
    """KiCad's stock symbol library directory."""
    for v in ("KICAD10_SYMBOL_DIR", "KICAD9_SYMBOL_DIR", "KICAD8_SYMBOL_DIR"):
        p = os.environ.get(v)
        if p and os.path.isdir(p):
            return p
    try:
        cli = cli or find_kicad_cli()
    except FileNotFoundError:
        cli = None
    cands = []
    if cli:
        root = os.path.dirname(os.path.dirname(os.path.abspath(cli)))
        cands += [os.path.join(root, "share", "kicad", "symbols"),
                  os.path.join(os.path.dirname(os.path.abspath(cli)), "..",
                               "SharedSupport", "symbols")]
    cands += ["/usr/share/kicad/symbols", "/usr/local/share/kicad/symbols",
              "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"]
    for c in cands:
        if os.path.isdir(c):
            return os.path.normpath(c)
    raise FileNotFoundError("KiCad symbol directory not found; set KICAD10_SYMBOL_DIR")


def _global_sym_lib_tables():
    if sys.platform.startswith("win"):
        base = os.path.join(os.environ.get("APPDATA", ""), "kicad")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Preferences/kicad")
    else:
        base = os.path.expanduser("~/.config/kicad")
    found = glob.glob(os.path.join(base, "*", "sym-lib-table"))

    def ver(p):
        try:
            return float(os.path.basename(os.path.dirname(p)))
        except ValueError:
            return 0.0
    return sorted(found, key=ver, reverse=True)[:1]


# ===========================================================================
# S-expression handling
# ===========================================================================

_TOK = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))')


def parse_sexp(text):
    """Tiny s-expression parser -> nested lists of strings."""
    stack = [[]]
    pos, n = 0, len(text)
    while pos < n:
        m = _TOK.match(text, pos)
        if not m:
            if not text[pos:].strip():
                break
            raise ValueError(f"s-expression parse error near {text[pos:pos + 40]!r}")
        pos = m.end()
        if m.group(1):
            stack.append([])
        elif m.group(2):
            top = stack.pop()
            stack[-1].append(top)
        elif m.group(3) is not None:
            stack[-1].append(re.sub(r"\\(.)", r"\1", m.group(3)))
        else:
            stack[-1].append(m.group(4))
    return stack[0]


def _balanced_end(text, open_idx):
    """Index one past the ')' closing the '(' at open_idx (string-aware)."""
    depth, in_str, esc = 0, False, False
    for i in range(open_idx, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError("unbalanced parentheses")


def _child_spans(block):
    """(start, end) spans of the direct children of a '(...)' block."""
    spans = []
    i = 1
    while i < len(block) - 1:
        ch = block[i]
        if ch == "(":
            end = _balanced_end(block, i)
            spans.append((i, end))
            i = end
            continue
        if ch == '"':
            j = i + 1
            while j < len(block) and not (block[j] == '"' and block[j - 1] != "\\"):
                j += 1
            i = j + 1
            continue
        i += 1
    return spans


def _child_key(raw):
    """('property', 'Value') style key for a child block's raw text."""
    t = parse_sexp(raw)[0]
    return (t[0], t[1] if len(t) > 1 and isinstance(t[1], str) else None)


# ===========================================================================
# Symbols and libraries
# ===========================================================================

class Symbol:
    """A library symbol: its raw text (flattened, renamed to lib_id), pins and
    body geometry. Pins are grouped by unit; unit 0 means 'common to all'."""

    def __init__(self, lib_id, raw):
        self.lib_id = lib_id
        self.raw = raw
        tree = parse_sexp(raw)[0]
        self.is_power = any(isinstance(c, list) and c and c[0] == "power" for c in tree)
        self._pins = []
        self._graphics = defaultdict(list)
        for sub in tree:
            if not (isinstance(sub, list) and sub and sub[0] == "symbol"):
                continue
            m = re.search(r"_(\d+)_(\d+)$", sub[1])
            unit = int(m.group(1)) if m else 0
            style = int(m.group(2)) if m else 1
            if style > 1:            # De Morgan alternate body style -- skip
                continue
            for el in sub[2:]:
                if not (isinstance(el, list) and el):
                    continue
                if el[0] == "pin":
                    self._pins.append(self._pin(el, unit))
                elif el[0] in ("rectangle", "polyline", "circle", "arc", "bezier"):
                    self._graphics[unit].append(el)
        units = sorted({p["unit"] for p in self._pins if p["unit"] > 0})
        self.units = units or [1]

    @staticmethod
    def _pin(el, unit):
        d = {"etype": el[1], "shape": el[2], "unit": unit, "name": "", "num": ""}
        for c in el[3:]:
            if not isinstance(c, list) or not c:
                continue
            if c[0] == "at":
                d["x"], d["y"] = float(c[1]), float(c[2])
                d["angle"] = int(float(c[3])) if len(c) > 3 else 0
            elif c[0] == "length":
                d["length"] = float(c[1])
            elif c[0] == "name":
                d["name"] = c[1]
            elif c[0] == "number":
                d["num"] = c[1]
        return d

    def pins(self, unit=1):
        seen, out = set(), []
        for p in self._pins:
            if p["unit"] in (0, unit) and p["num"] not in seen:
                seen.add(p["num"])
                out.append(p)
        return out

    def find_pin(self, key, unit=1):
        key = str(key)
        pins = self.pins(unit)
        for p in pins:
            if p["num"] == key:
                return p
        named = [p for p in pins if p["name"] == key]
        if len(named) == 1:
            return named[0]
        if len(named) > 1:
            raise KeyError(f"{self.lib_id}: pin name {key!r} is ambiguous "
                           f"(numbers {[p['num'] for p in named]}); use a number")
        raise KeyError(f"{self.lib_id} unit {unit} has no pin {key!r}; pins are "
                       + ", ".join(f"{p['num']}={p['name']}" for p in pins))

    def bbox(self, unit=1):
        xs, ys = [], []

        def pt(node):
            xs.append(float(node[1]))
            ys.append(float(node[2]))
        for el in self._graphics[0] + self._graphics.get(unit, []):
            for c in el[1:]:
                if not isinstance(c, list) or not c:
                    continue
                if c[0] in ("start", "end", "mid", "center"):
                    pt(c)
                elif c[0] == "pts":
                    for xy in c[1:]:
                        if isinstance(xy, list) and xy and xy[0] == "xy":
                            pt(xy)
            if el[0] == "circle":
                cx = cy = r = None
                for c in el[1:]:
                    if isinstance(c, list) and c and c[0] == "center":
                        cx, cy = float(c[1]), float(c[2])
                    if isinstance(c, list) and c and c[0] == "radius":
                        r = float(c[1])
                if r is not None:
                    xs += [cx - r, cx + r]
                    ys += [cy - r, cy + r]
        if not xs:
            return (-1.27, -1.27, 1.27, 1.27)
        return (min(xs), min(ys), max(xs), max(ys))


class Library:
    """Resolves lib_ids like 'Device:R' or 'myproj:ESP32-S3' to Symbols.

    Library nicknames come from the global sym-lib-table, then the project's
    sym-lib-table (which wins), then <stock dir>/<nick>.kicad_sym as a fallback.
    """

    def __init__(self, project_dir=None, stock_dir=None, cli=None):
        self.stock_dir = stock_dir or find_symbol_dir(cli)
        self.project_dir = project_dir
        self.paths = {}
        for t in _global_sym_lib_tables():
            self._load_table(t, None)
        if project_dir:
            self._load_table(os.path.join(project_dir, "sym-lib-table"), project_dir)
        self._text = {}
        self._cache = {}

    def add(self, nick, path):
        self.paths[nick] = path

    def _resolve_uri(self, uri, project_dir):
        def sub(m):
            var = m.group(1)
            if var == "KIPRJMOD":
                return project_dir or ""
            if re.fullmatch(r"KICAD\d*_SYMBOL_DIR", var):
                return self.stock_dir
            return os.environ.get(var, m.group(0))
        path = re.sub(r"\$\{([^}]+)\}", sub, uri)
        return None if "${" in path else os.path.normpath(path)

    def _load_table(self, path, project_dir):
        if not os.path.exists(path):
            return
        text = open(path, encoding="utf-8").read()
        for m in re.finditer(r'\(lib\s*\(name\s*"?([^")]+)"?\)\s*\(type\s*"?([^")]+)"?\)'
                             r'\s*\(uri\s*"?([^")]+)"?\)', text):
            nick, typ, uri = m.groups()
            if typ.strip() != "KiCad":
                continue
            p = self._resolve_uri(uri.strip(), project_dir)
            if p:
                self.paths[nick.strip()] = p

    def path_for(self, nick):
        p = self.paths.get(nick)
        if p and os.path.exists(p):
            return p
        fallback = os.path.join(self.stock_dir, f"{nick}.kicad_sym")
        if os.path.exists(fallback):
            return fallback
        raise KeyError(f"symbol library {nick!r} not found (not in any sym-lib-table "
                       f"and no {fallback})")

    def _file(self, nick):
        if nick not in self._text:
            path = self.path_for(nick)
            text = open(path, encoding="utf-8").read()
            m = re.search(r"\(version\s+(\d+)\)", text[:400])
            if m and int(m.group(1)) < LIB_NATIVE_VERSION:
                text = self._upgraded(path, text, int(m.group(1)))
            self._text[nick] = text
        return self._text[nick]

    def _upgraded(self, path, text, version):
        """An old-format library, converted to KiCad 10 syntax in memory.

        Schematics embed library symbols as-is, so an old library would put
        old syntax into every sheet. The file on disk is left alone; run
        `kicad-cli sym upgrade` on it once to stop this conversion happening."""
        cli = getattr(self, "_cli", None) or find_kicad_cli()
        tmp = tempfile.mkdtemp(prefix="schlib-lib-")
        try:
            dst = os.path.join(tmp, os.path.basename(path))
            subprocess.run([cli, "sym", "upgrade", "--force", "--output", dst, path],
                           capture_output=True, text=True)
            if not os.path.exists(dst):
                raise RuntimeError(f"kicad-cli could not upgrade {path}")
            print(f"  note: {os.path.basename(path)} is library format {version}; converted in "
                  f"memory. Upgrade it once with: kicad-cli sym upgrade \"{path}\"")
            return open(dst, encoding="utf-8").read()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def names(self, nick):
        return [n for n in re.findall(r'\(symbol "([^"]+)"', self._file(nick))
                if not re.search(r"_\d+_\d+$", n)]

    def _raw(self, nick, name):
        text = self._file(nick)
        m = re.search(r'\(symbol "' + re.escape(name) + r'"[\s)]', text)
        if not m:
            close = difflib.get_close_matches(name, self.names(nick), n=5)
            raise KeyError(f"{nick}:{name} not found. Close matches: {close}")
        return text[m.start():_balanced_end(text, m.start())]

    def _flatten(self, nick, name, depth=0):
        """Resolve `(extends "Parent")`: schematics embed only flat symbols."""
        if depth > 8:
            raise ValueError(f"extends chain too deep at {nick}:{name}")
        raw = self._raw(nick, name)
        em = re.search(r'\(extends "([^"]+)"\)', raw)
        if not em:
            return raw
        parent = em.group(1)
        out = self._flatten(nick, parent, depth + 1)
        out = out.replace(f'(symbol "{parent}"', f'(symbol "{name}"', 1)
        out = out.replace(f'(symbol "{parent}_', f'(symbol "{name}_')
        for cs, ce in _child_spans(raw):
            child = raw[cs:ce]
            key = _child_key(child)
            if key[0] != "property":
                continue
            replaced = False
            for ps, pe in _child_spans(out):
                if _child_key(out[ps:pe]) == key:
                    out = out[:ps] + child + out[pe:]
                    replaced = True
                    break
            if not replaced:
                # A property the parent lacks goes after the parent's last
                # property, not straight after the header line: KiCad writes
                # pin_names / exclude_from_sim / in_bom ahead of every
                # property, and putting one first fails the native-format
                # check (seen on Transistor_FET:AO3401A, which adds fields
                # its TP0610T parent does not have).
                props = [(ps, pe) for ps, pe in _child_spans(out)
                         if _child_key(out[ps:pe])[0] == "property"]
                if props:
                    at = props[-1][1]
                    out = out[:at] + "\n\t\t" + child + out[at:]
                else:
                    head_end = out.index("\n") if "\n" in out else len(out) - 1
                    out = out[:head_end] + "\n" + child + out[head_end:]
        return out

    def get(self, lib_id):
        if lib_id in self._cache:
            return self._cache[lib_id]
        if ":" not in lib_id:
            raise ValueError(f"lib_id must be 'Library:Symbol', got {lib_id!r}")
        nick, name = lib_id.split(":", 1)
        raw = self._flatten(nick, name)
        raw = re.sub(r'^\(symbol "[^"]+"', f'(symbol "{q(lib_id)}"', raw, count=1)
        sym = Symbol(lib_id, raw)
        self._cache[lib_id] = sym
        return sym


# ===========================================================================
# Placement transforms
# ===========================================================================

def _rot(px, py, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return (px * c - py * s, px * s + py * c)


def _rotate_point(px, py, cx, cy, deg):
    """Rotate (px, py) by `deg` about (cx, cy) -- SVG's rotate(deg cx cy)."""
    dx, dy = _rot(px - cx, py - cy, deg)
    return (cx + dx, cy + dy)


def _transform(px, py, rot, mirror):
    """Local (Y-up) offset -> sheet-space (Y-down) offset.

    Verified by probe_transforms.py against KiCad's exported netlist for every
    rotation x mirror combination: KiCad rotates first, then mirrors in sheet
    space. `mirror="x"` flips top/bottom (about the X axis); `mirror="y"`
    flips left/right (about the Y axis).
    """
    rx, ry = _rot(px, py, rot)
    sx, sy = rx, -ry
    if mirror == "x":
        sy = -sy
    elif mirror == "y":
        sx = -sx
    return sx, sy


def pin_position(sym, pin, x, y, rot=0, mirror=None):
    sx, sy = _transform(pin["x"], pin["y"], rot, mirror)
    return (round(x + sx, 4), round(y + sy, 4))


def pin_outward(pin, rot=0, mirror=None):
    """Unit vector (sheet space) pointing away from the body at a pin tip."""
    a = math.radians(pin["angle"])
    ox, oy = _transform(-math.cos(a), -math.sin(a), rot, mirror)
    return (round(ox), round(oy))


# ===========================================================================
# Sheet
# ===========================================================================

class Sheet:
    """One .kicad_sch file's worth of drawing."""

    def __init__(self, lib, filename, title, paper="A4", comment=""):
        self.lib = lib
        self.filename = filename
        self.title = title
        self.paper = paper
        self.comments = [comment] if isinstance(comment, str) else list(comment)
        self.uuid = sid("sheet", filename)
        self.instance_uuid = None     # set when linked from the root
        self.symbols = []
        self.segments = []
        self.labels = []              # (kind, name, x, y, angle, justify, shape)
        self.no_connects = []
        self.texts = []               # (content, x, y, size, justify, bold)
        self.rects = []               # (x1, y1, x2, y2)
        self.child_sheets = []        # root only

    # ---- placement ---------------------------------------------------------
    def place(self, ref, lib_id, value, x, y, rot=0, mirror=None, unit=1,
              props=None, dnp=False, in_bom=True, on_board=True):
        """Place a part. `props` become hidden fields (Footprint, MPN, LCSC...)."""
        if any(s["ref"] == ref and s["unit"] == unit for s in self.symbols):
            raise ValueError(f"{ref} unit {unit} placed twice on {self.filename}")
        sym = self.lib.get(lib_id)
        if unit not in sym.units:
            raise ValueError(f"{lib_id} has units {sym.units}, not {unit}")
        self.symbols.append(dict(ref=ref, lib_id=lib_id, value=value, x=x, y=y,
                                 rot=rot, mirror=mirror, unit=unit,
                                 props=dict(props or {}), power=False, dnp=dnp,
                                 in_bom=in_bom, on_board=on_board))
        return ref

    def power(self, kind, x, y, rot=0):
        """Power port (GND, +3V3, +5V, VBUS, PWR_FLAG ...). Its pin is at (x, y);
        at rot=0, GND hangs below that point and supply arrows point up from
        it -- rotate explicitly if you need another orientation. stub(power=)
        picks this automatically to match the stub's own direction."""
        lib_id = kind if ":" in kind else f"power:{kind}"
        self.lib.get(lib_id)
        value = lib_id.split(":", 1)[1]
        self.symbols.append(dict(ref=None, lib_id=lib_id, value=value, x=x, y=y,
                                 rot=rot, mirror=None, unit=1, props={}, power=True,
                                 dnp=False, in_bom=True, on_board=True))
        return (x, y)

    def gnd(self, x, y):
        return self.power("GND", x, y)

    def _sym(self, ref, unit=None):
        hits = [s for s in self.symbols if s["ref"] == ref]
        if unit is not None:
            hits = [s for s in hits if s["unit"] == unit]
        if not hits:
            raise KeyError(f"no component {ref} on {self.filename}")
        return hits

    def pin(self, ref, key, unit=None):
        """Sheet coordinates of a pin, by number or (unique) name."""
        err = None
        for s in self._sym(ref, unit):
            sym = self.lib.get(s["lib_id"])
            try:
                p = sym.find_pin(key, s["unit"])
            except KeyError as e:
                err = e
                continue
            return pin_position(sym, p, s["x"], s["y"], s["rot"], s["mirror"])
        raise err

    def pin_dir(self, ref, key, unit=None):
        for s in self._sym(ref, unit):
            sym = self.lib.get(s["lib_id"])
            try:
                return pin_outward(sym.find_pin(key, s["unit"]), s["rot"], s["mirror"])
            except KeyError:
                continue
        raise KeyError(f"{ref} has no pin {key!r}")

    def pins_of(self, ref):
        """[(num, name, (x, y))] for every pin of every placed unit of ref."""
        out = []
        for s in self._sym(ref):
            sym = self.lib.get(s["lib_id"])
            for p in sym.pins(s["unit"]):
                out.append((p["num"], p["name"],
                            pin_position(sym, p, s["x"], s["y"], s["rot"], s["mirror"])))
        return out

    # ---- wiring --------------------------------------------------------------
    def wire(self, *points):
        """Orthogonal polyline through (x, y) points. Returns the last point.

        Careful fanning multiple signals out from one box to another (e.g. on
        a root/hierarchy sheet) with a shared "over then down" pattern that
        routes them all through a common trunk x (or y): each signal's corner
        point then lands on the *interior* of every other signal's trunk
        segment at that coordinate, and KiCad's connectivity rule treats an
        endpoint landing on another wire's interior as a junction -- silently
        merging every fanned-out net into one. A direct multi-segment wire
        between two pins is only safe when nothing else shares its trunk
        coordinate; for real fan-out, give each pin its own matching label
        (same net name, placed right at the pin) instead of routing wires
        that converge."""
        pts = [(round(p[0], 4), round(p[1], 4)) for p in points]
        for a, b in zip(pts, pts[1:]):
            if abs(a[0] - b[0]) > 1e-6 and abs(a[1] - b[1]) > 1e-6:
                raise ValueError(f"{self.filename}: diagonal wire {a} -> {b}; "
                                 f"add a corner point or use route()")
            if not _same(a, b):
                self.segments.append((a[0], a[1], b[0], b[1]))
        return pts[-1]

    def route(self, a, b, first="h"):
        """L-shaped route from a to b: horizontal first ('h') or vertical first."""
        corner = (b[0], a[1]) if first == "h" else (a[0], b[1])
        return self.wire(a, corner, b)

    def stub(self, ref, key, length=2.54, label=None, hlabel=None, power=None,
             nc=False, shape="bidirectional", unit=None):
        """Short wire straight out of a pin, optionally terminated by a net
        label, hierarchical label or power port. Returns the stub's end.

        A power port's rotation is chosen so its own pin faces back along the
        stub, whatever direction that is -- otherwise every power flag would
        render in its library-default vertical orientation (GND hanging
        below, +XXX arrow pointing up) even on a horizontal stub, colliding
        with whatever sits one or two rows above or below it.

        Watch for two components placed symmetrically so their facing pins'
        stubs reach the same point (e.g. a feedback divider's two resistors,
        each stubbed halfway toward the other) -- two independent `label=`
        calls then land their labels on the exact same coordinate and render
        as one garbled overlapping mess (harmless electrically, broken
        visually). Wire the two raw pins directly instead (`s.pin()`, not the
        stub ends) and add a single label branching off that shared wire."""
        x, y = self.pin(ref, key, unit)
        if nc:
            self.no_connects.append((x, y))
            return (x, y)
        dx, dy = self.pin_dir(ref, key, unit)
        end = (round(x + dx * length, 4), round(y + dy * length, 4))
        self.wire((x, y), end)
        angle = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(dx, dy)]
        if label:
            self.label(label, *end, angle=angle)
        if hlabel:
            self.hlabel(hlabel, *end, angle=angle, shape=shape)
        if power:
            self.power(power, *end, rot=self._power_rot(power, (-dx, -dy)))
        return end

    def _power_rot(self, kind, want_outward):
        """Rotation (0/90/180/270) that makes `kind`'s pin face `want_outward`,
        whatever its native pin angle is -- GND and +XXX-style flags don't
        share one (see power())."""
        lib_id = kind if ":" in kind else f"power:{kind}"
        pin = self.lib.get(lib_id).find_pin("1", 1)
        for rot in (0, 90, 180, 270):
            if pin_outward(pin, rot) == want_outward:
                return rot
        raise ValueError(f"{lib_id}: no rotation makes its pin face {want_outward}")

    def label(self, name, x, y, angle=0, justify=None):
        """Local net label. angle 0: text runs right (wire arrives from the
        left); 180: text runs left; 90/270 for vertical wires."""
        justify = justify or ("right" if angle in (180, 270) else "left")
        self.labels.append(("label", name, x, y, angle, justify, None))
        return (x, y)

    def hlabel(self, name, x, y, angle=0, shape="bidirectional", justify=None):
        """Hierarchical label -- pairs with a same-named pin on the root's sheet
        symbol. shape: input, output, bidirectional, tri_state, passive."""
        justify = justify or ("right" if angle in (180, 270) else "left")
        self.labels.append(("hierarchical_label", name, x, y, angle, justify, shape))
        return (x, y)

    def nc(self, ref, *keys, unit=None):
        for k in keys:
            self.no_connects.append(self.pin(ref, k, unit))

    def note(self, content, x, y, size=1.27, justify="left", bold=False):
        self.texts.append((content, x, y, size, justify, bold))

    def box(self, x1, y1, x2, y2, title=None):
        """Dashed functional-block outline, optionally titled above its corner."""
        self.rects.append((x1, y1, x2, y2))
        if title:
            self.note(title, x1, y1 - 2.54, 1.6, bold=True)

    # ---- geometry --------------------------------------------------------
    def _placed_pins(self):
        out = []
        for s in self.symbols:
            sym = self.lib.get(s["lib_id"])
            for p in sym.pins(s["unit"]):
                out.append((s, p, pin_position(sym, p, s["x"], s["y"], s["rot"], s["mirror"])))
        return out

    def body_bbox(self, s):
        sym = self.lib.get(s["lib_id"])
        x0, y0, x1, y1 = sym.bbox(s["unit"])
        pts = [_transform(px, py, s["rot"], s["mirror"]) for px in (x0, x1) for py in (y0, y1)]
        xs = [s["x"] + a for a, _ in pts]
        ys = [s["y"] + b for _, b in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    def _sheet_pin_points(self):
        pts = []
        for cs in self.child_sheets:
            for (_n, py, side, _sh) in cs["pins"]:
                px = cs["x"] if side == "left" else cs["x"] + cs["w"]
                pts.append((round(px, 4), round(py, 4)))
        return pts

    def content_bbox(self):
        xs, ys = [], []

        def add(x, y):
            xs.append(x)
            ys.append(y)
        for s in self.symbols:
            l, t, r, b = self.body_bbox(s)
            add(l, t)
            add(r, b)
            if not s["power"]:
                # reference/value text sits just outside the body
                add(l, t - 4.0)
                add(r + 12.0 if (b - t) >= (r - l) else r, b + 4.0)
        for s, p, (x, y) in self._placed_pins():
            add(x, y)
        for x1, y1, x2, y2 in self.segments:
            add(x1, y1)
            add(x2, y2)
        for _k, name, x, y, angle, _j, _sh in self.labels:
            w = len(name) * 1.1 + 3.0
            add(x, y)
            if angle == 180:
                add(x - w, y)
            elif angle == 0:
                add(x + w, y)
            elif angle == 90:
                add(x, y - w)
            else:
                add(x, y + w)
        for content, x, y, size, _j, _b in self.texts:
            longest = max(len(line) for line in content.split("\n"))
            add(x, y - size)
            add(x + longest * size * 0.85, y + size * content.count("\n") * 1.6)
        for x1, y1, x2, y2 in self.rects:
            add(x1, y1)
            add(x2, y2)
        for x, y in self.no_connects:
            add(x, y)
        for cs in self.child_sheets:
            add(cs["x"], cs["y"] - 3)
            add(cs["x"] + cs["w"], cs["y"] + cs["h"] + 3)
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))

    def translate(self, dx, dy):
        """Move everything; connectivity is unaffected."""
        dx, dy = round(dx, 4), round(dy, 4)

        def mv(x, y):
            return round(x + dx, 4), round(y + dy, 4)
        for s in self.symbols:
            s["x"], s["y"] = mv(s["x"], s["y"])
        self.segments = [(*mv(a, b), *mv(c, d)) for a, b, c, d in self.segments]
        self.labels = [(k, n, *mv(x, y), a, j, sh) for k, n, x, y, a, j, sh in self.labels]
        self.no_connects = [mv(x, y) for x, y in self.no_connects]
        self.texts = [(c, *mv(x, y), s, j, b) for c, x, y, s, j, b in self.texts]
        self.rects = [(*mv(a, b), *mv(c, d)) for a, b, c, d in self.rects]
        for cs in self.child_sheets:
            cs["x"], cs["y"] = mv(cs["x"], cs["y"])
            cs["pins"] = [(n, round(py + dy, 4), side, sh) for n, py, side, sh in cs["pins"]]

    @staticmethod
    def usable_area(paper):
        pw, ph = PAPER_SIZES[paper]
        return (pw - 2 * MARGIN, ph - MARGIN - TITLE_BAND)

    def suggest_paper(self):
        """Smallest paper in AUTO_PAPER_ORDER that holds the drawing."""
        x0, y0, x1, y1 = self.content_bbox()
        w, h = x1 - x0, y1 - y0
        for p in AUTO_PAPER_ORDER:
            uw, uh = self.usable_area(p)
            if w <= uw and h <= uh:
                return p
        return AUTO_PAPER_ORDER[-1]

    def title_block_overlap(self):
        """True if any drawn point lands in the bottom-right title-block corner.

        The reserved bottom band spans the full width for centring, but the
        title block itself only fills the right-hand ~115 mm, so a tall drawing
        can legitimately dip into the band on the left. Only the corner counts.
        """
        pw, ph = PAPER_SIZES[self.paper]
        tx, ty = pw - 10.0 - 115.0, ph - 10.0 - 38.0
        x0, y0, x1, y1 = self.content_bbox()
        if x1 < tx or y1 < ty:
            return False
        pts = []
        for s in self.symbols:
            l, t, r, b = self.body_bbox(s)
            pts += [(l, t), (r, b), (l, b), (r, t)]
        pts += [(a, b) for a, b, _c, _d in self.segments]
        pts += [(c, d) for _a, _b, c, d in self.segments]
        pts += [(x, y) for _k, _n, x, y, *_ in self.labels]
        for content, x, y, size, _j, _b in self.texts:
            pts += [(x, y), (x + max(len(ln) for ln in content.split("\n")) * size * 0.85, y)]
        for a, b, c, d in self.rects:
            pts += [(c, d), (a, d), (c, b)]
        return any(px > tx and py > ty for px, py in pts)

    def utilization(self):
        x0, y0, x1, y1 = self.content_bbox()
        uw, uh = self.usable_area(self.paper)
        return ((x1 - x0) / uw, (y1 - y0) / uh)

    def center_on_page(self):
        """Centre the drawing in the frame, clear of the title block, on-grid."""
        pw, ph = PAPER_SIZES[self.paper]
        left, right = MARGIN, pw - MARGIN
        top, bottom = MARGIN, ph - TITLE_BAND
        x0, y0, x1, y1 = self.content_bbox()
        dx = max((left + right) / 2 - (x0 + x1) / 2, left - x0)
        dy = max((top + bottom) / 2 - (y0 + y1) / 2, top - y0)
        self.translate(snap(dx), snap(dy))

    # ---- checks ------------------------------------------------------------
    def check(self):
        """Return (errors, warnings, info) lists of strings.

        errors   off-grid pins/wire ends/labels (KiCad won't join them),
                 dangling wire ends
        warnings a pin landing mid-wire (KiCad connects it -- usually an
                 accident), a wire running through a part's body
        info     number of wire crossings (aim low; no dot = not connected)
        """
        errors, warnings, info = [], [], []
        for s, p, (x, y) in self._placed_pins():
            if not (on_grid(x) and on_grid(y)):
                errors.append(f"off grid: {s['ref'] or s['value']} pin {p['num']} at ({x}, {y})")
        for x1, y1, x2, y2 in self.segments:
            for x, y in ((x1, y1), (x2, y2)):
                if not (on_grid(x) and on_grid(y)):
                    errors.append(f"off grid: wire end at ({x}, {y})")
        for _k, name, x, y, *_ in self.labels:
            if not (on_grid(x) and on_grid(y)):
                errors.append(f"off grid: label {name} at ({x}, {y})")

        pin_pts = [(round(x, 4), round(y, 4)) for _s, _p, (x, y) in self._placed_pins()]
        anchors = set(pin_pts)
        anchors |= {(round(x, 4), round(y, 4)) for _k, _n, x, y, *_ in self.labels}
        anchors |= set(self._sheet_pin_points())

        def interior(px, py, seg):
            x1, y1, x2, y2 = seg
            if abs(y1 - y2) < 1e-6 and abs(py - y1) < 1e-6:
                return min(x1, x2) + 1e-6 < px < max(x1, x2) - 1e-6
            if abs(x1 - x2) < 1e-6 and abs(px - x1) < 1e-6:
                return min(y1, y2) + 1e-6 < py < max(y1, y2) - 1e-6
            return False

        def touches(px, py, seg):
            return _same((px, py), seg[:2]) or _same((px, py), seg[2:]) or interior(px, py, seg)

        for i, seg in enumerate(self.segments):
            for pt in (seg[:2], seg[2:]):
                if (round(pt[0], 4), round(pt[1], 4)) in anchors:
                    continue
                if any(touches(pt[0], pt[1], o) for j, o in enumerate(self.segments) if j != i):
                    continue
                errors.append(f"dangling wire end at ({pt[0]}, {pt[1]})")

        for s, p, (x, y) in self._placed_pins():
            for seg in self.segments:
                if interior(x, y, seg):
                    warnings.append(f"{s['ref'] or s['value']} pin {p['num']} lands mid-wire "
                                    f"at ({x}, {y}) -- KiCad will connect it")
        for s in self.symbols:
            if s["power"]:
                continue
            l, t, r, b = self.body_bbox(s)
            l, t, r, b = l + 0.3, t + 0.3, r - 0.3, b - 0.3
            sym = self.lib.get(s["lib_id"])
            own = [pin_position(sym, p, s["x"], s["y"], s["rot"], s["mirror"])
                   for p in sym.pins(s["unit"])]
            for x1, y1, x2, y2 in self.segments:
                # A wire ending on this part's own pin is normal even when the
                # body graphic (e.g. an LED's emission arrows) overhangs the tip.
                if any(_same(o, (x1, y1)) or _same(o, (x2, y2)) for o in own):
                    continue
                if abs(y1 - y2) < 1e-6 and t < y1 < b and min(x1, x2) < r and max(x1, x2) > l:
                    warnings.append(f"wire at y={y1} runs through {s['ref']}'s body")
                elif abs(x1 - x2) < 1e-6 and l < x1 < r and min(y1, y2) < b and max(y1, y2) > t:
                    warnings.append(f"wire at x={x1} runs through {s['ref']}'s body")

        horiz = [s for s in self.segments if abs(s[1] - s[3]) < 1e-6]
        vert = [s for s in self.segments if abs(s[0] - s[2]) < 1e-6 and abs(s[1] - s[3]) > 1e-6]
        crossings = 0
        for h in horiz:
            for v in vert:
                if min(h[0], h[2]) + 1e-6 < v[0] < max(h[0], h[2]) - 1e-6 and \
                   min(v[1], v[3]) + 1e-6 < h[1] < max(v[1], v[3]) - 1e-6:
                    crossings += 1
        info.append(f"{crossings} wire crossing(s)")
        return (sorted(set(errors)), sorted(set(warnings)), info)

    def _junctions(self):
        pts = [(round(x, 4), round(y, 4)) for _s, _p, (x, y) in self._placed_pins()]
        pin_set = set(pts)
        cands = set(pin_set)
        for x1, y1, x2, y2 in self.segments:
            cands.add((x1, y1))
            cands.add((x2, y2))
        out = []
        for (px, py) in cands:
            n = 0
            for x1, y1, x2, y2 in self.segments:
                if _same((px, py), (x1, y1)) or _same((px, py), (x2, y2)):
                    n += 1
                elif (abs(y1 - y2) < 1e-6 and abs(py - y1) < 1e-6 and
                      min(x1, x2) < px < max(x1, x2)) or \
                     (abs(x1 - x2) < 1e-6 and abs(px - x1) < 1e-6 and
                      min(y1, y2) < py < max(y1, y2)):
                    n += 2
            if (px, py) in pin_set:
                n += 1
            if n >= 3:
                out.append((px, py))
        return sorted(out)


# ===========================================================================
# Emission
# ===========================================================================

def _prop(name, value, x, y, hide, size=1.27, justify=None, bold=False, angle=0):
    j = f"\n\t\t\t\t(justify {justify})" if justify else ""
    b = "\n\t\t\t\t\t(bold yes)" if bold else ""
    h = "\n\t\t\t(hide yes)" if hide else ""
    return (f'\t\t(property "{q(name)}" "{q(value)}"\n'
            f"\t\t\t(at {fmt(x)} {fmt(y)} {angle}){h}\n"
            "\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n"
            f"\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size {fmt(size)} {fmt(size)}){b}\n\t\t\t\t){j}\n\t\t\t)\n"
            f"\t\t)\n")


def _kicad_order(text):
    """Reorder a sheet's top-level items the way KiCad 10 saves them: header
    and lib_symbols first, then items by type (_ITEM_ORDER) and UUID, then
    sheet_instances and embedded_fonts."""
    spans = _child_spans(text)
    head, items, tail = [], [], []
    for a, b in spans:
        chunk = text[a:b]
        kind = re.match(r"\((\w+)", chunk).group(1)
        if kind in _ITEM_ORDER:
            um = re.search(r'\n\t\t\(uuid "([^"]+)"\)', chunk) or re.search(r'\(uuid "([^"]+)"\)', chunk)
            items.append((_ITEM_ORDER.index(kind), um.group(1) if um else "", chunk))
        elif kind in ("sheet_instances", "embedded_fonts"):
            tail.append(chunk)
        else:
            head.append(chunk)
    items.sort(key=lambda t: (t[0], t[1]))
    body = head + [c for _r, _u, c in items] + tail
    return "(kicad_sch\n" + "".join("\t" + c + "\n" for c in body) + ")\n"


def _tbox(x, y, text, size=1.27, justify=None):
    """Approximate box of one line of field text, vertically centred on y."""
    w = len(str(text)) * size * 0.95 + 0.2
    x0 = x if justify == "left" else (x - w if justify == "right" else x - w / 2)
    return (x0, y - size * 0.6, x0 + w, y + size * 0.6)


def _boxes_hit(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _field_obstacles(sheet):
    """Everything reference/value text should stay off: wires, part bodies,
    pin lines, power-port graphics, labels, notes and no-connect flags."""
    obs = []
    for x1, y1, x2, y2 in sheet.segments:
        obs.append((min(x1, x2) - 0.25, min(y1, y2) - 0.25,
                    max(x1, x2) + 0.25, max(y1, y2) + 0.25))
    for s in sheet.symbols:
        sym = sheet.lib.get(s["lib_id"])
        x, y = s["x"], s["y"]
        if s["power"]:
            obs.append((x - 1.6, y, x + 1.6, y + 3.0) if s["value"] == "GND"
                       else (x - 1.6, y - 3.2, x + 1.6, y))
            continue
        obs.append(sheet.body_bbox(s))
        for pin in sym.pins(s["unit"]):
            tx, ty = pin_position(sym, pin, x, y, s["rot"], s["mirror"])
            ox, oy = pin_outward(pin, s["rot"], s["mirror"])
            ln = pin.get("length", 2.54)
            bx, by = tx - ox * ln, ty - oy * ln
            obs.append((min(tx, bx) - 0.3, min(ty, by) - 0.3,
                        max(tx, bx) + 0.3, max(ty, by) + 0.3))
    for _k, name, x, y, angle, _j, shape in sheet.labels:
        w = len(name) * 1.27 * 0.95 + (2.5 if shape else 0.5)
        obs.append({0: (x, y - 1.6, x + w, y + 0.3),
                    180: (x - w, y - 1.6, x, y + 0.3),
                    90: (x - 1.6, y - w, x + 0.3, y)}.get(angle, (x - 1.6, y, x + 0.3, y + w)))
    for content, x, y, size, _j, _b in sheet.texts:
        lines = content.split("\n")
        w = max(len(ln) for ln in lines) * size * 0.9
        obs.append((x, y - size * 0.8, x + w, y + size * (1.7 * (len(lines) - 1) + 0.4)))
    for x, y in sheet.no_connects:
        obs.append((x - 0.8, y - 0.8, x + 0.8, y + 0.8))
    return obs


def _choose_field_spots(s, body, vertical_pair, taken, ref, value):
    """Place reference and value clear of everything in `taken`.

    Tries the conventional spot first -- stacked beside a vertical two-pin
    part, above/below anything else -- then the alternatives, falling back to
    the least crowded. The chosen boxes join `taken` so later parts avoid
    them too."""
    l, t, r, b = body
    cx, cy = (l + r) / 2, (t + b) / 2
    y0 = s["y"] if vertical_pair else cy
    right = [(r + 1.78, y0 - 1.27, "left"), (r + 1.78, y0 + 1.27, "left")]
    left = [(l - 1.78, y0 - 1.27, "right"), (l - 1.78, y0 + 1.27, "right")]
    split = [(cx, t - 2.03, None), (cx, b + 2.03, None)]
    above = [(cx, t - 4.57, None), (cx, t - 2.03, None)]
    below = [(cx, b + 2.03, None), (cx, b + 4.57, None)]
    order = [right, left, above, below] if vertical_pair else [split, above, below, right, left]
    best = None
    for cand in order:
        boxes = [_tbox(cand[0][0], cand[0][1], ref, justify=cand[0][2]),
                 _tbox(cand[1][0], cand[1][1], value, justify=cand[1][2])]
        score = sum(1 for bx in boxes for o in taken if _boxes_hit(bx, o))
        if best is None or score < best[0]:
            best = (score, cand, boxes)
        if score == 0:
            break
    _score, cand, boxes = best
    taken.extend(boxes)
    return cand[0], cand[1]


def _file_just(j, s):
    """Justification to write so it *displays* as j.

    Two things flip left against right: a left/right mirror, and a 180 degree
    rotation now that its fields are written at angle 0 rather than 180. Both
    together cancel out.
    """
    if j and (s["mirror"] == "y") != (s["rot"] == 180):
        return {"left": "right", "right": "left"}[j]
    return j


def _emit(sheet, project, title_block, root_uuid=None, pwr_counter=None):
    p = []
    lib_ids = sorted({s["lib_id"] for s in sheet.symbols})
    p.append(f'(kicad_sch\n\t(version {SCH_VERSION})\n\t(generator "eeschema")\n'
             f'\t(generator_version "{GENERATOR_VERSION}")\n')
    p.append(f'\t(uuid "{sheet.uuid}")\n\t(paper "{sheet.paper}")\n')
    tb = [f'\t\t(title "{q(sheet.title)}")',
          f'\t\t(date "{q(title_block["date"])}")',
          f'\t\t(rev "{q(title_block["rev"])}")']
    if title_block["company"]:
        tb.append(f'\t\t(company "{q(title_block["company"])}")')
    for i, c in enumerate(sheet.comments[:9], 1):
        if c:
            tb.append(f'\t\t(comment {i} "{q(c)}")')
    p.append("\t(title_block\n" + "\n".join(tb) + "\n\t)\n")

    p.append("\t(lib_symbols\n")
    for lid in lib_ids:
        raw = sheet.lib.get(lid).raw
        p.append("\n".join("\t\t" + ln if ln.strip() else ln for ln in raw.split("\n")) + "\n")
    p.append("\t)\n")

    fn = sheet.filename
    for x1, y1, x2, y2 in sheet.rects:
        p.append("\t(rectangle\n"
                 f"\t\t(start {fmt(x1)} {fmt(y1)})\n\t\t(end {fmt(x2)} {fmt(y2)})\n"
                 "\t\t(stroke\n\t\t\t(width 0.254)\n\t\t\t(type dash)\n"
                 "\t\t\t(color 132 132 132 1)\n\t\t)\n"
                 "\t\t(fill\n\t\t\t(type none)\n\t\t)\n"
                 f'\t\t(uuid "{sid(fn, "rect", x1, y1, x2, y2)}")\n\t)\n')
    for x1, y1, x2, y2 in sheet.segments:
        p.append("\t(wire\n"
                 f"\t\t(pts\n\t\t\t(xy {fmt(x1)} {fmt(y1)}) (xy {fmt(x2)} {fmt(y2)})\n\t\t)\n"
                 "\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type solid)\n\t\t)\n"
                 f'\t\t(uuid "{sid(fn, "wire", x1, y1, x2, y2)}")\n\t)\n')
    for (jx, jy) in sheet._junctions():
        p.append("\t(junction\n"
                 f"\t\t(at {fmt(jx)} {fmt(jy)})\n\t\t(diameter 0)\n\t\t(color 0 0 0 0)\n"
                 f'\t\t(uuid "{sid(fn, "junction", jx, jy)}")\n\t)\n')
    for (nx, ny) in sheet.no_connects:
        p.append(f"\t(no_connect\n\t\t(at {fmt(nx)} {fmt(ny)})\n"
                 f'\t\t(uuid "{sid(fn, "nc", nx, ny)}")\n\t)\n')
    for kind, name, x, y, angle, justify, shape in sheet.labels:
        sh = f"\t\t(shape {shape})\n" if shape else ""
        p.append(f'\t({kind} "{q(name)}"\n{sh}'
                 f"\t\t(at {fmt(x)} {fmt(y)} {angle})\n"
                 "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n"
                 f"\t\t\t(justify {justify})\n\t\t)\n"
                 f'\t\t(uuid "{sid(fn, kind, name, x, y)}")\n\t)\n')
    for content, x, y, size, justify, bold in sheet.texts:
        b = "\n\t\t\t\t(bold yes)" if bold else ""
        p.append(f'\t(text "{q(content)}"\n\t\t(exclude_from_sim no)\n'
                 f"\t\t(at {fmt(x)} {fmt(y)} 0)\n"
                 f"\t\t(effects\n\t\t\t(font\n\t\t\t\t(size {fmt(size)} {fmt(size)}){b}\n\t\t\t)\n"
                 f"\t\t\t(justify {justify})\n\t\t)\n"
                 f'\t\t(uuid "{sid(fn, "text", content, x, y)}")\n\t)\n')

    for cs in sheet.child_sheets:
        sx, sy, sw, sh_ = cs["x"], cs["y"], cs["w"], cs["h"]
        p.append("\t(sheet\n"
                 f"\t\t(at {fmt(sx)} {fmt(sy)})\n\t\t(size {fmt(sw)} {fmt(sh_)})\n"
                 "\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n\t\t(dnp no)\n"
                 "\t\t(stroke\n\t\t\t(width 0.1524)\n\t\t\t(type solid)\n\t\t)\n"
                 "\t\t(fill\n\t\t\t(color 0 0 0 0)\n\t\t)\n"
                 f'\t\t(uuid "{cs["uuid"]}")\n')
        p.append(_prop("Sheetname", cs["name"], sx, sy - 1.0, False, 1.524, "left bottom", True))
        p.append(_prop("Sheetfile", cs["file"], sx, sy + sh_ + 1.2, False, 1.27, "left top"))
        for (pname, py, side, pshape) in cs["pins"]:
            px = sx if side == "left" else sx + sw
            ang = 180 if side == "left" else 0
            just = "left" if side == "left" else "right"
            p.append(f'\t\t(pin "{q(pname)}" {pshape}\n'
                     f"\t\t\t(at {fmt(px)} {fmt(py)} {ang})\n"
                     f'\t\t\t(uuid "{sid(cs["file"], "sheetpin", pname)}")\n'
                     "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n"
                     f"\t\t\t\t(justify {just})\n\t\t\t)\n\t\t)\n")
        p.append("\t\t(instances\n"
                 f'\t\t\t(project "{q(project)}"\n'
                 f'\t\t\t\t(path "/{sheet.uuid}"\n\t\t\t\t\t(page "{cs["page"]}")\n\t\t\t\t)\n'
                 "\t\t\t)\n\t\t)\n\t)\n")

    fields_taken = _field_obstacles(sheet)
    used_uuids = set()
    for s in sheet.symbols:
        sym = sheet.lib.get(s["lib_id"])
        x, y, rot = s["x"], s["y"], s["rot"]
        if s["power"]:
            ref = f"#PWR{next(pwr_counter):03d}"
            # rotation is part of the key: two ports stacked on one point at
            # different angles used to share a UUID, and KiCad renumbered one
            uid_ = sid(fn, "pwr", s["lib_id"], x, y, rot)
            while uid_ in used_uuids:
                uid_ = sid(uid_, "dup")
            used_uuids.add(uid_)
        else:
            ref = s["ref"]
            uid_ = sid(fn, "sym", ref, s["unit"])
        mir = f"\t\t(mirror {s['mirror']})\n" if s["mirror"] else ""
        p.append("\t(symbol\n"
                 f'\t\t(lib_id "{q(s["lib_id"])}")\n'
                 f"\t\t(at {fmt(x)} {fmt(y)} {rot})\n{mir}"
                 f'\t\t(unit {s["unit"]})\n\t\t(body_style 1)\n\t\t(exclude_from_sim no)\n'
                 f'\t\t(in_bom {"yes" if s["in_bom"] else "no"})\n'
                 f'\t\t(on_board {"yes" if s["on_board"] else "no"})\n'
                 "\t\t(in_pos_files yes)\n"
                 f'\t\t(dnp {"yes" if s["dnp"] else "no"})\n'
                 f'\t\t(uuid "{uid_}")\n')
        if s["power"]:
            vy = y + 4.06 if s["value"] == "GND" else y - 3.81
            p.append(_prop("Reference", ref, x, y - 2.54, True))
            p.append(_prop("Value", s["value"], x, vy, False))
        else:
            l, t, r, b = sheet.body_bbox(s)
            # Field angle AND justification are stored relative to the symbol,
            # so leaving angle 0 on a rotated part draws its text sideways.
            # Cancelling the part's rotation (angle = -rot) fixes 90 and 270,
            # where KiCad then normalises the result to read bottom-to-top.
            # It does NOT fix 180: KiCad draws that literally, upside down.
            # 180 therefore takes angle 0, and because the justification is
            # read in the symbol's frame, left/right swap with it.
            fa = 0 if rot == 180 else (-rot) % 360
            pins2 = sym.pins(s["unit"])
            vertical_pair = False
            if len(pins2) == 2:
                # Decide by where the pins are, not by the body's shape: some
                # library bodies (e.g. EasyEDA diodes) are taller than wide
                # even though the part is drawn horizontally.
                (ax, ay), (bx, by) = (pin_position(sym, pp, x, y, rot, s["mirror"])
                                      for pp in pins2)
                vertical_pair = abs(ax - bx) < abs(ay - by)
            (rx_, ry_, rj), (vx_, vy_, vj) = _choose_field_spots(
                s, (l, t, r, b), vertical_pair, fields_taken, ref, s["value"])
            p.append(_prop("Reference", ref, rx_, ry_, False, justify=_file_just(rj, s), angle=fa))
            p.append(_prop("Value", s["value"], vx_, vy_, False, justify=_file_just(vj, s), angle=fa))
        # KiCad 10 always stores Footprint, Datasheet and Description, in that
        # order, before any user fields.
        props = dict(s["props"])
        for k in ("Footprint", "Datasheet", "Description"):
            p.append(_prop(k, props.pop(k, ""), x, y, not s["power"]))
        for k, v in props.items():
            p.append(_prop(k, v, x, y, True))
        for pin in sym.pins(s["unit"]):
            p.append(f'\t\t(pin "{q(pin["num"])}"\n'
                     f'\t\t\t(uuid "{sid(fn, "sympin", ref, s["unit"], pin["num"])}")\n\t\t)\n')
        path = f"/{root_uuid}/{sheet.instance_uuid}" if root_uuid else f"/{sheet.uuid}"
        p.append("\t\t(instances\n"
                 f'\t\t\t(project "{q(project)}"\n'
                 f'\t\t\t\t(path "{path}"\n'
                 f'\t\t\t\t\t(reference "{q(ref)}")\n\t\t\t\t\t(unit {s["unit"]})\n\t\t\t\t)\n'
                 "\t\t\t)\n\t\t)\n\t)\n")

    if root_uuid is None:
        p.append('\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n')
    p.append(")\n")          # KiCad 10 omits a sheet-level (embedded_fonts no)
    return _kicad_order("".join(p))




# ===========================================================================
# Design: a set of sheets written together
# ===========================================================================

class GeometryError(RuntimeError):
    pass


class Design:
    """A project's schematic: an optional root sheet plus sub-sheets."""

    MANIFEST = ".schgen-manifest.json"

    def __init__(self, project_dir, name, lib=None, title="", rev="A", date=None,
                 company="", cli=None):
        self.project_dir = os.path.abspath(project_dir)
        self.name = name
        self.cli = cli
        self.lib = lib or Library(self.project_dir, cli=cli)
        self.title_block = {"date": date or datetime.date.today().isoformat(),
                            "rev": rev, "company": company}
        self.title = title or name
        self.children = []
        self.root = None

    # ---- construction ------------------------------------------------------
    def sheet(self, filename, title, paper="A4", comment=""):
        s = Sheet(self.lib, filename, title, paper, comment)
        self.children.append(s)
        return s

    def root_sheet(self, filename=None, title=None, paper="A4", comment=""):
        filename = filename or f"{self.name}.kicad_sch"
        self.root = Sheet(self.lib, filename, title or self.title, paper, comment)
        return self.root

    def link(self, child, x, y, w, h, pins=()):
        """Draw `child` as a sheet box on the root. pins: (name, side, y) or
        (name, side, y, shape); side 'left' or 'right'; y absolute, on-grid."""
        if self.root is None:
            raise RuntimeError("call root_sheet() before link()")
        child.instance_uuid = sid("sheetinstance", child.filename)
        norm = []
        for pin in pins:
            name, side, py = pin[:3]
            shape = pin[3] if len(pin) > 3 else "bidirectional"
            if side not in ("left", "right"):
                raise ValueError("sheet pin side must be 'left' or 'right'")
            norm.append((name, py, side, shape))
        self.root.child_sheets.append(dict(uuid=child.instance_uuid, name=child.title,
                                           file=child.filename, x=x, y=y, w=w, h=h,
                                           page=str(len(self.root.child_sheets) + 2),
                                           pins=norm))

    def all_sheets(self):
        return ([self.root] if self.root else []) + self.children

    # ---- output ------------------------------------------------------------
    def _hash(self, path):
        return hashlib.sha256(open(path, "rb").read()).hexdigest()

    def _guard(self, targets, force):
        """Refuse to overwrite schematics edited outside the generator.

        Opening a generated file in KiCad and saving it -- even just moving a
        part -- changes it. Blindly regenerating would silently discard that
        work, so compare against the hashes recorded at the last write.
        """
        man_path = os.path.join(self.project_dir, self.MANIFEST)
        manifest = json.load(open(man_path)) if os.path.exists(man_path) else {}
        changed = []
        for f in targets:
            p = os.path.join(self.project_dir, f)
            if os.path.exists(p) and manifest.get(f) != self._hash(p):
                changed.append(f)
        if changed:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            bdir = os.path.join(self.project_dir, ".schgen-backup", stamp)
            os.makedirs(bdir, exist_ok=True)
            for f in changed:
                shutil.copy2(os.path.join(self.project_dir, f), os.path.join(bdir, f))
            if not force:
                raise RuntimeError(
                    "These schematic files were modified outside the generator (or were "
                    f"never written by it): {changed}. Backed up to {bdir}. Open them in "
                    "KiCad, port any edits worth keeping into the generator script, then "
                    "rerun with write(force=True).")
            print(f"  force: overwriting {changed} (backups in {bdir})")
        return man_path, manifest

    def _patch_project(self):
        """Give every netclass a wire/bus width. A netclass without `wire_width`
        makes KiCad plot every wire and junction invisibly (stroke:none) in SVG
        and PDF while they stay electrically present. Verified by controlled
        test: stroke type is irrelevant, the width is the whole story."""
        pro = os.path.join(self.project_dir, f"{self.name}.kicad_pro")
        if not os.path.exists(pro):
            return
        data = json.load(open(pro, encoding="utf-8"))
        changed = False
        for cls in data.get("net_settings", {}).get("classes", []):
            for key in ("wire_width", "bus_width"):
                if not cls.get(key):
                    cls[key] = 6
                    changed = True
        if changed:
            json.dump(data, open(pro, "w", encoding="utf-8"), indent=2)
            print(f"  patched netclass wire/bus widths in {os.path.basename(pro)}")

    def write(self, center=True, force=False, strict=True, native_check=True):
        """Check, lay out and write every sheet. Returns written file paths."""
        sheets = self.all_sheets()
        if not sheets:
            raise RuntimeError("nothing to write")
        if self.children and self.root is None:
            if len(self.children) == 1:
                # a single sheet is its own root
                self.root, self.children = self.children[0], []
                sheets = [self.root]
            else:
                raise RuntimeError("several sheets but no root_sheet(); add one and link() them")
        linked = {cs["file"] for cs in (self.root.child_sheets if self.root else [])}
        for c in self.children:
            if c.filename not in linked:
                raise RuntimeError(f"{c.filename} is never link()ed from the root sheet")

        all_errors = []
        for s in sheets:
            if s.paper == "auto":
                s.paper = s.suggest_paper()
            errors, warnings, info = s.check()
            for e in errors:
                all_errors.append(f"{s.filename}: {e}")
            for w in warnings:
                print(f"  warning {s.filename}: {w}")
            print(f"  {s.filename}: {'; '.join(info)}")
        if all_errors and strict:
            raise GeometryError("geometry errors:\n  " + "\n  ".join(all_errors))

        targets = [s.filename for s in sheets]
        man_path, manifest = self._guard(targets, force)
        self._patch_project()

        pwr = iter(range(1, 100000))
        written = []
        for s in sheets:
            if center:
                s.center_on_page()
            root_uuid = None if s is self.root else self.root.uuid
            text = _emit(s, self.name, self.title_block, root_uuid, pwr)
            path = os.path.join(self.project_dir, s.filename)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            manifest[s.filename] = self._hash(path)
            ux, uy = s.utilization()
            written.append(path)
            print(f"  wrote {s.filename:32s} {s.paper:8s} fill {ux:4.0%} x {uy:4.0%}")
            if s.title_block_overlap():
                print(f"  warning {s.filename}: drawing reaches into the title-block "
                      f"corner -- check the render, or use a larger paper")
        json.dump(manifest, open(man_path, "w"), indent=2)
        if native_check:
            self.check_native()
        return written

    def check_native(self, quiet=False):
        """Prove the written sheets are what KiCad 10 itself would save.

        Copies every sheet to a temp folder, lets `kicad-cli sch upgrade`
        rewrite the copies, and compares structure token by token (whitespace
        ignored). The project files are never touched. Returns
        {filename: first difference} for sheets that differ."""
        cli = _cli(self.cli)
        tmp = tempfile.mkdtemp(prefix="schlib-native-")
        problems = {}
        try:
            # without the project file KiCad blanks the instance project names
            pro = os.path.join(self.project_dir, f"{self.name}.kicad_pro")
            if os.path.exists(pro):
                shutil.copy2(pro, tmp)
            for s in self.all_sheets():
                src = os.path.join(self.project_dir, s.filename)
                dst = os.path.join(tmp, s.filename)
                shutil.copy2(src, dst)
                subprocess.run([cli, "sch", "upgrade", "--force", dst], capture_output=True, text=True)
                ours = parse_sexp(open(src, encoding="utf-8").read())
                theirs = parse_sexp(open(dst, encoding="utf-8").read())
                d = _tree_diff(ours, theirs)
                if d:
                    problems[s.filename] = d
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if not quiet:
            if problems:
                print(f"  native format: {len(problems)} sheet(s) differ from KiCad {GENERATOR_VERSION}'s own save:")
                for f, d in problems.items():
                    print(f"    {f}: {d}")
            else:
                print(f"  native format: all {len(self.all_sheets())} sheets match KiCad {GENERATOR_VERSION}'s own save")
        return problems

    # ---- verification ----------------------------------------------------
    def root_path(self):
        return os.path.join(self.project_dir, self.root.filename)

    def verify(self, nets, no_connect=(), quiet=False):
        ok, lines = verify_netlist(self.root_path(), nets, no_connect, self.cli)
        if not quiet:
            print("\n".join(lines))
        return ok

    def erc(self, quiet=False):
        res = run_erc(self.root_path(), self.cli)
        if not quiet:
            print(f"  ERC: {res['errors']} error(s), {res['warnings']} warning(s)")
            for (sev, typ), n in sorted(res["by_type"].items()):
                print(f"    {n:4d}  {sev:8s} {typ}")
        return res

    def render(self, outdir):
        return render(self.root_path(), outdir, self.cli)

    def check_text(self, quiet=False):
        """Render every sheet and report text KiCad drew sideways, or on top of
        a part or a wire (see text_collisions). Cheaper and more reliable than
        spotting it in screenshots -- but still look at the render."""
        tmp = tempfile.mkdtemp(prefix="schlib-text-")
        problems, skipped = [], []
        try:
            pages = render(self.root_path(), tmp, self.cli)
            by_title = {_sanitize_sheet_label(s.title): s for s in self.children}
            for path, label in pages:
                sheet = self.root if label == "root" else by_title.get(label)
                if sheet is None:
                    skipped.append(label)
                    continue
                problems += [f"{sheet.filename}: {p}" for p in text_collisions(sheet, path)]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if not quiet:
            print(f"  text check: {len(problems)} problem(s)")
            for p in problems:
                print("    " + p)
            if skipped:
                print(f"    (could not match rendered pages {skipped} to sheets)")
        return problems


# ===========================================================================
# KiCad-backed checks
# ===========================================================================

def _tree_diff(a, b, path="kicad_sch"):
    """First structural difference between two parsed s-expressions, or None."""
    if isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            if i >= len(a) or i >= len(b):
                extra = a[i] if i < len(a) else b[i]
                who = "ours" if i < len(a) else "KiCad"
                snippet = extra if isinstance(extra, str) else "(" + " ".join(
                    x if isinstance(x, str) else "(" + str(x[0]) + " ..." for x in extra[:4]) + ")"
                return f"at {path}: only {who} has {snippet}"
            here = a[0] if a and isinstance(a[0], str) else "?"
            d = _tree_diff(a[i], b[i], f"{path}/{here}[{i}]" if i else path)
            if d:
                return d
        return None
    return None if a == b else f"at {path}: ours {a!r}, KiCad {b!r}"


def _cli(cli):
    return cli or find_kicad_cli()


def export_netlist(root_sch, cli=None):
    """{net_name: {(ref, pin)}} from KiCad's own connectivity engine."""
    fd, out = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        r = subprocess.run([_cli(cli), "sch", "export", "netlist", "--format", "kicadxml",
                            "-o", out, root_sch], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.getsize(out):
            raise RuntimeError(f"netlist export failed (KiCad could not load the "
                               f"schematic?)\n{r.stdout}\n{r.stderr}")
        nets = {}
        for net in ET.parse(out).getroot().iter("net"):
            nets[net.get("name")] = {(n.get("ref"), n.get("pin")) for n in net.findall("node")}
        return nets
    finally:
        os.remove(out)


def verify_netlist(root_sch, nets, no_connect=(), cli=None):
    """Diff KiCad's extracted netlist against the intended one.

    Nets are matched by their *set of pins*, not by name -- a different name is
    reported but isn't an error; a different grouping is. This is what catches
    a mistyped coordinate silently shorting two nets or orphaning a pin.
    Returns (ok, report_lines).
    """
    actual = export_netlist(root_sch, cli)
    actual = {n: {p for p in pins if not p[0].startswith("#")} for n, pins in actual.items()}
    actual = {n: pins for n, pins in actual.items() if pins}
    nc_drawn = {p for n, ps in actual.items() if n.startswith("unconnected-") for p in ps}
    actual = {n: ps for n, ps in actual.items() if not n.startswith("unconnected-")}

    expected = {n: {(r, str(p)) for r, p in pins} for n, pins in nets.items()}
    nc_want = {(r, str(p)) for r, p in no_connect}
    short = lambda n: n.rsplit("/", 1)[-1]  # noqa: E731  (strip sheet path)

    lines, errors, renames = [], [], []
    if nc_drawn - nc_want:
        errors.append(f"unconnected but not in NO_CONNECT: {sorted(nc_drawn - nc_want)}")
    if nc_want - nc_drawn:
        errors.append(f"in NO_CONNECT but wired to something: {sorted(nc_want - nc_drawn)}")

    by_pins = {frozenset(v): short(k) for k, v in actual.items()}
    want_by_pins = {frozenset(v): k for k, v in expected.items()}
    for pins, want in want_by_pins.items():
        if pins in by_pins:
            if by_pins[pins] != want:
                renames.append(f"{want} -> drawn as {by_pins[pins]}")
            continue
        touching = sorted({short(n) for n, ps in actual.items() if ps & pins})
        errors.append(f"net {want}: pins {sorted(pins)} land in drawn net(s) {touching or ['<none>']}")
        for n in touching:
            got = set().union(*(ps for k, ps in actual.items() if short(k) == n))
            if got - pins:
                errors.append(f"    {n} also has {sorted(got - pins)}")
            if pins - got:
                errors.append(f"    {n} is missing {sorted(pins - got)}")
    for pins, name in by_pins.items():
        if pins not in want_by_pins and not any(pins & e for e in want_by_pins):
            errors.append(f"unexpected net {name}: {sorted(pins)}")

    lines.append(f"  nets drawn: {len(actual)}   expected: {len(expected)}")
    if renames:
        lines.append("  renamed (same pins, different name -- usually fine; add a label "
                     "to keep your name):")
        lines += [f"    {r}" for r in renames]
    if errors:
        lines.append("  NETLIST MISMATCH:")
        lines += [f"    {e}" for e in errors]
    else:
        lines.append("  netlist matches the specification exactly")
    return (not errors, lines)


def run_erc(root_sch, cli=None):
    fd, out = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        subprocess.run([_cli(cli), "sch", "erc", "--format", "json", "-o", out, root_sch],
                       capture_output=True, text=True)
        data = json.load(open(out, encoding="utf-8"))
    finally:
        os.remove(out)
    by_type = defaultdict(int)
    errors = warnings = 0
    for sh in data.get("sheets", []):
        for v in sh.get("violations", []):
            sev = v.get("severity", "?")
            by_type[(sev, v.get("type", "?"))] += 1
            if sev == "error":
                errors += 1
            elif sev == "warning":
                warnings += 1
    return {"errors": errors, "warnings": warnings, "by_type": dict(by_type), "raw": data}


def text_collisions(sheet, svg_path):
    """Check reference/value, label and note text as KiCad actually drew it.

    The netlist can't see text, so this reads the exported SVG, which carries an
    invisible <text> element for every string (position, length, rotation),
    and compares each string we placed against part bodies and wires. Returns
    a list of problems: sideways text, and text lying on a body or a wire.

    KiCad wraps a rotated (vertical) label's <text> in its own
    `<g transform="rotate(deg cx cy)">` rather than rotating the <text>
    element itself, so the rotation has to be pulled from that wrapper --
    `<text>`'s own attrs never carry it. Get this wrong (or skip it, as a
    prior version of this function did) and every vertical label's box is
    computed as if it were horizontal: a thin sideways sliver near its
    anchor point instead of the tall sliver it actually occupies running
    along the wire. That both misses real overlaps along the label's true
    (vertical) extent and reports false ones against unrelated geometry that
    merely happens to sit within the wrong sideways sliver.
    """
    t = open(svg_path, encoding="utf-8").read()
    drawn = []
    pat = re.compile(r'(?:<g transform="rotate\(([-\d.]+)\s+([-\d.]+)[, ]+([-\d.]+)\)">\s*)?'
                      r"<text\b([^>]*)>([^<]*)</text>")
    for rdeg, rcx, rcy, attrs, body in pat.findall(t):
        g = dict(re.findall(r'([\w-]+)="([^"]*)"', attrs))
        try:
            x, y = float(g["x"]), float(g["y"])
            w, fs = float(g.get("textLength", 0)), float(g.get("font-size", 1.27))
        except (KeyError, ValueError):
            continue
        anchor = g.get("text-anchor", "start")
        x0 = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
        has_rotate = bool(rdeg)
        if has_rotate:
            # Box in the text's own unrotated frame, then rotate its corners
            # the same way the wrapping <g> rotates the glyphs.
            deg, cx, cy = float(rdeg), float(rcx), float(rcy)
            corners = [(x0, y - fs * 0.8), (x0 + w, y - fs * 0.8),
                       (x0, y + fs * 0.1), (x0 + w, y + fs * 0.1)]
            rc = [_rotate_point(px, py, cx, cy, deg) for px, py in corners]
            xs, ys = [p[0] for p in rc], [p[1] for p in rc]
            box = (min(xs), min(ys), max(xs), max(ys))
        else:
            box = (x0, y - fs * 0.8, x0 + w, y + fs * 0.1)
        # Two different faults, and the SVG wrapper tells them apart:
        # an odd multiple of 90 reads top-to-bottom (sideways), 180 reads
        # upside down. KiCad keeps its own field text upright, so either one
        # means we wrote the wrong field angle.
        deg_ = round(float(rdeg)) % 360 if has_rotate else 0
        orient = "sideways" if deg_ % 180 == 90 else (
            "upside down" if deg_ == 180 else None)
        drawn.append((body.strip(), box, orient, (x, y)))

    # what we placed: fields of real parts, labels, notes (first line)
    wanted = []
    # Labels first, deliberately. Each drawn string is claimed by the nearest
    # unclaimed item with the same text, and a label knows exactly where it
    # was put, while a symbol field is only located by its symbol's origin.
    # A test point valued after the net it probes ("TP1", value "LOOP_V",
    # wired to a LOOP_V label) puts the label nearer the symbol origin than
    # the symbol's own value field, so matching fields first made the value
    # steal the label's text and report it as sitting on a wire.
    for _k, name, x, y, *_ in sheet.labels:
        wanted.append((name, (x, y), "label"))
    for s in sheet.symbols:
        if not s["power"]:
            wanted.append((s["ref"], s, "reference"))
            wanted.append((s["value"], s, "value"))
    for content, x, y, *_ in sheet.texts:
        wanted.append((content.split("\n")[0], (x, y), "note"))

    bodies = [(s["ref"], sheet.body_bbox(s)) for s in sheet.symbols if not s["power"]]

    def hits(a, b, pad=0.15):
        return a[0] < b[2] - pad and a[2] > b[0] + pad and a[1] < b[3] - pad and a[3] > b[1] + pad

    problems = []
    used = set()
    for text, owner, kind in wanted:
        if not text:
            continue
        if isinstance(owner, dict):
            ox, oy = owner["x"], owner["y"]
        else:
            ox, oy = owner
        best, bd = None, 1e9
        for i, (body, box, rot, (tx, ty)) in enumerate(drawn):
            if body == text and i not in used:
                d = (tx - ox) ** 2 + (ty - oy) ** 2
                if d < bd:
                    best, bd = i, d
        if best is None or bd > 30 ** 2:
            continue
        used.add(best)
        _b, box, rot, _xy = drawn[best]
        who = f"{kind} '{text}'" + (f" of {owner['ref']}" if isinstance(owner, dict) else "")
        if rot and kind in ("reference", "value"):
            problems.append(f"{who} is drawn {rot}")
        for ref, bb in bodies:
            if hits(box, bb):
                problems.append(f"{who} overlaps {ref}'s body")
        for x1, y1, x2, y2 in sheet.segments:
            seg = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
            seg = (seg[0] - 0.01, seg[1] - 0.01, seg[2] + 0.01, seg[3] + 0.01)
            if kind == "label" and _on_segment(owner, (x1, y1, x2, y2)):
                continue       # a label sits on its own wire by design
            if hits(box, seg, pad=0.0):
                problems.append(f"{who} lies on a wire at ({fmt(x1)}, {fmt(y1)})-({fmt(x2)}, {fmt(y2)})")
                break
    return sorted(set(problems))


def _sanitize_sheet_label(title):
    """Match kicad-cli's filename sanitization for a sheet title, so a title
    that isn't filesystem-safe (e.g. "Power / Reset Control", a legitimate
    sheet name) can still be matched back from the exported SVG's filename,
    where kicad-cli has already replaced each such character with "_"."""
    for ch in '\\/:*?"<>|':
        title = title.replace(ch, "_")
    return title


def render(root_sch, outdir, cli=None):
    """Export every page as SVG (short names p1.svg, p2.svg...) plus one PDF,
    and drop a pan/zoom viewer (view.html) next to them."""
    os.makedirs(outdir, exist_ok=True)
    for f in glob.glob(os.path.join(outdir, "*.svg")):
        os.remove(f)
    tmp = tempfile.mkdtemp()
    try:
        subprocess.run([_cli(cli), "sch", "export", "svg", "-o", tmp, root_sch],
                       capture_output=True, text=True)
        base = os.path.splitext(os.path.basename(root_sch))[0]
        files = sorted(glob.glob(os.path.join(tmp, "*.svg")), key=os.path.getmtime)
        files.sort(key=lambda f: os.path.basename(f) != f"{base}.svg")   # root first
        pages = []
        for i, f in enumerate(files, 1):
            dst = os.path.join(outdir, f"p{i}.svg")
            shutil.move(f, dst)
            label = os.path.basename(f)[len(base):].lstrip("-")[:-4] or "root"
            pages.append((dst, label))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    subprocess.run([_cli(cli), "sch", "export", "pdf", "-o",
                    os.path.join(outdir, "schematic.pdf"), root_sch],
                   capture_output=True, text=True)
    viewer = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "view.html")
    if os.path.exists(viewer):
        shutil.copy(viewer, os.path.join(outdir, "view.html"))
    with open(os.path.join(outdir, "pages.txt"), "w", encoding="utf-8") as f:
        for dst, label in pages:
            f.write(f"{os.path.basename(dst)}\t{label}\n")
    return pages
