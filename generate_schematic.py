#!/usr/bin/env python3
"""Generates the ESP32 4-20 mA ESPHome board schematic: one sheet.

The design is small enough (~50 parts) that hierarchy only adds page-flipping,
so it is one sheet of titled blocks, ONE BLOCK PER CIRCUIT, in signal order:

    USB-C input & ESD  ->  3.3 V regulator  ->  ESP32-S3 module
    24 V boost converter  ->  loop current limiter  ->  loop terminal & measurement
    test points, sheet notes

A block is a whole circuit -- the boost converter with its load switch, input
and output, not three boxes for the three of them; the module with its reset,
boot, pull-ups and decoupling, not "module" and "support". That is how the
reference sheets for these parts are drawn (Adafruit's ESP32-S3 Feather:
"POWER AND FILTERING", "USB TO SERIAL CONVERTER", "LIPO CHARGING", and the
module with everything that serves it in one region).

Each block is drawn in its own working coordinates inside s.block_start() /
s.block_end(). schlib derives the outline from what is inside -- parts, field
text, labels, notes -- plus a margin, and arrange() flows the blocks across the
page, so an outline can never cut through a label and no rectangle is typed by
hand. check_text() then reads KiCad's own render and fails on any string that
touches an outline. Blocks connect by net name: rails through power ports,
signals through net labels.

    python generate_schematic.py [--force]

Edit this script, not the .kicad_sch -- it is regenerated. schlib.py is the
builder (copied from the kicad-schematic-layout skill). write() refuses to
overwrite a sheet that was changed in KiCad since the last run; port those
edits here, then rerun with --force.
"""
import argparse
import os
import sys

PROJDIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJDIR)
from schlib import Design, snap  # noqa: E402

REV = "G"
DATE = "2026-09-20"
LIB = "esp32_4to20ma_lib"
ROOT_FILE = "esp32-4to20ma-board.kicad_sch"


def fp(name):
    return f"{LIB}:{name}"


# ---------------------------------------------------------------------------
# Bill of materials: ref -> (lib_id, value, footprint, LCSC, manufacturer, MPN)
# ---------------------------------------------------------------------------
TP_FP = "TestPoint:TestPoint_Pad_D1.0mm"

