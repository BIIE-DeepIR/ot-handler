# Changelog

All notable changes to the OT Handler project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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