# Changelog

All notable changes to the OT Handler project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.2] - 2026-10-01

### Fixed
- `load_liquids()` called over RPyC never recorded anything: `dict()` on the proxied mapping iterated the well names as character sequences (`'B': 'B'` warnings, `ValueError` for three-character names). It now reads `volumes.items()`.

## [0.6.1] - 2026-10-01

### Fixed
- **Tracked aspirations drew air on the OT-2.** 0.6.0 passed `end_location` so the tip would follow the meniscus down while aspirating; that is a Flex feature, and an OT-2 runs the plunger before the tip reaches the liquid (confirmed on the bench: 15 µL of air from a 15 mL tube, then a short dip). A tracked aspiration now uses one fixed location, 2 mm (3 mm in a deep tube) under where the meniscus will stand after the draw.

## [0.6.0] - 2026-10-01

### Added
- **Liquid-level tracking in any well.** `load_liquids(labware, {well: ul})` records what a plate, trough or rack holds (0 marks a well empty). Aspirations from a recorded well whose definition has `innerLabwareGeometry` start `LIQUID_SUBMERGE_MM` (2 mm) under the meniscus and follow it down to the same depth under where it ends (Protocol API 2.24+ `end_location`), never closer than 1 mm to the bottom or under the heater-shaker clearance. The 8-channel takes the lowest level in its column; eight tips in one trough well draw eight times the volume. Deep tubes keep `TUBE_SUBMERGE_MM`, now following the surface too.
- Wells marked empty are tracked as they fill, so an intermediate plate is aspirated from the same way later in the run.

### Changed (behaviour)
- A tracked aspiration into an empty tip first resets the plunger above the well (`prepare_to_aspirate`), which Opentrons requires after a dispense or blow-out.
- Wells without a recorded volume, or labware without inner geometry, are aspirated exactly as before. Opentrons' `meniscus()` targets are not used: on OT-2 GEN2 pipettes they fail for lack of liquid-level-detection settings (`KeyError: 't200'`), so heights come from `current_liquid_height()` and `volume_from_height()`.

## [0.5.0] - 2026-10-01

### Changed (behaviour)
- **Logging is no longer configured on import.** The module used to call `logging.basicConfig(filename="ot_handler.log", level=DEBUG)` for the whole application; it now only emits on the `ot_handler` logger (one child per instance). Applications that relied on `ot_handler.log` appearing in the working directory must pass `log_file=` or configure logging themselves.
- `retention_time`, `sleep()` and `shake(wait=True)` pause through `protocol_api.delay`: the simulator no longer waits in real time and the pauses appear in the run log.
- `transfer()` validates `blow_out_to` with a `ValueError` instead of an `assert`.

### Added
- `log_file=` constructor argument: one log file per LiquidHandler (DEBUG and up), read back with `run_log_text()`, closed by `close()`.
- `close()` and `with LiquidHandler(...) as lh:` end a run explicitly (shaker latch, log file); `__del__` only falls back to it.

### Fixed
- Sources were ordered as text (A10 before A2); wells are now in column-major order everywhere.
- `remove_default_position()` crashed for integer slots and for slots missing from a section.
- The search for `default_layout.ot2` under the working directory never matched.
- `stamp()` raised `NameError` for a non-numeric volume; it raises `TypeError`.
- A log message printed `{old}` literally.
- `blow_out_to` was annotated as `bool`; the air-gap docstring said it was drawn after the liquid.

## [0.4.0] - 2026-10-01