PARTS = {
    # The -1U: U.FL connector, no PCB antenna. Same symbol, same pins, and --
    # per Espressif's own land-pattern figures -- the same pads, so the board
    # is untouched. To go back to the PCB-antenna module, restore this line:
    #   fp("WIFIM-SMD_ESP32-S3-WROOM-1-N8"), "C2913197", "Espressif", "ESP32-S3-WROOM-1-N4"
    # The board outline, the antenna overhang and the mounting holes are all
    # still laid out for it.
    "U1":  (f"{LIB}:ESP32-S3-WROOM-1-N4", "ESP32-S3-WROOM-1U-N4",
            fp("WIFIM-SMD_ESP32-S3-WROOM-1U"), "C2980296", "Espressif", "ESP32-S3-WROOM-1U-N4"),
    "U3":  (f"{LIB}:INA226AIDGSR", "INA226AIDGSR",
            fp("MSOP-10_L3.0-W3.0-P0.50-LS5.0-BL"), "C49851", "Texas Instruments", "INA226AIDGSR"),
    "U4":  (f"{LIB}:AP2112K-3.3TRG1", "AP2112K-3.3",
            fp("SOT-25-5_L2.9-W1.6-P0.95-LS2.8-BL"), "C51118", "Diodes Inc", "AP2112K-3.3TRG1"),
    "U5":  (f"{LIB}:MT3608", "MT3608",
            fp("SOT-23-6_L2.9-W1.6-P0.95-LS2.8-BL"), "C84817", "Aerosemi", "MT3608"),
    "J1":  (f"{LIB}:TYPE-C16PIN2MD", "USB-C Receptacle",
            fp("USB-C-SMD_TYPE-C-16PIN-2MD-073"), "C2765186", "SHOU HAN", "TYPE-C 16PIN 2MD(073)"),
    # One-piece push-in spring terminal (WAGO-250 style): a solid or ferruled
    # wire pushes straight in, the button releases it or opens it for bare
    # stranded. Three pins: GND, mA in, +24 V out. The ground pin is what lets
    # a 3-wire or self-powered (sourcing) transmitter be connected at all.
    # Numbered from the left looking into the wire entry, which puts +24 V on
    # the right under the limiter and GND on the left beside D5's anode.
    "J2":  (f"{LIB}:KF250NH-5.0-3P", "4-20mA Loop",
            fp("CONN-TH_KF250NH-5.0-3P"), "C976567", "Cixi Kefa", "KF250NH-5.0-3P"),
    "D1":  (f"{LIB}:USBLC6-2SC6_C2687116", "USBLC6-2SC6",
            fp("SOT-23-6_L2.9-W1.6-P0.95-LS2.8-BL"), "C2687116", "UMW", "USBLC6-2SC6"),
    "D2":  (f"{LIB}:SS34_C8678", "SS34",
            fp("SMA_L4.3-W2.6-LS5.2-RD"), "C8678", "MDD", "SS34"),
    # Both TVS parts share the project's unidirectional TVS symbol (1 = K, 2 = A).
    "D3":  (f"{LIB}:SMAJ36A_C113967", "SMAJ28A",
            fp("SMA_L4.3-W2.6-LS5.2-RD"), "C353458", "Jingdao Microelectronics", "SMAJ28A"),
    "D5":  (f"{LIB}:SMAJ36A_C113967", "SMAJ12A",
            fp("SMA_L4.3-W2.6-LS5.2-RD"), "C113957", "MDD", "SMAJ12A"),
    # Blocks LOOP_V from driving Q1 backwards into the 24 V rail. Deliberately
    # not a Schottky: it sees D3's clamp minus the rail in reverse.
    "D4":  ("Diode:1N4148W", "1N4148W",
            "Diode_SMD:D_SOD-123", "C81598", "ST (Semtech)", "1N4148W"),
    "SW1": (f"{LIB}:KH-6X6X5H-STM", "RESET",
            fp("SW-SMD_4P-L6.0-W6.0-P4.50-LS9.0_H5.0"), "C2837531", "Kinghelm", "KH-6X6X5H-STM"),
    "SW2": (f"{LIB}:KH-6X6X5H-STM", "BOOT",
            fp("SW-SMD_4P-L6.0-W6.0-P4.50-LS9.0_H5.0"), "C2837531", "Kinghelm", "KH-6X6X5H-STM"),
    # 22 uH, the top of the MT3608's 4.7-22 uH range: at ~0.17 A average input
    # it quarters the ripple current of the old 4.7 uH. Isat 1.2 A.
    "L1":  (f"{LIB}:FNR4030S4R7MT", "22uH",
            fp("IND-SMD_L4.0-W4.0_FNR40XXS"), "C167883", "cjiang", "FNR4030S220MT"),

    "R1":  ("Device:R", "10k",   "Resistor_SMD:R_0402_1005Metric", "C25744", "Uniroyal", "0402WGF1002TCE"),
    "R5":  ("Device:R", "4.7k",  "Resistor_SMD:R_0402_1005Metric", "C25900", "Uniroyal", "0402WGF4701TCE"),
    "R6":  ("Device:R", "4.7k",  "Resistor_SMD:R_0402_1005Metric", "C25900", "Uniroyal", "0402WGF4701TCE"),
    "R7":  ("Device:R", "5.1k",  "Resistor_SMD:R_0402_1005Metric", "C25905", "Uniroyal", "0402WGF5101TCE"),
    "R8":  ("Device:R", "5.1k",  "Resistor_SMD:R_0402_1005Metric", "C25905", "Uniroyal", "0402WGF5101TCE"),
    "R9":  ("Device:R", "330",   "Resistor_SMD:R_0402_1005Metric", "C25104", "Uniroyal", "0402WGF3300TCE"),
    "R10": ("Device:R", "390k",  "Resistor_SMD:R_0402_1005Metric", "C2909352", "FOJAN", "FRC0402F3903TS"),   # C25782 had 14 in stock
    "R11": ("Device:R", "10k",   "Resistor_SMD:R_0402_1005Metric", "C25744", "Uniroyal", "0402WGF1002TCE"),
    "R12": ("Device:R", "3.32",  "Resistor_SMD:R_0805_2012Metric", "C3013220", "FOJAN", "FRC0805F3R32TS"),
    "R13": ("Device:R", "10",    "Resistor_SMD:R_0402_1005Metric", "C25077", "Uniroyal", "0402WGF100JTCE"),
    "R14": ("Device:R", "10",    "Resistor_SMD:R_0402_1005Metric", "C25077", "Uniroyal", "0402WGF100JTCE"),
    "R15": ("Device:R", "100k",  "Resistor_SMD:R_0402_1005Metric", "C25741", "Uniroyal", "0402WGF1003TCE"),
    # --- current limiter on the 24 V loop feed (R19, the foldback, is gone) ---
    "R16": ("Device:R", "18",    "Resistor_SMD:R_0402_1005Metric", "C138043", "Yageo", "RC0402FR-0718RL"),
    "R17": ("Device:R", "47k",   "Resistor_SMD:R_0402_1005Metric", "C25792", "Uniroyal", "0402WGF4702TCE"),
    "R18": ("Device:R", "1k",    "Resistor_SMD:R_0402_1005Metric", "C11702", "Uniroyal", "0402WGF1001TCE"),
    # Series protection for the INA226 bus-voltage pin -- see the note on
    # sheet 4. Same part as R1/R11, so it adds no BOM line.
    "R20": ("Device:R", "10k",   "Resistor_SMD:R_0402_1005Metric", "C25744", "Uniroyal", "0402WGF1002TCE"),
    # --- soft-start load switch ahead of the boost ---
    "Q3":  ("Transistor_FET:AO3401A", "AO3401A",
            "Package_TO_SOT_SMD:SOT-23", "C15127", "Alpha & Omega", "AO3401A"),
    "Q4":  ("Transistor_FET:2N7002", "2N7002",
            "Package_TO_SOT_SMD:SOT-23", "C8545", "JSCJ", "2N7002"),
    "R21": ("Device:R", "390k",  "Resistor_SMD:R_0402_1005Metric", "C2909352", "FOJAN", "FRC0402F3903TS"),
    "R22": ("Device:R", "100k",  "Resistor_SMD:R_0402_1005Metric", "C25741", "Uniroyal", "0402WGF1003TCE"),
    "C12": ("Device:C", "100nF",    "Capacitor_SMD:C_0402_1005Metric", "C1525",  "Samsung Electro-Mechanics", "CL05B104KO5NNNC"),
    # Q1 is SOT-223 because a constant-current limiter puts the whole rail
    # across it in a short: 24 V x 35 mA = 0.85 W. hFE >= 100 against 0.5 mA of
    # base drive from R17 supports 50 mA. Pins: 1 B, 2 and 4 (tab) C, 3 E.
    "Q1":  ("Transistor_BJT:BCP53", "BCP53-16",
            "Package_TO_SOT_SMD:SOT-223", "C148109", "JSCJ", "BCP53-16"),
    # C8326 is LCSC's hFE 200-300 bin of the MMBT5401, a JLCPCB basic part.
    "Q2":  ("Transistor_BJT:Q_PNP_BEC", "MMBT5401",
            "Package_TO_SOT_SMD:SOT-23", "C8326", "JSCJ", "MMBT5401"),

    "C1":  ("Device:C", "1uF",      "Capacitor_SMD:C_0402_1005Metric", "C52923", "Samsung Electro-Mechanics", "CL05A105KA5NQNC"),
    "C2":  ("Device:C", "22uF",     "Capacitor_SMD:C_0805_2012Metric", "C45783", "Samsung Electro-Mechanics", "CL21A226MAQNNNE"),
    "C3":  ("Device:C", "100nF",    "Capacitor_SMD:C_0402_1005Metric", "C1525",  "Samsung Electro-Mechanics", "CL05B104KO5NNNC"),
    "C6":  ("Device:C", "1uF",      "Capacitor_SMD:C_0402_1005Metric", "C52923", "Samsung Electro-Mechanics", "CL05A105KA5NQNC"),
    "C7":  ("Device:C", "10uF",     "Capacitor_SMD:C_0603_1608Metric", "C19702", "Samsung Electro-Mechanics", "CL10A106KP8NNNC"),
    "C8":  ("Device:C", "100nF",    "Capacitor_SMD:C_0402_1005Metric", "C1525",  "Samsung Electro-Mechanics", "CL05B104KO5NNNC"),
    "C9":  ("Device:C", "100nF",    "Capacitor_SMD:C_0402_1005Metric", "C1525",  "Samsung Electro-Mechanics", "CL05B104KO5NNNC"),
    "C10": ("Device:C", "10uF/50V", "Capacitor_SMD:C_1210_3225Metric", "C2918502", "Samwha", "CS3225X7R106K500NRL"),
    "C11": ("Device:C", "10uF/50V", "Capacitor_SMD:C_1210_3225Metric", "C2918502", "Samwha", "CS3225X7R106K500NRL"),

    "LED1": ("Device:LED", "Power", "LED_SMD:LED_0805_2012Metric", "C84256", "Nationstar", "NCD0805R1"),

    # Bare copper, not purchased parts: LCSC None marks them out of the BOM.
    # The value is the net, so the fab drawing and the board both name it.
    "TP1": ("Connector:TestPoint", "LOOP_V",   TP_FP, None, None, None),
    "TP2": ("Connector:TestPoint", "LOOP_RTN", TP_FP, None, None, None),
    "TP3": ("Connector:TestPoint", "+24V",     TP_FP, None, None, None),
    "TP4": ("Connector:TestPoint", "+3V3",     TP_FP, None, None, None),
    "TP5": ("Connector:TestPoint", "MT_EN",    TP_FP, None, None, None),
}


