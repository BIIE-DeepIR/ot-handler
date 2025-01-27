# Liquid Handling Automation with Opentrons

This project, OT Handler, provides a comprehensive solution for automating liquid handling tasks and more using the Opentrons OT-2 robot. It includes a `LiquidHandler` class for managing labware, pipettes, and modules, as well as a suite of tests to ensure reliable operation.

Before getting started with the liquid handler programming, it's worth reading the list of counter-intuitive quirks to be aware of when working with OpenTrons OT-2: [liquid_handling_quirks.md](./liquid_handling_quirks.md)

## TODO

- It seems there's two aspirations of air (at two heights) before aspirating the liquid
- Determine a way to set the offset for liquid handling functions (either by moving wells or by providing a source and destination offset)

## Features

- **Liquid Handling**: Automate complex liquid handling tasks with support for multi-channel and single-channel pipetting.
- **Labware Management**: Load and manage labware on the OT-2 deck.
- **Module Integration**: Control temperature, shaking, and magnetic modules.
- **Error Handling**: Robust error handling for common issues like deck conflicts and volume mismatches.

## Setup

### Prerequisites

- **Opentrons App**: Ensure you have the latest version of the Opentrons app installed.
- **Submodule Setup**: We assume you are hosting your own github repository for the liquid handling workflow, and would like to include the OT Handler as a submodule to be able to edit both repositories while maintaining the dependency.

### Installation

1. **Add OT Handler as a Submodule**:

    ```bash
    git submodule add git@github.com:BIIE-DeepIR/ot-handler.git ./ot_handler
    ```

2. **Install Dependencies**:

    ```bash
    pip install -r ot_handler/requirements.txt
    ```

## Usage

### Using the LiquidHandler class to distribute liquid

```python
from ot_handler.liquid_handler import LiquidHandler  # edit path if you cloned the submodule to another path

# Initialize the LiquidHandler in simulation mode
lh = LiquidHandler(simulation=True)

# Load labware
sample_plate = lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 5, "sample plate")
reservoir = lh.load_labware("nest_12_reservoir_15ml", 3, "reservoir")

# Distribute 50 ul of liquid from the first well of the reservoir to each well in the sample plate
# The pipette is chosen automatically, and multi-dispense is used of new_tip is "once" or "on aspiration" or "never"
lh.distribute(
    volumes=50,
    source_well=reservoir.wells()[0],
    destination_wells=sample_plate.wells(),
    new_tip="once")

# Drops tips if any left on the pipettes and homes to robot to a safe position
lh.home()
```

### Example: Using the Opentrons commands

```python
# The pipettes are stored in lh.p300_multi and lh.p20
lh.p300_multi.pick_up_tip()
lh.p300_multi.mix(repetitions=5, volume=100, location=sample_plate.wells("A1"))
lh.p300_multi.drop_tip()

# The protocol api can be accessed through lh.protocol_api
lh.protocol_api.home()
```

### Example: Operating attached modules

```python
# Engage magnets for magnetic bead separation, 5.4mm from labware bottom
lh.engage_magnets(5.4)

# Disengage magnets after separation
lh.disengage_magnets()

# Set the temperature to 8 C, but don't wait until it's reached
lh.set_temperature(
    temperature=8,
    wait=False
)

# Shake for 30 seconds and continue once done
lh.shake(
    speed=1000,
    duration=30,
    wait=True
)
```

### Connecting to the OT-2

- **WiFi Connection**: It is generally not recommended to connect the OT-2 to WiFi in the ETH network. If necessary, follow the instructions in [opentrons_connection.md](./opentrons_connection.md).
- **SSH Access**: Use SSH to connect to the OT-2 for advanced operations. See [opentrons_connection.md](./opentrons_connection.md) for details.

### Running Tests

The project includes a suite of unit tests to verify the functionality of the `LiquidHandler` class. To run the tests:

``` bash
python -m unittest discover -s ./tests
```
