import numpy

# opentrons_shared_data (through 10.x) imports numpy.trapz, removed in numpy 2.4.
# Here as well as in __init__.py so the module also works copied out of the package.
if not hasattr(numpy, "trapz"):
    numpy.trapz = numpy.trapezoid

import opentrons  # noqa: E402
import opentrons.simulate  # noqa: E402
import opentrons.execute
from opentrons.protocol_api.labware import Well, Labware
from opentrons.protocol_api.labware import OutOfTipsError
from opentrons.protocol_api.disposal_locations import TrashBin
from opentrons.protocol_engine.errors import ProtocolCommandFailedError, ProtocolEngineError
from opentrons.protocols.api_support.types import APIVersion
from threading import Timer
import os
import time
import math
import logging
import json

log_filepath = "ot_handler.log"

#: The highest Protocol API level an OT-2 runs (Flex-only levels start at 2.29).
#: The default api_version is the lower of this and what the installed
#: opentrons supports, so a simulator on a new opentrons behaves like the robot.
OT2_MAX_API_LEVEL = APIVersion(2, 28)

#: Wells deeper than this are "deep tubes" (15/50 mL conicals are ~113-118 mm;
#: 1.5 mL tube racks and deep-well plates are under 40 mm). The 8-channel can
#: never reach their bottom - the idle nozzles hit the rack - so it only ever
#: dispenses into them, from just below the rim, and the p20 does the rest.
DEEP_TUBE_DEPTH_MM = 60.0
#: How far below the rim the p300 dispenses into a deep tube.
TUBE_DISPENSE_DEPTH_MM = 10.0
#: How far below the (post-operation) meniscus the p20 pipettes in a deep tube
#: when the tube's liquid volume is known, and the floor it never goes under.
TUBE_SUBMERGE_MM = 3.0
TUBE_MIN_CLEARANCE_MM = 1.0

#: Opentrons dispenses this far above the well bottom unless told otherwise.
OPENTRONS_DEFAULT_CLEARANCE_MM = 1.0

#: The largest lift the heater-shaker can cause: a plate carried entirely on
#: the platform. Not applied by default - it is the upper bound on what
#: ``set_shaker_clearance`` should ever be asked for; the client decides the
#: actual lift per plate from measured gaps.
SHAKER_DISPENSE_CLEARANCE_MM = OPENTRONS_DEFAULT_CLEARANCE_MM + 2.0

#: Errors from a single protocol command (bad volume, tip pickup failure, ...).
#: transfer() records these as failed operations and carries on; anything else
#: (connection loss, hardware faults, bugs) is re-raised after the tip is secured.
RECOVERABLE_ERRORS = (ProtocolEngineError, OutOfTipsError)

logging.basicConfig(
    filename=log_filepath,
    filemode="w",  # use 'w' for overwrite mode, 'a' for append mode
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.DEBUG,
)


