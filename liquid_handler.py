import opentrons
import opentrons.simulate
import opentrons.execute
from opentrons.protocol_api.labware import Well
from opentrons.protocol_api.disposal_locations import TrashBin
from opentrons.protocol_engine.errors import ProtocolCommandFailedError
from opentrons.protocol_api.core.engine.deck_conflict import PartialTipMovementNotAllowedError
from threading import Thread
import time
import math
import logging
import json
import platform

# Configure logging to display messages in the terminal
logging.basicConfig(
    filename='opentrons.log',
    filemode='w',        # use 'w' for overwrite mode, 'a' to for append mode
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)


class LiquidHandler:
    
    def __init__(self, api_version: str = '2.20', load_default: bool = True, simulation: bool = False):
        """
        Initialize the LiquidHandler class.

        Default layout:
        # Default layout:
        # - Eppendorf tuberack on slot 1
        # - P300 tip rack on slot 7
        # - Partial P300 tip rack on slot 6
        # - P20 tip rack on slot 11
        # - Temperature module on slot 4
        # - Heater-shaker module on slot 10
        # - Magnetic module on slot 9
        # - P300 multi-channel pipette on the right mount
        # - P20 single-channel pipette on the left mount
        """

        # initialize protocol API
        logging.info(f"Initializing protocol API with version {api_version}")
        if simulation:
            self.protocol_api = opentrons.simulate.get_protocol_api(api_version)
        else:
            self.protocol_api = opentrons.execute.get_protocol_api(api_version)
        self.simulation_mode = simulation

        # default values
        self.p300_tips = []
        self.partial_p300_tips = []
        self.p20_tips = []
        self.temperature_timer = None
        self.shaking_timer = None
        self.single_tip_mode = False

        # Default labware
        if load_default:
            logging.info("Loading default labware")

            self.protocol_api.load_labware(
                "opentrons_24_tuberack_eppendorf_1.5ml_safelock_snapcap",
                "1"
            )
            self.p300_tips.append(self.protocol_api.load_labware('opentrons_96_tiprack_300ul', "7"))
            self.partial_p300_tips.append(self.protocol_api.load_labware('opentrons_96_tiprack_300ul', "6"))
            self.p20_tips.append(self.protocol_api.load_labware('opentrons_96_tiprack_20ul', "11"))

        # load fixed hardware
        logging.info("Loading instruments")
        self.trash = self.protocol_api.fixed_trash
        self.p300_multi = self.protocol_api.load_instrument('p300_multi_gen2', 'right', tip_racks=self.p300_tips)
        self.p20 = self.protocol_api.load_instrument('p20_single_gen2', 'left', tip_racks=self.p20_tips)

        logging.info("Loading modules")
        self.temperature_module = self.protocol_api.load_module(module_name="temperature module gen2", location="4") # Adapter might need to be loaded separately
        self.shaker_module = self.protocol_api.load_module(module_name="heaterShakerModuleV1", location="10")
        self.magnetic_module = self.protocol_api.load_module(module_name="magnetic module gen2", location="9")

        logging.info("Closing labware latch")
        try:
            self.shaker_module.close_labware_latch()  # Currently all heater-shaker commands fail
        except:
            pass

        self.home()
        self.toggle_light(state=True)

    def toggle_light(self, state: bool=True):
        """
        Toggles the light of the OT-2 robot based on the provided state.

        Parameters:
            state (bool): If True, turn on the light; if False, turn off the light.
        TODO: Does not work
        """
        logging.debug(f"Setting OT-2 light to {'on' if state else 'off'}")
        self.protocol_api.set_rail_lights(state)

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
                style=opentrons.protocol_api.SINGLE,
                start="A1",
                tip_racks=self.partial_p300_tips
            )
            self.single_tip_mode = True
        elif not state and self.single_tip_mode:
            if self.p300_multi.has_tip:
                self.p300_multi.drop_tip()
            self.p300_multi.configure_nozzle_layout(
                style=opentrons.protocol_api.ALL,
                tip_racks=self.p300_tips
            )
            self.single_tip_mode = False
        return self.single_tip_mode

    def _allocate_liquid_handling_steps(self, source_wells, destination_wells, volumes):
        """
        Allocates the provided liquid handling operations into three categories optimally:
        - p300 multichannel compatible operations
        - p300 single channel compatible operations
        - p20 single channel compatible operations

        Allocation is based on:
        - Volume of each operation
        - Alignment of the operation (column-wise vs. well-wise vs. vertical well like a trough)
        - Accessibility of the p300 pipette in single tip mode

        Raises:
            ValueError: If the number of source wells, destination wells, and volumes do not match.
            ValueError: If a well is used as both a source and destination.
            ValueError: If operations involve different labware.
        
        TODO:
        - Check: how does trash operate as "column" index?
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
        if not (isinstance(source_wells, list) and isinstance(source_wells[0], Well)):
            raise ValueError("The source_wells must be a list of Well objects")
        if not (isinstance(destination_wells, list) and (isinstance(destination_wells[0], Well) or isinstance(destination_wells[0], TrashBin))):
            raise ValueError("The destination_wells must be a list of Well objects or TrashBin objects")
        if not (len(source_wells) == len(destination_wells) == len(volumes)):
            raise ValueError("The number of wells in source and destination must be equal to the number of volumes provided.")

        source_labware = source_wells[0].parent
        for well in source_wells:
            if well.parent != source_labware:
                raise ValueError("The operations to allocate must be between up to two labware.")

        if isinstance(destination_wells[0], Well):  # Could also be TrashBin
            destination_labware = destination_wells[0].parent
            for well in destination_wells:
                if well.parent != destination_labware:
                    raise ValueError("The operations to allocate must be between up to two labware.")

            source_well_names = {well.well_name for well in source_wells}
            destination_well_names = {well.well_name for well in destination_wells}
            if source_labware == destination_labware and source_well_names.intersection(destination_well_names):
                raise ValueError("A well cannot be both a source and destination, because this function cannot be used for order-dependent liquid handling operations.")
        else:
            destination_labware = destination_wells[0]

        # Construct helper dictionaries to assist in well allocation
        pipette = self.p300_multi
        column_operations = {}
        large_volume_operations = []
        for i, source, dest, vol in zip(range(len(volumes)), source_wells, destination_wells, volumes):
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
                    matching_volumes = [op for op in column_ops if op[3] == vol and op[0] not in multichannel_operations_indexes]
                    # Eight column-wise operations with the same volume exist
                    if len(matching_volumes) >= 8:
                        found = True
                        while found:
                            found = False
                            # Scenario 1: row indexes match and populate the whole column
                            matching_rows = [op for op in matching_volumes if get_row_index(op[1]) == get_row_index(op[2])]
                            row_indices_source = {get_row_index(op[1]) for op in matching_rows}
                            row_indices_dest = {get_row_index(op[2]) for op in matching_rows}
                            if len(row_indices_source) == 8 and len(row_indices_dest) == 8:
                                # We have 8 addressed unique matching rows. Now capture those operations
                                ops_collection = {get_row_index(op[1]): op for op in matching_rows}

                                if len(ops_collection) == 8:
                                    multichannel_operations.append(ops_collection["A"])
                                    multichannel_operations_indexes.extend([op[0] for op in ops_collection.values()])
                                    matching_volumes = [op for op in matching_volumes if op[0] not in multichannel_operations_indexes]
                                    found = True
                            else:
                                # Scenario 2: source or destination well can fit all multichannel pipettes
                                # Find a well that is present at least 8 times
                                source_well_names = [op[1].well_name for op in matching_volumes]
                                destination_well_names = [op[2].well_name if isinstance(op[2], Well) else "A1" for op in matching_volumes]
                                source_well_count = {}
                                destination_well_count = {}
                                for well_name in source_well_names:
                                    source_well_count[well_name] = source_well_count.get(well_name, 0) + 1
                                for well_name in destination_well_names:
                                    destination_well_count[well_name] = destination_well_count.get(well_name, 0) + 1

                                source_troughs = []
                                for name, count in source_well_count.items():
                                    well = source_labware.wells(name)[0]
                                    if count >= 8 and hasattr(well, 'width') and well.width > 70:
                                        source_troughs.append(well)

                                destination_troughs = []
                                if isinstance(destination_labware, TrashBin):
                                    destination_troughs.append(destination_labware)
                                else:
                                    for name, count in destination_well_count.items():
                                        well = destination_labware.wells(name)[0]
                                        if count >= 8 and hasattr(well, 'width') and well.width > 70:
                                            destination_troughs.append(well)
                                # Check transfers between troughs and columns
                                check_set = [
                                    (source_troughs, destination_troughs, 2, 1),
                                    (destination_troughs, source_troughs, 1, 2)
                                ]
                                for primary, secondary, idxa, idxb in check_set:
                                    for well in primary:
                                        # Primary is a trough
                                        ops = [op for op in matching_volumes if op[idxb] == well and op[0] not in multichannel_operations_indexes]
                                        if len(ops) >= 8:
                                            found2 = True
                                            while found2:
                                                found2 = False
                                                # Scenario 1: secondary is a column
                                                ops_collection = {get_row_index(op[idxa]): op for op in ops}
                                                if len(ops_collection) == 8:
                                                    multichannel_operations.append(ops_collection["A"])
                                                    multichannel_operations_indexes.extend([op[0] for op in ops_collection.values()])
                                                    ops = [op for op in ops if op[0] not in multichannel_operations_indexes]
                                                    found = True
                                                    found2 = True
                                                else:
                                                    # Scenario 2: secondary is a trough
                                                    for dest_well in secondary:
                                                        trough_to_trough = [op for op in ops if op[2] == dest_well]
                                                        while len(trough_to_trough) >= 8:
                                                            # Operations are identical; add the first one
                                                            multichannel_operations.append(trough_to_trough[0])
                                                            multichannel_operations_indexes.extend([op[0] for op in trough_to_trough[:8]])
                                                            del trough_to_trough[:8]
                                                            found = True
                                                            found2 = True
                                                            ops = [op for op in ops if op[0] not in multichannel_operations_indexes]

        allocated_operations = multichannel_operations_indexes
        p300_single_ops = []
        p20_ops = []
        labware_forcing_p20 = [
            "opentrons_10_tuberack_falcon_4x50ml_6x15ml_conical",
            "opentrons_10_tuberack_nest_4x50ml_6x15ml_conical",
            "opentrons_15_tuberack_falcon_15ml_conical",
            "opentrons_15_tuberack_nest_15ml_conical"
        ]
        for op in large_volume_operations:
            if op[0] in allocated_operations:
                continue
            if (source_labware.parent in ["1", "2", "3"] and get_row_index(op[1]) in ["G", "H"]) or (
                destination_labware.parent in ["1", "2", "3"] and get_row_index(op[2]) in ["G", "H"]):
                p20_ops.append(op)
                allocated_operations.append(op[0])
            elif source_labware.load_name in labware_forcing_p20 or destination_labware in labware_forcing_p20:
                p20_ops.append(op)
                allocated_operations.append(op[0])
            else:
                p300_single_ops.append(op)
                allocated_operations.append(op[0])

        for i in range(len(volumes)):
            if i not in allocated_operations:
                p20_ops.append([i, source_wells[i], destination_wells[i], volumes[i]])

        return multichannel_operations, p300_single_ops, p20_ops
        
    def _find_parent(self, well: Well):
        while not isinstance(well, str):
            well = well.parent
        return well

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

    def sleep(self, duration):
        "Sleep if not in simulation mode"
        if self.simulation_mode:
            pass
        else:
            time.sleep(duration)

    def load_labware(self, model_string: str, deck_position: int, name: str = "", add_to_default=False):
        """
        Load a new labware onto the deck at the specified position. If the position contains a module,
        the labware is loaded on the module.

        Args:
            deck_position (int): The position on the deck where the labware should be placed.
            model_string (str): The model string of the labware to be loaded.
            name (str): An optional name for the labware.

        Returns:
            The loaded labware object.

        Example:
        >>> lh.load_labware("opentrons_10_tuberack_falcon_4x50ml_6x15ml_conical", 8, "Falcon tube rack")
        """
        logging.debug(f"Loading labware: {model_string} on position {deck_position}...")

        if not name:
            name = model_string
        
        # Check that name is not already on deck
        original_name = name
        suffix = 1

        # Check that the deck position is empty
        module = False
        if self.protocol_api.deck[deck_position] is not None:
            try:
                self.protocol_api.deck[deck_position].type
                module = True
            except AttributeError:
                raise ValueError(f"Deck position {deck_position} is already occupied. Please choose an empty position.")

        if module:
            logging.debug("Loading labware on the module")
            try:
                labware = self.protocol_api.deck[deck_position].load_labware(model_string)
            except ProtocolCommandFailedError:
                # The model string could match a custom labware file on the system
                with open(f'labware/{model_string}.json') as labware_file:
                    labware_def = json.load(labware_file)
                labware = self.protocol_api.deck[deck_position].load_labware_from_definition(labware_def, None)
        else:
            logging.debug("Loading labware on an empty slot")
            try:
                labware = self.protocol_api.load_labware(model_string, deck_position, label=name)
            except ProtocolCommandFailedError:
                # The model string could match a custom labware file on the system
                with open(f'labware/{model_string}.json') as labware_file:
                    labware_def = json.load(labware_file)
                labware = self.protocol_api.load_labware_from_definition(labware_def, deck_position)
        
        # Log the loading of the labware
        if module:
            msg = f"Loaded labware {model_string} at position {self.protocol_api.deck[deck_position]} with name '{name}'"
        else:
            msg = f"Loaded labware {model_string} at position {deck_position} with name '{name}'"
        logging.info(msg)

        if add_to_default:
            with open('default_layout.ot2', 'r') as file:
                default_layout = json.load(file)
            old = default_layout.get(deck_position)
            default_layout[deck_position] = model_string
            with open('default_layout.ot2', 'w') as file:
                json.dump(default_layout, file, indent=4)
            msg = f"{model_string} is now loaded on position {deck_position} by default."
            if old != model_string:
                msg += " This overrides the previous value of {old}."
            logging.info(msg)
        
        return labware     

    def unload_labware(self, labware):
        self.protocol_api.move_labware(labware=labware, location=self.protocol_api.OFF_DECK, use_gripper=False)

    def set_temperature(self, temperature: float, wait: bool = False):
        """
        Set the temperature of the temperature module.

        Args:
            temperature (float): The target temperature to set.
            wait (bool): If True, wait for the temperature to be set before returning. If False, set the temperature in a separate thread.
        """
        if wait:
            if self.temperature_timer:
                if self.temperature_module.target != temperature:
                    # Cancel the current thread if the target temperature has changed and set the new target temperature and thread
                    self.release_temperature()
                    self.temperature_module.set_temperature(temperature)
                else:
                    self.temperature_timer.join()
            else:
                self.temperature_module.set_temperature(temperature)
        else:
            self.temperature_timer = Thread(target=self.temperature_module.set_temperature, args=(temperature,))
            self.temperature_timer.start()

    def release_temperature(self):
        """
        Release the temperature module by deactivating it and joining any active temperature setting thread.
        """
        if self.temperature_timer:
            self.temperature_timer.join()  # there seems to be no way to cancel the thread / temperature set

        self.temperature_module.deactivate()
        self.temperature_timer = None

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
        self.start_shaking(speed)
        if duration > 0:
            if wait:
                time.sleep(duration)
                self.stop_shaking()
            else:
                # Start a thread to stop the shaker after the duration
                self.shaking_timer = Thread(target=self.shake, args=(speed, duration, True))
                self.shaking_timer.start()

    def start_shaking(self, speed: float):
        """
        Start shaking the shaker module.
        """
        self.shaker_module.set_and_wait_for_shake_speed(speed)

    def stop_shaking(self):
        """
        Stop shaking the shaker module.
        """
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
            new_tip: str="once",
            touch_tip: bool=False,
            blow_out_to: str="trash",
            trash_tips: bool=True,
            add_air_gap: bool=True,
            overhead_liquid: bool=True,
            mix_after=False,
            **kwargs):
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
        - blow_out_to (str, optional): Whether the remainder of liquid is blown out to "source", "destination" or "trash".
        - trash_tips (bool, optional): Whether to discard tips after use.
        - add_air_gap (bool, optional): Whether to add an air gap after aspiration.
        - overhead_liquid (bool, optional): Whether to aspirate extra liquid to ensure complete transfer.
        - mix_after (tuple, optional): First element is repetitions and second element is volume of mixing at the destination well after dispense. False when no mixing needed. Will block multi-dispense mode.
        - **kwargs: Additional keyword arguments for pipette operations.
        

        Returns:
        - list: A list of failed operations, each represented as [index, well, volume].

        TODO:
        - Don't stop on error, but keep handling the liquids and return the failed operations
        """
        logging.debug(f"Transfer called with new tip: {new_tip}")
        
        volumes = [volumes] * len(source_wells) if isinstance(volumes, float) or isinstance(volumes, int) else volumes
        volumes = volumes if isinstance(volumes, list) and len(volumes) == len(source_wells) else volumes * len(source_wells)

        # Parameter validation
        assert blow_out_to in ["source", "destination", "trash"], "The parameter blow_out_to must always be defined and one of source, destination or trash. Blow out happens only if there's air gap or overhead liquid"

        # Split the liquid handling operations so that the source wells are within one labware, and destination wells too
        source_labware = {well.parent for well in source_wells}
        destination_labware = {well.parent if isinstance(well, Well) else well for well in destination_wells}
        transfer_params = {
            "new_tip": new_tip,
            "touch_tip": touch_tip,
            "blow_out_to": blow_out_to,
            "trash_tips": trash_tips,
            "add_air_gap": add_air_gap,
            "overhead_liquid": overhead_liquid,
            **kwargs
        }
        failed_operations = []
        done = False
        if len(source_labware) > 1:
            for labware in source_labware:
                # Take a fresh tip only for the first call
                if transfer_params["new_tip"] == "once" and done:
                    transfer_params["new_tip"] = "never"
                indexes = [i for i, well in enumerate(source_wells) if well.parent == labware]
                failed_operations += self.transfer(
                    [volumes[i] for i in indexes], 
                    [source_wells[i] for i in indexes], 
                    [destination_wells[i] for i in indexes],
                    **transfer_params
                )
                done = True
        elif len(destination_labware) > 1:
            for labware in destination_labware:
                # Take a fresh tip only for the first call
                if transfer_params["new_tip"] == "once" and done:
                    transfer_params["new_tip"] = "never"
                indexes = [i for i, well in enumerate(destination_wells) if well.parent == labware or well == labware]
                failed_operations += self.transfer(
                    [volumes[i] for i in indexes], 
                    [source_wells[i] for i in indexes], 
                    [destination_wells[i] for i in indexes],
                    **transfer_params
                )
                done = True
        if done:
            return failed_operations

        # Allocate the liquid handling operations to each available pipette configuration
        # Format: [index, source well, destination well, volume]
        p300_multi_steps, p300_single_steps, p20_steps = self._allocate_liquid_handling_steps(
            source_wells=source_wells,
            destination_wells=destination_wells,
            volumes=volumes
        )

        # [pipette to use, in single channel mode, steps to take]
        allocated_sets = [
            [self.p300_multi, False, p300_multi_steps],
            [self.p300_multi, True, p300_single_steps],
            [self.p20, False, p20_steps],
        ]
        # When possible, group the operations for multi-dispense and multi-aspiration
        allocated_indexes = []
        for pipette, single_tip_mode, steps in allocated_sets:
            unique_source_wells = {op[1] for op in steps}
            unique_destination_wells = {op[2] for op in steps}
            # Scenario 1: shared source, possibly different destination
            grouped_sets = {1: [], 2: []}
            for pivot_set, p_idx in [[unique_source_wells, 1], [unique_destination_wells, 2]]:
                for pivot_well in pivot_set:
                    ops = [op for op in steps if op[p_idx] == pivot_well and op[0] not in allocated_indexes]
                    ops.sort(key=lambda x: x[-1])
                    current_set = []
                    set_volume = 0
                    for idx, source, destination, volume in ops:
                        if idx in allocated_indexes or volume <= 0:
                            continue
                        if volume < pipette.min_volume:
                            logging.warning("Volume too low, requested operation ignored: dispense {volume} ul to {well} with pipette {pipette}")
                            failed_operations.append([source, destination, volume])
                            continue
                        # No multi-dispense if tip change is set as "always", no-multi aspiration if if tip change set as "always" or "on aspiration"
                        if set_volume + volume < pipette.max_volume and new_tip != "always" and ((p_idx==1 and mix_after is False) or (p_idx==2 and new_tip != "on aspiration")):
                            current_set.append([source, destination, volume])
                            set_volume += volume
                            allocated_indexes.append(idx)
                        else:
                            if current_set:
                                grouped_sets[p_idx].append(current_set)
                                current_set = []
                            if volume > pipette.max_volume:
                                sets = math.ceil(volume / pipette.max_volume)
                                set_volume = volume / sets
                                for i in range(sets):
                                    grouped_sets[p_idx].append([[source, destination, set_volume]])
                                allocated_indexes.append(idx)
                                continue
                            current_set.append([source, destination, volume])
                            allocated_indexes.append(idx)
                            set_volume = volume
                    if current_set:
                        grouped_sets[p_idx].append(current_set)
            aspiration_sets = grouped_sets[1]
            dispense_sets = grouped_sets[2]

            
            first_round = True
            if single_tip_mode and steps:
                self._set_single_tip_mode(True)

            # Actual liquid handling
            # Single aspirate, multi-dispense
            for aspiration_set in aspiration_sets:
                # [[[source, dest, vol], [source, dest, vol]],[[source, dest2, vol2], [source, dest2, vol2]],...]
                source_well = aspiration_set[0][0]
                set_volume = sum([op[2] for op in aspiration_set])
                extra_volume = min(pipette.min_volume, max(0, pipette.max_volume - set_volume)) if overhead_liquid else 0
                air_gap = min(pipette.min_volume * 2, 20, max(0, pipette.max_volume - set_volume - extra_volume)) if add_air_gap else 0
                match new_tip:
                    case "always" | "on aspiration":
                        if pipette.has_tip:
                            pipette.drop_tip() if trash_tips or single_tip_mode else pipette.return_tip()
                        pipette.pick_up_tip()
                    case "once":
                        if first_round:
                            if pipette.has_tip:
                                pipette.drop_tip()  # Tips are trashed always, because they are leftovers from previous operations
                            first_round = False
                        if not pipette.has_tip:
                            pipette.pick_up_tip()
                    case _:
                        # Keep the tips already attached, otherwise pick up fresh ones
                        if not pipette.has_tip:
                            pipette.pick_up_tip() 
                if air_gap:
                    pipette.aspirate(
                        volume=air_gap,
                        location=source_well.top(5)
                    )
                pipette.aspirate(
                    volume=set_volume + extra_volume,
                    location=source_well
                )
                for idx, (source, dest, volume) in enumerate(aspiration_set):
                    pipette.dispense(volume, dest, **kwargs)
                
                if pipette.current_volume:
                    if blow_out_to != "trash" and new_tip in ["always", "on aspiration"]:
                        logging.warning("Blow out to source or destination may result in contamination even when changing tips!")
                    if blow_out_to == "trash":
                        pipette.blow_out(self.trash)
                    elif blow_out_to == "source":
                        pipette.blow_out(source_well.top())
                    elif blow_out_to == "destination":
                        pipette.blow_out(dest.top())

                
                if mix_after:
                    # Do not mix if there's liquid left it the pipette
                    if len(aspiration_set) == 1:
                        if mix_after[1] > pipette.max_volume or mix_after[1] < pipette.min_volume:
                            logging.warning(f"Mixing ignored: mixing volume ({mix_after[1]} ul) exceeds the pipette volume range ({pipette.min_volume} ul - {pipette.max_volume} ul)")
                        else:
                            pipette.mix(repetitions=mix_after[0], volume=mix_after[1], location=dest)
                    else:
                        logging.warning("Mixing ignored: trying to mix several wells during multi-dispense, which is not allowed.")
            
            # Multi-aspirate single dispense
            for dispense_set in dispense_sets:
                destination_well = dispense_set[0][1]
                set_volume = sum([op[2] for op in dispense_set])
                air_gap = min(pipette.min_volume * 2, pipette.max_volume - set_volume - extra_volume) if add_air_gap else 0

                match new_tip:
                    case "always" | "on aspiration":
                        if pipette.has_tip:
                            pipette.drop_tip() if trash_tips or single_tip_mode else pipette.return_tip()
                        pipette.pick_up_tip()
                    case "once":
                        if first_round:
                            if pipette.has_tip:
                                pipette.drop_tip()  # Tips are trashed always, because they are leftovers from previous operations
                            first_round = False
                        if not pipette.has_tip:
                            pipette.pick_up_tip()
                    case _:
                        # Keep the tips already attached, otherwise pick up fresh ones
                        if not pipette.has_tip:
                            pipette.pick_up_tip() 
                if air_gap:
                    pipette.aspirate(
                        volume=air_gap,
                        location=aspiration_set[0][0].top(5)
                    )
                for source, dest, volume in aspiration_set:
                    pipette.aspirate(
                        volume=volume,
                        location=source,
                        **kwargs
                    )
                pipette.dispense(set_volume, destination_well, **kwargs)
                if pipette.current_volume:
                    if blow_out_to == "trash":
                        pipette.blow_out(self.trash)
                    elif blow_out_to == "source":
                        logging.warning("Ignoring blow-out: 'source' is invalid parameter when there are multiple sources")
                    else:
                        pipette.blow_out(destination_well.top())
                
                if mix_after:
                    pipette.mix(repetitions=mix_after[0], volume=mix_after[1], location=destination_well)


            if single_tip_mode:
                self._set_single_tip_mode(False)

        if pipette.has_tip:
            if new_tip != "never":
                if trash_tips:
                    pipette.drop_tip()
                else:
                    pipette.return_tip()

        return failed_operations

    def distribute(
        self,
        volumes,
        source_well,
        destination_wells,
        new_tip: str="once",
        touch_tip: bool=False,
        blow_out_to: bool="trash",
        trash_tips: bool=True,
        add_air_gap: bool=True,
        overhead_liquid: bool=True,
        **kwargs):
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
            blow_out_to (bool or str, optional): Whether the remainder of liquid is blown out to "source", "destination" or "trash". False will result in no blow-out.
            trash_tips (bool, optional): Whether to discard the tip to the trash after use (True) or return to tip box (False). Default is True.
            add_air_gap (bool, optional): Whether to add an air gap before aspirating the liquid. Default is True.
            overhead_liquid (bool, optional): Whether to aspirate extra liquid for more accurate dispensing, but consumes more source liquid. Default is True.
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
            - Source well out of range for multichannel pipette in the single mode
            - Single tip touch before aspiration if reusing tips
            - Keep using the currently attached tips for the first aspiration (assume clean tips from previous operation)
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

        if blow_out_to is False and new_tip in ["on aspiration", "always"]:
            msg = "blow_out_to should be set to True when new_tip is 'on aspiration' or 'always'. Setting to True."
            logging.warning(msg)
            blow_out_to=True

        if isinstance(volumes, float) or isinstance(volumes, int):
            volumes = [volumes]*len(destination_wells)

        return self.transfer(
            volumes,
            [source_well]*len(destination_wells),
            destination_wells,
            new_tip=new_tip,
            touch_tip=touch_tip,
            blow_out_to=blow_out_to,
            trash_tips=trash_tips,
            add_air_gap=add_air_gap,
            overhead_liquid=overhead_liquid,
            **kwargs
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
        **kwargs):
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
            if len(destination_well) >= 1:
                raise TypeError(f"The destination well must be a Well object or a list of a single Well, got {type(destination_well)}.")
            destination_well = destination_well[0]
        if not isinstance(destination_well, Well) and not isinstance(destination_well, TrashBin):
            raise TypeError(f"The destination well must be a Well object, TashBin or a list of a single Well, got {type(destination_well)}.")

        if isinstance(source_wells, Well):
            source_wells = [source_wells]

        if new_tip not in ["always", "once", "never", "on aspiration"]:
            raise ValueError(f"Got an invalid value for the optional argument 'new_tip': {new_tip}")

        if isinstance(volumes, (float, int)):
            volumes = [volumes] * (len(source_wells) if isinstance(source_wells, list) else 1)

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
            **kwargs
        )

    def stamp(
        self,
        volume: float,
        source_plate,
        destination_plate,
        sample_count: int =0,
        new_tip: str="always",
        touch_tip: bool=False,
        blow_out_to: bool="destination",
        trash_tips: bool=True,
        add_air_gap: bool=True,
        overhead_liquid: bool=False,
        **kwargs):
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
            blow_out_to (bool or str, optional): Whether the remainder of liquid is blown out to "source", "destination" or "trash". False will result in no blow-out.
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
            volumes = [volume]*len(destination_wells)

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
            **kwargs
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
        logging.debug(f"Mixing {len(wells)} wells with {repetitions} repetitions at {volume}µL each")

        fresh_tip = False
        i = 0
        while i < len(wells):
            well = wells[i]
            column_wells = well.parent.columns_by_name()[well.well_name[1:]]
            all_wells_in_column = all(w in wells for w in column_wells)

            if all_wells_in_column and volume > self.p20.max_volume:
                pipette = self.p300_multi
                self._set_single_tip_mode(False)
            elif volume > self.p20.max_volume:
                pipette = self.p300_multi
                self._set_single_tip_mode(True)
            else:
                pipette = self.p20
                
            if not pipette.has_tip:
                pipette.pick_up_tip()
            elif not fresh_tip and new_tip == "always" or (i == 0 and new_tip == "once"):
                if pipette.has_tip:
                    if trash_tip:
                        pipette.drop_tip()
                    else:
                        pipette.return_tip()
                pipette.pick_up_tip()

            pipette.mix(repetitions=repetitions, volume=volume, location=well)
            fresh_tip = False

            if all_wells_in_column:
                i += len(column_wells)  # Skip the remaining wells in the column
            else:
                i += 1

        if new_tip in ["once", "always"] and pipette.has_tip:
            if trash_tip:
                pipette.drop_tip()
            else:
                pipette.return_tip()
        
        if pipette == self.p300_multi:
            self._set_single_tip_mode(False)

    def engage_magnets(self, height=5.4, **kwargs):
        """
        Engage the magnets of the magnetic module.

        Additionally accepts any keyword arguments accepted by the opentrons engage method.
        """
        self.magnetic_module.engage(height_from_base=height, **kwargs)

    def disengage_magnets(self):
        """
        Disengage the magnets of the magnetic module.
        """
        self.magnetic_module.disengage()