def put(sheet, ref, x, y, rot=0, mirror=None):
    lib_id, value, footprint, lcsc, mfr, mpn = PARTS[ref]
    if lcsc is None:
        # a pad, not a part: nothing to order, so keep it out of the BOM
        sheet.place(ref, lib_id, value, x, y, rot, mirror,
                    props={"Footprint": footprint}, in_bom=False)
        return
    sheet.place(ref, lib_id, value, x, y, rot, mirror, props={
        "Footprint": footprint,
        "Datasheet": f"https://www.lcsc.com/product-detail/{lcsc}.html",
        "LCSC": lcsc,
        "Manufacturer": mfr,
        "MPN": mpn,
    })


# ---------------------------------------------------------------------------
# Intended netlist -- the specification the drawn sheets must reproduce.
# verify_schematic.py diffs KiCad's own extracted netlist against this.
# ---------------------------------------------------------------------------
NETS = {
    "GND": [
        ("U1", "1"), ("U1", "40"), ("U1", "41"),
        ("U3", "1"), ("U3", "2"), ("U3", "7"),
        ("U4", "2"), ("U5", "2"),
        ("J1", "A1B12"), ("J1", "B1A12"), ("J1", "13"), ("J1", "14"),
        ("D1", "2"),
        ("SW1", "2"), ("SW1", "4"), ("SW2", "2"), ("SW2", "4"),
        ("LED1", "1"),
        ("C1", "2"), ("C2", "2"), ("C3", "2"), ("C6", "2"), ("C7", "2"),
        ("C8", "2"), ("C10", "2"), ("C11", "2"),
        ("R7", "2"), ("R8", "2"), ("R11", "2"), ("R12", "2"), ("R14", "1"),
        ("R17", "2"), ("Q4", "2"), ("D3", "2"), ("D5", "2"), ("J2", "1"),
    ],
    "+3V3": [
        ("U1", "2"), ("U3", "6"), ("U4", "5"),
        ("R1", "1"), ("R5", "1"), ("R6", "1"), ("R9", "1"), ("R15", "1"),
        ("C2", "1"), ("C3", "1"), ("C7", "1"), ("C8", "1"), ("TP4", "1"),
    ],
    "+5V": [
        ("U4", "1"), ("U4", "3"),
        ("J1", "A4B9"), ("J1", "B4A9"), ("D1", "5"), ("C6", "1"),
        ("Q3", "2"), ("R21", "1"), ("C12", "1"),
    ],
    # Everything the boost hangs on VBUS sits behind Q3, so a USB host sees
    # only C6 (1 uF) at attach. U5's EN rides on its own input.
    "VIN_SW":  [("Q3", "3"), ("U5", "5"), ("U5", "4"), ("L1", "1"), ("C10", "1")],
    "SW_GATE": [("Q3", "1"), ("R21", "2"), ("C12", "2"), ("R22", "1")],
    "SW_PD":   [("R22", "2"), ("Q4", "3")],
    # The rail now stops at the limiter; everything downstream is LOOP_V.
    "+24V": [
        ("D2", "1"), ("C11", "1"), ("R10", "1"), ("R16", "1"), ("Q2", "2"),
        ("TP3", "1"),
    ],
    "LOOP_SNS": [("R16", "2"), ("Q1", "3"), ("R18", "1")],
    "LOOP_DRV": [("Q1", "1"), ("Q2", "3"), ("R17", "1")],
    "LOOP_FB":  [("Q2", "1"), ("R18", "2")],
    "LOOP_C":   [("Q1", "2"), ("Q1", "4"), ("D4", "2")],
    "LOOP_V":   [("D4", "1"), ("J2", "3"), ("D3", "1"), ("R20", "1"), ("TP1", "1")],
    "INA_VBUS": [("R20", "2"), ("U3", "8")],
    "USB_P":   [("J1", "A6"), ("J1", "B6"), ("D1", "1"), ("D1", "6"), ("U1", "14")],
    "USB_N":   [("J1", "A7"), ("J1", "B7"), ("D1", "3"), ("D1", "4"), ("U1", "13")],
    "CC1":      [("J1", "A5"), ("R7", "1")],
    "CC2":      [("J1", "B5"), ("R8", "1")],
    "EN":       [("U1", "3"), ("R1", "2"), ("SW1", "1"), ("SW1", "3"), ("C1", "1")],
    "IO0":      [("U1", "27"), ("SW2", "1"), ("SW2", "3")],
    "I2C_SDA":  [("U1", "12"), ("U3", "4"), ("R5", "2")],
    "I2C_SCL":  [("U1", "17"), ("U3", "5"), ("R6", "2")],
    "MT_SW":    [("U5", "1"), ("L1", "2"), ("D2", "2")],
    "LOOP_RTN": [("J2", "2"), ("R12", "1"), ("R13", "1"), ("D5", "1"), ("TP2", "1")],
    "INA_INP":  [("R13", "2"), ("U3", "10"), ("C9", "1")],
    "INA_INN":  [("R14", "2"), ("U3", "9"), ("C9", "2")],
    "MT_FB":    [("U5", "3"), ("R10", "2"), ("R11", "1")],
    "MT_EN":    [("U1", "18"), ("Q4", "1"), ("R15", "2"), ("TP5", "1")],
    "LED_A":    [("R9", "2"), ("LED1", "2")],
}

NO_CONNECT = [
    # Unused ESP32-S3 GPIOs. Native USB replaces UART0 for flashing and logging,
    # so U0RXD/U0TXD are deliberately left unconnected too.
    ("U1", n) for n in [
        "4", "5", "6", "7", "8", "9", "10", "11", "15", "16", "19", "20",
        "21", "22", "23", "24", "25", "26", "28", "29", "30", "31", "32", "33",
        "34", "35", "36", "37", "38", "39"]
] + [("U3", "3"), ("U4", "4"), ("U5", "6"), ("J1", "A8"), ("J1", "B8")]