class LiquidHandler:
    def __init__(
        self,
        api_version=None,
        load_default: bool = True,
        simulation: bool = False,
        max_volume=None,
        deck_layout=None,
        labware_folder=None,
        p20_min_volume: float = 0.5,
    ):
        """
        Initialize a LiquidHandler instance.

        This constructor sets up the protocol API interface, configures instrument parameters,
        and loads default labware if specified.

        Parameters:
            api_version (str): The protocol API level to use. Defaults to the lower of 2.28 (the OT-2's
                ceiling) and the highest level the installed opentrons supports.
            load_default (bool): Whether to load the default labware configuration from the file 'default_layout.ot2'. Defaults to True.
            simulation (bool): If True, the handler operates in simulation mode. Defaults to False.
            max_volume: Custom maximum volume setting for pipette transfers in ul. If not provided, defaults to the pipette's inherent max volume.
            deck_layout (Union[str, dict]): Path to a JSON file or dictionary containing deck layout configuration. If provided, overrides load_default.
            labware_folder (str): Path to a folder containing labware definitions. If provided, overrides the default labware folder.
            p20_min_volume (float): Smallest volume the p20 is allowed to pipette. Opentrons' own figure is
                1 ul; 0.5 ul is below spec and must be calibrated for on each robot. None keeps Opentrons'.
        """
        # Check for conflicting parameters
        if load_default and deck_layout is not None:
            logging.warning(
                "Both load_default=True and deck_layout provided. The deck_layout will override the default layout."
            )

        if api_version is None:
            api_version = min(opentrons.protocol_api.MAX_SUPPORTED_VERSION, OT2_MAX_API_LEVEL)
        api_version = str(api_version)

        # initialize protocol API
        logging.info(f"Initializing protocol API with version {api_version}")
        if simulation:
            self.protocol_api = opentrons.simulate.get_protocol_api(api_version)
        else:
            self.protocol_api = opentrons.execute.get_protocol_api(api_version)
        self.simulation_mode = simulation
        self.api_version = self.protocol_api.api_version

        # Dispense height for labware riding the heater-shaker. None means
        # Opentrons' own clearance: a robot nobody has instructed behaves
        # exactly as it did before this existed. The client decides, per plate.
        self._shaker_dispense_clearance_mm = None
        # Deep tubes whose liquid level is unknown, warned about once each.
        self._unknown_level_warned = set()

        # default values
        self.p300_tips = []
        self.single_p300_tips = []
        self.p20_tips = []  # Not yet supported
        self.single_p20_tips = []
        self.temperature_timer = None
        self.shaking_timer = None
        self.single_tip_mode = False
        self.p300_multi = None
        self.p20 = None
        self.temperature_module = None
        self.shaker_module = None
        self.magnetic_module = None
        self.labware_folder = (
            labware_folder if labware_folder else os.path.join(os.path.dirname(__file__), "labware")
        )
        self.p300_multi = self.protocol_api.load_instrument(
            "p300_multi_gen2", "right", tip_racks=self.p300_tips
        )
        self.p20 = self.protocol_api.load_instrument(
            "p20_single_gen2", "left", tip_racks=self.single_p20_tips
        )
        if p20_min_volume is not None:
            # Opentrons has no public way to lower a pipette's minimum, so this
            # reaches into the core. Fail loudly if that internal ever moves,
            # rather than silently keeping Opentrons' 1 ul.
            if not callable(getattr(self.p20._core, "get_min_volume", None)):
                raise RuntimeError(
                    "Cannot set the p20 minimum volume: InstrumentCore.get_min_volume is gone "
                    "in this opentrons version. Pass p20_min_volume=None to keep Opentrons' own."
                )
            self.p20._core.get_min_volume = lambda: p20_min_volume

        self.max_volume = max_volume if max_volume else self.p300_multi.max_volume

        # Load deck layout from file/dict or default
        if deck_layout is not None:
            if isinstance(deck_layout, str):
                with open(deck_layout) as f:
                    layout_config = json.load(f)
            else:
                layout_config = deck_layout

            self.load_deck_layout(layout_config)
        # Default labware
        elif load_default:
            self.load_default_labware()

        # load fixed hardware
        logging.info("Loading instruments")
        self.trash = self.protocol_api.fixed_trash

        if len(self.p300_multi.tip_racks) == 0:
            logging.warning(
                "No tip racks confiugured for the pipette. Use lh.p300_multi.configure_nozzle_layout() to load the tips."
            )

        if len(self.p20.tip_racks) == 0:
            logging.warning(
                "No tip racks confiugured for the pipette. Use lh.p20.configure_nozzle_layout() to load the tips."
            )

        logging.info("Closing labware latch")
        self.close_shaker_latch()

        self.home()

    def __del__(self):
        # getattr, not self.simulation_mode: a constructor that failed part way
        # leaves the attribute unset, and the AttributeError raised here then
        # lands on top of - and obscures - whatever actually went wrong.
        if not getattr(self, "simulation_mode", True):
            logging.info("Opening the labware latch as a part of the cleanup procedure.")
            # Deliberately does NOT home: the gantry is parked either way, and
            # it cost the better part of a minute at the end of every run with
            # the operator waiting on it before they could clear the deck.
            self.open_shaker_latch()

    def _count_columns(self, plate_object, sample_count: int):
        """
        Count the number of columns to cover all samples. Used for multichannel pipetting.
        """
        logging.debug(f"Counting columns for {plate_object} with {sample_count} samples")
        total_rows = len(plate_object.columns()[0])
        return math.ceil(sample_count / total_rows) * total_rows

    def _set_single_tip_mode(self, state: bool):
        """
        Set the single tip mode of the p300_multi.
        """
        if state and not self.single_tip_mode:
            if self.p300_multi.has_tip:
                self.p300_multi.drop_tip()
            self.p300_multi.configure_nozzle_layout(
                style=opentrons.protocol_api.SINGLE, start="A1", tip_racks=self.single_p300_tips
            )
            self.single_tip_mode = True
        elif not state and self.single_tip_mode:
            if self.p300_multi.has_tip:
                self.p300_multi.drop_tip()
            self.p300_multi.configure_nozzle_layout(
                style=opentrons.protocol_api.ALL, tip_racks=self.p300_tips
            )
            self.single_tip_mode = False
        return self.single_tip_mode

    def _save_labware_to_default(
        self, labware, model_string, deck_position, is_single_channel=False
    ):
        deck_position = str(deck_position)
        try:
            default_file = os.path.join(os.path.dirname(__file__), "default_layout.ot2")
            if not os.path.isfile(default_file):
                for root, dirs, files in os.walk(os.getcwd()):
                    if default_file in files:
                        default_file = os.path.join(root, default_file)
                        break
            with open(default_file) as f:
                default_layout = json.load(f)
        except FileNotFoundError:
            logging.warning(
                f"The default layout file 'default_layout.ot2' does not exist. Creating an empty file at: {default_file}"
            )
            default_layout = {
                "labware": {},
                "multichannel_tips": {},
                "single_channel_tips": {},
                "modules": {},
            }

        for key in default_layout.keys():
            old = default_layout[key].get(deck_position)
            if old:
                del default_layout[key][deck_position]
                break
        if isinstance(labware, Labware):
            if not labware.is_tiprack:
                default_layout["labware"][deck_position] = model_string
            else:
                if is_single_channel:
                    default_layout["single_channel_tips"][deck_position] = model_string
                else:
                    default_layout["multichannel_tips"][deck_position] = model_string
        else:
            default_layout["modules"][deck_position] = model_string

        with open(default_file, "w") as file:
            json.dump(default_layout, file, indent=4)
        msg = f"{model_string} is now loaded on position {deck_position} by default."
        if old != model_string:
            msg += " This overrides the previous value of {old}."
        logging.info(msg)

    def _allocate_liquid_handling_steps(self, source_wells, destination_wells, volumes):
        """
        Allocates the provided liquid handling operations into three categories optimally:
        - p300 multichannel compatible operations
        - p300 single channel compatible operations
        - p20 single channel compatible operations

        Format for operations: [index, source_well, destination_well, volume]

        Allocation is based on:
        - Volume of each operation
        - Alignment of the operation (column-wise vs. well-wise vs. vertical well like a trough)
        - Accessibility of the p300 pipette in single tip mode

        Raises:
            ValueError: If the number of source wells, destination wells, and volumes do not match.
            ValueError: If a well is used as both a source and destination.
            ValueError: If operations involve different labware.
        """

        def get_column_index(well):
            if isinstance(well, Well):
                return well.well_name[1:]
            if isinstance(well, TrashBin):
                return "1"

        def get_row_index(well):
            if isinstance(well, Well):
                return well.well_name[0]
            if isinstance(well, TrashBin):
                return "A"

        # Check that parameters are compatible with this function
        if not (isinstance(source_wells, list) and source_wells and isinstance(source_wells[0], Well)):
            raise ValueError("The source_wells must be a list of Well objects")
        if not (
            isinstance(destination_wells, list)
            and (
                isinstance(destination_wells[0], Well) or isinstance(destination_wells[0], TrashBin)
            )
        ):
            raise ValueError(
                "The destination_wells must be a list of Well objects or TrashBin objects"
            )
        if not (len(source_wells) == len(destination_wells) == len(volumes)):
            raise ValueError(
                "The number of wells in source and destination must be equal to the number of volumes provided."
            )

        source_labware = source_wells[0].parent
        for well in source_wells:
            if well.parent != source_labware:
                raise ValueError("The operations to allocate must be between up to two labware.")

        if isinstance(destination_wells[0], Well):  # Could also be TrashBin
            destination_labware = destination_wells[0].parent
            for well in destination_wells:
                if well.parent != destination_labware:
                    raise ValueError(
                        "The operations to allocate must be between up to two labware."
                    )

            source_well_names = {well.well_name for well in source_wells}
            destination_well_names = {well.well_name for well in destination_wells}
            if source_labware == destination_labware and source_well_names.intersection(
                destination_well_names
            ):
                raise ValueError(
                    "A well cannot be both a source and destination, because this function cannot be used for order-dependent liquid handling operations."
                )
        else:
            destination_labware = destination_wells[0]

        # Construct helper dictionaries to assist in well allocation
        pipette = self.p300_multi
        column_operations = {}
        large_volume_operations = []
        for i, source, dest, vol in zip(
            range(len(volumes)), source_wells, destination_wells, volumes
        ):
            if vol > pipette.min_volume:
                op = (i, source, dest, vol)
                large_volume_operations.append(op)
                key = (get_column_index(source), get_column_index(dest))
                column_operations.setdefault(key, []).append(op)

        # Search for column-wise operations with equal volumes
        multichannel_operations = []
        multichannel_operations_indexes = []
        for key, column_ops in column_operations.items():
            if len(column_ops) >= 8:
                volumes_set = set(op[3] for op in column_ops)
                for vol in volumes_set:
                    matching_volumes = [
                        op
                        for op in column_ops
                        if op[3] == vol and op[0] not in multichannel_operations_indexes
                    ]
                    # Eight column-wise operations with the same volume exist
                    if len(matching_volumes) >= 8:
                        found = True
                        while found:
                            found = False
                            # Scenario 1: row indexes match and populate the whole column
                            matching_rows = [
                                op
                                for op in matching_volumes
                                if get_row_index(op[1]) == get_row_index(op[2])
                            ]
                            row_indices_source = {get_row_index(op[1]) for op in matching_rows}
                            row_indices_dest = {get_row_index(op[2]) for op in matching_rows}
                            if len(row_indices_source) == 8 and len(row_indices_dest) == 8:
                                # We have 8 addressed unique matching rows. Now capture those operations
                                ops_collection = {get_row_index(op[1]): op for op in matching_rows}

                                if len(ops_collection) == 8:
                                    multichannel_operations.append(ops_collection["A"])
                                    multichannel_operations_indexes.extend(
                                        [op[0] for op in ops_collection.values()]
                                    )
                                    matching_volumes = [
                                        op
                                        for op in matching_volumes
                                        if op[0] not in multichannel_operations_indexes
                                    ]
                                    found = True
                            else:
                                # Scenario 2: source or destination well can fit all multichannel pipettes
                                # Find a well that is present at least 8 times
                                source_well_names = [op[1].well_name for op in matching_volumes]
                                destination_well_names = [
                                    op[2].well_name if isinstance(op[2], Well) else "A1"
                                    for op in matching_volumes
                                ]
                                source_well_count = {}
                                destination_well_count = {}
                                for well_name in source_well_names:
                                    source_well_count[well_name] = (
                                        source_well_count.get(well_name, 0) + 1
                                    )
                                for well_name in destination_well_names:
                                    destination_well_count[well_name] = (
                                        destination_well_count.get(well_name, 0) + 1
                                    )

                                source_troughs = []
                                for name, count in source_well_count.items():
                                    well = source_labware.wells(name)[0]
                                    if count >= 8 and hasattr(well, "width") and well.width and well.width > 70:
                                        source_troughs.append(well)

                                destination_troughs = []
                                if isinstance(destination_labware, TrashBin):
                                    destination_troughs.append(destination_labware)
                                else:
                                    for name, count in destination_well_count.items():
                                        well = destination_labware.wells(name)[0]
                                        if (
                                            count >= 8
                                            and (getattr(well, "width", None) or 0) > 70
                                        ):
                                            destination_troughs.append(well)
                                # Check transfers between troughs and columns
                                check_set = [
                                    (source_troughs, destination_troughs, 2, 1),
                                    (destination_troughs, source_troughs, 1, 2),
                                ]
                                for primary, secondary, idxa, idxb in check_set:
                                    for well in primary:
                                        # Primary is a trough
                                        ops = [
                                            op
                                            for op in matching_volumes
                                            if op[idxb] == well
                                            and op[0] not in multichannel_operations_indexes
                                        ]
                                        if len(ops) >= 8:
                                            found2 = True
                                            while found2:
                                                found2 = False
                                                # Scenario 1: secondary is a column
                                                ops_collection = {
                                                    get_row_index(op[idxa]): op for op in ops
                                                }
                                                if len(ops_collection) == 8:
                                                    multichannel_operations.append(
                                                        ops_collection["A"]
                                                    )
                                                    multichannel_operations_indexes.extend(
                                                        [op[0] for op in ops_collection.values()]
                                                    )
                                                    ops = [
                                                        op
                                                        for op in ops
                                                        if op[0]
                                                        not in multichannel_operations_indexes
                                                    ]
                                                    found = True
                                                    found2 = True
                                                else:
                                                    # Scenario 2: secondary is a trough
                                                    for dest_well in secondary:
                                                        trough_to_trough = [
                                                            op for op in ops if op[2] == dest_well
                                                        ]
                                                        while len(trough_to_trough) >= 8:
                                                            # Operations are identical; add the first one
                                                            multichannel_operations.append(
                                                                trough_to_trough[0]
                                                            )
                                                            multichannel_operations_indexes.extend(
                                                                [
                                                                    op[0]
                                                                    for op in trough_to_trough[:8]
                                                                ]
                                                            )
                                                            del trough_to_trough[:8]
                                                            found = True
                                                            found2 = True
                                                            ops = [
                                                                op
                                                                for op in ops
                                                                if op[0]
                                                                not in multichannel_operations_indexes
                                                            ]

        allocated_operations = multichannel_operations_indexes
        p300_single_ops = []
        p20_ops = []
        for op in large_volume_operations:
            if op[0] in allocated_operations:
                continue
            if self._needs_p20(op[1], op[2]):
                p20_ops.append(op)
            else:
                p300_single_ops.append(op)
            allocated_operations.append(op[0])

        for i in range(len(volumes)):
            if i not in allocated_operations:
                p20_ops.append(
                    [i, source_wells[i], destination_wells[i], volumes[i]]
                )  # i is the original index

        return multichannel_operations, p300_single_ops, p20_ops

    def _find_parent(self, well: Well):
        while not isinstance(well, str):
            well = well.parent
        return well

    def _slot_of(self, well):
        """The deck slot ("1".."11") holding a well, through any module; None for the trash."""
        if isinstance(well, TrashBin):
            return None
        return self._find_parent(well)

    def _is_deep_tube(self, well) -> bool:
        """Deep tube (15/50 mL conical): the 8-channel can't reach its bottom, see DEEP_TUBE_DEPTH_MM."""
        return isinstance(well, Well) and (well.depth or 0) > DEEP_TUBE_DEPTH_MM

    def _in_front_row(self, well) -> bool:
        """Rows G/H of slots 1-3: the 8-channel's idle nozzles would hit the robot's front."""
        return (
            isinstance(well, Well)
            and self._slot_of(well) in ("1", "2", "3")
            and well.well_name[0] in ("G", "H")
        )

    def _needs_p20(self, source, destination) -> bool:
        """Whether a single-well operation must use the p20 rather than the 8-channel in single-tip mode.

        - Front-row wells (rows G/H, slots 1-3), on the deck or on a module there.
        - Aspirating from a deep tube: the 8-channel never reaches its liquid.
          Dispensing into one is fine, the p300 does it from below the rim.
        """
        return (
            self._in_front_row(source)
            or self._in_front_row(destination)
            or self._is_deep_tube(source)
        )

    def _pipetting_location(self, well, pipette):
        """Where a pipette aspirates/dispenses/mixes in ``well``.

        - 8-channel into a deep tube: TUBE_DISPENSE_DEPTH_MM below the rim; it can't go deeper.
        - p20 in a deep tube whose liquid volume is known (``set_well_volume`` or Opentrons'
          ``load_liquid``): TUBE_SUBMERGE_MM under the meniscus, never closer than
          TUBE_MIN_CLEARANCE_MM to the bottom. A tip and nozzle driven to the bottom of a
          full tube displace enough to overflow it. Opentrons updates the level after every
          aspirate and dispense; a p20's 20 ul moves a 15 mL tube's meniscus ~0.2 mm, so the
          pre-operation level is used as is. Unknown level: the bottom, as before, with one
          warning per tube.
        - Labware on the heater-shaker: lifted by the configured clearance.
        - Everything else: Opentrons' default (1 mm above the bottom).
        """
        if not isinstance(well, Well):
            return well
        if self._is_deep_tube(well):
            if pipette is self.p300_multi:
                return well.top(-TUBE_DISPENSE_DEPTH_MM)
            try:
                height = float(well.current_liquid_height())
            except Exception as e:  # LiquidHeightUnknownError, or an opentrons too old for it
                if well not in self._unknown_level_warned:
                    self._unknown_level_warned.add(well)
                    logging.warning(
                        f"Liquid level of {well} unknown ({type(e).__name__}); pipetting at the "
                        "bottom. Call set_well_volume() first to keep the tip near the surface."
                    )
                return self._shaker_location(well)
            return well.bottom(max(TUBE_MIN_CLEARANCE_MM, height - TUBE_SUBMERGE_MM))
        return self._shaker_location(well)

    def set_well_volume(self, well: Well, volume_ul: float, name: str = None):
        """Tell Opentrons how much liquid a well holds, so deep-tube pipetting can track the level.

        Opentrons then keeps the figure current through every aspirate and dispense.
        Needs Protocol API 2.14 or later; older levels log a warning and track nothing.
        """
        try:
            liquid = self.protocol_api.define_liquid(name or f"{well.parent.load_name} {well.well_name}")
            well.load_liquid(liquid, volume_ul)
        except Exception as e:  # APIVersionError on old levels
            logging.warning(f"Cannot record the liquid volume of {well}: {e}")

    def _touch_tip(self, pipette, well):
        """touch_tip, skipped with a warning where the labware forbids it.

        Reservoirs and other wide labware carry Opentrons' ``touchTipDisabled`` quirk.
        Protocol API 2.28 turned the skip-with-warning into an error; keep the old behaviour.
        """
        if isinstance(well, Well) and "touchTipDisabled" in well.parent.quirks:
            logging.warning(f"Touch tip skipped: not allowed on {well.parent.load_name}")
            return
        pipette.touch_tip(v_offset=-1)

    def _secure_tip(self, pipette):
        """After a failed command: empty the tip into the trash and drop it.

        Otherwise the next aspiration starts with the previous source's liquid
        still in the tip and contaminates the new source.
        """
        try:
            if pipette.has_tip:
                if pipette.current_volume:
                    pipette.blow_out(self.trash)
                pipette.drop_tip()
        except Exception as e:  # noqa: BLE001 - best effort, the original error matters more
            logging.error(f"Could not secure the tip of {pipette}: {e}")

    def set_shaker_dispense_clearance(self, clearance_mm=SHAKER_DISPENSE_CLEARANCE_MM):
        """Backwards-compatible alias for ``set_shaker_clearance``."""
        return self.set_shaker_clearance(clearance_mm)

    def set_shaker_clearance(self, clearance_mm=SHAKER_DISPENSE_CLEARANCE_MM):
        """Override the height used for labware on the heater-shaker.

        Pass None to pipette in shaker labware at Opentrons' own clearance,
        like any other plate. Returns the value in force.
        """
        self._shaker_dispense_clearance_mm = clearance_mm
        logging.info("Shaker dispense clearance set to %s mm", clearance_mm)
        if clearance_mm and self._labware_on_shaker() is None:
            logging.warning(
                "Shaker dispense clearance set to %s mm but no labware is on the "
                "heater-shaker - the clearance will not apply to anything",
                clearance_mm,
            )
        return self._shaker_dispense_clearance_mm

    def _labware_on_shaker(self):
        """The labware currently riding the heater-shaker, if any."""
        module = getattr(self, "shaker_module", None)
        if module is None:
            return None
        return getattr(module, "labware", None)

    def _shaker_location(self, destination):
        """A well location, raised when its labware rides the heater-shaker.

        A plate on the module sits slightly proud of where the deck model puts
        it, so a tip aimed at the modelled bottom can meet the real one. Applies
        to aspiration and dispensing alike. Only the passed location is rebased;
        the well itself is left alone because blow-outs call ``.top()`` on it.
        """
        clearance = getattr(self, "_shaker_dispense_clearance_mm", None)
        if not clearance:
            return destination
        on_shaker = self._labware_on_shaker()
        if on_shaker is None or getattr(destination, "parent", None) is not on_shaker:
            return destination
        try:
            return destination.bottom(clearance)
        except AttributeError:
            return destination

    def home(self):
        """
        Home the robot to its initial position.

        This method ensures that the robot's pipettes and other movable components
        return to their default starting positions. It is typically used at the
        beginning or end of a protocol to ensure that the robot is in a known state.

        This method also drops any tips that are currently held by the pipettes
        to prevent contamination or errors in subsequent operations.
        """
        self.drop_tips(True)
        logging.debug("Homing...")
        self.protocol_api.home()

    def toggle_light(self, state: bool = True):
        """
        Toggles the light of the OT-2 robot based on the provided state.

        Parameters:
            state (bool): If True, turn on the light; if False, turn off the light.
        TODO: Does not work
        """
        logging.debug(f"Setting OT-2 light to {'on' if state else 'off'}")
        self.protocol_api.set_rail_lights(state)

    def sleep(self, duration):
        "Sleep if not in simulation mode"
        if self.simulation_mode:
            pass
        else:
            time.sleep(duration)

    def remove_default_position(self, deck_position):
        default_file = os.path.join(os.path.dirname(__file__), "default_layout.ot2")
        if not os.path.isfile(default_file):
            for root, dirs, files in os.walk(os.getcwd()):
                if default_file in files:
                    default_file = os.path.join(root, default_file)
                    break
        with open(default_file) as f:
            default_layout = json.load(f)

        for key, _ in default_layout.items():
            del default_layout[key][deck_position]

        with open(default_file, "w") as file:
            json.dump(default_layout, file, indent=4)

    def load_deck_layout(self, layout_config: dict):
        """
        Load deck configuration from a dictionary containing labware, tips, and module specifications.

        Parameters:
            layout_config (dict): Dictionary containing deck layout configuration with the following structure:
                {
                    "modules": {deck_position: model_string, ...},
                    "multichannel_tips": {deck_position: model_string, ...},
                    "single_channel_tips": {deck_position: model_string, ...},
                    "labware": {deck_position: model_string, ...}
                }
        """
        # Load modules first
        for deck_position, model_string in layout_config.get("modules", {}).items():
            self.load_module(model_string, deck_position)

        # Load multichannel tips
        for deck_position, model_string in layout_config.get("multichannel_tips", {}).items():
            self.load_tips(model_string, deck_position, single_channel=False)

        # Load single channel tips
        for deck_position, model_string in layout_config.get("single_channel_tips", {}).items():
            self.load_tips(model_string, deck_position, single_channel=True)

        # Load other labware
        for deck_position, model_string in layout_config.get("labware", {}).items():
            self.load_labware(model_string, deck_position)

    def load_default_labware(self):
        """
        Load the default labware configuration from the default_layout.ot2 file.
        This method reads a JSON dictionary and loads each labware onto the deck.
        """
        logging.info("Loading default labware from default_layout.ot2...")
        try:
            default_file = os.path.join(os.path.dirname(__file__), "default_layout.ot2")
            if not os.path.isfile(default_file):
                for root, dirs, files in os.walk(os.getcwd()):
                    if default_file in files:
                        default_file = os.path.join(root, default_file)
                        break
            with open(default_file) as f:
                default_layout = json.load(f)

            for deck_position, model_string in default_layout["multichannel_tips"].items():
                self.load_tips(model_string, deck_position, single_channel=False)

            for deck_position, model_string in default_layout["single_channel_tips"].items():
                self.load_tips(model_string, deck_position, single_channel=True)

            for location, model_name in default_layout["modules"].items():
                self.load_module(model_name, location)

            for deck_position, model_string in default_layout["labware"].items():
                self.load_labware(model_string, deck_position)

        except FileNotFoundError:
            logging.error("No default layout file found. No default labware loaded")

    def load_labware(
        self, model_string: str, deck_position: int, name: str = "", add_to_default=False
    ):
        """
        Load a specified labware onto the deck at a given position. If the designated position is occupied by a module,
        the labware will be loaded onto that module.

        Args:
            model_string (str): The model string of the labware to be loaded.
            deck_position (int): The position on the deck where the labware should be placed.
            name (str): An optional name for the labware. If not provided, the model string will be used as the name.
            add_to_default (bool): If True, adds the loaded labware to the default layout configuration.

        Returns:
            The loaded labware object.

        Example:
        >>> lh.load_labware("opentrons_10_tuberack_falcon_4x50ml_6x15ml_conical", 8, "Falcon tube rack")
        """
        logging.debug(f"Loading labware: {model_string} on position {deck_position}...")

        if not name:
            name = model_string

        deck_position = str(deck_position)

        # Check that the deck position is empty
        on_module = False
        if self.protocol_api.deck[deck_position] is not None:
            try:
                self.protocol_api.deck[deck_position].type
                on_module = True
            except AttributeError:
                raise ValueError(
                    f"Deck position {deck_position} is already occupied. Please choose an empty position."
                )

        if on_module:
            logging.debug("Loading labware on the module")
            try:
                labware = self.protocol_api.deck[deck_position].load_labware(model_string)
            except Exception:
                # The model string could match a custom labware file on the system
                with open(f"{self.labware_folder}/{model_string}.json") as labware_file:
                    labware_def = json.load(labware_file)
                labware = self.protocol_api.deck[deck_position].load_labware_from_definition(
                    labware_def, None
                )
        else:
            logging.debug("Loading labware on an empty slot")
            try:
                labware = self.protocol_api.load_labware(model_string, deck_position, label=name)
            except ProtocolCommandFailedError:
                # The model string could match a custom labware file on the system
                with open(f"{self.labware_folder}/{model_string}.json") as labware_file:
                    labware_def = json.load(labware_file)
                labware = self.protocol_api.load_labware_from_definition(labware_def, deck_position)

        # Log the loading of the labware
        if on_module:
            msg = f"Loaded labware {model_string} at position {self.protocol_api.deck[deck_position]} with name '{name}'"
        else:
            msg = f"Loaded labware {model_string} at position {deck_position} with name '{name}'"
        logging.info(msg)

        if add_to_default and not labware.is_tiprack:
            self._save_labware_to_default(labware, model_string, deck_position)
        return labware

    def load_tips(
        self,
        model_string: str,
        deck_position: int,
        single_channel: bool = False,
        add_to_default: bool = False,
    ):
        """
        Load tips into the specified deck position, and add them to the corresponding pipettes, if loaded.

        Args:
            model_string (str): The model string of the tip rack to load.
            deck_position (int): The position on the deck where the tip rack should be loaded.
            single_channel (bool): If True, load the tips in for single channel mode; defaults to False.
            add_to_default (bool): If True, add the loaded labware to the default layout; defaults to False.
        """

        labware = self.load_labware(model_string, deck_position, add_to_default=False)
        if labware.is_tiprack:
            if single_channel:
                if labware.tip_length > 50:
                    # Every 300 ul rack is a full 8x12 rack, so both modes draw from it.
                    # Opentrons tracks the tips per rack: the 8-channel takes full
                    # columns only, single-tip mode works a column up from row H
                    # and finishes a part-used column before opening a fresh one.
                    self.single_p300_tips.append(labware)
                    self.p300_tips.append(labware)
                    if self.p300_multi is not None and not self.single_tip_mode:
                        self.p300_multi.tip_racks = self.p300_tips
                else:
                    self.single_p20_tips.append(labware)
                    if self.p20 is not None:
                        self.p20.tip_racks = self.single_p20_tips
            else:
                if labware.tip_length > 50:
                    self.p300_tips.append(labware)
                    if self.p300_multi is not None and not self.single_tip_mode:
                        self.p300_multi.tip_racks = self.p300_tips
                    # Shared with single-tip mode, except in the front row: a single
                    # pickup starts at row H with the idle nozzles hanging in front of
                    # the rack, which in slots 1-3 is the robot's front frame.
                    if str(deck_position) not in ("1", "2", "3"):
                        self.single_p300_tips.append(labware)
                    else:
                        logging.info(
                            f"Tip rack in slot {deck_position} serves the 8-channel only; "
                            "single-tip pickups at row H would reach past the deck front."
                        )
                else:
                    self.p20_tips.append(labware)
                    raise NotImplementedError("Multichannel p20 pipette is not yet supported.")
            if "200ul" in model_string and self.max_volume > 200:
                logging.info(
                    f"Limiting the maximum transfer volume from {self.max_volume} to 200ul due to tip size limit."
                )
                self.max_volume = 200
            if add_to_default:
                self._save_labware_to_default(
                    labware, model_string, deck_position, is_single_channel=single_channel
                )

        else:
            logging.error(
                "A model string was passed to load_tips, which doesn't correspond to a tip rack. Labware is unloaded."
            )
            self.unload_labware(labware)
            return False

        return labware

    def unload_labware(self, labware):
        if isinstance(labware, opentrons.protocol_api.labware.Labware):
            self.unload_labware_from_slot(labware.location)
        else:
            raise ValueError("Labware is not a valid labware object.")

    def unload_labware_from_slot(self, slot):
        del self.protocol_api.deck[slot]

    def load_module(self, module_name: str, location: int, add_to_default=False):
        module = self.protocol_api.load_module(module_name, location)
        if "temperature" in module_name.lower():
            self.temperature_module = module
        elif "magnetic" in module_name.lower():
            self.magnetic_module = module
        elif "shaker" in module_name.lower():
            self.shaker_module = module
        else:
            raise ValueError(f"Module name {module_name} is invalid or not yet supported.")

        if add_to_default:
            self._save_labware_to_default(module, module_name, location)

        return module

    def set_temperature(self, temperature: float, wait: bool = False):
        """
        Set the temperature of the temperature module.

        Args:
            temperature (float): The target temperature to set.
            wait (bool): If True, wait for the temperature to be set before returning. If False, set the temperature in a separate thread.
        """
        if not self.temperature_module:
            raise Exception("No temperature module has been loaded on the deck.")
        if wait:
            self.temperature_module.set_temperature(temperature)
        else:
            # start_set_temperature, not a thread around the blocking
            # set_temperature: that thread's wait ran on the shared hardware
            # loop and stalled the whole protocol until the block was at
            # temperature. This sets the target and returns.
            self.temperature_module.start_set_temperature(temperature)
        self.temperature_timer = None

    def wait_for_temperature(self):
        """Block until the temperature module reaches the target set with ``set_temperature(wait=False)``."""
        if not self.temperature_module:
            raise Exception("No temperature module has been loaded on the deck.")
        if self.temperature_module.target is not None:
            self.temperature_module.await_temperature(self.temperature_module.target)

    def release_temperature(self):
        """
        Release the temperature module by deactivating it.
        """
        if not self.temperature_module:
            raise Exception("No temperature module has been loaded on the deck.")
        self.temperature_module.deactivate()
        self.temperature_timer = None

    def open_shaker_latch(self):
        """
        Open the shaker module's labware latch.
        """
        if self.shaker_module:
            try:
                self.shaker_module.open_labware_latch()
            except Exception:
                pass

    def close_shaker_latch(self):
        """
        Close the shaker module's labware latch.
        """
        if self.shaker_module:
            try:
                self.shaker_module.close_labware_latch()
            except Exception:
                pass

    def shake(self, speed: float, duration: float, wait: bool = False):
        """
        Shake the shaker module.

        Args:
            speed (float): The speed (rpm) to shake the shaker module at.
            duration (float): The duration (s) to shake the shaker module for.
            wait (bool): If True, wait for the shaking to finish before returning. If False, shake the shaker module in a separate thread if duration > 0.

        TODO:
        - Check that the labware latch is closed. Same for other functions
        - Stop shaking and finish of this command should open the latch
        """
        if not self.shaker_module:
            raise Exception("No shaker module has been loaded on the deck.")
        if self.shaking_timer is not None:
            self.shaking_timer.cancel()
            self.shaking_timer = None
        self.start_shaking(speed)
        if duration > 0:
            if wait:
                self.protocol_api.delay(seconds=duration)
                self.stop_shaking()
            else:
                # Only the stop is deferred; the old thread re-ran shake() and
                # so started the shaker a second time.
                self.shaking_timer = Timer(duration, self.stop_shaking)
                self.shaking_timer.daemon = True
                self.shaking_timer.start()

    def start_shaking(self, speed: float):
        """
        Start shaking the shaker module.
        """
        if not self.shaker_module:
            raise Exception("No shaker module has been loaded on the deck.")
        self.shaker_module.set_and_wait_for_shake_speed(speed)

    def stop_shaking(self):
        """
        Stop shaking the shaker module.
        """
        if not self.shaker_module:
            raise Exception("No shaker module has been loaded on the deck.")
        self.shaker_module.deactivate_shaker()

    def drop_tips(self, trash_tips=True):
        """
        Drop or return tips for the p20 and p300_multi pipettes.

        This method handles the disposal or return of tips for the p20 and p300_multi pipettes
        based on the `trash_tips` parameter. If `trash_tips` is True, the tips are dropped into
        the trash. If False, the tips are returned to their respective tip racks.

        Parameters:
        - trash_tips (bool, optional): Determines whether to discard the tips (True) or return them
          to the tip rack (False). Default is True.

        This method ensures that the pipettes do not retain tips after operations, which is crucial
        for maintaining cleanliness and preventing cross-contamination in subsequent operations.
        """
        if self.p20.has_tip:
            if trash_tips:
                self.p20.drop_tip()
            else:
                self.p20.return_tip()
        if self.p300_multi.has_tip:
            if trash_tips:
                self.p300_multi.drop_tip()
            else:
                self.p300_multi.return_tip()

    def transfer(
        self,
        volumes,
        source_wells,
        destination_wells,
        new_tip: str = "once",
        touch_tip: bool = False,
        blow_out_to: str = "trash",
        trash_tips: bool = True,
        add_air_gap: bool = True,
        overhead_liquid: bool = True,
        mix_after: bool = False,
        retention_time: float = 0.0,
        tip_reuse_limit: int = None,
        **kwargs,
    ):
        """
        Transfer specified volumes of liquid from source wells to destination wells.

        This method handles the transfer of liquid between specified source and destination wells
        using the available pipettes. It supports various configurations for tip usage, air gaps,
        and liquid handling parameters.

        Parameters:
        - volumes (list of float): The volumes of liquid to transfer for each operation.
        - source_wells (list of Well): The wells from which liquid will be aspirated.
        - destination_wells (list of Well): The wells to which liquid will be dispensed.
        - new_tip (str, optional): Strategy for using tips. Options are "once", "always", "on aspiration", or "never".
        - touch_tip (bool, optional): Whether to touch the tip to the side of the well after aspirating or dispensing.
        - blow_out_to (str, optional): Whether the remainder of liquid is blown out to "source", "destination", "trash", or "source_after_pipetting". Empty string will result in no blow-out, which can be used e.g. for reverse pipetting. The "source_after_pipetting" option keeps overhead liquid and air gap through operations and blows out to source when the tip is about to be changed or dropped, and also at the end of all transfers.
        - trash_tips (bool, optional): Whether to discard tips after use.
        - add_air_gap (bool, optional): Whether to add an air gap after aspiration. When enabled, the air gap volume equals the minimum pipette volume and reduces the effective maximum volume.
        - overhead_liquid (bool, optional): Whether to aspirate extra liquid to ensure complete transfer.
        - mix_after (tuple, optional): First element is repetitions and second element is volume of mixing at the destination well after dispense. False when no mixing needed. Will block multi-dispense mode.
        - retention_time (float, optional): time to wait in seconds after every aspiration & dispense prior to moving on. Defaults to 0.0 s. Helps viscous liquids to populate the tip fully.
        - tip_reuse_limit (int, optional): Maximum number of aspiration-dispense cycles before forcing a tip change, even when new_tip is "never" or "once". If None (default), no limit is enforced.
        - **kwargs: Additional keyword arguments for pipette operations.


        Returns:
        - list: A list of failed operations, each represented as [source, destination, volume, index, reason].
          The reason field explains why the operation failed (e.g., "volume_too_low", "out_of_tips", "pipette_error").
          Please note that even if an operation fails, it might have already aspirated liquid and been partially executed.

        Note:
        - The method gracefully handles OutOfTipsError by continuing with operations that don't involve the pipette
          that ran out of tips, and returning the operations that failed due to lack of tips.
        """
        logging.debug(f"Transfer called with new tip: {new_tip}")

        # A scalar or a one-element list applies to every operation; any other
        # length must match. Silently running the shorter list, as this used
        # to, skipped steps without a word.
        as_list = lambda x: list(x) if isinstance(x, (list, tuple)) else [x]  # noqa: E731
        volumes, source_wells, destination_wells = (
            as_list(volumes), as_list(source_wells), as_list(destination_wells)
        )
        operations_length = max(len(volumes), len(source_wells), len(destination_wells))
        lengths = {
            "volumes": len(volumes),
            "source_wells": len(source_wells),
            "destination_wells": len(destination_wells),
        }
        bad = [f"{k}={n}" for k, n in lengths.items() if n not in (1, operations_length)]
        if bad:
            raise ValueError(
                f"transfer() lists must have one element or {operations_length} "
                f"(the longest); got {', '.join(bad)}"
            )
        volumes = volumes * operations_length if len(volumes) == 1 else volumes
        source_wells = source_wells * operations_length if len(source_wells) == 1 else source_wells
        destination_wells = (
            destination_wells * operations_length
            if len(destination_wells) == 1
            else destination_wells
        )
        # Parameter validation
        assert blow_out_to in ["source", "destination", "trash", "source_after_pipetting", ""], (
            "The parameter blow_out_to must always be defined and one of source, destination, trash, source_after_pipetting or empty string. Blow out happens only if there's air gap or overhead liquid"
        )

        # Check for volumes exceeding effective pipette max volume (accounting for overhead liquid and air gap)
        air_gap_volume = self.p300_multi.min_volume if add_air_gap else 0
        overhead_volume = self.p300_multi.min_volume if overhead_liquid else 0
        effective_max_single_volume = self.max_volume - overhead_volume - air_gap_volume
        new_operations = []
        # The caller's operation index behind each split operation. Everything
        # below indexes the split list; failures are reported against the
        # caller's list, or a failed chunk of one well lands on another well.
        caller_index = []
        for op_index, operation in enumerate(
            [[v, s, d] for v, s, d in zip(volumes, source_wells, destination_wells)]
        ):
            volume = operation[0]
            chunks_before = len(new_operations)
            while volume > effective_max_single_volume:
                if volume > effective_max_single_volume + self.p300_multi.min_volume:
                    new_operations.append([effective_max_single_volume, operation[1], operation[2]])
                    volume -= effective_max_single_volume
                else:
                    split_volume = volume / 2
                    new_operations.append([split_volume, operation[1], operation[2]])
                    new_operations.append([split_volume, operation[1], operation[2]])
                    volume = 0
            if volume > 0:
                new_operations.append([volume, operation[1], operation[2]])
            caller_index += [op_index] * (len(new_operations) - chunks_before)
        volumes, source_wells, destination_wells = [list(lst) for lst in zip(*new_operations)] if new_operations else ([], [], [])

        def to_caller_indices(failed):
            """Re-key failures from split-list indices to the caller's, one per operation."""
            out = []
            for failure in sorted(failed, key=lambda x: x[3]):
                index = failure[3]
                if 0 <= index < len(caller_index):
                    index = caller_index[index]
                if index >= 0 and index in [o[3] for o in out]:
                    continue
                out.append([*failure[:3], index, *failure[4:]])
            return out

        # Split the liquid handling operations so that the source wells are within one labware, and destination wells too
        source_labware = {well.parent for well in source_wells}
        destination_labware = {
            well.parent if isinstance(well, Well) else well for well in destination_wells
        }
        transfer_params = {
            "new_tip": new_tip,
            "touch_tip": touch_tip,
            "blow_out_to": blow_out_to,
            "trash_tips": trash_tips,
            "add_air_gap": add_air_gap,
            "overhead_liquid": overhead_liquid,
            "mix_after": mix_after,
            "retention_time": retention_time,
            "tip_reuse_limit": tip_reuse_limit,
            **kwargs,
        }
        failed_operations = []
        done = False
        if len(source_labware) > 1:
            for labware in source_labware:
                # Take a fresh tip only for the first call
                if transfer_params["new_tip"] == "once" and done:
                    transfer_params["new_tip"] = "never"
                indexes = [i for i, well in enumerate(source_wells) if well.parent == labware]
                for failure in self.transfer(
                    [volumes[i] for i in indexes],
                    [source_wells[i] for i in indexes],
                    [destination_wells[i] for i in indexes],
                    **transfer_params,
                ):
                    # The sub-call reports against its own slice of the list.
                    if 0 <= failure[3] < len(indexes):
                        failure[3] = indexes[failure[3]]
                    failed_operations.append(failure)
                done = True
        elif len(destination_labware) > 1:
            for labware in destination_labware:
                # Take a fresh tip only for the first call
                if transfer_params["new_tip"] == "once" and done:
                    transfer_params["new_tip"] = "never"
                indexes = [
                    i
                    for i, well in enumerate(destination_wells)
                    if well.parent == labware or well == labware
                ]
                for failure in self.transfer(
                    [volumes[i] for i in indexes],
                    [source_wells[i] for i in indexes],
                    [destination_wells[i] for i in indexes],
                    **transfer_params,
                ):
                    # The sub-call reports against its own slice of the list.
                    if 0 <= failure[3] < len(indexes):
                        failure[3] = indexes[failure[3]]
                    failed_operations.append(failure)
                done = True
        if done:
            return to_caller_indices(failed_operations)

        def add_failed_pipette_operations(
            pipette_name: str, orig_idx: int, failed_operations: list, failure_reason: str
        ):
            added_indexes = []
            if pipette_name == "p300_multi":
                # Recreate the original operations
                hidden_source_wells = source.parent.columns()[int(source.well_name[1:]) - 1]
                if len(hidden_source_wells) == 1:
                    hidden_source_wells = hidden_source_wells * 8

                hidden_destination_wells = destination.parent.columns()[
                    int(destination.well_name[1:]) - 1
                ]
                if len(hidden_destination_wells) == 1:
                    hidden_destination_wells = hidden_destination_wells * 8

                for i in range(8):
                    original_idx = -1
                    for op in zip(
                        source_wells, destination_wells, volumes, range(len(source_wells))
                    ):
                        if (
                            op[0] == hidden_source_wells[i]
                            and op[1] == hidden_destination_wells[i]
                            and op[2] == volume
                        ):
                            original_idx = op[3]
                            break
                    if original_idx not in [o[3] for o in failed_operations]:
                        failed_operations.append(
                            [
                                hidden_source_wells[i],
                                hidden_destination_wells[i],
                                volume,
                                original_idx,
                                failure_reason,
                            ]
                        )
                        added_indexes.append(original_idx)
            else:
                if orig_idx not in [o[3] for o in failed_operations]:
                    failed_operations.append(
                        [source, destination, volume, orig_idx, failure_reason]
                    )
                    added_indexes.append(orig_idx)
            return added_indexes, failed_operations

        # Allocate the liquid handling operations to each available pipette configuration
        # Format: [index, source well, destination well, volume]
        p300_multi_steps, p300_single_steps, p20_steps = self._allocate_liquid_handling_steps(
            source_wells=source_wells, destination_wells=destination_wells, volumes=volumes
        )

        # [pipette to use, in single channel mode, steps to take]
        allocated_sets = [
            [self.p300_multi, False, p300_multi_steps, "p300_multi"],
            [self.p300_multi, True, p300_single_steps, "p300_multisingle"],
            [self.p20, False, p20_steps, "p20"],
        ]

        # Track which pipettes have run out of tips
        out_of_tips_pipettes = set()

        # Track tip usage counts for tip_reuse_limit
        tip_usage_counts = {pipette_name: 0 for _, _, _, pipette_name in allocated_sets}
        
        # Track tip state for overhead liquid and air gap to prevent duplicate additions
        tip_state = {pipette_name: {"has_overhead": False, "has_air_gap": False} for _, _, _, pipette_name in allocated_sets}

        # When possible, group the operations for multi-dispense and multi-aspiration
        allocated_indexes = []
        for pipette, single_tip_mode, steps, pipette_name in allocated_sets:
            # Skip operations for pipettes that have run out of tips
            if pipette_name in out_of_tips_pipettes:
                # Add all operations from this pipette to failed operations
                for idx, source, destination, volume in steps:
                    if idx not in allocated_indexes:
                        idxs, failed_operations = add_failed_pipette_operations(
                            pipette_name, idx, failed_operations, "out_of_tips"
                        )
                        allocated_indexes.extend(idxs)
                continue

            max_vol = min(self.max_volume, pipette.max_volume)
            unique_source_wells = {op[1] for op in steps}
            unique_destination_wells = {op[2] for op in steps}
            # Scenario 1: shared source, possibly different destination
            grouped_sets = {1: [], 2: []}
            for pivot_set, p_idx in [[unique_source_wells, 1], [unique_destination_wells, 2]]:
                for pivot_well in pivot_set:
                    ops = [
                        op
                        for op in steps
                        if op[p_idx] == pivot_well and op[0] not in allocated_indexes
                    ]
                    if len(ops) > 1:
                        ops.sort(key=lambda x: x[-1])
                        current_set = []
                        set_volume = 0
                        for idx, source, destination, volume in ops:
                            if idx in allocated_indexes or volume <= 0:
                                continue
                            if volume < pipette.min_volume:
                                logging.warning(
                                    f"Volume too low, requested operation ignored: dispense {volume} ul to {destination} with pipette {pipette}"
                                )
                                idxs, failed_operations = add_failed_pipette_operations(
                                    pipette_name, idx, failed_operations, "volume_too_low"
                                )
                                allocated_indexes.extend(idxs)
                                continue
                            # No multi-dispense if tip change is set as "always", no-multi aspiration if if tip change set as "always" or "on aspiration".
                            # No multi-aspiration either when the leftover goes back to the source: a tip
                            # holding several sources' liquid can only blow it back into one of them.
                            air_gap_vol = pipette.min_volume if add_air_gap else 0
                            overhead_vol = pipette.min_volume if overhead_liquid else 0
                            effective_max_vol = max_vol - overhead_vol - air_gap_vol
                            if (
                                set_volume + volume <= effective_max_vol
                                and new_tip != "always"
                                and (
                                    (p_idx == 1 and mix_after is False)
                                    or (
                                        p_idx == 2
                                        and new_tip != "on aspiration"
                                        and blow_out_to not in ("source", "source_after_pipetting")
                                    )
                                )
                            ):
                                current_set.append([source, destination, volume, idx])
                                set_volume += volume
                                allocated_indexes.append(idx)
                            else:
                                if current_set:
                                    grouped_sets[p_idx].append(current_set)
                                    current_set = []
                                air_gap_vol_single = pipette.min_volume if add_air_gap else 0
                                overhead_vol_single = pipette.min_volume if overhead_liquid else 0
                                effective_max_vol_single = max_vol - overhead_vol_single - air_gap_vol_single
                                if volume > effective_max_vol_single:
                                    sets = math.ceil(volume / effective_max_vol_single)
                                    set_volume = volume / sets
                                    for i in range(sets):
                                        grouped_sets[p_idx].append(
                                            [[source, destination, set_volume, idx]]
                                        )
                                    allocated_indexes.append(idx)
                                    continue
                                current_set.append([source, destination, volume, idx])
                                allocated_indexes.append(idx)
                                set_volume = volume
                        if current_set:
                            grouped_sets[p_idx].append(current_set)
            aspiration_sets = grouped_sets[1]
            dispense_sets = grouped_sets[2]
            orphan_operations = []
            for op in steps:
                if op[0] not in allocated_indexes:
                    idx, source, destination, volume = op
                    air_gap_vol_orphan = pipette.min_volume if add_air_gap else 0
                    overhead_vol_orphan = pipette.min_volume if overhead_liquid else 0
                    effective_max_vol_single = max_vol - overhead_vol_orphan - air_gap_vol_orphan
                    if volume > effective_max_vol_single:
                        sets = math.ceil(volume / effective_max_vol_single)
                        sub_volume = volume / sets
                        for _ in range(sets):
                            orphan_operations.append([source, destination, sub_volume, idx])

                    elif volume >= pipette.min_volume:
                        orphan_operations.append([source, destination, volume, idx])
                    else:
                        logging.warning(
                            f"Volume too low, requested operation ignored: dispense {volume} ul to {destination} with pipette {pipette}"
                        )
                        idxs, failed_operations = add_failed_pipette_operations(
                            pipette_name, idx, failed_operations, "volume_too_low"
                        )
                        allocated_indexes.extend(idxs)

            first_round = True
            if single_tip_mode and steps:
                self._set_single_tip_mode(True)

            # Actual liquid handling

            # Single aspirate, multi-dispense
            # Sort the dispense operations based on the destination well name
            def well_order(well):
                """Column-major order (A1, B1, ... A2); the trash sorts first."""
                name = getattr(well, "well_name", "A0")
                return (
                    int("".join(filter(str.isdigit, name))),
                    "".join(filter(str.isalpha, name)),
                )

            aspiration_sets = sorted(
                [sorted(a_set, key=lambda x: well_order(x[1])) for a_set in aspiration_sets],
                key=lambda x: well_order(x[0][1]),
            )
            for aspiration_set in aspiration_sets:
                # Skip this set if pipette has run out of tips
                if pipette_name in out_of_tips_pipettes:
                    # Add all operations in this set to failed operations
                    for source, destination, volume, orig_idx in aspiration_set:
                        idxs, failed_operations = add_failed_pipette_operations(
                            pipette_name, orig_idx, failed_operations, "out_of_tips"
                        )
                        allocated_indexes.extend(idxs)
                    continue

                # [[[source, dest, vol], [source, dest, vol]],[[source, dest2, vol2], [source, dest2, vol2]],...]
                source_well = aspiration_set[0][0]
                set_volume = sum([op[2] for op in aspiration_set])

                try:
                    # Check if tip should be changed due to reuse limit
                    force_tip_change = (
                        tip_reuse_limit is not None 
                        and tip_usage_counts[pipette_name] >= tip_reuse_limit
                        and pipette.has_tip
                    )
                    
                    match new_tip:
                        case "always" | "on aspiration":
                            if pipette.has_tip:
                                # For source_after_pipetting, blow out to source before dropping/returning tip
                                if blow_out_to == "source_after_pipetting" and pipette.current_volume:
                                    pipette.blow_out(source_well.top())
                                pipette.drop_tip() if trash_tips or single_tip_mode else pipette.return_tip()
                                # Reset tip state when tip is dropped/returned
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                            pipette.pick_up_tip()
                            tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                            # Reset tip state for new tip
                            tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        case "once":
                            if first_round or force_tip_change:
                                if pipette.has_tip:
                                    # For source_after_pipetting, blow out to source before dropping tip
                                    if blow_out_to == "source_after_pipetting" and pipette.current_volume:
                                        pipette.blow_out(source_well.top())
                                    pipette.drop_tip()  # Tips are trashed always, because they are leftovers from previous operations
                                    # Reset tip state when tip is dropped
                                    tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                                first_round = False
                                tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                            if not pipette.has_tip:
                                pipette.pick_up_tip()
                                tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                                # Reset tip state for new tip
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        case _:
                            # Keep the tips already attached, otherwise pick up fresh ones
                            if force_tip_change:
                                # For source_after_pipetting, blow out to source before dropping/returning tip
                                if blow_out_to == "source_after_pipetting" and pipette.current_volume:
                                    pipette.blow_out(source_well.top())
                                pipette.drop_tip() if trash_tips or single_tip_mode else pipette.return_tip()
                                # Reset tip state when tip is dropped/returned
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                                pipette.pick_up_tip()
                                tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                                # Reset tip state for new tip
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                            elif not pipette.has_tip:
                                pipette.pick_up_tip()
                                tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                                # Reset tip state for new tip
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                                
                    # Now calculate overhead liquid and air gap AFTER tip management
                    # Check if overhead liquid and air gap should be added based on current tip state
                    should_add_overhead = overhead_liquid and not tip_state[pipette_name]["has_overhead"]
                    should_add_air_gap = add_air_gap and not tip_state[pipette_name]["has_air_gap"]
                    
                    extra_volume = (
                        pipette.min_volume if should_add_overhead and set_volume + pipette.min_volume <= max_vol else 0
                    )
                    air_gap_volume = (
                        pipette.min_volume if should_add_air_gap else 0
                    )
                except OutOfTipsError:
                    logging.error(
                        f"Out of tips for {pipette}. Marking all related operations as failed."
                    )
                    out_of_tips_pipettes.add(pipette_name)
                    # Add all operations in this set to failed operations
                    for source, destination, volume, orig_idx in aspiration_set:
                        idxs, failed_operations = add_failed_pipette_operations(
                            pipette_name, orig_idx, failed_operations, "out_of_tips"
                        )
                        allocated_indexes.extend(idxs)
                    continue

                last_index = 0
                try:
                    # Perform aspiration with air gap
                    if air_gap_volume:
                        pipette.move_to(location=source_well.top(5))
                        pipette.air_gap(volume=air_gap_volume)
                        # Mark that air gap has been added to this tip
                        tip_state[pipette_name]["has_air_gap"] = True
                    pipette.aspirate(
                        volume=set_volume + extra_volume,
                        location=self._pipetting_location(source_well, pipette),
                        **kwargs,
                    )
                    # Mark that overhead liquid has been added to this tip if extra_volume > 0
                    if extra_volume > 0:
                        tip_state[pipette_name]["has_overhead"] = True
                    time.sleep(retention_time)
                    if touch_tip:
                        self._touch_tip(pipette, source_well)

                    # Perform dispenses
                    for last_index, (source, destination_well, volume, orig_idx) in enumerate(
                        aspiration_set
                    ):
                        pipette.dispense(
                            volume=volume,
                            location=self._pipetting_location(destination_well, pipette),
                            **kwargs,
                        )
                        time.sleep(retention_time)
                        if touch_tip:
                            self._touch_tip(pipette, destination_well)

                        if mix_after:
                            if len(aspiration_set) == 1:
                                self._mix_after(pipette, destination_well, mix_after, max_vol)
                            else:
                                logging.warning(
                                    "Mixing ignored: mixing volume is not supported for multi-dispense operations"
                                )

                    # Handle remaining volume
                    if pipette.current_volume:
                        if blow_out_to == "trash":
                            pipette.blow_out(self.trash)
                            # Reset tip state after blowout as air gap and overhead liquid are expelled
                            tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        elif blow_out_to == "source":
                            pipette.blow_out(source_well.top())
                            # Reset tip state after blowout as air gap and overhead liquid are expelled
                            tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        elif blow_out_to == "destination":
                            pipette.blow_out(destination_well.top())
                            # Reset tip state after blowout as air gap and overhead liquid are expelled
                            tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        elif blow_out_to in ["source_after_pipetting", ""]:
                            # Don't blow out here - keep overhead liquid and air gap for reuse
                            pass
                        # If blow_out_to is empty string, no blowout occurs, so tip state is preserved
                    
                    # Increment tip usage counter after successful aspiration-dispense cycle
                    if tip_reuse_limit is not None:
                        tip_usage_counts[pipette_name] += 1

                except RECOVERABLE_ERRORS as e:
                    logging.error(f"Error during aspiration/dispense: {str(e)}")
                    self._secure_tip(pipette)
                    tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                    for source, destination, volume, orig_idx in aspiration_set[last_index:]:
                        idxs, failed_operations = add_failed_pipette_operations(
                            pipette_name, orig_idx, failed_operations, f"pipette_error: {str(e)}"
                        )
                        allocated_indexes.extend(idxs)
                    continue
                except Exception:
                    logging.exception("Unrecoverable error during aspiration/dispense; tip secured, stopping")
                    self._secure_tip(pipette)
                    raise

            # Multi-aspirate single dispense
            # Sort the dispense operations based on the source well name
            dispense_sets = sorted(
                [sorted(d_set, key=lambda x: str(x[0])) for d_set in dispense_sets],
                key=lambda x: str(x[0][0]),
            )
            for dispense_set in dispense_sets:
                # Skip this set if pipette has run out of tips
                if pipette_name in out_of_tips_pipettes:
                    # Add all operations in this set to failed operations
                    for source, destination, volume, orig_idx in dispense_set:
                        idxs, failed_operations = add_failed_pipette_operations(
                            pipette_name, orig_idx, failed_operations, "out_of_tips"
                        )
                        allocated_indexes.extend(idxs)
                    continue

                # [[[source1, dest, vol1], [source2, dest, vol2]],[[source3, dest, vol3], [source4, dest, vol4]],...]
                destination_well = dispense_set[0][1]
                set_volume = sum([op[2] for op in dispense_set])

                try:
                    # Check if tip should be changed due to reuse limit
                    force_tip_change = (
                        tip_reuse_limit is not None 
                        and tip_usage_counts[pipette_name] >= tip_reuse_limit
                        and pipette.has_tip
                    )
                    
                    match new_tip:
                        case "always" | "on aspiration":
                            if pipette.has_tip:
                                # For source_after_pipetting, blow out to source before dropping/returning tip
                                if blow_out_to == "source_after_pipetting" and pipette.current_volume:
                                    # Use the first source well from the dispense set
                                    pipette.blow_out(dispense_set[0][0].top())
                                pipette.drop_tip() if trash_tips or single_tip_mode else pipette.return_tip()
                                # Reset tip state when tip is dropped/returned
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                            pipette.pick_up_tip()
                            tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                            # Reset tip state for new tip
                            tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        case "once":
                            if first_round or force_tip_change:
                                if pipette.has_tip:
                                    # For source_after_pipetting, blow out to source before dropping tip
                                    if blow_out_to == "source_after_pipetting" and pipette.current_volume:
                                        pipette.blow_out(dispense_set[0][0].top())
                                    pipette.drop_tip()  # Tips are trashed always, because they are leftovers from previous operations
                                    # Reset tip state when tip is dropped
                                    tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                                first_round = False
                                tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                            if not pipette.has_tip:
                                pipette.pick_up_tip()
                                tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                                # Reset tip state for new tip
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        case _:
                            # Keep the tips already attached, otherwise pick up fresh ones
                            if force_tip_change:
                                # For source_after_pipetting, blow out to source before dropping/returning tip
                                if blow_out_to == "source_after_pipetting" and pipette.current_volume:
                                    pipette.blow_out(dispense_set[0][0].top())
                                pipette.drop_tip() if trash_tips or single_tip_mode else pipette.return_tip()
                                # Reset tip state when tip is dropped/returned
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                                pipette.pick_up_tip()
                                tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                                # Reset tip state for new tip
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                            elif not pipette.has_tip:
                                pipette.pick_up_tip()
                                tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                                # Reset tip state for new tip
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                                
                    # Now calculate air gap AFTER tip management
                    # Check if air gap should be added based on current tip state
                    should_add_air_gap = add_air_gap and not tip_state[pipette_name]["has_air_gap"]
                    
                    air_gap_volume = (
                        pipette.min_volume if should_add_air_gap else 0
                    )
                except OutOfTipsError:
                    logging.error(
                        f"Out of tips for {pipette}. Marking all related operations as failed."
                    )
                    out_of_tips_pipettes.add(pipette_name)
                    # Add all operations in this set to failed operations
                    for source, destination, volume, orig_idx in dispense_set:
                        idxs, failed_operations = add_failed_pipette_operations(
                            pipette_name, orig_idx, failed_operations, "out_of_tips"
                        )
                        allocated_indexes.extend(idxs)
                    continue

                try:
                    # Perform aspirations with air gap
                    if air_gap_volume:
                        pipette.move_to(location=dispense_set[0][0].top(5))
                        pipette.air_gap(volume=air_gap_volume)
                        # Mark that air gap has been added to this tip
                        tip_state[pipette_name]["has_air_gap"] = True
                    total_volume = 0
                    for source, _, volume, idx in dispense_set:
                        pipette.aspirate(
                            volume=volume,
                            location=self._pipetting_location(source, pipette),
                            **kwargs,
                        )
                        time.sleep(retention_time)
                        if touch_tip:
                            self._touch_tip(pipette, source)
                        total_volume += volume

                    # Perform dispense
                    pipette.dispense(
                        volume=total_volume,
                        location=self._pipetting_location(destination_well, pipette),
                        **kwargs,
                    )
                    time.sleep(retention_time)
                    if touch_tip:
                        self._touch_tip(pipette, destination_well)

                    if mix_after:
                        self._mix_after(pipette, destination_well, mix_after, max_vol)

                    # Handle remaining volume
                    if pipette.current_volume:
                        if blow_out_to == "trash":
                            pipette.blow_out(self.trash)
                            # Reset tip state after blowout as air gap and overhead liquid are expelled
                            tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        elif blow_out_to == "source":
                            # Grouping is disabled for this blow_out_to, so the set holds one source.
                            pipette.blow_out(source.top())
                            # Reset tip state after blowout as air gap and overhead liquid are expelled
                            tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        elif blow_out_to == "destination":
                            pipette.blow_out(destination_well.top())
                            # Reset tip state after blowout as air gap and overhead liquid are expelled
                            tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        elif blow_out_to in ["source_after_pipetting", ""]:
                            # Don't blow out here - keep overhead liquid and air gap for reuse
                            # Blow out will happen only when tip is about to be changed/dropped (for source_after_pipetting)
                            # If blow_out_to is empty string, no blowout occurs, so tip state is preserved
                            pass
                    
                    # Increment tip usage counter after successful aspiration-dispense cycle
                    if tip_reuse_limit is not None:
                        tip_usage_counts[pipette_name] += 1

                except RECOVERABLE_ERRORS as e:
                    logging.error(f"Error during aspiration/dispense: {str(e)}", exc_info=True)
                    self._secure_tip(pipette)
                    tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                    for source, destination, volume, orig_idx in dispense_set:
                        idxs, failed_operations = add_failed_pipette_operations(
                            pipette_name, orig_idx, failed_operations, f"pipette_error: {str(e)}"
                        )
                        allocated_indexes.extend(idxs)
                    continue
                except Exception:
                    logging.exception("Unrecoverable error during aspiration/dispense; tip secured, stopping")
                    self._secure_tip(pipette)
                    raise

            # Simple aspirate and dispense
            # Sort the orphan operations based on the source well name
            orphan_operations = sorted(orphan_operations, key=lambda x: str(x[0]))
            for source, destination, volume, orig_idx in orphan_operations:
                # Skip this operation if pipette has run out of tips
                if pipette_name in out_of_tips_pipettes:
                    idxs, failed_operations = add_failed_pipette_operations(
                        pipette_name, orig_idx, failed_operations, "out_of_tips"
                    )
                    allocated_indexes.extend(idxs)
                    continue

                try:
                    # Check if tip should be changed due to reuse limit
                    force_tip_change = (
                        tip_reuse_limit is not None 
                        and tip_usage_counts[pipette_name] >= tip_reuse_limit
                        and pipette.has_tip
                    )
                    
                    match new_tip:
                        case "always" | "on aspiration":
                            if pipette.has_tip:
                                # For source_after_pipetting, blow out to source before dropping/returning tip
                                if blow_out_to == "source_after_pipetting" and pipette.current_volume:
                                    pipette.blow_out(source.top())
                                pipette.drop_tip() if trash_tips or single_tip_mode else pipette.return_tip()
                                # Reset tip state when tip is dropped/returned
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                            pipette.pick_up_tip()
                            tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                            # Reset tip state for new tip
                            tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        case "once":
                            if first_round or force_tip_change:
                                if pipette.has_tip:
                                    # For source_after_pipetting, blow out to source before dropping tip
                                    if blow_out_to == "source_after_pipetting" and pipette.current_volume:
                                        pipette.blow_out(source.top())
                                    pipette.drop_tip()  # Tips are trashed always, because they are leftovers from previous operations
                                    # Reset tip state when tip is dropped
                                    tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                                first_round = False
                                tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                            if not pipette.has_tip:
                                pipette.pick_up_tip()
                                tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                                # Reset tip state for new tip
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        case _:
                            # Keep the tips already attached, otherwise pick up fresh ones
                            if force_tip_change:
                                # For source_after_pipetting, blow out to source before dropping/returning tip
                                if blow_out_to == "source_after_pipetting" and pipette.current_volume:
                                    pipette.blow_out(source.top())
                                pipette.drop_tip() if trash_tips or single_tip_mode else pipette.return_tip()
                                # Reset tip state when tip is dropped/returned
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                                pipette.pick_up_tip()
                                tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                                # Reset tip state for new tip
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                            elif not pipette.has_tip:
                                pipette.pick_up_tip()
                                tip_usage_counts[pipette_name] = 0  # Reset counter on new tip
                                # Reset tip state for new tip
                                tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                                
                    # Now calculate overhead liquid and air gap AFTER tip management
                    # Check if overhead liquid and air gap should be added based on current tip state
                    should_add_overhead = overhead_liquid and not tip_state[pipette_name]["has_overhead"]
                    should_add_air_gap = add_air_gap and not tip_state[pipette_name]["has_air_gap"]
                    
                    extra_volume = (
                        pipette.min_volume if should_add_overhead and volume + pipette.min_volume <= max_vol else 0
                    )
                    air_gap_volume = (
                        pipette.min_volume if should_add_air_gap else 0
                    )
                except OutOfTipsError:
                    logging.error(
                        f"Out of tips for {pipette}. Marking all related operations as failed."
                    )
                    out_of_tips_pipettes.add(pipette_name)
                    idxs, failed_operations = add_failed_pipette_operations(
                        pipette_name, orig_idx, failed_operations, "out_of_tips"
                    )
                    allocated_indexes.extend(idxs)
                    continue

                try:
                    # Perform aspiration with air gap
                    if air_gap_volume:
                        pipette.move_to(location=source.top(5))
                        pipette.air_gap(volume=air_gap_volume)
                        # Mark that air gap has been added to this tip
                        tip_state[pipette_name]["has_air_gap"] = True
                    pipette.aspirate(
                        volume=volume + extra_volume,
                        location=self._pipetting_location(source, pipette),
                        **kwargs,
                    )
                    # Mark that overhead liquid has been added to this tip if extra_volume > 0
                    if extra_volume > 0:
                        tip_state[pipette_name]["has_overhead"] = True
                    time.sleep(retention_time)
                    if touch_tip:
                        self._touch_tip(pipette, source)

                    # Perform dispense
                    pipette.dispense(
                        volume=volume,
                        location=self._pipetting_location(destination, pipette),
                        **kwargs,
                    )
                    time.sleep(retention_time)
                    if touch_tip:
                        self._touch_tip(pipette, destination)

                    if mix_after:
                        self._mix_after(pipette, destination, mix_after, max_vol)

                    # Handle remaining volume
                    if pipette.current_volume:
                        if blow_out_to == "trash":
                            pipette.blow_out(self.trash)
                            # Reset tip state after blowout as air gap and overhead liquid are expelled
                            tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        elif blow_out_to == "source":
                            pipette.blow_out(source.top())
                            # Reset tip state after blowout as air gap and overhead liquid are expelled
                            tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        elif blow_out_to == "destination":
                            pipette.blow_out(destination.top())
                            # Reset tip state after blowout as air gap and overhead liquid are expelled
                            tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                        elif blow_out_to in ["source_after_pipetting", ""]:
                            # Don't blow out here - keep overhead liquid and air gap for reuse
                            # Blow out will happen only when tip is about to be changed/dropped (for source_after_pipetting)
                            # If blow_out_to is empty string, no blowout occurs, so tip state is preserved
                            pass
                    
                    # Increment tip usage counter after successful aspiration-dispense cycle
                    if tip_reuse_limit is not None:
                        tip_usage_counts[pipette_name] += 1

                except RECOVERABLE_ERRORS as e:
                    logging.error(f"Error during aspiration/dispense: {str(e)}")
                    self._secure_tip(pipette)
                    tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                    idxs, failed_operations = add_failed_pipette_operations(
                        pipette_name, orig_idx, failed_operations, f"pipette_error: {str(e)}"
                    )
                    allocated_indexes.extend(idxs)
                    continue
                except Exception:
                    logging.exception("Unrecoverable error during aspiration/dispense; tip secured, stopping")
                    self._secure_tip(pipette)
                    raise

            # Clean up tips for this pipette at the end of its operations
            if pipette_name not in out_of_tips_pipettes and pipette.has_tip:
                try:
                    # For source_after_pipetting, blow out to source at the end of transfers, regardless of tip handling
                    if blow_out_to == "source_after_pipetting" and pipette.current_volume:
                        # Find the last source well used by this pipette
                        last_source_well = None
                        for step in reversed(steps):
                            if step:  # step format: [idx, source, destination, volume]
                                last_source_well = step[1]
                                break
                        if last_source_well:
                            pipette.blow_out(last_source_well.top())
                            # Reset tip state after blowout
                            tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                    
                    if new_tip != "never":
                        if trash_tips:
                            pipette.drop_tip()
                        else:
                            pipette.return_tip()
                        # Reset tip state when tip is dropped/returned
                        tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}
                except Exception as e:
                    logging.error(f"Error dropping/returning tip: {str(e)}")
                    # Reset tip state even if drop/return fails
                    tip_state[pipette_name] = {"has_overhead": False, "has_air_gap": False}

            # All liquid handling is done
            try:
                if single_tip_mode:
                    self._set_single_tip_mode(False)
            except Exception as e:
                logging.error(f"Error resetting single tip mode: {str(e)}")

        return to_caller_indices(failed_operations)

    def _mix_after(self, pipette, well, mix_after, max_vol):
        """The mix_after of one dispense, skipped with a warning where it cannot be done."""
        repetitions, volume = mix_after
        if volume > max_vol or volume < pipette.min_volume:
            logging.warning(
                f"Mixing ignored: mixing volume ({volume} ul) exceeds the pipette / tip volume range ({pipette.min_volume} ul - {max_vol} ul)"
            )
            return
        if pipette is self.p300_multi and self._is_deep_tube(well):
            logging.warning(
                f"Mixing ignored: the p300 cannot reach the liquid in {well} (deep tube); mix with the p20 instead"
            )
            return
        pipette.mix(
            repetitions=repetitions,
            volume=volume,
            location=self._pipetting_location(well, pipette),
        )

    def distribute(
        self,
        volumes,
        source_well,
        destination_wells,
        new_tip: str = "once",
        touch_tip: bool = False,
        blow_out_to: bool = "trash",
        trash_tips: bool = True,
        add_air_gap: bool = True,
        overhead_liquid: bool = True,
        tip_reuse_limit: int = None,
        **kwargs,
    ):
        """
        Distribute liquid from a source well to multiple destination wells.

        This method is capable of handling multiple dispense operations, automatically choosing the appropriate pipette,
        and distributing liquid across different labware. It supports both single and multi-channel pipetting, optimizing
        the process based on the volume and configuration of the wells.

        Args:
            volumes (float or list of floats): The volume(s) to distribute. If a single float is provided, the same volume
                                               is used for all destination wells. If a list is provided, each volume corresponds
                                               to a destination well.
            source_well (Well or list of Well): The well from which to distribute the liquid. If a list is provided, it must
                                                contain only one well.
            destination_wells (list of Well): The wells to which the liquid will be distributed.
            new_tip (str, optional): When to use a new tip. Options are: "always", "once", "never", "on aspiration". Default is "once".
            touch_tip (bool, optional): Whether to touch the tip to the side of the well after dispensing. Default is False.
            blow_out_to (str, optional): Whether the remainder of liquid is blown out to "source", "destination", "trash", or "source_after_pipetting". Empty string will result in no blow-out. The "source_after_pipetting" option keeps overhead liquid and air gap through operations and blows out to source when the tip is about to be changed or dropped, and also at the end of all transfers.
            trash_tips (bool, optional): Whether to discard the tip to the trash after use (True) or return to tip box (False). Default is True.
            add_air_gap (bool, optional): Whether to add an air gap before aspirating the liquid. Default is True.
            overhead_liquid (bool, optional): Whether to aspirate extra liquid for more accurate dispensing, but consumes more source liquid. Default is True.
            tip_reuse_limit (int, optional): Maximum number of aspiration-dispense cycles before forcing a tip change
                even if new_tip is "never" or "once". Default: None (no limit enforced).
            **kwargs: Additional keyword arguments to pass to the underlying transfer method. Such as:
                - mix_after (tuple, optional): First element is repetitions and second element is volume of mixing at the destination well after dispense. False when no mixing needed. Will block multi-dispense mode.

        Returns:
            list: A list of failed operations, where each entry is a list containing the index of the destination well,
                  the well itself, and the volume that failed to be dispensed. This could be used to repeat failed operations.

        Usage advice:
            - `blow_out_to` cannot be `False` if `new_tip` is 'on aspiration' or 'always'
            - If reusing tips, consider hovering the dispense with a tip touch to avoid contaminating the source well,
              unless the destination well content is identical.

        TODO:
            - Manage contamination through hover dispense, tip touch and tip handling strategies.
            - Calculate tips in advance, raise error if not enough tips
            - Single tip touch before aspiration if reusing tips
            - Enable chaching of tips (providing a tip box location where tips are found with the well index)

        Nice-to-have:
            - Optimize the order within the dispense set to minimize the path.

        Raises:
            TypeError: If the source well is not a Well object or a list containing a single Well.
        """
        # Checking and reformatting parameters
        if not isinstance(source_well, Well):
            if isinstance(source_well, list) and len(source_well) == 1:
                source_well = source_well[0]
            else:
                raise TypeError(f"The source well must be a well, got {type(source_well)}.")

        if isinstance(destination_wells, Well):
            destination_wells = [destination_wells]
        if new_tip not in ["always", "once", "never", "on aspiration"]:
            raise ValueError(f"Got an invalid value for the optional argument 'new_tip': {new_tip}")

        if blow_out_to == "" and new_tip in ["on aspiration", "always"]:
            msg = "blow_out_to should be set when new_tip is 'on aspiration' or 'always'. Setting to 'trash'."
            logging.warning(msg)
            blow_out_to = "trash"

        if isinstance(volumes, float) or isinstance(volumes, int):
            volumes = [volumes] * len(destination_wells)

        return self.transfer(
            volumes,
            [source_well] * len(destination_wells),
            destination_wells,
            new_tip=new_tip,
            touch_tip=touch_tip,
            blow_out_to=blow_out_to,
            trash_tips=trash_tips,
            add_air_gap=add_air_gap,
            overhead_liquid=overhead_liquid,
            tip_reuse_limit=tip_reuse_limit,
            **kwargs,
        )

    def pool(
        self,
        volumes,
        source_wells,
        destination_well,
        new_tip: str = "once",
        touch_tip: bool = False,
        trash_tips: bool = True,
        add_air_gap: bool = True,
        **kwargs,
    ):
        """
        Collects liquid from multiple source wells and combines it into a single destination well.

        Parameters:
            volumes (Union[float, int, List[Union[float, int]]]): Volume(s) to pool from each source well.
            source_wells (Union[Well, List[Well]]): Single well or list of wells to pool from.
            destination_well (Union[Well, List[Well]]): Single well or list of wells to pool into.
            new_tip (str): Strategy for using tips ("always", "once", "never", "on aspiration").
            touch_tip (bool): Whether to touch the tip to the sides after dispensing.
            trash_tips (bool): Whether to trash tips after use.
            add_air_gap (bool): Whether to add an air gap during transfer.
            **kwargs: Additional keyword arguments.

        Raises:
            TypeError: If the source well is not a Well object or a list containing Well objects.
            ValueError: If an invalid value is provided for 'new_tip'.
        """
        # Checking and reformatting parameters
        if isinstance(destination_well, list):
            if len(destination_well) != 1:
                raise TypeError(
                    f"The destination well must be a Well object or a list of a single Well, got {type(destination_well)}."
                )
            destination_well = destination_well[0]
        if not isinstance(destination_well, Well) and not isinstance(destination_well, TrashBin):
            raise TypeError(
                f"The destination well must be a Well object, TrashBin or a list of a single Well, got {type(destination_well)}."
            )

        if isinstance(source_wells, Well):
            source_wells = [source_wells]

        if new_tip not in ["always", "once", "never", "on aspiration"]:
            raise ValueError(f"Got an invalid value for the optional argument 'new_tip': {new_tip}")

        if isinstance(volumes, (float, int)):
            volumes = [volumes] * (len(source_wells) if isinstance(source_wells, list) else 1)

        if "overhead_liquid" in kwargs:
            logging.warning("overhead_liquid is not supported for pool, ignoring")
            del kwargs["overhead_liquid"]

        source_wells = source_wells if isinstance(source_wells, list) else [source_wells]

        # Multiply the destination wells to match the number of source wells for the transfer method format
        destination_wells = [destination_well] * len(source_wells)

        return self.transfer(
            volumes,
            source_wells,
            destination_wells,
            new_tip=new_tip,
            touch_tip=touch_tip,
            blow_out_to="destination",
            trash_tips=trash_tips,
            add_air_gap=add_air_gap,
            overhead_liquid=False,
            **kwargs,
        )

    def consolidate(self, *args, **kwargs):
        # Ensure same naming convention is available
        return self.pool(*args, **kwargs)

    def stamp(
        self,
        volume: float,
        source_plate,
        destination_plate,
        sample_count: int = 0,
        new_tip: str = "always",
        touch_tip: bool = False,
        blow_out_to: str = "destination",
        trash_tips: bool = True,
        add_air_gap: bool = True,
        overhead_liquid: bool = False,
        **kwargs,
    ):
        """
        Stamp a plate with a pipette selected based on the specified volume. This method assumes that the sample count
        progresses column by column, from top to bottom. For cherry-picking wells or stamping variable volumes, use the
        `transfer` method instead.

        Parameters:
            volume (float): The volume to stamp into each well.
            source_plate: The source plate from which to stamp.
            destination_plate: The destination plate to which the liquid will be stamped.
            sample_count (int, optional): The number of samples to stamp. Defaults to 0, which stamps all samples.
            new_tip (str, optional): Strategy for using tips. Options are "always", "once", "never", "on aspiration". Default is "always".
            touch_tip (bool, optional): Whether to touch the tip to the side of the well after dispensing. Default is False.
            blow_out_to (str, optional): Whether the remainder of liquid is blown out to "source", "destination", "trash", or "source_after_pipetting". Empty string will result in no blow-out. The "source_after_pipetting" option keeps overhead liquid and air gap through operations and blows out to source when the tip is about to be changed or dropped, and also at the end of all transfers.
            trash_tips (bool, optional): Whether to discard tips after use. Default is True.
            add_air_gap (bool, optional): Whether to add an air gap prior to aspiration. Default is True.
            overhead_liquid (bool, optional): Whether to aspirate extra liquid for more accurate dispensing. Default is False.
            **kwargs: Additional keyword arguments for pipette operations.

        Returns:
            list: A list of failed operations, where each entry is a list containing the index of the operation,
                  source well, destination well, and the volume that failed to be dispensed. This can be used to repeat failed operations.
        """

        source_wells = source_plate.wells()
        destination_wells = destination_plate.wells()
        if sample_count > 0:
            source_wells = source_wells[:sample_count]
            destination_wells = destination_wells[:sample_count]

        if isinstance(volume, float) or isinstance(volume, int):
            volumes = [volume] * len(destination_wells)

        return self.transfer(
            volumes,
            source_wells,
            destination_wells,
            new_tip=new_tip,
            touch_tip=touch_tip,
            blow_out_to=blow_out_to,
            trash_tips=trash_tips,
            add_air_gap=add_air_gap,
            overhead_liquid=overhead_liquid,
            **kwargs,
        )

    def mix(self, wells, repetitions, volume, new_tip="once", trash_tip=True):
        """
        Mix the contents of the specified wells using an appropriate pipette based on the volume.

        Parameters:
            wells (list): A list of wells to be mixed.
            repetitions (int): The number of mixing repetitions.
            volume (float): The volume to aspirate and dispense during mixing.
            new_tip (str): Strategy for using tips. Options are "always", "once", "never". Default is "once".
            trash_tip (bool): Whether to discard tips after use. Default is True.

        TODO:
        - Could this be done with transfer, using the mix after, but zero aspiration for same source and destination?
        """
        logging.debug(
            f"Mixing {len(wells)} wells with {repetitions} repetitions at {volume}µL each"
        )
        wells = list(dict.fromkeys(wells))  # the caller's order, each well once
        if not wells:
            return
        if new_tip not in ["always", "once", "never"]:
            raise ValueError(f"Got an invalid value for the optional argument 'new_tip': {new_tip}")

        # Assign each well a pipette mode. A column goes to the 8-channel only when
        # all of its wells are listed - wherever they appear in the list - and none
        # of them is out of the 8-channel's reach (front row, deep tube).
        # [(mode, well, volume)]; a column is represented by its row-A well.
        plan = []
        taken = set()
        p20_max = self.p20.max_volume
        for well in wells:
            if well in taken:
                continue
            column = well.parent.columns_by_name()[well.well_name[1:]]
            whole_column = len(column) == 8 and all(w in wells for w in column)
            reachable = not any(self._needs_p20(w, None) for w in column)
            if volume > p20_max and whole_column and reachable:
                plan.append(("multi", column[0], volume))
                taken.update(column)
                continue
            taken.add(well)
            if self._needs_p20(well, None) or volume <= p20_max:
                if volume > p20_max:
                    logging.warning(
                        f"Mixing {well} with {p20_max} ul instead of {volume} ul: only the p20 can reach it"
                    )
                plan.append(("p20", well, min(volume, p20_max)))
            else:
                plan.append(("single", well, volume))

        def park(pipette):
            if pipette.has_tip:
                if trash_tip:
                    pipette.drop_tip()
                else:
                    pipette.return_tip()

        # One mode at a time, so the nozzle layout changes at most twice and no
        # pipette is left holding a used tip while the other one works.
        previous = None
        for mode in ("multi", "single", "p20"):
            steps = [step for step in plan if step[0] == mode]
            if not steps:
                continue
            pipette = self.p20 if mode == "p20" else self.p300_multi
            if previous is not None and previous is not pipette:
                park(previous)
            if mode != "p20":
                self._set_single_tip_mode(mode == "single")
            if new_tip == "once":
                park(pipette)
            for _, well, mix_volume in steps:
                if new_tip == "always":
                    park(pipette)
                if not pipette.has_tip:
                    pipette.pick_up_tip()
                pipette.mix(
                    repetitions=repetitions,
                    volume=mix_volume,
                    location=self._pipetting_location(well, pipette),
                )
            if new_tip in ["once", "always"]:
                park(pipette)
            previous = pipette

        self._set_single_tip_mode(False)

    def engage_magnets(self, height=5.4, **kwargs):
        """
        Engage the magnets of the magnetic module.

        Additionally accepts any keyword arguments accepted by the opentrons engage method.
        """
        if not self.magnetic_module:
            raise Exception("No magnetic module has been loaded on the deck.")
        self.magnetic_module.engage(height_from_base=height, **kwargs)

    def disengage_magnets(self):
        """
        Disengage the magnets of the magnetic module.
        """
        if not self.magnetic_module:
            raise Exception("No magnetic module has been loaded on the deck.")
        self.magnetic_module.disengage()
