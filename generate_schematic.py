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

REV = "H"
DATE = "2026-11-11"
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
    # Rev H: the mA-in pin's clamp is now the same 28 V part as D3. A 12 V part
    # there conducted when 24 V was wired to the pin by mistake, and let a surge
    # put 90-140 W into the shunt before it clamped at all (sim/8_input_protection.py).
    "D5":  (f"{LIB}:SMAJ36A_C113967", "SMAJ28A",
            fp("SMA_L4.3-W2.6-LS5.2-RD"), "C353458", "Jingdao Microelectronics", "SMAJ28A"),
    # Behind the pin clamp: a resettable fuse in series, then a silicon diode
    # straight across the shunt. In a surge or with 24 V on the pin the shunt
    # never sees more than the diode's forward drop (about 1 V, under 1 W) and
    # the fuse opens the fault. At 24 mA the diode has 82 mV across it and
    # steals about 1 ppm of the reading at 25 C, 77 ppm at 85 C. Not a Schottky:
    # its leakage at 82 mV would be a thousand times that.
    "F1":  ("Device:Polyfuse", "100mA/60V",
            "Fuse:Fuse_1206_3216Metric", "C70065", "TECHFUSE", "nSMD010"),
    "D6":  ("Diode:1N4007", "1N4007W",
            "Diode_SMD:D_SOD-123F", "C7528871", "MSKSEMI", "1N4007W"),
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
    "TP2": ("Connector:TestPoint", "LOOP_IN",  TP_FP, None, None, None),
    "TP3": ("Connector:TestPoint", "+24V",     TP_FP, None, None, None),
    "TP4": ("Connector:TestPoint", "+3V3",     TP_FP, None, None, None),
    "TP5": ("Connector:TestPoint", "MT_EN",    TP_FP, None, None, None),
}


#: Clear space between a block's contents and its outline. schlib's default is
#: 5.08; at 3.81 the eight blocks of this board compose onto A3.
PAD = 3.81

#: ref -> lib_id of the functional symbol drawn for it (filled in by
#: functional_symbols()). The vendor symbols these replace have their pins in
#: package order; see schlib.functional_symbol.
FUNC = {}


def functional_symbols(d):
    """Redraw the five parts whose vendor symbols fight the drawing."""
    FUNC["J1"] = d.functional_symbol(
        "USB_C_2.0", ref="J",
        right=[("A4B9,B4A9", "VBUS"), ("A6,B6", "D+", "io"), ("A7,B7", "D-", "io"),
               ("A5", "CC1"), ("B5", "CC2"), ("A8", "SBU1", "nc"), ("B8", "SBU2", "nc")],
        bottom=[("A1B12,B1A12", "GND"), ("13,14", "SHIELD")])
    FUNC["D1"] = d.functional_symbol(
        "USBLC6-2SC6", ref="D",
        top=[("1,6", "IO1")], bottom=[("3,4", "IO2")], left=[("5", "VBUS")], right=[("2", "GND")])
    FUNC["U4"] = d.functional_symbol(
        "AP2112K-3.3", left=[("1", "VIN", "pwr"), ("3", "EN", "in")],
        right=[("5", "VOUT"), ("4", "NC", "nc")], bottom=[("2", "GND", "pwr")])
    FUNC["U5"] = d.functional_symbol(
        "MT3608", left=[("5", "IN", "pwr"), ("4", "EN", "in"), ("6", "NC", "nc")],
        right=[("1", "SW"), ("3", "FB", "in")], bottom=[("2", "GND", "pwr")])
    FUNC["U3"] = d.functional_symbol(
        "INA226", left=[("10", "IN+", "in"), ("9", "IN-", "in")],
        right=[("4", "SDA", "io"), ("5", "SCL", "in"), ("3", "ALERT", "oc")],
        top=[("8", "VBUS", "in"), None, None, ("6", "VS", "pwr")],
        bottom=[("1", "A1", "in"), ("2", "A0", "in"), ("7", "GND", "pwr")])