# ===========================================================================
# Sheet 1 -- USB-C input, ESD protection, 3.3 V regulation, power LED
# ===========================================================================
def build_usb_power(s):
    s.block_start("USB-C INPUT & ESD PROTECTION")

    # ---- USB-C receptacle -------------------------------------------------
    put(s, "J1", 45.72, 67.31, 180)

    # Both signal grounds and both shell tabs collect onto a rail down the left
    # side of the connector, ending in a single ground port at the bottom.
    s.wire(s.pin("J1", "B1A12"), (52.07, 48.26), (27.94, 48.26))
    # The bottom ground route runs a clear 7.6 mm below the connector body so
    # J1's reference and value have room underneath it -- the connector is
    # otherwise walled in by wires on all four sides.
    s.wire((27.94, 48.26), (27.94, 93.98))
    s.wire(s.pin("J1", "14"), (27.94, 53.34))
    s.wire(s.pin("J1", "13"), (27.94, 81.28))
    s.wire(s.pin("J1", "A1B12"), (57.15, 81.28), (57.15, 91.44), (27.94, 91.44))
    s.gnd(27.94, 93.98)
    # GND and +5V originate at this connector, so the ERC power-source flags
    # for both rails belong here.
    s.wire((27.94, 93.98), (19.05, 93.98))
    s.power("PWR_FLAG", 19.05, 93.98)

    # VBUS: both pairs straight out to +5V ports.
    s.wire(s.pin("J1", "B4A9"), (60.96, 55.88), (68.58, 55.88))
    s.power("+5V", 60.96, 55.88)
    s.power("PWR_FLAG", 68.58, 55.88)
    s.wire(s.pin("J1", "A4B9"), (60.96, 78.74))
    s.power("+5V", 60.96, 78.74)

    # CC pins -> 5.1 k pulldowns (advertise UFP, sink 5 V / default current).
    s.wire(s.pin("J1", "B5"), (66.04, 58.42))
    s.label("CC2", 66.04, 58.42)
    s.wire(s.pin("J1", "A5"), (66.04, 73.66))
    s.label("CC1", 66.04, 73.66)

    put(s, "R7", 74.93, 96.52)
    put(s, "R8", 87.63, 96.52)
    s.wire(s.pin("R7", "1"), (74.93, 88.9))
    s.label("CC1", 74.93, 88.9, 90)
    s.wire(s.pin("R8", "1"), (87.63, 88.9))
    s.label("CC2", 87.63, 88.9, 90)
    s.wire(s.pin("R7", "2"), (74.93, 104.14))
    s.gnd(74.93, 104.14)
    s.wire(s.pin("R8", "2"), (87.63, 104.14))
    s.gnd(87.63, 104.14)
    s.note("CC1/CC2 pulldowns: 5.1 k = UFP,", 68.58, 111.76, 1.0)
    s.note("advertises default 500 mA USB 2.0 sink.", 68.58, 114.3, 1.0)

    # Both D+ halves and both D- halves of the reversible connector.
    for pin, y, name in (("B6", 63.5, "USB_P"), ("A7", 66.04, "USB_N"),
                         ("A6", 68.58, "USB_P"), ("B7", 71.12, "USB_N")):
        s.wire(s.pin("J1", pin), (66.04, y))
        s.label(name, 66.04, y)

    s.nc("J1", "A8", "B8")

    # ---- ESD clamp --------------------------------------------------------
    # Rotated 90 so VBUS faces up and GND down. In its native orientation GND
    # sits *between* the two data pins on the same side, so any ground wire
    # leaving it has to cross the D- line or its label. Connector-side data
    # leaves the bottom, MCU-side data the top, each turning outward.
    put(s, "D1", 99.06, 66.04, 90)
    s.stub("D1", "2", 2.54, power="GND")
    s.stub("D1", "5", 2.54, power="+5V")
    s.wire(s.pin("D1", "1"), (96.52, 82.55), (91.44, 82.55))
    s.label("USB_P", 91.44, 82.55, 180)
    s.wire(s.pin("D1", "3"), (101.6, 82.55), (106.68, 82.55))
    s.label("USB_N", 106.68, 82.55)
    s.wire(s.pin("D1", "6"), (96.52, 49.53), (91.44, 49.53))
    s.label("USB_P", 91.44, 49.53, 180)
    s.wire(s.pin("D1", "4"), (101.6, 49.53), (106.68, 49.53))
    s.label("USB_N", 106.68, 49.53)
    s.note("D1 ESD clamp\n15 kV air /\n8 kV contact\n(IEC 61000-4-2)", 105.41, 60.96, 1.0)

    s.block_end()

    # ---- 3.3 V LDO --------------------------------------------------------
    s.block_start("3.3 V REGULATOR & POWER LED")
    put(s, "U4", 152.4, 66.04)
    put(s, "C6", 133.35, 69.85)      # 5 V input cap
    put(s, "C7", 187.96, 69.85)      # 3.3 V output cap

    # 5 V rail into VIN, with the input cap hanging off it.
    s.wire(s.pin("U4", "1"), (128.27, 63.5))
    s.wire((128.27, 63.5), (128.27, 57.15))
    s.power("+5V", 128.27, 57.15)
    s.wire(s.pin("C6", "1"), (133.35, 63.5))
    s.wire(s.pin("C6", "2"), (133.35, 77.47))
    s.gnd(133.35, 77.47)

    # EN tied high -- the LDO has no shutdown control on this board.
    s.wire(s.pin("U4", "3"), (137.16, 68.58))
    s.power("+5V", 137.16, 68.58)
    s.wire(s.pin("U4", "2"), (135.89, 66.04), (135.89, 82.55))
    s.gnd(135.89, 82.55)
    s.nc("U4", "4")

    # 3.3 V output rail.
    s.wire(s.pin("U4", "5"), (196.85, 63.5))
    s.wire(s.pin("C7", "1"), (187.96, 63.5))
    s.wire(s.pin("C7", "2"), (187.96, 77.47))
    s.gnd(187.96, 77.47)
    s.wire((196.85, 63.5), (196.85, 57.15))
    s.power("+3V3", 196.85, 57.15)
    s.wire((191.77, 63.5), (191.77, 55.88))
    s.power("PWR_FLAG", 191.77, 55.88)
    s.note("AP2112K-3.3: 600 mA LDO, 250 mV dropout.", 124.46, 92.71, 1.0)
    s.note("Worst-case dissipation (5 V in, 3.3 V out, 300 mA)", 124.46, 95.25, 1.0)
    s.note("= 0.51 W -- well inside SOT-25 on 2 oz copper.", 124.46, 97.79, 1.0)

    # ---- Power-on LED -----------------------------------------------------
    # Sits under the regulator rather than beside it, so the sheet stays a
    # sensible shape instead of running off to the right.
    put(s, "R9", 140.97, 119.38)
    put(s, "LED1", 140.97, 133.35, 90)  # anode up (from R9), cathode down to GND
    s.wire(s.pin("R9", "1"), (140.97, 111.76))
    s.power("+3V3", 140.97, 111.76)
    s.wire(s.pin("R9", "2"), s.pin("LED1", "2"))
    # horizontal: a vertical label here runs straight up through R9's body
    s.label("LED_A", 140.97, 125.73)
    s.wire(s.pin("LED1", "1"), (140.97, 140.97))
    s.gnd(140.97, 140.97)
    s.note("Power LED: (3.3 - 1.9) / 330 = 4.2 mA", 149.86, 130.81, 1.0)

    s.block_end()


