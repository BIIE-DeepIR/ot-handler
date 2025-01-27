# Liquid Handling Automation with Opentrons

This project provides a comprehensive solution for automating liquid handling tasks using the Opentrons OT-2 robot. It includes a `LiquidHandler` class for managing labware, pipettes, and modules, as well as a suite of tests to ensure reliable operation.

Before getting started with the liquid handler programming, it's worth reading the list of counter-intuitive quirks to be aware of when working with OpenTrons OT-2: [liquid_handling_quirks.md](./liquid_handling_quirks.md)

## TODO:
- It seems there's two aspirations of air (at two heights) before aspirating the liquid
- force blow out if air gap was added 
- Determine a way to set the offset for liquid handling functions (either by moving wells or by providing a source and destination offset)
- If the volume is within range for both pipettes, choose the larger one (e.g. 20ul in distributing ethanol wash in the magnetic bead purification)


## Features

- **Liquid Handling**: Automate complex liquid handling tasks with support for multi-channel and single-channel pipetting.
- **Labware Management**: Load and manage labware on the OT-2 deck.
- **Module Integration**: Control temperature, shaking, and magnetic modules.
- **Error Handling**: Robust error handling for common issues like deck conflicts and volume mismatches.

## Setup

### Prerequisites

- **Opentrons App**: Ensure you have the latest version of the Opentrons app installed.

### Installation

1. **Clone the Repository**:

    ```bash
    git clone git@github.com:BIIE-DeepIR/opentrons_workflows.git
    cd opentrons_workflows
    ```

2. **Set Up Virtual Environment**:

    ```bash
    python -m venv .venv
    source .venv/bin/activate
    ```

3. **Install Dependencies**:

    ```bash
    pip install -r requirements.txt
    ```

## Usage

It's advised to create a Jupyter notebook for each protocol formatted as `protocol_<protocol name>.ipynb` and sectioning your commands into cells, so you can recover from potential mistakes. You can upload the protocol on the robot by running the `move_content_to_ot2.py` file or double clicking the shortcut on the desktop.

You can run protocols by accessing the Jupyter web server running on the robot at the address: `http://169.254.32.33:48888/notebooks/biie_workflows/` where you might have to use the currently allocated IP address, which you can find in the OpenTrons app (robot settings / Networking).

### Using the LiquidHandler class to distribute liquid

```python
from liquid_handler import LiquidHandler

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

- **WiFi Connection**: It is generally not recommended to connect the OT-2 to WiFi. If necessary, follow the instructions in [opentrons_connection.md](./opentrons_connection.md).
- **SSH Access**: Use SSH to connect to the OT-2 for advanced operations. See [opentrons_connection.md](./opentrons_connection.md) for details.

### Running Tests

The project includes a suite of unit tests to verify the functionality of the `LiquidHandler` class. To run the tests:

``` bash
python -m unittest discover -s ./tests
```