def put(sheet, ref, x, y, rot=0, mirror=None):
    lib_id, value, footprint, lcsc, mfr, mpn = PARTS[ref]
    lib_id = FUNC.get(ref, lib_id)
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
        ("R15", "1"), ("D6", "1"),
    ],
    "+3V3": [
        ("U1", "2"), ("U3", "6"), ("U4", "5"),
        ("R1", "1"), ("R5", "1"), ("R6", "1"), ("R9", "1"),
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
    # Rev H: the pin and the shunt are different nets, with F1 between them.
    "LOOP_IN":  [("J2", "2"), ("D5", "1"), ("F1", "1"), ("TP2", "1")],
    "LOOP_RTN": [("F1", "2"), ("R12", "1"), ("R13", "1"), ("D6", "2")],
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
    s.block_start("USB-C INPUT & ESD PROTECTION", pad=PAD)
    # The connector is drawn as what it is electrically -- VBUS, D+, D-, two CC
    # pins, ground -- with the reversible plug's duplicate contacts stacked on
    # one pin each. D+ runs over the clamp and D- under it, so the clamp taps
    # each line without either crossing the other.
    put(s, "J1", 49.53, 76.2)
    vb, dp, dn = s.pin("J1", "A4B9"), s.pin("J1", "A6"), s.pin("J1", "A7")
    c1, c2 = s.pin("J1", "A5"), s.pin("J1", "B5")
    s.nc("J1", "A8", "B8")
    X = vb[0]                             # where the connector's pins end

    s.wire(vb, (X + 8.89, vb[1]), (X + 8.89, vb[1] - 2.54))
    s.power("PWR_FLAG", X + 8.89, vb[1] - 2.54)
    s.wire((X + 3.81, vb[1]), (X + 3.81, vb[1] - 7.62))
    s.power("+5V", X + 3.81, vb[1] - 7.62)

    # CC pins -> 5.1 k pulldowns (advertise UFP, sink 5 V / default current).
    # The lower line's resistor is the nearer one, so neither drop crosses.
    put(s, "R8", X + 8.89, c2[1] + 7.62)
    put(s, "R7", X + 16.51, c2[1] + 7.62)
    s.wire(c2, (X + 8.89, c2[1]), s.pin("R8", "1"))
    s.wire(c1, (X + 16.51, c1[1]), s.pin("R7", "1"))
    s.label("CC1", X + 10.16, c1[1])
    s.label("CC2", X + 2.54, c2[1])
    yg = s.pin("R7", "2")[1] + 2.54
    for ref in ("R7", "R8"):
        x = s.pin(ref, "2")[0]
        s.wire(s.pin(ref, "2"), (x, yg))
        s.gnd(x, yg)

    # The clamp sits between the two data lines: D+ passes over it, D- drops
    # and passes under it, and each line taps its own side.
    DX = X + 44.45
    put(s, "D1", DX, dp[1] + 15.24)
    io1, io2 = s.pin("D1", "1"), s.pin("D1", "3")
    yu = io2[1] + 5.08                    # the lower run
    s.wire(dp, (DX + 30.48, dp[1]))
    s.label("USB_P", DX + 30.48, dp[1])
    s.wire(io1, (io1[0], dp[1]))
    s.wire(dn, (X + 24.13, dn[1]), (X + 24.13, yu), (DX + 25.4, yu), (DX + 25.4, dn[1]),
           (DX + 30.48, dn[1]))
    s.label("USB_N", DX + 30.48, dn[1])
    s.wire(io2, (io2[0], yu))
    dv, dg = s.pin("D1", "5"), s.pin("D1", "2")
    s.wire(dv, (dv[0] - 3.81, dv[1]), (dv[0] - 3.81, dv[1] - 5.08))
    s.power("+5V", dv[0] - 3.81, dv[1] - 5.08)
    s.wire(dg, (dg[0] + 2.54, dg[1]), (dg[0] + 2.54, dg[1] + 2.54))
    s.gnd(dg[0] + 2.54, dg[1] + 2.54)

    # Ground and shell together; GND and +5V originate at this connector, so
    # the ERC power-source flags for both rails belong here.
    g, sh = s.pin("J1", "A1B12"), s.pin("J1", "13")
    s.wire(g, (g[0], g[1] + 2.54))
    s.wire(sh, (sh[0], sh[1] + 2.54), (g[0] - 5.08, g[1] + 2.54))
    s.power("PWR_FLAG", g[0] - 5.08, g[1] + 2.54)
    s.wire((g[0], g[1] + 2.54), (g[0], g[1] + 5.08))
    s.gnd(g[0], g[1] + 5.08)

    yn = yu + 6.35
    s.note("CC1/CC2 pulldowns: 5.1 k = UFP, advertises", X - 1.27, yn, 1.0)
    s.note("a default-current (500 mA) USB 2.0 sink.", X - 1.27, yn + 2.54, 1.0)
    s.note("D1 ESD clamp: 15 kV air / 8 kV contact", DX - 6.35, yn, 1.0)
    s.note("(IEC 61000-4-2). On the board D+ / D- run", DX - 6.35, yn + 2.54, 1.0)
    s.note("through its pads: pins 1+6 and 3+4.", DX - 6.35, yn + 5.08, 1.0)
    s.block_end()

    # ---- 3.3 V LDO --------------------------------------------------------
    s.block_start("3.3 V REGULATOR & POWER LED", pad=PAD)
    put(s, "U4", 152.4, 66.04)
    vin, en, vout = s.pin("U4", "1"), s.pin("U4", "3"), s.pin("U4", "5")
    put(s, "C6", 137.16, 71.12)      # 5 V input cap
    put(s, "C7", 172.72, 71.12)      # 3.3 V output cap
    s.power("+5V", 132.08, 59.69)
    s.wire((132.08, 59.69), (132.08, vin[1]), vin)
    s.wire((137.16, vin[1]), s.pin("C6", "1"))
    s.wire(s.pin("C6", "2"), (137.16, 77.47))
    s.gnd(137.16, 77.47)
    # EN tied to VIN -- the LDO has no shutdown control on this board.
    s.wire(en, (139.7, en[1]), (139.7, vin[1]))
    s.nc("U4", "4")
    gnd = s.pin("U4", "2")
    s.wire(gnd, (gnd[0], 77.47))
    s.gnd(gnd[0], 77.47)
    s.wire(vout, (182.88, vout[1]), (182.88, 59.69))
    s.power("+3V3", 182.88, 59.69)
    s.wire((172.72, vout[1]), s.pin("C7", "1"))
    s.wire(s.pin("C7", "2"), (172.72, 77.47))
    s.gnd(172.72, 77.47)
    s.wire((177.8, vout[1]), (177.8, vout[1] - 2.54))
    s.power("PWR_FLAG", 177.8, vout[1] - 2.54)
    s.note("AP2112K-3.3: 600 mA LDO, 250 mV dropout.", 132.08, 86.36, 1.0)
    s.note("Worst-case dissipation (5 V in, 3.3 V out, 300 mA)", 132.08, 88.9, 1.0)
    s.note("= 0.51 W -- well inside SOT-25 on 2 oz copper.", 132.08, 91.44, 1.0)

    # ---- Power-on LED -----------------------------------------------------
    put(s, "R9", 195.58, 68.58)
    put(s, "LED1", 195.58, 81.28, 90)   # anode up (from R9), cathode down to GND
    s.wire(s.pin("R9", "1"), (195.58, 59.69))
    s.power("+3V3", 195.58, 59.69)
    s.wire(s.pin("R9", "2"), s.pin("LED1", "2"))
    s.label("LED_A", 195.58, 74.93)
    s.wire(s.pin("LED1", "1"), (195.58, 88.9))
    s.gnd(195.58, 88.9)
    s.note("Power LED: (3.3 - 1.9) / 330 = 4.2 mA", 132.08, 93.98, 1.0)
    s.block_end()


# ===========================================================================
# Sheet 2 -- ESP32-S3 module, reset & boot, I2C pull-ups
# ===========================================================================
def build_mcu(s):
    # Native-USB ESP32-S3-WROOM-1U-N4 (U.FL antenna); no UART bridge required
    s.block_start("ESP32-S3 MODULE  -  reset, boot, I2C pull-ups, decoupling", pad=PAD)

    put(s, "U1", 152.4, 96.52)

    # ---- Module grounds ---------------------------------------------------
    # Pins 1, 40 and the exposed pad (41) are all at the top of the symbol;
    # they join a bus above the module that ends in one ground port beside it.
    s.wire(s.pin("U1", "1"), (137.16, 73.66), (137.16, 63.5))
    s.wire((137.16, 63.5), (177.8, 63.5))
    s.wire(s.pin("U1", "41"), (152.4, 63.5))
    s.wire(s.pin("U1", "40"), (168.91, 73.66), (168.91, 63.5))
    s.wire((177.8, 63.5), (177.8, 66.04))
    s.gnd(177.8, 66.04)

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
    put(s, "SW2", 177.8, 116.84)
    b1, b3 = s.pin("SW2", "1"), s.pin("SW2", "3")
    s.wire(s.pin("U1", "27"), (170.18, 106.68), (170.18, b1[1]), b1)
    s.label("IO0", 170.18, 106.68)
    s.wire(b3, (170.18, b3[1]), (170.18, b1[1]))
    b2, b4 = s.pin("SW2", "2"), s.pin("SW2", "4")
    s.wire(b2, (187.96, b2[1]), (187.96, b4[1] + 3.81))
    s.wire(b4, (187.96, b4[1]))
    s.gnd(187.96, b4[1] + 3.81)

    # ---- Module decoupling ------------------------------------------------
    put(s, "C2", 114.3, 130.81)
    put(s, "C3", 127.0, 130.81)
    for ref, x in (("C2", 114.3), ("C3", 127.0)):
        s.wire(s.pin(ref, "1"), (x, 124.46))
        s.power("+3V3", x, 124.46)
        s.gnd(*s.pin(ref, "2"))
    s.note("Bulk + HF decoupling;", 133.35, 137.16, 1.0)
    s.note("C3 within 5 mm of U1 pin 2.", 133.35, 139.7, 1.0)

    # ---- Notes: in the block's two empty corners --------------------------
    s.note("USB: the S3's USB-Serial/JTAG block handles reset and", 58.42, 59.69, 1.0)
    s.note("bootloader entry over native USB, so no DTR/RTS", 58.42, 62.23, 1.0)
    s.note("transistor circuit is needed.", 58.42, 64.77, 1.0)
    s.note("RESET: 10 k + 1 uF give a ~10 ms rise on EN.", 58.42, 69.85, 1.0)
    s.note("I2C: 4.7 k pull-ups for one INA226 at 400 kHz.", 58.42, 73.66, 1.0)
    s.note("STRAPPING PINS", 58.42, 121.92, 1.4, bold=True)
    s.note("IO0  (27) - internal pull-up, held high by SW2 idle.", 58.42, 125.73, 1.0)
    s.note("IO46 (16) - internal pull-down; leave floating (NC).", 58.42, 128.27, 1.0)
    s.note("IO45 (26) - VDD_SPI select; must stay low on -N4.", 58.42, 130.81, 1.0)
    s.note("            Do not add a pull-up here.", 58.42, 133.35, 1.0)
    s.note("IO3  (15) - no internal pull; JTAG source select only,", 58.42, 135.89, 1.0)
    s.note("            floating is safe with no JTAG header.", 58.42, 138.43, 1.0)

    used = {"1", "2", "3", "12", "13", "14", "17", "18", "27", "40", "41"}
    s.nc("U1", *[n for n in [str(i) for i in range(1, 42)] if n not in used])

    s.block_end()


# ===========================================================================
# Sheet 3 -- MT3608 boost converter, 5 V -> 24 V loop supply
# ===========================================================================
def build_boost(s):
    # 5 V -> 24 V @ 30 mA for the 2-wire 4-20 mA transmitter
    s.block_start("24 V BOOST CONVERTER  -  soft-start load switch, MT3608, feedback", pad=PAD)

    # One power path, left to right along one rail, as a datasheet draws a
    # boost: +5 V in, the load switch, the input capacitor, the inductor, the
    # switch node, the rectifier, the output capacitor, +24 V out. The
    # controller hangs under the inductor with IN/EN up to its input side and
    # SW up to its output side; the feedback divider hangs off the output and
    # is wired back to FB. Net names name nets; nothing is joined by label.
    Y = 76.2

    # ---- Soft-start load switch ------------------------------------------
    # Q3 sits between VBUS and everything the boost hangs on it (C10, and C11
    # through L1/D2, which a boost cannot disconnect). C12 is gate-to-SOURCE so
    # the gate follows VBUS up at plug-in and Q3 stays off through the edge;
    # a gate-to-drain capacitor does the opposite (sim/7_usb_inrush.py).
    put(s, "Q3", 73.66, Y + 2.54, 270, mirror="x")   # S left, D right, G down
    put(s, "R21", 50.8, 81.28)                       # source to gate
    put(s, "C12", 58.42, 81.28)                      # source to gate
    put(s, "R22", 50.8, 95.25)                       # gate down to Q4
    put(s, "Q4", 48.26, 109.22)                      # D up, S down, G left
    put(s, "R15", 39.37, 115.57, 180)                # MT_EN pull-DOWN: off until firmware says on
    s.power("+5V", 45.72, 71.12)
    s.wire((45.72, 71.12), (45.72, Y), s.pin("Q3", "2"))
    s.wire((50.8, Y), s.pin("R21", "1"))
    s.wire((58.42, Y), s.pin("C12", "1"))
    gx, gy = s.pin("Q3", "1")
    s.wire(s.pin("R21", "2"), (50.8, 88.9), (gx, 88.9), (gx, gy))
    s.wire(s.pin("C12", "2"), (58.42, 88.9))
    s.label("SW_GATE", 60.96, 88.9)
    s.wire((50.8, 88.9), s.pin("R22", "1"))
    s.wire(s.pin("R22", "2"), s.pin("Q4", "3"))
    s.label("SW_PD", 50.8, 101.6)
    s.wire(s.pin("Q4", "2"), (50.8, 116.84))
    s.gnd(50.8, 116.84)
    # Enable: pulled DOWN, driven high by the MCU to power the loop (Rev H).
    # Rev G pulled it up, which left the 24 V rail live through reset, flashing
    # and any firmware hang, with only Q1's dissipation between a shorted loop
    # and the limit. It gates the load switch; U5's own EN rides on its input.
    s.wire(s.pin("Q4", "1"), (34.29, 109.22))
    s.label("MT_EN", 34.29, 109.22, 180)
    s.wire(s.pin("R15", "2"), (39.37, 109.22))
    s.gnd(*s.pin("R15", "1"))
    s.note("R21/R22 leave Vgs at -4.0 V; C12 x (R21 || R22) = 8 ms.", 63.5, 96.52, 1.0)
    s.note("VBUS sees 1 uF at attach, not 27 uF (USB limit 10 uF).", 63.5, 99.06, 1.0)
    s.note("MT_EN is pulled down: the loop supply stays off", 63.5, 102.87, 1.0)
    s.note("until the firmware turns it on.", 63.5, 105.41, 1.0)

    # ---- Input rail, inductor, switch node --------------------------------
    put(s, "C10", 101.6, 83.82)
    put(s, "L1", 124.46, Y)
    put(s, "U5", 121.92, 93.98)                      # IN/EN left, SW/FB right, GND underneath
    put(s, "D2", 152.4, Y, 180)
    s.wire(s.pin("Q3", "3"), s.pin("L1", "1"))
    s.wire((83.82, Y), (83.82, Y - 5.08))
    s.power("PWR_FLAG", 83.82, Y - 5.08)
    s.label("VIN_SW", 86.36, Y)
    s.wire((101.6, Y), s.pin("C10", "1"))
    s.wire(s.pin("C10", "2"), (101.6, 90.17))
    s.gnd(101.6, 90.17)
    # IN and EN both come up to the input rail, on the supply side of L1
    vin, en, sw, fb, gnd = (s.pin("U5", n) for n in ("5", "4", "1", "3", "2"))
    s.wire(en, (109.22, en[1]), (109.22, Y))
    s.wire(vin, (109.22, vin[1]))
    s.nc("U5", "6")
    s.wire(s.pin("L1", "2"), s.pin("D2", "2"))
    s.label("MT_SW", 139.7, Y)
    s.wire(sw, (137.16, sw[1]), (137.16, Y))
    s.wire(gnd, (gnd[0], gnd[1] + 2.54))
    s.gnd(gnd[0], gnd[1] + 2.54)

    # ---- 24 V output and the feedback divider ------------------------------
    put(s, "R10", 167.64, 83.82)
    put(s, "R11", 167.64, 101.6)
    put(s, "C11", 180.34, 83.82)
    s.wire(s.pin("D2", "1"), (190.5, Y))
    s.wire((167.64, Y), s.pin("R10", "1"))
    s.wire(s.pin("R10", "2"), s.pin("R11", "1"))
    s.wire(s.pin("R11", "2"), (167.64, 107.95))
    s.gnd(167.64, 107.95)
    # feedback: straight across from the divider's midpoint
    s.wire(fb, (167.64, fb[1]))
    s.label("MT_FB", 142.24, fb[1])
    s.wire((180.34, Y), s.pin("C11", "1"))
    s.wire(s.pin("C11", "2"), (180.34, 90.17))
    s.gnd(180.34, 90.17)
    s.wire((185.42, Y), (185.42, Y - 5.08))
    s.power("PWR_FLAG", 185.42, Y - 5.08)
    s.wire((190.5, Y), (190.5, 71.12))
    s.power("+24V", 190.5, 71.12)

    s.note("Load is one 2-wire transmitter at 24 mA max, so the", 63.5, 111.76, 1.0)
    s.note("converter runs at roughly 30 mA / 0.72 W out.", 63.5, 114.3, 1.0)
    s.note("D2 (SS34) and C11 are rated 40 V / 50 V for margin", 63.5, 118.11, 1.0)
    s.note("over the 24 V rail; U5's SW pin is the tight one, 30 V.", 63.5, 120.65, 1.0)
    s.note("FEEDBACK MATH", 127.0, 109.22, 1.4, bold=True)
    s.note("Vout = Vref x (1 + R10/R11), Vref = 0.6 V", 127.0, 114.3, 1.0)
    s.note("     = 0.6 x (1 + 390k/10k) = 24.00 V", 127.0, 116.84, 1.0)
    s.block_end()


def build_test_points(s):
    s.block_start("TEST POINTS", pad=PAD)
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
    s.label("LOOP_IN", 119.38, 152.4)
    s.power("+24V", 132.08, 152.4)
    s.power("+3V3", 144.78, 152.4)
    s.label("MT_EN", 157.48, 152.4)
    s.block_end()


# ===========================================================================
# Loop current limiter
# ===========================================================================
def build_limiter(s):
    s.block_start("LOOP CURRENT LIMITER  -  35 mA, reverse blocking", pad=PAD)

    # Drawn as the textbook two-transistor limiter, left to right along one
    # rail: +24 V in, sense resistor, pass transistor, blocking diode, LOOP_V
    # out. Q2 sits under the sense resistor it watches, wired across it, and
    # steals Q1's base drive. Every connection is a wire; the three net names
    # are there to name the nets, not to join them.
    #
    # Q1 passes the loop current; R16 senses it; Q2 robs Q1's base drive at
    # the limit. Constant current, deliberately NOT foldback: a 2-wire
    # transmitter is a constant-current load, and Rev F's foldback could park
    # one at ~9 V / 14 mA after a short or a hot-plug -- a plausible, wrong
    # reading (sim/recover.py). Q1 is SOT-223 to carry a dead short instead.
    # D4 stops LOOP_V driving Q1 backwards into the rail, which it did from
    # ~25 V, long before the TVS ever conducted (sim/4_reverse_conduction.py).
    Y = 139.7                                       # the rail
    put(s, "R16", 134.62, Y, 90)                    # 1 (+24V) left, 2 (sense) right
    put(s, "Q1", 165.1, Y + 2.54, 270, mirror="x")  # E left, C right, B down
    put(s, "D4", 184.15, Y, 180)                    # anode left, cathode right
    put(s, "Q2", 127.0, 149.86, 180)                # E up on the rail, B right, C down
    put(s, "R18", 147.32, 149.86, 270)              # 2 (to Q2's base) left, 1 (sense) right
    put(s, "R17", 165.1, 165.1)

    s.power("+24V", 121.92, 134.62)
    s.wire((121.92, 134.62), (121.92, Y), s.pin("R16", "1"))
    s.wire(s.pin("R16", "2"), s.pin("Q1", "3"))
    s.label("LOOP_SNS", 140.97, Y)
    # pins 2 and 4 are both the collector (4 is the tab)
    s.wire(s.pin("Q1", "4"), s.pin("Q1", "2"))
    s.wire(s.pin("Q1", "2"), s.pin("D4", "2"))
    s.label("LOOP_C", 171.45, Y)
    s.wire(s.pin("D4", "1"), (195.58, Y))
    s.label("LOOP_V", 195.58, Y)

    # Q2 across the sense resistor: emitter on the +24 V side, base on the
    # far side through R18
    s.wire(s.pin("Q2", "2"), (124.46, Y))
    s.wire(s.pin("Q2", "1"), s.pin("R18", "2"))
    s.label("LOOP_FB", 133.35, 149.86)
    s.wire(s.pin("R18", "1"), (154.94, 149.86), (154.94, Y))

    # base drive: R17 pulls Q1's base down, Q2's collector pulls it back up
    s.wire(s.pin("Q1", "1"), (165.1, 160.02), s.pin("R17", "1"))
    s.wire(s.pin("Q2", "3"), (124.46, 160.02), (165.1, 160.02))
    s.label("LOOP_DRV", 133.35, 160.02)
    s.gnd(*s.pin("R17", "2"))

    s.note("Ilim = Vbe(Q2) / R16: 35 / 33 / 27 mA at", 175.26, 152.4, 1.0)
    s.note("-20 / 25 / 85 C, so 24 mA always reads.", 175.26, 154.94, 1.0)
    s.note("Dead short: 24 V x 35 mA = 0.85 W in Q1,", 175.26, 157.48, 1.0)
    s.note("hence SOT-223. R16 + Q1 + D4 cost 1.2 V:", 175.26, 160.02, 1.0)
    s.note("22.8 V at J2 with 20 mA flowing.", 175.26, 162.56, 1.0)
    s.block_end()


# ===========================================================================
# Sheet 4 -- 4-20 mA loop terminal, shunt, INA226 current sense
# ===========================================================================
def build_loop_sense(s):
    # Low-side 3.32 ohm shunt, INA226 at I2C address 0x40
    s.block_start("LOOP TERMINAL & CURRENT MEASUREMENT  -  protection, shunt, filter, INA226", pad=PAD)
    # Left to right, the way the current goes: field terminal, the clamp at
    # each pin, then on the mA line the fuse, the diode across the shunt, the
    # shunt, its Kelvin filter and the INA226. Every connection is a wire.
    YA, YB = 71.12, 93.98                # +24 V out row, mA in row
    put(s, "J2", 104.14, YB, 180)        # pins face right: 3 on top, 2, 1 underneath
    p3, p2, p1 = s.pin("J2", "3"), s.pin("J2", "2"), s.pin("J2", "1")
    put(s, "D3", 121.92, 78.74, 270)     # LOOP_V  -> GND, 28 V stand-off
    put(s, "D5", 121.92, 101.6, 270)     # LOOP_IN -> GND, 28 V stand-off
    put(s, "F1", 139.7, YB, 90)          # 1 (pin side) left, 2 (shunt side) right
    put(s, "D6", 160.02, 101.6, 90)      # anode up on the mA line, cathode to GND
    put(s, "R12", 170.18, 101.6)         # the shunt
    put(s, "R13", 180.34, YB, 90)        # 1 (shunt) left, 2 (IN+) right
    put(s, "R14", 180.34, 107.95, 90)    # 1 (shunt's ground end) left, 2 (IN-) right
    put(s, "C9", 189.23, 100.33)
    put(s, "R20", 177.8, YA, 90)         # 1 (LOOP_V) left, 2 (bus pin) right
    put(s, "U3", 220.98, 95.25)

    # +24 V out: terminal pin 3, its clamp, and on to the bus-voltage pin
    s.wire(p3, (111.76, p3[1]), (111.76, YA), s.pin("R20", "1"))
    s.label("LOOP_V", 127.0, YA)
    s.wire((121.92, YA), s.pin("D3", "1"))
    s.wire(s.pin("D3", "2"), (121.92, 85.09))
    s.gnd(121.92, 85.09)
    vbus = s.pin("U3", "8")
    s.wire(s.pin("R20", "2"), (vbus[0], YA), vbus)
    s.label("INA_VBUS", 184.15, YA)

    # mA in: terminal pin 2, clamp, fuse, then the shunt with its diode
    s.wire(p2, s.pin("F1", "1"))
    s.label("LOOP_IN", 124.46, YB)
    s.wire((121.92, YB), s.pin("D5", "1"))
    s.wire(s.pin("D5", "2"), (121.92, 107.95))
    s.gnd(121.92, 107.95)
    s.wire(s.pin("F1", "2"), s.pin("R13", "1"))
    s.label("LOOP_RTN", 146.05, YB)
    s.wire((160.02, YB), s.pin("D6", "2"))
    s.wire(s.pin("D6", "1"), (160.02, 107.95))
    s.gnd(160.02, 107.95)
    s.wire((170.18, YB), s.pin("R12", "1"))
    # the shunt's ground end: the Kelvin tap leaves it BEFORE the ground port
    s.wire(s.pin("R12", "2"), (170.18, 107.95), (170.18, 110.49))
    s.gnd(170.18, 110.49)
    s.wire((170.18, 107.95), s.pin("R14", "1"))

    # differential filter into IN+ / IN-
    inp, inn = s.pin("U3", "10"), s.pin("U3", "9")
    s.wire(s.pin("R13", "2"), inp)
    s.label("INA_INP", 191.77, YB)
    s.wire(s.pin("R14", "2"), (195.58, 107.95), (195.58, inn[1]), inn)
    s.label("INA_INN", 196.85, inn[1])
    s.wire((189.23, YB), s.pin("C9", "1"))
    s.wire(s.pin("C9", "2"), (189.23, 107.95))

    # terminal pin 1: ground, for a 3-wire or self-powered transmitter
    s.wire(p1, (111.76, p1[1]), (111.76, 101.6))
    s.gnd(111.76, 101.6)

    # INA226: supply and decoupling above, address pins and ground underneath
    vs = s.pin("U3", "6")
    s.wire(vs, (vs[0], vs[1] - 12.7))
    s.power("+3V3", vs[0], vs[1] - 12.7)
    put(s, "C8", vs[0] + 11.43, vs[1] - 6.35)
    s.wire((vs[0], vs[1] - 10.16), s.pin("C8", "1"))
    s.gnd(*s.pin("C8", "2"))
    a1, a0, g = s.pin("U3", "1"), s.pin("U3", "2"), s.pin("U3", "7")
    for q in (a1, a0, g):
        s.wire(q, (q[0], q[1] + 2.54))
    s.wire((a1[0], a1[1] + 2.54), (g[0], g[1] + 2.54))
    s.wire((a0[0], a0[1] + 2.54), (a0[0], a0[1] + 5.08))
    s.gnd(a0[0], a0[1] + 5.08)
    s.nc("U3", "3")
    sda, scl = s.pin("U3", "4"), s.pin("U3", "5")
    s.wire(sda, (sda[0] + 5.08, sda[1]))
    s.label("I2C_SDA", sda[0] + 5.08, sda[1])
    s.wire(scl, (scl[0] + 5.08, scl[1]))
    s.label("I2C_SCL", scl[0] + 5.08, scl[1])

    s.note("SHUNT SIZING", 104.14, 119.38, 1.4, bold=True)
    s.note("R12 = 3.32 ohm: the INA226's +/-81.92 mV full scale", 104.14, 124.46, 1.0)
    s.note("then reaches 24.67 mA, so a sensor driving 23.5 mA", 104.14, 127.0, 1.0)
    s.note("over-range still reads instead of clipping.", 104.14, 129.54, 1.0)
    s.note("24 mA x 3.32 = 79.7 mV (97% of range); LSB 2.5 uV", 104.14, 132.08, 1.0)
    s.note("-> 0.75 uA. Dissipation at 24 mA = 1.9 mW (0805).", 104.14, 134.62, 1.0)
    s.note("R13/R14 + C9: 10 ohm / 100 nF differential filter", 104.14, 139.7, 1.0)
    s.note("(fc ~ 80 kHz). R14 taps the shunt's own ground pad.", 104.14, 142.24, 1.0)
    s.note("PROTECTION", 165.1, 119.38, 1.4, bold=True)
    s.note("D3 / D5 (28 V) clamp each field wire to ground at 45 V.", 165.1, 124.46, 1.0)
    s.note("R20 holds that into U3's 40 V bus pin to 0.5 mA", 165.1, 127.0, 1.0)
    s.note("(costs 1.19% of bus-voltage gain).", 165.1, 129.54, 1.0)
    s.note("F1 + D6: with 24 V wired to the mA pin, or in a surge, the", 165.1, 134.62, 1.0)
    s.note("shunt sees D6's 1 V, not the fault, and F1 opens it.", 165.1, 137.16, 1.0)
    s.note("D6 at 82 mV steals 1 ppm at 25 C, 77 ppm at 85 C.", 165.1, 139.7, 1.0)
    s.note("J2: 1 = GND, 2 = mA in, 3 = +24 V out.", 104.14, 147.32, 1.0)
    s.note("2-wire sensor on 3-2; sourcing sensor on 2-1.", 104.14, 149.86, 1.0)
    s.block_end()


# ===========================================================================
# One sheet: one block per circuit. The page is composed, not flowed: the 5 V
# side along the top (USB in, regulator, module), the 24 V loop along the
# bottom (boost, limiter, terminal and measurement), the two small blocks
# tucked into the space the short ones leave. Flowed, the same blocks need A2; composed they fit A3, which
# is the largest sheet that is still readable printed on A4.
# ===========================================================================
LAYOUT = [
    ["USB-C INPUT", ["3.3 V REGULATOR", "TEST POINTS"], "ESP32-S3 MODULE"],
    [["24 V BOOST", ["LOOP CURRENT LIMITER", "POWER RAILS"]], "LOOP TERMINAL"],
]
GUTTER = 10.16
BUILDERS = [build_usb_power, build_mcu, build_boost, build_limiter, build_loop_sense,
            build_test_points]


def build_notes(s):
    """Sheet-level notes: a layout group of its own, so it flows with the blocks."""
    s.block_start("POWER RAILS & SIGNAL LINKS", pad=PAD)
    s.note("POWER RAILS  (global power ports)", 25.4, 25.4, 1.27, bold=True)
    for i, line in enumerate(("+5V    USB-C VBUS -> LDO, load switch",
                              "+3V3   LDO -> ESP32-S3, INA226",
                              "+24V   boost -> limiter -> loop terminal",
                              "GND    single ground plane")):
        s.note(line, 25.4, 30.48 + 2.54 * i, 1.0)
    s.note("SIGNAL LINKS  (net labels)", 25.4, 44.45, 1.27, bold=True)
    for i, line in enumerate(("USB_P / USB_N        USB-C -> ESP32-S3",
                              "I2C_SDA / I2C_SCL    ESP32-S3 -> INA226",
                              "MT_EN                ESP32-S3 -> load switch",
                              "LOOP_V               limiter -> terminal")):
        s.note(line, 25.4, 49.53 + 2.54 * i, 1.0)
    s.block_end()


def build_flat(d):
    s = d.sheet(ROOT_FILE, "ESP32 4-20 mA ESPHome Sensor Board", paper="auto",
                comment="USB-C powered 4-20 mA loop reader with onboard 24 V loop supply")
    for fn in BUILDERS:
        fn(s)
    build_notes(s)
    # relieve=False: the wiring inside each block is hand-drawn and already
    # clean; only the blocks' places on the page are computed
    s.arrange(relieve=False, layout=LAYOUT, gutter=GUTTER)
    if "--sizes" in sys.argv:
        for b in s.blocks:
            e = s.block_extent(b)
            print("  block %-58s %6.1f x %5.1f" % ((b["title"] or "")[:58], e[2] - e[0], e[3] - e[1]))
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="overwrite a sheet changed outside the generator (it is backed up)")
    ap.add_argument("--sizes", action="store_true", help="print each block's size")
    args = ap.parse_args()
    d = Design(PROJDIR, "esp32-4to20ma-board", title="ESP32 4-20 mA ESPHome Sensor Board",
               rev=REV, date=DATE)
    functional_symbols(d)
    build_flat(d)
    d.write(force=args.force, relieve=False)
    ok = d.verify(NETS, NO_CONNECT)
    d.erc()
    d.check_text()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