# ===========================================================================
# Sheet 2 -- ESP32-S3 module, reset & boot, I2C pull-ups
# ===========================================================================
def build_mcu(s):
    # Native-USB ESP32-S3-WROOM-1U-N4 (U.FL antenna); no UART bridge required
    s.block_start("ESP32-S3 MODULE  -  reset, boot, I2C pull-ups, decoupling")

    put(s, "U1", 152.4, 96.52)

    # ---- Module grounds ---------------------------------------------------
    # Pins 1, 40 and the exposed pad (41) are all at the top of the symbol;
    # they join a bus above the module that runs down the unused right flank
    # to a single ground port at the bottom.
    s.wire(s.pin("U1", "1"), (137.16, 73.66), (137.16, 63.5))
    s.wire((137.16, 63.5), (177.8, 63.5))
    s.wire(s.pin("U1", "41"), (152.4, 63.5))
    s.wire(s.pin("U1", "40"), (168.91, 73.66), (168.91, 63.5))
    s.wire((177.8, 63.5), (177.8, 124.46))
    s.gnd(177.8, 124.46)

    # ---- Module supply ----------------------------------------------------
    s.wire(s.pin("U1", "2"), (133.35, 76.2))
    s.power("+3V3", 133.35, 76.2)

    # ---- Reset: RC + pull-up + button ------------------------------------
    put(s, "R1", 114.3, 71.12)
    put(s, "C1", 104.14, 85.09)
    put(s, "SW1", 124.46, 88.9)

    s.wire(s.pin("R1", "1"), (114.3, 63.5))
    s.power("+3V3", 114.3, 63.5)
    s.wire((104.14, 78.74), s.pin("U1", "3"))          # EN node
    s.label("EN", 128.27, 78.74)
    s.wire(s.pin("R1", "2"), (114.3, 78.74))
    s.wire(s.pin("C1", "1"), (104.14, 78.74))
    s.wire(s.pin("C1", "2"), (104.14, 92.71))
    s.gnd(104.14, 92.71)
    s.wire(s.pin("SW1", "1"), (114.3, 87.63), (114.3, 78.74))
    s.wire(s.pin("SW1", "3"), (114.3, 92.71), (114.3, 87.63))
    s.wire(s.pin("SW1", "2"), (133.35, 87.63), (133.35, 96.52))
    s.wire(s.pin("SW1", "4"), (133.35, 92.71))
    s.gnd(133.35, 96.52)
    s.note("RESET: 10 k pull-up + 1 uF", 66.04, 128.27, 1.0)
    s.note("gives a ~10 ms rise on EN.", 66.04, 130.81, 1.0)

    # ---- I2C to the sense sheet, with pull-ups ---------------------------
    # SDA is IO8 (pin 12), SCL is IO9 (pin 17). Each pull-up drops to its bus
    # line at an x that clears every line running out below it.
    put(s, "R5", 88.9, 88.9)      # SDA
    put(s, "R6", 71.12, 88.9)     # SCL
    s.wire(s.pin("U1", "12"), (81.28, 101.6))
    s.label("I2C_SDA", 81.28, 101.6, 180)
    s.wire(s.pin("R5", "2"), (88.9, 101.6))
    s.wire(s.pin("R5", "1"), (88.9, 81.28))
    s.power("+3V3", 88.9, 81.28)

    s.wire(s.pin("U1", "17"), (66.04, 114.3))
    s.label("I2C_SCL", 66.04, 114.3, 180)
    s.wire(s.pin("R6", "2"), (71.12, 114.3))
    s.wire(s.pin("R6", "1"), (71.12, 81.28))
    s.power("+3V3", 71.12, 81.28)
    s.note("4.7 k pull-ups: one INA226, 400 kHz.", 66.04, 120.65, 1.0)

    # ---- Loop-supply enable ----------------------------------------------
    # IO10 (pin 18) gates the MT3608. It is not a strapping pin and has no
    # other use here. R15 on the boost sheet holds it high, so the loop
    # supply comes up with the board and firmware can switch it off.
    s.wire(s.pin("U1", "18"), (76.2, 116.84))
    s.label("MT_EN", 76.2, 116.84, 180)

    # ---- Native USB -------------------------------------------------------
    s.wire(s.pin("U1", "13"), (82.55, 104.14))
    s.label("USB_N", 82.55, 104.14, 180)
    s.wire(s.pin("U1", "14"), (82.55, 106.68))
    s.label("USB_P", 82.55, 106.68, 180)

    # ---- Boot strap button -----------------------------------------------
    put(s, "SW2", 177.8, 134.62)
    s.wire(s.pin("U1", "27"), (170.18, 106.68), (170.18, 133.35), (172.72, 133.35))
    s.label("IO0", 170.18, 106.68)
    s.wire(s.pin("SW2", "3"), (170.18, 138.43), (170.18, 133.35))
    s.wire(s.pin("SW2", "2"), (187.96, 133.35), (187.96, 142.24))
    s.wire(s.pin("SW2", "4"), (187.96, 138.43))
    s.gnd(187.96, 142.24)

    # ---- Module decoupling ------------------------------------------------
    put(s, "C2", 110.49, 128.27)
    put(s, "C3", 123.19, 128.27)
    for ref, x in (("C2", 110.49), ("C3", 123.19)):
        s.wire(s.pin(ref, "1"), (x, 120.65))
        s.power("+3V3", x, 120.65)
        s.wire(s.pin(ref, "2"), (x, 135.89))
        s.gnd(x, 135.89)
    s.note("Bulk + HF decoupling for the module;", 96.52, 143.51, 1.0)
    s.note("place C3 within 5 mm of U1 pin 2.", 96.52, 146.05, 1.0)

    # ---- Strapping-pin notes ---------------------------------------------
    s.note("STRAPPING PINS", 193.04, 71.12, 1.4, bold=True)
    s.note("IO0  (27) - internal pull-up, held high by SW2 idle.", 193.04, 76.2, 1.0)
    s.note("IO46 (16) - internal pull-down; leave floating (NC).", 193.04, 78.74, 1.0)
    s.note("IO45 (26) - VDD_SPI select; must stay low on -N4.", 193.04, 81.28, 1.0)
    s.note("            Do not add a pull-up here.", 193.04, 83.82, 1.0)
    s.note("IO3  (15) - no internal pull; JTAG source select only,", 193.04, 86.36, 1.0)
    s.note("            floating is safe with no JTAG header.", 193.04, 88.9, 1.0)
    s.note("USB: the S3's USB-Serial/JTAG block handles reset and", 193.04, 96.52, 1.0)
    s.note("bootloader entry over native USB, so no DTR/RTS", 193.04, 99.06, 1.0)
    s.note("transistor circuit is needed.", 193.04, 101.6, 1.0)

    used = {"1", "2", "3", "12", "13", "14", "17", "18", "27", "40", "41"}
    s.nc("U1", *[n for n in [str(i) for i in range(1, 42)] if n not in used])

    s.block_end()


