# Firmware — ESPHome

ESPHome configuration for the Rev G board. It turns the INA226's shunt reading
into a calibrated 4-20 mA measurement, classifies loop faults to NAMUR NE43,
and protects the board against a sustained field short.

Validated against **ESPHome 2026.9.0**: `esphome config` is clean and
`esphome compile` builds at **867 KB of the 1.835 MB** application partition
(47 %) with 30 % of RAM used, so there is real headroom on the N4 module.

## Files

```
package/esp32-4to20ma-board.yaml   The instrument. Everything hardware-specific
                                   and all the logic. Shared by every board.
loop-sensor-1.yaml                 One board: a name, a Wi-Fi network and the
                                   process scaling. Copy this per unit.
secrets.yaml.example               Copy to secrets.yaml and fill in.
```

The split exists so a logic fix reaches every unit at once. The device file
pulls the package straight from GitHub:

```yaml
packages:
  loop_board: github://Diode663/ESP32_4-20mA_Sensor/firmware/package/esp32-4to20ma-board.yaml@main
```

**Pin a tag rather than `@main`** on any instrument you care about — otherwise
an upstream edit rewrites its firmware the next time you flash it.

When you are working on the package *itself*, switch that line to the
commented `!include` next to it. With `github://` you compile whatever was last
**pushed**, not what is on your disk, which is a confusing half hour if you
forget.

## Getting started

```bash
cp secrets.yaml.example secrets.yaml   # then fill it in
esphome run loop-sensor-1.yaml
```

The first flash has to be over USB. The board enumerates as a native
USB-Serial-JTAG device — there is no bridge chip — so `esphome run` finds it
without a driver on any current OS. If it does not appear, hold **SW2 (BOOT)**,
tap **SW1 (RESET)**, release SW2, and try again.

## Calibrating

**Do this before you trust a reading.** R12 is a 1 % shunt with 200 ppm/°C
drift, and R20 adds a fixed 1.19 % to the voltage reading. A single point
cannot remove both a gain and an offset error, which is why there are two.

1. Wire a loop calibrator into **J2 pins 3 and 2** as if it were a 2-wire
   transmitter — the board supplies the 24 V and the calibrator sinks the
   current. (An active source works too: push into pin 2, return on pin 1, and
   turn *Loop power* off first.)
2. Set **4.000 mA**. Watch `Loop current (raw)` and wait for it to settle —
   the median filter takes about 3 s, so give it ten.
3. Press **Calibrate: capture 4 mA**.
4. Set **20.000 mA**, wait again, press **Calibrate: capture 20 mA**.
5. Read the **Calibration** entity. It reports the pair you captured plus the
   resulting gain and offset, e.g.
   `4mA=4.0123  20mA=19.9871  gain=1.00212  offset=-0.0208 mA`.

A capture is **refused** if the raw reading is more than 2 mA from the
reference, and the log says why. That is deliberate: it stops a mistimed press
silently destroying the calibration.

The result is stored in flash and survives reboots and OTA updates.
**Calibrate: reset to factory** puts back the values compiled into the YAML.

Recalibrate if the board's ambient changes a lot: 200 ppm/°C over a 40 °C swing
is 0.8 % of reading, about 0.13 mA across the span.

## Entities

| Entity | What it is |
|---|---|
| **Process value** | The scaled reading, in your engineering units. Goes **unknown** rather than wrong whenever the loop is not trustworthy |
| **Loop current** | mA, calibrated |
| **Loop fault** | Problem flag — true for any status from "Fault:" down |
| **Loop status** | The text below |
| **Loop power** | `MT_EN`. Off removes the 24 V supply entirely |
| *Loop current (raw)* | mA, uncalibrated. This is what you read while calibrating |
| *Loop supply voltage* | Measured at J2 pin 3, corrected for R20 |
| *Transmitter voltage* | The above, less the drop across the shunt — what the transmitter actually gets. Expect ~22.8 V at 20 mA |
| *Loop span* | Percent of 4-20 mA |
| *Reading valid* | True for OK, under-range and over-range |
| *Calibration* | The captured pair, gain and offset |
| *BOOT button* | SW2, readable as a user button after boot |
| *Board temperature*, *Uptime*, *Wi-Fi signal*, *IP address* | |
| **Buttons** | Capture 4 mA · Capture 20 mA · Reset to factory · Power-cycle the loop · Restart |

*Italic* entities are diagnostic.

## Loop status

| Status | Means | Look at |
|---|---|---|
| `OK` | 4.0–20.0 mA | |
| `Under-range` | 3.8–4.0 mA | Transmitter slightly below zero, or drift |
| `Over-range` | 20.0–20.5 mA | Process above full scale |
| `Fault: low (NAMUR)` | below 3.6 mA | Transmitter signalling a fault, or a poor connection |
| `Fault: high (NAMUR)` | above 21 mA | Transmitter fault, or a partial short. Note the ADC clips at **24.67 mA** — the hardware limiter is higher, at ~33 mA, so a hard short reads as "pegged" |
| `Fault: open circuit` | under 0.1 mA | Nothing connected, or a broken wire |
| `Fault: reversed polarity` | negative current | A sourcing transmitter wired backwards across pins 1 and 2. It is also forward-biasing D5 — fix it |
| `Fault: supply low` | `LOOP_V` under 20 V with current flowing | Too much cable resistance, or a partial short |
| `Fault: field short` | `LOOP_V` under 3 V | The field pair is shorted |
| `Fault: short, latched off` | three cuts in a row | Clear the short, then turn *Loop power* back on |
| `Fault: no sensor data` | the INA226 is not answering | I²C, or the 3.3 V rail |
| `Loop power off` | *Loop power* is off | |

## Short-circuit handling

The hardware limiter holds a dead short at about 33 mA, which puts 0.85 W into
Q1 against a 1.5 W package — survivable, but not something to leave running
unattended for days. So:

`LOOP_V` under 3 V for 3 s → drop `MT_EN` → wait 30 s → retry. After three
failures the board **latches off** and says so, and only a human turning *Loop
power* back on clears it. Ten minutes of healthy running resets the counter, so
an intermittent fault weeks apart never accumulates into a latch.

## Things worth knowing

- **The loop is powered before firmware runs.** R15 is a 100 kΩ pull-up on
  `MT_EN`, so the 24 V comes up with the 3.3 V rail and stays up until ESPHome
  configures GPIO10. The instrument therefore still works with dead firmware —
  but *Loop power* is **not a safety interlock**, and must not be used as one.
- **There is no user LED.** LED1 is hardwired across the 3.3 V rail. All status
  goes to Home Assistant; there is nothing to look at on the board itself.
- **Current comes from the shunt-voltage register**, not the chip's current
  register. The shunt LSB is exactly 2.5 µV, so the conversion is
  deterministic — 753 nA per count — with no integer calibration register
  rounding in the way.
- **4 MB flash, no PSRAM.** The build uses less than half the app partition,
  but anything that pulls in Bluetooth (`esp32_ble_tracker`, `bluetooth_proxy`,
  `esp32_improv`) will not leave room for OTA. Do not add `psram:`.
- **Mains hum is rejected by brute force.** The INA226 has no 50/60 Hz notch
  and no averaging length lands on a whole number of mains cycles, so the
  1100 µs × 128 conversion and the 5-deep median do the work instead.