### Changed (behaviour)
- **Protocol API level**: defaults to the lower of 2.28 (the OT-2's ceiling) and what the installed opentrons supports, instead of the newest level. Pass `api_version=` to pin another.
- **Mismatched list lengths** in `transfer()` raise `ValueError` instead of silently running the shorter list. Scalars and one-element lists still apply to every operation.
- **Errors during pipetting**: the tip is emptied into the trash and dropped before anything else happens. Opentrons command failures (`ProtocolEngineError`, `OutOfTipsError`) are still reported in the failure list; any other exception now propagates after the tip is secured.
- **`blow_out_to="source"` / `"source_after_pipetting"`** no longer pool several sources into one tip: each aspiration's leftover goes back to its own source. More moves, no cross-contamination.
- **300 µL tip racks are shared** by the 8-channel and single-tip mode (both ways). Opentrons' tip tracking keeps the modes apart: full columns for the 8-channel, single tips taken from row H upwards, a part-used column finished before a fresh one is opened. Racks loaded for the 8-channel in slots 1–3 stay 8-channel-only. Keep the slot in front of a shared rack free of tall labware, or Opentrons raises `PartialTipMovementNotAllowedError` on single-tip pickup.
- **Deep tubes** (wells deeper than 60 mm, i.e. 15/50 mL conicals; replaces the list of four rack names): the p300 dispenses 10 mm below the rim and never aspirates from or mixes in them; the p20 handles aspiration and, when the tube's volume is known (`set_well_volume()`), pipettes 3 mm under the meniscus instead of at the bottom.
- **Front-row rule** (rows G/H of slots 1–3 go to the p20) now also applies to labware on a module in those slots.
- **`mix()`** groups full columns wherever they appear in the list, hands front-row and deep-tube wells to the p20, works one pipette mode at a time, and parks a pipette's tip before the other one starts. `mix([])` is a no-op.
- **A volume exactly at the pipette minimum** is accepted on every code path.
- **Temperature module** `set_temperature(wait=False)` uses `start_set_temperature`; the thread that stalled the protocol is gone. New `wait_for_temperature()`.
- **Heater-shaker** `shake(wait=False)` starts the shaker once; only the stop is deferred.
- `touch_tip` on labware that forbids it (reservoirs) is skipped with a warning instead of failing at API 2.28.
- `__del__` no longer homes the robot, and no longer masks constructor errors.

### Added
- `set_well_volume(well, volume_ul)`, `wait_for_temperature()`, `set_shaker_clearance()` (heater-shaker pipetting height, from the automation-suite fork), `p20_min_volume=` constructor argument (default 0.5 µL; `None` keeps Opentrons' 1 µL).

### Fixed
- Failures reported against the wrong wells once a volume was split into several cycles, or a transfer spanned several plates.
- `mix_after` and `tip_reuse_limit` dropped when a transfer spanned several plates.
- Pooling into a round well crashed (`width` is `None`); several transfers into the trash crashed.
- The p20 tube-rack rule never fired for destination racks.
- Single-tip steps failed `out_of_tips` with full 8-channel racks on the deck.

## [0.3.0] - 2026-10-01

### Changed
- **Opentrons**: Requires `opentrons>=10.0.0` (pydantic 2). Robots are unaffected: they run their own opentrons, not this package.

## [0.2.1] - 2026-09-30

### Changed
- **Opentrons**: Requires `opentrons>=8.2.0` instead of exactly 8.2.0, so it installs next to opentrons 9.x (pydantic 2).

### Fixed
- **numpy 2.4+**: Aliases the removed `numpy.trapz` to `numpy.trapezoid` before opentrons loads.

## [0.2.0] - 2024-12-19

### Added
- **Tip Reuse Limiting**: New `limit_tip_reuse` parameter allows forcing tip changes after a specified number of uses
- **Advanced Blow-out Control**: New `source_on_tip_change` blow-out behavior for enhanced liquid handling precision
- **Retention Time**: Added `retention_time` parameter for transfers to improve accuracy and allow proper settling
- **Custom Labware Support**: Support for custom labware definitions folder via `labware_folder` parameter in constructor
- **Deck Layout Configuration**: Custom deck layout can be provided via JSON string or file path using `deck_layout` parameter
- **Overhead Liquid & Air Gap Tracking**: Enhanced tracking of overhead liquid and air gap volumes for better precision
- **Graceful Error Recovery**: OutOfTipsError no longer halts all operations - failed operations are tracked and returned with reasons
- **Large Volume Handling**: Operations exceeding pipette max volume are automatically split into manageable operations
- **Column-wise Pipetting**: Optimized pipetting order that prioritizes column-wise operations for improved efficiency
- **Filter Tips Support**: Improved filter tip utilization for full volleys
- **Automatic Resource Management**: Enhanced homing and labware latch management on exit

### Changed
- **Error Handling**: OutOfTipsError exceptions are now caught and handled gracefully, allowing other operations to continue
- **Pipetting Order**: Default pipetting order now prioritizes column-wise operations for better efficiency
- **Volume Allocation**: Improved volume allocation algorithm with better overhead liquid calculations
- **Air Gap Behavior**: Air gap volume reduced to minimum volume for better precision

### Fixed
- **Filter Tips**: Fixed issue where filter tips were not properly utilized for full volleys
- **Multichannel Access**: Improved handling of multichannel pipette access to prevent coordinate loss
- **Large Volume Transfers**: Fixed volume allocations for operations that exceed single pipette capacity
- **Reverse Pipetting**: Improved reverse pipetting functionality to maintain overhead liquid consistency
- **Custom Labware Loading**: Fixed issues with loading adapters on custom modules
- **Simulation Mode**: Removed unnecessary homing operations in simulation mode

### Technical
- Added comprehensive test coverage for new features including tip reuse limits and error handling
- Improved code formatting and linting with Ruff policy
- Enhanced logging and debugging capabilities
- Better resource cleanup and error recovery mechanisms

## [0.1.1] - 2024-11-15

### Changed
- **Log File**: Changed log file name from `opentrons.log` to `ot_handler.log` and moved to working directory
- **Default Layout**: `default_layout.ot2` file is now located in the working directory instead of package directory

### Fixed
- Installation instructions updated for better clarity

## [0.1.0] - 2024-10-01

### Added
- Initial release of OT Handler
- Core `LiquidHandler` class for automating liquid handling tasks
- Support for multi-channel and single-channel pipetting
- Labware and module management capabilities
- Error handling for common issues like deck conflicts and volume mismatches
- Default layout system for rapid development
- Comprehensive test suite
- Documentation and examples