# Limiter simulations (ngspice)

KiCad ships ngspice as a DLL; `ngs.py` drives it through ctypes, so no separate
simulator install is needed. Run each script with KiCad's Python:

    "C:\Program Files\KiCad\10.0\bin\python.exe" sim\1_limiter_iv_curve.py

| Script | Shows |
|---|---|
| `1_limiter_iv_curve.py` | Current the Rev F foldback limiter can deliver vs. output voltage, -20..85 C |
| `start.py` | Cold power-up into a 2-wire transmitter (works: LOOP_V tracks the rail up) |
| `recover.py` | Short removed / transmitter hot-plugged with the rail already at 24 V (locks up) |
| `3_proposed_fix.py` | Constant-current limiter (R19 removed, R16 18 ohm): limit vs. temperature, recovery |
| `4_reverse_conduction.py` | LOOP_V driven above the rail: Q1 conducts backwards long before D3 breaks down |
| `5_firmware_recovery.py` | A stuck Rev F loop released by pulsing MT_EN low |
| `6_rev_g_limiter.py` | Rev G as built: limit and terminal voltage vs. temperature with worst-case hFE, and zero reverse current with D4 |
| `7_usb_inrush.py` | Capacitance VBUS sees at attach, Rev F vs. the Rev G load switch (and why C12 is gate-to-source) |

Q1/Q2 use the Fairchild 2N5401/MMBT5401 Gummel-Poon model. The transmitter is
modelled generously -- zero current below its lift-off voltage, then whatever
it can get through 50 ohm up to its set point. A real transmitter draws
quiescent current below lift-off, which makes the lock-up worse, not better.
