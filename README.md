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
- **Submodule Setup**: We assume you are hosting your own GitHub repository for the liquid handling workflow and would like to include the OT Handler as a submodule to be able to edit both repositories while maintaining the dependency.

### Installation

1. **Add OT Handler as a Submodule**:

    ```bash
    git submodule add git@github.com:BIIE-DeepIR/ot-handler.git ./ot_handler
    ```

    **Note**: To keep the submodule up to date, remember to pull from the submodule repository separately using:

    ```bash
    git submodule update --remote
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
lh = LiquidHandler(simulation=True, load_default=False)

# Load tips
lh.load_tips('opentrons_96_tiprack_300ul', "7")

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

### Example: Saving a default layout

You can save your default deck layout to a file called `default_layout.ot2`, which is then loaded whenever `LiquidHandler(load_default=True)` (this is True if not otherwise specified). This way you don't need to load the deck layout on every script, rather, you only load the variable elements.

The easiest way to generate your layout file is by passing `add_to_default=True` to `lh.load_tips`, `lh.load_labware` or `lh.load_module`. This flag saves the default position, so you no longer have to load it. Please note, that any existing item in that deck position will be overwritten by the new object, if there are any conflicts.

```python
from ot_handler.liquid_handler import LiquidHandler

lh = LiquidHandler(simulation=True, load_default=False)
lh.load_tips('opentrons_96_tiprack_300ul', "7", add_to_default=True)
lh.load_tips('opentrons_96_tiprack_300ul', "6", add_to_default=True, single_channel=True)
lh.load_tips('opentrons_96_tiprack_20ul', "11", add_to_default=True, single_channel=True)

lh.load_module(module_name="temperature module gen2", location="4", add_to_default=True)
lh.load_module(module_name="heaterShakerModuleV1", location="10", add_to_default=True)
lh.load_module(module_name="magnetic module gen2", location="9", add_to_default=True)
```

Here's an example of a `default_layout.ot2`, which is the recommended setup.

```json
{
    "labware": {},
    "multichannel_tips": {
        "7": "opentrons_96_tiprack_300ul"
    },
    "single_channel_tips": {
        "6": "opentrons_96_tiprack_300ul",
        "11": "opentrons_96_tiprack_20ul"
    },
    "modules": {
        "4": "temperature module gen2",
        "10": "heaterShakerModuleV1",
        "9": "magnetic module gen2"
    }
}
```

### Example: Rapid development

Below we illustrate the advantages of the LiquidHandler class:

```python
import random
from ot_handler.liquid_handler import LiquidHandler

lh = LiquidHandler(simulation=True)
lh.set_temperature(8)

dna_plate = lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", "2")
reservoir = lh.load_labware("nest_12_reservoir_15ml", "3")

# Adding 25 ul on the first two columns
volumes = [25] * 16

# Adding 10 ul on the third column
volumes += [25] * 8

# Adding random volumes on the rest
volumes += [random.randint(5, 50)] * 8 * 9

# Let's change the well at half point to ensure sufficient volume
source_wells = [reservoir.wells()[0]] * 48 + [reservoir.wells()[1]] * 48

lh.transfer(
    volumes,
    source_wells=source_wells,
    destination_wells=dna_plate.wells(),
    new_tip="once"
)

lh.home()
```

Without the class, the above would require much more programming, such as:

- Loading pipettes and tip racks
- Choosing the right pipette for each volume
- Changing the nozzle layout of the multichannel pipette to single mode and back
- If the volume exceeds the pipette range, repeating the liquid transfer until the volume is reached

In addition, the following operations would not be available on the native OpenTrons python SDK:

- Aspirating liquid once, and dispensing different volumes to multiple wells
- As single channel mode of multichannel mode cannot access the bottom well rows in the first three deck slots, the robot would crash
- Set temperature would be a blocking call

What makes the LiquidHandler particularly powerful is the fact that it optimizes the order of liquid handling operations to be able to cover maximum amount of wells with single aspiration. This effectively reduces time to transfer liquids when contamination is not an issue.

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

### Accessing the log files

In the same folder where you find `liquid_handler.py` you will also find the .log file, `opentrons.log` which contains information about the last run. If something goes wrong, be sure to preserve this log file for troubleshooting.


### Connecting to the OT-2

- **WiFi Connection**: It is generally not recommended to connect the OT-2 to WiFi in the ETH network. If necessary, follow the instructions in [opentrons_connection.md](./opentrons_connection.md).
- **SSH Access**: Use SSH to connect to the OT-2 for advanced operations. See [opentrons_connection.md](./opentrons_connection.md) for details.

### Running Tests

The project includes a suite of unit tests to verify the functionality of the `LiquidHandler` class. To run the tests:

``` bash
python -m unittest discover -s ./tests
```