# ===========================================================================
# Sheet 3 -- MT3608 boost converter, 5 V -> 24 V loop supply
# ===========================================================================
def build_boost(s):
    # 5 V -> 24 V @ 30 mA for the 2-wire 4-20 mA transmitter
    s.block_start("24 V BOOST CONVERTER  -  soft-start load switch, MT3608, feedback")

    put(s, "U5", 152.4, 91.44, 180)
    put(s, "L1", 127.0, 76.2)
    put(s, "D2", 177.8, 76.2, 180)
    put(s, "C10", 105.41, 83.82)
    put(s, "C11", 213.36, 83.82)   # clear of R10 side text
    put(s, "R10", 198.12, 88.9)
    put(s, "R11", 198.12, 102.87)

    # ---- 5 V input --------------------------------------------------------
    s.wire((105.41, 76.2), s.pin("L1", "1"))
    s.wire((114.3, 76.2), (114.3, 69.85))
    s.label("VIN_SW", 114.3, 69.85, 90)
    s.wire(s.pin("C10", "1"), (105.41, 76.2))
    s.wire(s.pin("C10", "2"), (105.41, 93.98))
    s.gnd(105.41, 93.98)

    s.wire(s.pin("U5", "5"), (132.08, 91.44), (132.08, 85.09))
    s.label("VIN_SW", 132.08, 85.09, 90)
    s.nc("U5", "6")

    # ---- Enable: pulled up to 3.3 V, driven low by the MCU to kill the loop.
    # MT_EN no longer reaches U5 -- it gates the load switch, and U5's own EN
    # rides on its switched input, the datasheet's automatic-start-up hookup.
    put(s, "R15", 120.65, 95.25)
    s.wire(s.pin("R15", "1"), (120.65, 87.63))
    s.power("+3V3", 120.65, 87.63)
    s.wire(s.pin("R15", "2"), (120.65, 102.87), (116.84, 102.87))
    s.label("MT_EN", 116.84, 102.87, 180)
    # EN is the top pin of this flank, so it leaves upward: going down would
    # cross the VIN wire, and going straight left would put the label text
    # on top of it.
    s.wire(s.pin("U5", "4"), (139.7, 88.9), (139.7, 78.74))
    s.label("VIN_SW", 139.7, 78.74, 180)

    # ---- Soft-start load switch ------------------------------------------
    # Q3 sits between VBUS and everything the boost hangs on it (C10, and C11
    # through L1/D2, which a boost cannot disconnect). C12 is gate-to-SOURCE so
    # the gate follows VBUS up at plug-in and Q3 stays off through the edge;
    # a gate-to-drain capacitor does the opposite (sim/7_usb_inrush.py).
    X = -15.24
    put(s, "Q3", 66.04 + X, 66.04, 270, mirror="x")   # S left, D right, G down (KiCad's canonical form)
    put(s, "R21", 58.42 + X, 76.2, 90)
    put(s, "C12", 58.42 + X, 83.82, 90)
    put(s, "R22", 76.2 + X, 76.2, 90)
    put(s, "Q4", 88.9 + X, 83.82)
    sx, sy = s.pin("Q3", "2"); dx, dy = s.pin("Q3", "3"); gx, gy = s.pin("Q3", "1")
    s.wire((50.8 + X, 55.88), (50.8 + X, 83.82))
    s.power("+5V", 50.8 + X, 55.88)
    s.wire((50.8 + X, sy), (sx, sy))
    s.wire((dx, dy), (86.36 + X, dy))
    s.label("VIN_SW", 86.36 + X, dy)
    s.wire((81.28 + X, dy), (81.28 + X, dy - 5.08))
    s.power("PWR_FLAG", 81.28 + X, dy - 5.08)
    s.wire((gx, gy), (gx, 83.82))
    s.wire((50.8 + X, 76.2), s.pin("R21", "1"))
    s.wire(s.pin("R21", "2"), (gx, 76.2))
    s.wire((50.8 + X, 83.82), s.pin("C12", "1"))
    s.wire(s.pin("C12", "2"), (gx, 83.82))
    s.label("SW_GATE", gx, 73.66, 0)
    s.wire((gx, 76.2), s.pin("R22", "1"))
    qd = s.pin("Q4", "3"); qs = s.pin("Q4", "2"); qg = s.pin("Q4", "1")
    s.wire(s.pin("R22", "2"), (qd[0], 76.2), qd)
    s.label("SW_PD", s.pin("R22", "2")[0], 76.2)
    s.wire(qs, (qs[0], 91.44))
    s.gnd(qs[0], 91.44)
    s.wire(qg, (qg[0], 93.98), (71.12 + X, 93.98))
    s.label("MT_EN", 71.12 + X, 93.98, 180)
    s.note("R21/R22 leave Vgs at -4.0 V; C12 x (R21 || R22) = 8 ms.", 43.18 + X, 101.6, 1.0)
    s.note("VBUS sees 1 uF at attach, not 27 uF (USB limit 10 uF),", 43.18 + X, 104.14, 1.0)
    s.note("and MT_EN low now truly disconnects the loop supply.", 43.18 + X, 106.68, 1.0)

    # ---- Switch node, ground and feedback --------------------------------
    # SW, GND and FB all leave the same flank of U5 in the order FB / GND / SW,
    # with GND in the middle heading down. Wiring SW up to the switch node and
    # FB across to the divider would cross GND both times, so SW and FB
    # leave as short labelled stubs and only GND is a real wire. No crossings.
    s.wire(s.pin("L1", "2"), s.pin("D2", "2"))
    s.label("MT_SW", 160.02, 76.2)
    s.stub("U5", "1", 2.54, label="MT_SW")
    s.stub("U5", "3", 2.54, label="MT_FB")
    s.wire(s.pin("U5", "2"), (175.26, 91.44), (175.26, 101.6))
    s.gnd(175.26, 101.6)

    # ---- Feedback divider: Vout = 0.6 x (1 + R10/R11) ---------------------
    s.wire(s.pin("R10", "2"), s.pin("R11", "1"))
    s.wire((190.5, 96.52), (198.12, 96.52))
    s.label("MT_FB", 190.5, 96.52, 180)
    s.wire(s.pin("R10", "1"), (198.12, 76.2))
    s.wire(s.pin("R11", "2"), (198.12, 110.49))
    s.gnd(198.12, 110.49)

    # ---- 24 V output ------------------------------------------------------
    s.wire(s.pin("D2", "1"), (223.52, 76.2))
    s.wire(s.pin("C11", "1"), (213.36, 76.2))
    s.wire(s.pin("C11", "2"), (213.36, 93.98))
    s.gnd(213.36, 93.98)
    s.wire((223.52, 76.2), (223.52, 66.04))
    s.power("+24V", 223.52, 66.04)
    s.wire((218.44, 76.2), (218.44, 68.58))
    s.power("PWR_FLAG", 218.44, 68.58)

    s.note("FEEDBACK MATH", 96.52, 114.3, 1.4, bold=True)
    s.note("Vout = Vref x (1 + R10/R11), Vref = 0.6 V", 96.52, 119.38, 1.0)
    s.note("     = 0.6 x (1 + 390k/10k) = 24.00 V", 96.52, 121.92, 1.0)
    s.note("Load is one 2-wire transmitter at 24 mA max, so the", 96.52, 127.0, 1.0)
    s.note("converter runs at roughly 30 mA / 0.72 W out.", 96.52, 129.54, 1.0)

    s.note("D2 (SS34) and C11 are rated 40 V / 50 V for margin", 96.52, 134.62, 1.0)
    s.note("over the 24 V rail; U5's SW pin is the tight one, 30 V.", 96.52, 137.16, 1.0)

    s.block_end()


