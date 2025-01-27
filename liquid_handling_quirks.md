# OT-2 native Liquid handling quirks

## Single channel dispensing with multi-channel pipettes

- `transfer` does not work with single tip mode
- Labware in front of the tip rack will cause an error when picking up tips even if it's much shallower than the tip box (e.g. PCR plate in front of the tip rack) (Note: Valentin claims that a reservoir works well on API version 2.13)
- `distribute` and `transfer` does not do multidispense if the volumes are different
- The modules loaded on the deck affects how high the safety distance is. If you have modules on deck, but you don't load them, you risk a collision!
- If the tip pick-up fails (e.g. tips already attached), the next move will be direct to the location and safe z-distance is ignored. This will likely cause a crash!
- It seems to be possible to access a shaking 96 deep well plate with 8-channel pipette by loading a reservoir instead of DWP `usascientific_96_wellplate_2.4ml_deep` and then calling `lh.p300_multi.aspirate(20, mbeads.wells("A1")[0].bottom().move(Point(-0.5, -1, 0)))`. This might also be due to raised exception when starting the shaking, which does not switch the state while shaking starts.

## BIIE LiquidHandler class quirks

- If mix after is on, and the whole volume does not fit in single tip, mixing will happen as many times as the tip volume is dispensed to reach final volume
- Warning is issued if attempting to mix with volume out of liquid handling range
