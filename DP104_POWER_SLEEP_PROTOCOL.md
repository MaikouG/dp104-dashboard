# DP104 Power / Sleep HID Notes

These packet shapes were captured from the official configurator on real hardware.

## Global LED power

Report ID 0:

- OFF: `07 11 01 00` + zero padding
- ON: `07 11 01 01` + zero padding
- followed by `09 11 00` + zero padding

The standalone OFF-only test remained dark until an explicit ON packet was sent.

## Firmware sleep setting

Report ID 0:

- 5 min: `07 11 02 01` + zero padding
- 15 min: `07 11 02 02` + zero padding
- 30 min: `07 11 02 03` + zero padding
- 1 h: value `04`
- 3 h: value `05`
- 6 h: value `06`
- followed by `09 11 00` + zero padding

The v2.3 tray auto-sleep feature does not depend on firmware inactivity timing, because normal dashboard HID refreshes can interfere with that timer.