def build_test_points(s):
    s.block_start("TEST POINTS")
    # ---- Test points -----------------------------------------------------
    # Bring-up access for the five nets worth probing. They join their nets by
    # name, so they live here in the one piece of free sheet rather than being
    # threaded into the dense sections they belong to. Rotated 180 so the pad
    # symbol hangs below its pin and the wire can run up to the label.
    for ref, x in (("TP1", 106.68), ("TP2", 119.38), ("TP3", 132.08),
                   ("TP4", 144.78), ("TP5", 157.48)):
        put(s, ref, x, 157.48, 180)
        s.wire(s.pin(ref, "1"), (x, 152.4))
    s.label("LOOP_V", 106.68, 152.4)
    s.label("LOOP_RTN", 119.38, 152.4)
    s.power("+24V", 132.08, 152.4)
    s.power("+3V3", 144.78, 152.4)
    s.label("MT_EN", 157.48, 152.4)
    s.block_end()


# ===========================================================================
# Loop current limiter
# ===========================================================================
def build_limiter(s):
    s.block_start("LOOP CURRENT LIMITER  -  35 mA constant current, reverse blocking")

    # ---- Current limiter -------------------------------------------------
    # Q1 passes the loop current; R16 senses it; Q2 robs Q1's base drive at
    # the limit. Constant current, deliberately NOT foldback: a 2-wire
    # transmitter is a constant-current load, and Rev F's foldback could park
    # one at ~9 V / 14 mA after a short or a hot-plug -- a plausible, wrong
    # reading (sim/recover.py). Q1 is SOT-223 to carry a dead short instead.
    # D4 stops LOOP_V driving Q1 backwards into the rail, which it did from
    # ~25 V, long before the TVS ever conducted (sim/4_reverse_conduction.py).
    put(s, "R16", 157.48, 137.16)
    put(s, "Q1", 160.02, 149.86, 180)      # E up, C down, B to the right
    put(s, "Q2", 195.58, 142.24, 0, mirror="x")   # KiCad's canonical form for a 180+mirror-y flip
    put(s, "R17", 165.1, 158.75)
    put(s, "R18", 215.9, 137.16)
    put(s, "D4", 157.48, 161.29, 90)       # anode up at Q1's collector

    s.wire((157.48, 130.81), s.pin("R16", "1"))
    s.power("+24V", 157.48, 130.81)
    s.wire(s.pin("R16", "2"), s.pin("Q1", "3"))
    s.wire((157.48, 142.24), (151.13, 142.24))
    s.label("LOOP_SNS", 151.13, 142.24, 180)

    # pins 2 and 4 are both the collector (4 is the tab)
    s.wire(s.pin("Q1", "2"), s.pin("Q1", "4"), (149.86, 154.94))
    s.label("LOOP_C", 149.86, 154.94, 180)
    s.wire(s.pin("Q1", "2"), s.pin("D4", "2"))
    s.wire(s.pin("D4", "1"), (157.48, 167.64), (151.13, 167.64))
    s.label("LOOP_V", 151.13, 167.64, 180)
    # base drive is a real wire down to R17; only Q2's collector joins by label
    s.wire(s.pin("Q1", "1"), s.pin("R17", "1"))
    s.label("LOOP_DRV", 165.1, 152.4)

    s.wire(s.pin("Q2", "2"), (198.12, 132.08))
    s.power("+24V", 198.12, 132.08)
    s.wire(s.pin("Q2", "3"), (198.12, 152.4), (186.69, 152.4))
    s.label("LOOP_DRV", 186.69, 152.4, 180)
    s.wire(s.pin("Q2", "1"), (184.15, 142.24))
    s.label("LOOP_FB", 184.15, 142.24, 180)

    s.wire(s.pin("R17", "2"), (165.1, 165.1))
    s.gnd(165.1, 165.1)

    # a short stub: the label's text runs left, toward Q2's +24V port
    s.wire(s.pin("R18", "1"), (215.9, 130.81), (213.36, 130.81))
    s.label("LOOP_SNS", 213.36, 130.81, 180)
    s.wire(s.pin("R18", "2"), (215.9, 143.51), (222.25, 143.51))
    s.label("LOOP_FB", 222.25, 143.51)

    s.note("Ilim = Vbe(Q2) / R16: 35 / 33 / 27 mA at", 96.52, 137.16, 1.0)
    s.note("-20 / 25 / 85 C, so 24 mA always reads.", 96.52, 139.7, 1.0)
    s.note("Dead short: 24 V x 35 mA = 0.85 W in Q1,", 96.52, 142.24, 1.0)
    s.note("hence SOT-223. R16 + Q1 + D4 cost 1.2 V:", 96.52, 144.78, 1.0)
    s.note("22.8 V at J2 with 20 mA flowing.", 96.52, 147.32, 1.0)
    s.block_end()


