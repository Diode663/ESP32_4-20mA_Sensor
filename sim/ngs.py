"""Minimal ctypes driver for KiCad's bundled ngspice.dll."""
import ctypes, os, sys
from ctypes import c_int, c_char_p, c_void_p, c_bool, CFUNCTYPE, POINTER, Structure, c_double
BIN = r"C:\Program Files\KiCad\10.0\bin"
os.add_dll_directory(BIN)
os.environ["PATH"] = BIN + ";" + os.environ["PATH"]
lib = ctypes.CDLL(os.path.join(BIN, "ngspice.dll"))
OUT = []
@CFUNCTYPE(c_int, c_char_p, c_int, c_void_p)
def _send(s, i, p):
    OUT.append(s.decode(errors="replace")); return 0
@CFUNCTYPE(c_int, c_char_p, c_int, c_void_p)
def _stat(s, i, p): return 0
@CFUNCTYPE(c_int, c_int, c_bool, c_bool, c_int, c_void_p)
def _exit(a, b, c, d, p): return 0
lib.ngSpice_Init(_send, _stat, _exit, None, None, None, None)
class ngcomplex(Structure): _fields_ = [("re", c_double), ("im", c_double)]
class vector_info(Structure):
    _fields_ = [("v_name", c_char_p), ("v_type", c_int), ("v_flags", ctypes.c_short),
                ("v_realdata", POINTER(c_double)), ("v_compdata", POINTER(ngcomplex)), ("v_length", c_int)]
lib.ngGet_Vec_Info.restype = POINTER(vector_info)
lib.ngSpice_Circ.argtypes = [POINTER(c_char_p)]
def cmd(s): return lib.ngSpice_Command(s.encode())
def circ(text):
    lines = [l.encode() for l in text.strip().splitlines()] + [None]
    arr = (c_char_p * len(lines))(*lines)
    return lib.ngSpice_Circ(arr)
def vec(name):
    p = lib.ngGet_Vec_Info(name.encode())
    if not p: raise KeyError(name)
    v = p.contents
    return [v.v_realdata[i] for i in range(v.v_length)]