# ===========================================================================
# Sheet 4 -- 4-20 mA loop terminal, shunt, INA226 current sense
# ===========================================================================
def build_loop_sense(s):
    # Low-side 3.32 ohm shunt, INA226 at I2C address 0x40
    s.block_start("LOOP TERMINAL & CURRENT MEASUREMENT  -  TVS, shunt, filter, INA226")

    put(s, "U3", 152.4, 88.9)
    # flipped top-to-bottom so pin 3 (+24 V) is uppermost and the wiring below
    # reads the same as before: 3 = +24 V out, 2 = mA in, 1 = GND
    put(s, "J2", 241.3, 77.47, 0, mirror="x")
    # Each field wire gets its own clamp to GROUND. One TVS across the pair only
    # handles a differential surge; the common-mode one -- both wires lifted
    # against the board -- went through the shunt and into U3's inputs.
    put(s, "D3", 226.06, 85.09, 270)   # LOOP_V  -> GND, 28 V stand-off
    put(s, "D5", 226.06, 111.76, 270)  # LOOP_RTN -> GND, 12 V stand-off
    put(s, "R12", 203.2, 110.49)
    put(s, "R13", 193.04, 96.52, 270)  # pin 2 (INA_INP) left, pin 1 (LOOP_RTN) right
    put(s, "R14", 193.04, 116.84, 270)  # pin 1 (GND) right, pin 2 (INA_INN) left
    put(s, "C9", 184.15, 106.68)
    put(s, "C8", 168.91, 106.68)

    # ---- Address pins strapped low (I2C 0x40) ----------------------------
    # one ground for both: two ports side by side crowded the Alert pin below them
    s.wire(s.pin("U3", "1"), (129.54, 83.82))
    s.wire(s.pin("U3", "2"), (134.62, 86.36), (134.62, 83.82))
    s.gnd(129.54, 83.82)
    s.nc("U3", "3")

    # ---- I2C --------------------------------------------------------------
    s.wire(s.pin("U3", "4"), (127.0, 91.44))
    s.label("I2C_SDA", 127.0, 91.44, 180)
    s.wire(s.pin("U3", "5"), (127.0, 93.98))
    s.label("I2C_SCL", 127.0, 93.98, 180)

    # ---- Supply + decoupling ---------------------------------------------
    s.wire(s.pin("U3", "6"), (172.72, 93.98), (172.72, 99.06), (168.91, 99.06))
    s.power("+3V3", 168.91, 99.06)
    s.wire(s.pin("C8", "1"), (168.91, 99.06))
    s.wire(s.pin("C8", "2"), (168.91, 114.3))
    s.gnd(168.91, 114.3)
    s.wire(s.pin("U3", "7"), (176.53, 91.44), (176.53, 104.14))
    s.gnd(176.53, 104.14)

    # ---- Bus voltage monitor ---------------------------------------------
    # Tapped downstream of the limiter, so a field short shows up as the loop
    # voltage collapsing as well as the current pegging at full scale.
    # R20 is what keeps that tap from killing the part: D3 is a 36 V TVS
    # whose clamp reaches 58 V at its rated surge current, well past the
    # INA226's 40 V absolute maximum on VBUS, and the pin itself is rated
    # for only +/-5 mA. 10 k holds the worst case to 1.8 mA. It costs
    # 1.19% of gain against the 830 k input impedance -- firmware
    # correction, and this reading is diagnostic, not the measurement.
    put(s, "R20", 190.5, 72.39, 270)   # pin 2 (INA_VBUS) left, pin 1 (LOOP_V) right
    s.wire(s.pin("U3", "8"), (182.88, 88.9), (182.88, 72.39), s.pin("R20", "2"))
    s.label("INA_VBUS", 168.91, 88.9)
    s.wire(s.pin("R20", "1"), (201.93, 72.39))
    s.label("LOOP_V", 201.93, 72.39)

    # ---- Differential sense inputs ---------------------------------------
    s.wire(s.pin("U3", "10"), (172.72, 83.82))
    s.label("INA_INP", 172.72, 83.82)
    s.wire(s.pin("U3", "9"), (172.72, 86.36))
    s.label("INA_INN", 172.72, 86.36)

    # ---- Shunt, input filter and loop terminal ---------------------------
    s.wire(s.pin("R13", "2"), (184.15, 96.52))
    s.wire((186.69, 96.52), (186.69, 93.98))
    s.label("INA_INP", 186.69, 93.98, 90)
    s.wire(s.pin("R13", "1"), (203.2, 96.52), (203.2, 101.6))
    s.wire(s.pin("R14", "2"), (180.34, 116.84))
    s.label("INA_INN", 180.34, 116.84, 180)
    s.wire(s.pin("R14", "1"), (203.2, 116.84))
    s.wire(s.pin("C9", "1"), (184.15, 96.52))
    s.wire(s.pin("C9", "2"), (184.15, 116.84))

    s.wire(s.pin("R12", "1"), (203.2, 101.6))
    s.wire(s.pin("R12", "2"), (203.2, 121.92))
    s.gnd(203.2, 121.92)

    s.wire((203.2, 101.6), (231.14, 101.6))
    s.wire((231.14, 101.6), (231.14, 77.47), s.pin("J2", "2"))
    s.wire(s.pin("J2", "1"), (233.68, 80.01), (233.68, 86.36))
    s.gnd(233.68, 86.36)
    s.label("LOOP_RTN", 213.36, 101.6)

    s.wire((215.9, 74.93), s.pin("J2", "3"))
    s.wire((215.9, 74.93), (215.9, 68.58), (209.55, 68.58))
    s.label("LOOP_V", 209.55, 68.58, 180)

    # One TVS per field wire, each to ground.
    s.wire(s.pin("D3", "1"), (226.06, 74.93))
    s.wire(s.pin("D3", "2"), (226.06, 93.98))
    s.gnd(226.06, 93.98)
    s.wire(s.pin("D5", "1"), (226.06, 101.6))
    s.wire(s.pin("D5", "2"), (226.06, 120.65))
    s.gnd(226.06, 120.65)

    s.note("SHUNT SIZING", 121.92, 116.84, 1.4, bold=True)
    s.note("R12 = 3.32 ohm: the INA226's +/-81.92 mV full scale", 121.92, 121.92, 1.0)
    s.note("then reaches 24.67 mA, so a sensor driving 23.5 mA", 121.92, 124.46, 1.0)
    s.note("over-range still reads instead of clipping.", 121.92, 127.0, 1.0)
    s.note("24 mA x 3.32 = 79.7 mV (97% of range); LSB 2.5 uV", 121.92, 129.54, 1.0)
    s.note("-> 0.75 uA. Dissipation at 24 mA = 1.9 mW (0805).", 121.92, 132.08, 1.0)
    s.note("R13/R14 + C9 form a 10 ohm / 100 nF differential", 121.92, 137.16, 1.0)
    s.note("input filter (fc ~ 80 kHz). Keep the R12 ground end", 121.92, 139.7, 1.0)
    s.note("and R14 on the same node -- Kelvin return.", 121.92, 142.24, 1.0)
    s.note("D3/D5 clamp each field wire to ground: 45 V / 20 V.", 121.92, 147.32, 1.0)
    s.note("R20 holds D3's clamp into U3's 40 V bus pin to", 121.92, 149.86, 1.0)
    s.note("0.5 mA of its 5 mA rating (costs 1.19% of gain).", 121.92, 152.4, 1.0)
    s.note("J2: 1 = GND, 2 = mA in, 3 = +24 V out.", 121.92, 157.48, 1.0)
    s.note("2-wire sensor on 3-2; sourcing sensor on 2-1.", 121.92, 160.02, 1.0)

    s.block_end()


# ===========================================================================
# One sheet: one block per circuit, declared in signal order; arrange() flows them
# ===========================================================================
BUILDERS = [build_usb_power, build_mcu, build_boost, build_limiter, build_loop_sense,
            build_test_points]


def build_notes(s):
    """Sheet-level notes: a layout group of its own, so it flows with the blocks."""
    s.block_start("POWER RAILS & SIGNAL LINKS")
    s.note("POWER RAILS  (global power ports)", 25.4, 25.4, 1.27, bold=True)
    s.note("+5V    USB-C VBUS -> LDO, load switch\n"
           "+3V3   LDO -> ESP32-S3, INA226\n"
           "+24V   boost -> limiter -> loop terminal\n"
           "GND    single ground plane", 25.4, 30.48, 1.0)
    s.note("SIGNAL LINKS  (net labels)", 25.4, 45.72, 1.27, bold=True)
    s.note("USB_P / USB_N        USB-C -> ESP32-S3\n"
           "I2C_SDA / I2C_SCL    ESP32-S3 -> INA226\n"
           "MT_EN                ESP32-S3 -> load switch\n"
           "LOOP_V / LOOP_RTN    limiter -> terminal -> shunt", 25.4, 50.8, 1.0)
    s.block_end()


def build_flat(d):
    s = d.sheet(ROOT_FILE, "ESP32 4-20 mA ESPHome Sensor Board", paper="auto",
                comment="USB-C powered 4-20 mA loop reader with onboard 24 V loop supply")
    for fn in BUILDERS:
        fn(s)
    build_notes(s)
    # relieve=False: the wiring inside each block is hand-drawn and already
    # clean; only the blocks' places on the page are computed
    s.arrange(relieve=False)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="overwrite a sheet changed outside the generator (it is backed up)")
    args = ap.parse_args()
    d = Design(PROJDIR, "esp32-4to20ma-board", title="ESP32 4-20 mA ESPHome Sensor Board",
               rev=REV, date=DATE)
    build_flat(d)
    d.write(force=args.force, relieve=False)
    ok = d.verify(NETS, NO_CONNECT)
    d.erc()
    d.check_text()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
