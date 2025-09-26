import json
import unittest
import math
import random
from unittest.mock import MagicMock, patch, mock_open
from ot_handler.liquid_handler import LiquidHandler


class TestLiquidHandlerDistribute(unittest.TestCase):
    def setUp(self):
        # Initialize LiquidHandler with simulation mode
        self.lh = LiquidHandler(simulation=True, load_default=False)
        self.lh.p300_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_300ul", "7")
        )
        self.lh.single_p300_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_300ul", "6")
        )
        self.lh.single_p20_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_20ul", "11")
        )

        # Mock pipettes
        self.lh.p300_multi = MagicMock()
        self.lh.p20 = MagicMock()
        self.lh.p20.min_volume = 1
        self.lh.p20.max_volume = 20
        self.lh.p300_multi.min_volume = 20
        self.lh.p300_multi.max_volume = 300

        # Mock labware
        self.mock_labware = self.lh.load_labware(
            "nest_96_wellplate_100ul_pcr_full_skirt", 9, "mock labware"
        )
        self.mock_reservoir = self.lh.load_labware(
            "nest_12_reservoir_15ml", 2, "mock reservoir source"
        )
        self.dest_wells = self.mock_labware.wells()

        # Create mock wells
        self.source_well = self.mock_reservoir.wells("A1")[0]

    def test_distribute_variable_volumes_first_row(self):
        first_row_labware = self.lh.load_labware(
            "nest_96_wellplate_100ul_pcr_full_skirt", 3, "first row"
        )
        # Arrange
        p300_single_volumes = []
        p300_single_volumes.append([25, 30, 35, 40, 60, 80, 0, 0])
        p20_volumes = []
        p20_volumes.append([1, 5, 10, 12, 18, 20, 2, 13])
        p20_volumes.append([0, 0, 0, 0, 0, 0, 2, 13])
        p20_volumes.append([0, 0, 0, 0, 0, 0, 30, 30])
        p20_volumes.append([10] * 8)
        p300_multi_volumes = []
        p300_multi_volumes.append([21] * 8)
        p300_multi_volumes.append([30] * 8)
        p300_multi_volumes.append([80] * 8)
        p300_multi_volumes.append([100] * 8)
        both_volumes = []
        both_volumes.append([1, 5, 10, 30, 50, 20, 2, 13])
        both_volumes.append([30] * 7 + [40])

        for i, volumes in enumerate(p300_multi_volumes):
            with self.subTest(volumes=volumes):
                self.lh.distribute(
                    volumes=volumes,
                    source_well=self.source_well,
                    destination_wells=first_row_labware.columns()[i],
                    new_tip="once",
                )
                self.lh.p300_multi.dispense.assert_called_once()
                self.lh.p20.dispense.assert_not_called()
                self.lh.p300_multi.reset_mock()
                self.lh.p20.reset_mock()

        for i, volumes in enumerate(p20_volumes):
            with self.subTest(volumes=volumes):
                self.lh.distribute(
                    volumes=volumes,
                    source_well=self.source_well,
                    destination_wells=first_row_labware.columns()[i],
                    new_tip="always",
                )
                self.lh.p300_multi.dispense.assert_not_called()
                self.assertGreaterEqual(
                    self.lh.p20.dispense.call_count,
                    sum([math.ceil(v / self.lh.p20.max_volume) for v in volumes if v]),
                )
                self.lh.p300_multi.reset_mock()
                self.lh.p20.reset_mock()

        for i, volumes in enumerate(p300_single_volumes):
            with self.subTest(volumes=volumes):
                self.lh.distribute(
                    volumes=volumes,
                    source_well=self.source_well,
                    destination_wells=first_row_labware.columns()[i],
                    new_tip="always",
                )
                self.assertEqual(
                    self.lh.p300_multi.dispense.call_count, len([v for v in volumes if v > 20])
                )
                self.lh.p20.dispense.assert_not_called()
                self.lh.p300_multi.reset_mock()
                self.lh.p20.reset_mock()

        for i, volumes in enumerate(both_volumes):
            with self.subTest(volumes=volumes):
                self.lh.distribute(
                    volumes=volumes,
                    source_well=self.source_well,
                    destination_wells=first_row_labware.columns()[i],
                    new_tip="once",
                )
                self.lh.p300_multi.dispense.assert_called()
                self.lh.p20.dispense.assert_called()
                self.lh.p300_multi.reset_mock()
                self.lh.p20.reset_mock()

    def test_distribute_variable_volumes_second_row(self):
        # On the second row, single mode multichannel should be able to access anywhere
        second_row_labware = self.lh.load_labware(
            "nest_96_wellplate_100ul_pcr_full_skirt", 5, "second row"
        )
        p300_single_volumes = []
        p300_single_volumes.append([25, 30, 35, 40, 60, 80, 60, 50])
        p300_single_volumes.append([30] * 7 + [40])
        p20_volumes = []
        p20_volumes.append([1, 5, 10, 12, 18, 20, 2, 13])
        p20_volumes.append([0, 0, 0, 0, 0, 0, 2, 13])
        p20_volumes.append([10] * 8)
        p300_multi_volumes = []
        p300_multi_volumes.append([21] * 8)
        p300_multi_volumes.append([30] * 8)
        p300_multi_volumes.append([80] * 8)
        p300_multi_volumes.append([100] * 8)
        both_volumes = []
        both_volumes.append([1, 5, 10, 30, 50, 20, 2, 13])

        for i, volumes in enumerate(p300_multi_volumes):
            with self.subTest(volumes=volumes):
                self.lh.distribute(
                    volumes=volumes,
                    source_well=self.source_well,
                    destination_wells=second_row_labware.columns()[i],
                    new_tip="once",
                )
                self.lh.p300_multi.dispense.assert_called_once()
                self.lh.p20.dispense.assert_not_called()
                self.lh.p300_multi.reset_mock()
                self.lh.p20.reset_mock()

        for i, volumes in enumerate(p20_volumes):
            with self.subTest(volumes=volumes):
                self.lh.distribute(
                    volumes=volumes,
                    source_well=self.source_well,
                    destination_wells=second_row_labware.columns()[i],
                    new_tip="always",
                )
                self.lh.p300_multi.dispense.assert_not_called()
                self.assertGreaterEqual(
                    self.lh.p20.dispense.call_count,
                    sum([math.ceil(v / self.lh.p20.max_volume) for v in volumes if v]),
                )
                self.lh.p300_multi.reset_mock()
                self.lh.p20.reset_mock()

        for i, volumes in enumerate(p300_single_volumes):
            with self.subTest(volumes=volumes):
                self.lh.distribute(
                    volumes=volumes,
                    source_well=self.source_well,
                    destination_wells=second_row_labware.columns()[i],
                    new_tip="never",
                )
                self.assertEqual(
                    self.lh.p300_multi.dispense.call_count, len([v for v in volumes if v > 20])
                )
                self.lh.p20.dispense.assert_not_called()
                self.lh.p300_multi.reset_mock()
                self.lh.p20.reset_mock()

        for i, volumes in enumerate(both_volumes):
            with self.subTest(volumes=volumes):
                self.lh.distribute(
                    volumes=volumes,
                    source_well=self.source_well,
                    destination_wells=second_row_labware.columns()[i],
                    new_tip="once",
                )
                self.lh.p300_multi.dispense.assert_called()
                self.lh.p20.dispense.assert_called()
                self.lh.p300_multi.reset_mock()
                self.lh.p20.reset_mock()

    def test_distribute_multiple_volumes_multi_channel(self):
        volumes = [100] * 8  # Assuming multi-channel

        # Mock destination Wells to simulate a multi-channel scenario
        self.lh.distribute(
            volumes=volumes,
            source_well=self.source_well,
            destination_wells=self.dest_wells[:8],
            new_tip="always",
            overhead_liquid=False,
        )
        # Assert
        self.lh.p300_multi.aspirate.assert_called_with(volume=100, location=self.source_well)
        self.lh.p300_multi.dispense.assert_called()
        self.lh.p300_multi.blow_out.assert_called()

    def test_distribute_invalid_new_tip(self):
        # Arrange
        volume = 10
        new_tip = "invalid_option"

        # Act & Assert
        with self.assertRaises(ValueError) as context:
            self.lh.distribute(
                volumes=volume,
                source_well=self.source_well,
                destination_wells=self.dest_wells,
                new_tip=new_tip,
            )
        self.assertIn("invalid value for the optional argument 'new_tip'", str(context.exception))

    def test_distribute_volume_below_minimum(self):
        # Arrange
        volume = 0.1  # Below p20.min_volume

        # Act & Assert
        with self.assertLogs(level="WARNING") as log:
            self.lh.distribute(
                volumes=volume,
                source_well=self.source_well,
                destination_wells=[self.dest_wells[0]],
                new_tip="never",
            )
        self.assertIn("Volume too low, requested operation ignored", log.output[0])
        self.lh.p20.dispense.assert_not_called()

    def test_distribute_multiple_labwares(self):
        # Arrange
        another_labware = self.lh.load_labware("nest_12_reservoir_15ml", 3, "Mock reservoir")
        another_well = another_labware.wells("A1")[0]
        destination_wells = self.dest_wells[:3] + [another_well] + self.dest_wells[3:]
        volumes = [15] * len(destination_wells)

        # Act & Assert
        with patch.object(self.lh, "transfer", wraps=self.lh.transfer) as mock_transfer:
            self.lh.distribute(
                volumes=volumes,
                source_well=self.source_well,
                destination_wells=destination_wells,
                new_tip="always",
            )

            # Assert
            # The transfer method should be called recursively for each labware
            self.assertEqual(self.lh.p20.dispense.call_count, len(destination_wells))
            self.assertEqual(mock_transfer.call_count, 3)

    def test_distribute_large_volume_with_multiple_aspirations(self):
        # Arrange
        volume = 90  # Exceeds p20.max_volume, should use p300_multi

        # Act
        self.lh.distribute(
            volumes=volume,
            source_well=self.source_well,
            destination_wells=self.dest_wells[:3],
            new_tip="always",
            overhead_liquid=False,
        )

        # Assert
        self.lh.p300_multi.aspirate.assert_called_with(volume=90, location=self.source_well)
        self.lh.p300_multi.dispense.assert_called()

    def test_distribute_single_vs_multiple_aspirations(self):
        # Arrange
        volume = 80  # Exceeds p20.max_volume, should use p300_multi
        wells = self.dest_wells[:16]
        wells.pop(10)  # Second column is missing a well
        # Act
        self.lh.distribute(
            volumes=volume,
            source_well=self.source_well,
            destination_wells=wells,
            new_tip="once",
            overhead_liquid=False,
        )

        # Assert
        self.assertEqual(self.lh.p300_multi.dispense.call_count, 1 + 7)

    def test_distribute_slightly_over_capacity_volume(self):
        # Arrange
        volume = self.lh.p300_multi.max_volume + 1  # Slightly over p300_multi's max volume
        test_labware = self.lh.load_labware("nest_96_wellplate_2ml_deep", 5, "test")

        # Act
        with self.subTest(wells=[w.well_name for w in test_labware.columns()[0]], volumes=volume):
            self.lh.distribute(
                volumes=volume,
                source_well=self.source_well,
                destination_wells=test_labware.columns()[0],
                new_tip="once",
                overhead_liquid=False,
            )
            # Assert
            # Ensure p300_multi is used for both the main volume and the remainder
            self.assertEqual(self.lh.p300_multi.dispense.call_count, 2)
            self.lh.p20.dispense.assert_not_called()
            self.lh.p300_multi.dispense.reset_mock()
            self.lh.p20.dispense.reset_mock()

        # Dispense incomplete column
        wells = test_labware.columns()[1]
        wells.pop(0)
        with self.subTest(wells=[w.well_name for w in wells], volumes=volume):
            self.lh.distribute(
                volumes=volume,
                source_well=self.source_well,
                destination_wells=wells,
                new_tip="once",
                overhead_liquid=False,
            )

            # Assert
            # Ensure p300_multi is used for both the main volume and the remainder
            self.assertEqual(self.lh.p300_multi.dispense.call_count, 2 * len(wells))
            self.lh.p20.dispense.assert_not_called()
            self.lh.p300_multi.dispense.reset_mock()
            self.lh.p20.dispense.reset_mock()

    def test_distribute_with_mix_after(self):
        # Arrange
        volume = 50
        mix_after = (3, 20)  # 3 repetitions of 20µL each
        test_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 3, "test")

        # Act
        self.lh.distribute(
            volumes=volume,
            source_well=self.source_well,
            destination_wells=test_labware.columns()[0],
            new_tip="once",
            overhead_liquid=False,
            mix_after=mix_after,
        )

        # Assert
        self.lh.p300_multi.mix.assert_called_once_with(
            repetitions=mix_after[0], volume=mix_after[1], location=test_labware.columns()[0][0]
        )
        self.lh.p300_multi.dispense.assert_called()
        self.lh.p20.dispense.assert_not_called()
        self.lh.p300_multi.mix.reset_mock()
        self.lh.p300_multi.dispense.reset_mock()

    def test_distribute_with_mix_after_exceed_pipette_range(self):
        # Arrange
        volume = 50
        mix_after = (
            3,
            1,
        )  # 3 repetitions of 1µL each, which should fail because out of volume range
        test_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 3, "test")

        # Act
        self.lh.distribute(
            volumes=volume,
            source_well=self.source_well,
            destination_wells=test_labware.columns()[0],
            new_tip="once",
            overhead_liquid=False,
            mix_after=mix_after,
        )

        # Assert
        self.lh.p300_multi.mix.assert_not_called()
        self.lh.p300_multi.dispense.assert_called()
        self.lh.p20.dispense.assert_not_called()
        self.lh.p300_multi.mix.reset_mock()
        self.lh.p300_multi.dispense.reset_mock()

    def test_p300_access_to_first_row(self):
        # The single channel mode in multichannel pipette can only reach rows A-F
        # Ensure that single channel pipette is used otherwise

        # Arrange
        volume = 100  # Exceeds p300_multi.max_volume, should raise ValueError
        test_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 3, "test")

        # Act & Assert
        self.lh.distribute(
            volumes=volume,
            source_well=self.source_well,
            destination_wells=test_labware.wells("H1"),
            new_tip="once",
            overhead_liquid=False,
        )
        self.lh.p300_multi.dispense.assert_not_called()
        self.lh.p20.dispense.assert_called()

        # Reset mock calls
        self.lh.p300_multi.dispense.reset_mock()
        self.lh.p20.dispense.reset_mock()

        # Act & Assert
        self.lh.distribute(
            volumes=volume,
            source_well=self.source_well,
            destination_wells=test_labware.wells("A1"),
            new_tip="once",
            overhead_liquid=False,
        )
        self.lh.p300_multi.dispense.assert_called()
        self.lh.p20.dispense.assert_not_called()


class TestLiquidHandlerTransfer(unittest.TestCase):
    def setUp(self):
        # Initialize LiquidHandler with simulation mode
        self.lh = LiquidHandler(simulation=True, load_default=False)
        self.lh.p300_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_300ul", "7")
        )
        self.lh.single_p300_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_300ul", "6")
        )
        self.lh.single_p20_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_20ul", "11")
        )

        # Mock pipettes
        self.lh.p300_multi = MagicMock()
        self.lh.p20 = MagicMock()
        self.lh.p20.min_volume = 1
        self.lh.p20.max_volume = 20
        self.lh.p300_multi.min_volume = 20
        self.lh.p300_multi.max_volume = 300

        # Mock labware
        self.mock_labware = self.lh.load_labware(
            "nest_96_wellplate_100ul_pcr_full_skirt", 9, "mock labware"
        )
        self.mock_reservoir = self.lh.load_labware(
            "nest_12_reservoir_15ml", 2, "mock reservoir source"
        )
        self.dest_wells = self.mock_labware.wells()

        # Create mock wells
        self.source_well = self.mock_reservoir.wells("A1")[0]

    def test_transfer_multi_aspirate_with_mix_after(self):
        # Arrange
        volume = 50
        mix_after = (3, 21)  # 3 repetitions of 21µL each
        test_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 3, "test")

        # Act
        self.lh.transfer(
            volumes=[volume] * 16,
            source_wells=test_labware.columns()[2] + test_labware.columns()[3],
            destination_wells=test_labware.columns()[0] + test_labware.columns()[0],
            new_tip="never",
            overhead_liquid=False,
            mix_after=mix_after,
        )

        # Assert
        self.lh.p300_multi.mix.assert_called_once_with(
            repetitions=mix_after[0], volume=mix_after[1], location=test_labware.columns()[0][0]
        )
        self.lh.p300_multi.dispense.assert_called()
        self.lh.p20.dispense.assert_not_called()
        self.lh.p300_multi.drop_tip.assert_not_called()
        self.lh.p300_multi.mix.reset_mock()
        self.lh.p300_multi.dispense.reset_mock()

    def test_transfer_mutlichannel_on_inequal_full_volumes(self):
        # If inequal volumes exceed the pipette's max volume, the pipette should aspirate and dispense the first set of volumes in the multichannel mode, and then use the single channel mode for the remaining volumes (with multidispense)

        # Arrange
        volumes = [330, 325, 350, 328, 335, 340, 345, 337]

        self.lh.transfer(
            volumes=volumes,
            source_wells=[self.mock_reservoir.wells()[0]] * 8,
            destination_wells=list(self.mock_labware.columns()[0]),
            new_tip="never",
            overhead_liquid=False,
            add_air_gap=False,
        )

        self.assertEqual(self.lh.p300_multi.dispense.call_count, 1 + 8)
        self.assertEqual(self.lh.p300_multi.aspirate.call_count, 2)

    def test_transfer_order_of_operations(self):
        volumes = [5, 2, 7, 17, 12, 15, 1, 9]
        source_well = self.mock_reservoir.wells()[0]
        dest_wells = [
            self.mock_labware[w] for w in ["A1", "A2", "B1", "B2", "A3", "C1", "D1", "F5"]
        ]

        # Mock the p20 dispense method to collect call arguments
        original_dispense = self.lh.p20.dispense
        dispense_calls = []

        def mock_dispense(volume, location, **kwargs):
            dispense_calls.append((volume, location))
            return original_dispense(volume, location, **kwargs)

        self.lh.p20.dispense = mock_dispense

        self.lh.transfer(
            volumes=volumes,
            source_wells=[source_well] * 8,
            destination_wells=dest_wells,
            new_tip="always",
            overhead_liquid=False,
            add_air_gap=False,
        )

        # Check number of calls
        self.assertEqual(len(dispense_calls), 8)
        self.assertEqual(self.lh.p300_multi.dispense.call_count, 0)

        # Check each dispense operation matches expected volume and well
        expected_operations = sorted(
            zip(volumes, dest_wells), key=lambda x: (x[1].well_name[1:], x[1].well_name[0])
        )

        for (volume, well), call in zip(expected_operations, dispense_calls):
            call_vol, call_well = call  # Unpack our collected call args

            self.assertEqual(
                call_well,
                well,
                f"Was expecting {well.well_name} but got {call_well.well_name}",
            )
            self.assertEqual(call_vol, volume, f"Was expecting {volume} but got {call_vol}")

        # Verify pick_up_tip and drop_tip were called for each operation (new_tip="always")
        self.assertEqual(self.lh.p20.pick_up_tip.call_count, 8)

        # Reset the mock for future tests
        self.lh.p20.dispense = original_dispense

    def test_transfer_with_large_volumes(self):
        # Arrange
        volumes = [1200, 1200]
        source_wells = [self.mock_reservoir.wells()[0]] * 2
        destination_wells = list(self.mock_labware.wells()[:2])

        # Act
        self.lh.transfer(
            volumes=volumes,
            source_wells=source_wells,
            destination_wells=destination_wells,
            new_tip="always",
            overhead_liquid=False,
            add_air_gap=False,
        )

        # Assert
        self.assertEqual(self.lh.p300_multi.dispense.call_count, 8)
        self.assertEqual(self.lh.p300_multi.aspirate.call_count, 8)
        self.assertEqual(self.lh.p20.dispense.call_count, 0)
        self.assertEqual(self.lh.p20.aspirate.call_count, 0)

    def test_transfer_with_large_volumes_and_filter_tips(self):
        # Initialize LiquidHandler with simulation mode
        lh = LiquidHandler(simulation=True, load_default=False)
        lh.load_tips("opentrons_96_filtertiprack_200ul", 7, single_channel=False)
        lh.load_tips("opentrons_96_filtertiprack_200ul", 6, single_channel=True)
        lh.load_tips("opentrons_96_tiprack_20ul", 11, single_channel=True)

        # Mock pipettes
        lh.p300_multi = MagicMock()
        lh.p20 = MagicMock()
        lh.p20.min_volume = 1
        lh.p20.max_volume = 20
        lh.p300_multi.min_volume = 20
        lh.p300_multi.max_volume = 300

        # Mock labware
        mock_labware = lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 9, "mock labware")
        mock_reservoir = lh.load_labware("nest_12_reservoir_15ml", 2, "mock reservoir source")

        # Arrange
        volumes = [1000, 1000]
        source_wells = [mock_reservoir.wells()[0]] * 2
        destination_wells = list(mock_labware.wells()[:2])

        # Act
        lh.transfer(
            volumes=volumes,
            source_wells=source_wells,
            destination_wells=destination_wells,
            new_tip="always",
            overhead_liquid=False,
            add_air_gap=False,
        )

        # Assert
        self.assertEqual(lh.p300_multi.dispense.call_count, 10)
        self.assertEqual(lh.p300_multi.aspirate.call_count, 10)
        self.assertEqual(lh.p20.dispense.call_count, 0)
        self.assertEqual(lh.p20.aspirate.call_count, 0)


class TestLiquidHandlerReversePipetting(unittest.TestCase):
    def setUp(self):
        # Initialize LiquidHandler with simulation mode
        self.lh = LiquidHandler(simulation=True, load_default=False)
        
        self.lh.load_tips("opentrons_96_tiprack_300ul", "7", single_channel=False)
        self.lh.load_tips("opentrons_96_tiprack_300ul", "6", single_channel=True)
        self.lh.load_tips("opentrons_96_tiprack_20ul", "11", single_channel=True)

        # Mock pipettes
        self.lh.p300_multi = MagicMock()
        self.lh.p20 = MagicMock()
        self.lh.p20.min_volume = 1
        self.lh.p20.max_volume = 20
        self.lh.p300_multi.min_volume = 20
        self.lh.p300_multi.max_volume = 300

        # Mock labware
        self.mock_labware = self.lh.load_labware(
            "nest_96_wellplate_100ul_pcr_full_skirt", 9, "mock labware"
        )
        self.mock_reservoir = self.lh.load_labware(
            "nest_12_reservoir_15ml", 2, "mock reservoir source"
        )
        self.dest_wells = self.mock_labware.wells()

        # Create mock wells
        self.source_well = self.mock_reservoir.wells("A1")[0]

    def test_reverse_pipetting_with_never_tip_change(self):
        """Test reverse pipetting with new_tip='never' - pipette should retain liquid until tip is manually dropped"""
        volumes = [50, 45, 40, 35]  # Multiple dispenses with the same tip
        destination_wells = self.dest_wells[:4]
        
        # Mock the pipette to track current_volume
        self.lh.p300_multi.current_volume = 0
        
        # Simulate reverse pipetting behavior - pipette retains overhead liquid
        def mock_aspirate(volume, location, **kwargs):
            self.lh.p300_multi.current_volume += volume
            
        def mock_dispense(volume, location, **kwargs):
            # In reverse pipetting, we only dispense the requested volume, not all liquid
            # The pipette can dispense below min_volume, but overhead liquid should remain
            self.lh.p300_multi.current_volume = max(0, self.lh.p300_multi.current_volume - volume)
            
        self.lh.p300_multi.aspirate.side_effect = mock_aspirate
        self.lh.p300_multi.dispense.side_effect = mock_dispense

        # Act - perform reverse pipetting
        failed_ops = self.lh.distribute(
            volumes=volumes,
            source_well=self.source_well,
            destination_wells=destination_wells,
            new_tip="never",
            overhead_liquid=True,
            blow_out_to="",  # Empty string prevents blow-out
        )

        # Assert - verify reverse pipetting behavior
        self.assertEqual(len(failed_ops), 0, "No operations should fail")
        
        # Verify that blow_out was never called (key characteristic of reverse pipetting)
        self.lh.p300_multi.blow_out.assert_not_called()
        
        # Verify aspirate was called (should aspirate overhead liquid each time)
        self.assertGreater(self.lh.p300_multi.aspirate.call_count, 0)
        
        # Verify dispense was called for each destination
        self.assertEqual(self.lh.p300_multi.dispense.call_count, len(volumes))
        
        # Verify pipette behavior (in reverse pipetting, overhead liquid is aspirated initially)
        # The key is that blow_out is not called, so any remaining liquid stays in the tip
        self.assertGreaterEqual(
            self.lh.p300_multi.current_volume, 
            0,
            "Pipette should have some liquid or be empty, but never negative"
        )

    def test_multivolley_reverse_pipetting_with_never_tip_change(self):
        """Test reverse pipetting with new_tip='never' - pipette should retain liquid until tip is manually dropped"""
        volumes = [50, 35, 70, 21, 55, 150, 55, 100]  # Multiple dispenses with the same tip (>300µL total)
        destination_wells = self.dest_wells[:8]
        
        # Mock the pipette to track current_volume
        self.lh.p300_multi.current_volume = 0
        
        # Simulate reverse pipetting behavior - pipette retains overhead liquid
        def mock_aspirate(volume, location, **kwargs):
            self.lh.p300_multi.current_volume += volume
            
        def mock_dispense(volume, location, **kwargs):
            # In reverse pipetting, we only dispense the requested volume, not all liquid
            # The pipette can dispense below min_volume, but overhead liquid should remain
            self.lh.p300_multi.current_volume = max(0, self.lh.p300_multi.current_volume - volume)
            
        self.lh.p300_multi.aspirate.side_effect = mock_aspirate
        self.lh.p300_multi.dispense.side_effect = mock_dispense

        # Act - perform reverse pipetting
        failed_ops = self.lh.distribute(
            volumes=volumes,
            source_well=self.source_well,
            destination_wells=destination_wells,
            new_tip="never",
            overhead_liquid=True,
            add_air_gap=False,
            blow_out_to="",  # Empty string prevents blow-out
        )

        # Assert - verify reverse pipetting behavior
        self.assertEqual(len(failed_ops), 0, "No operations should fail")
        
        # Verify that blow_out was never called (key characteristic of reverse pipetting)
        self.lh.p300_multi.blow_out.assert_not_called()
        
        # Verify aspirate was called (should aspirate overhead liquid each time)
        self.assertGreater(self.lh.p300_multi.aspirate.call_count, 0)
        
        # Verify dispense was called for each destination
        self.assertEqual(self.lh.p300_multi.dispense.call_count, len(volumes))
        
        # Verify pipette behavior (in reverse pipetting, overhead liquid is aspirated initially)
        # The key is that blow_out is not called, so any remaining liquid stays in the tip
        self.assertGreaterEqual(
            self.lh.p300_multi.current_volume, 
            0,
            "Pipette should have some liquid or be empty, but never negative"
        )
        self.assertEqual(
            self.lh.p300_multi.current_volume, 
            self.lh.p300_multi.min_volume,
            "Pipette should have the overhead liquid remaining (min_volume)"
        )

    def test_multivolley_reverse_pipetting_with_air_gap_and_never_tip_change(self):
        """Test reverse pipetting with new_tip='never' - pipette should retain liquid until tip is manually dropped"""
        volumes = [50, 35, 70, 21, 55, 150, 55, 100]  # Multiple dispenses with the same tip (>300µL total)
        destination_wells = self.dest_wells[:8]
        self.total_aspiration = 0
        
        # Mock the pipette to track current_volume
        self.lh.p300_multi.current_volume = 0
        
        # Simulate reverse pipetting behavior - pipette retains overhead liquid
        def mock_aspirate(volume, location, **kwargs):
            self.lh.p300_multi.current_volume += volume
            self.total_aspiration += volume

        def mock_air_gap(volume, location=None, **kwargs):
            self.lh.p300_multi.current_volume += volume
            
        def mock_dispense(volume, location, **kwargs):
            # In reverse pipetting, we only dispense the requested volume, not all liquid
            # The pipette can dispense below min_volume, but overhead liquid should remain
            self.lh.p300_multi.current_volume = max(0, self.lh.p300_multi.current_volume - volume)
            
        def mock_drop_tip():
            # When tip is dropped, pipette volume should reset to 0
            self.lh.p300_multi.current_volume = 0
            
        def mock_blow_out(location):
            # When blowing out, pipette volume should reset to 0
            self.lh.p300_multi.current_volume = 0
            
        self.lh.p300_multi.aspirate.side_effect = mock_aspirate
        self.lh.p300_multi.dispense.side_effect = mock_dispense
        self.lh.p300_multi.air_gap.side_effect = mock_air_gap
        self.lh.p300_multi.drop_tip.side_effect = mock_drop_tip
        self.lh.p300_multi.blow_out.side_effect = mock_blow_out

        # Act - perform reverse pipetting
        failed_ops = self.lh.distribute(
            volumes=volumes,
            source_well=self.source_well,
            destination_wells=destination_wells,
            new_tip="never",
            overhead_liquid=True,
            add_air_gap=True,
            blow_out_to="",  # Empty string prevents blow-out
        )

        # Assert - verify reverse pipetting behavior
        self.assertEqual(len(failed_ops), 0, "No operations should fail")
        
        # Verify that blow_out was never called (key characteristic of reverse pipetting)
        self.lh.p300_multi.blow_out.assert_not_called()
        
        # Verify aspirate was called (should aspirate overhead liquid each time)
        self.assertGreater(self.lh.p300_multi.aspirate.call_count, 0)
        
        # Verify dispense was called for each destination
        self.assertEqual(self.lh.p300_multi.dispense.call_count, len(volumes))
        
        # Verify pipette behavior (in reverse pipetting, overhead liquid is aspirated initially)
        # The key is that blow_out is not called, so any remaining liquid stays in the tip
        self.assertGreaterEqual(
            self.lh.p300_multi.current_volume, 
            0,
            "Pipette should have some liquid or be empty, but never negative"
        )
        self.assertEqual(
            self.total_aspiration - sum(volumes),
            self.lh.p300_multi.min_volume,
            "Pipette should have the overhead liquid remaining (min_volume)"
        )

    def test_multivolley_reverse_pipetting_with_air_gap_no_resizing_gap(self):
        """Test reverse pipetting with new_tip='never' - pipette should retain liquid until tip is manually dropped"""
        volumes = [260, 280]  # Multiple dispenses with the same tip (>300µL total)
        destination_wells = self.dest_wells[:2]
        self.total_aspiration = 0
        
        # Mock the pipette to track current_volume
        self.lh.p300_multi.current_volume = 0
        
        # Simulate reverse pipetting behavior - pipette retains overhead liquid
        def mock_aspirate(volume, location, **kwargs):
            self.lh.p300_multi.current_volume += volume
            if self.lh.p300_multi.current_volume > self.lh.p300_multi.max_volume:
                raise RuntimeError("Pipette over-aspiration beyond max volume")
            self.total_aspiration += volume

        def mock_air_gap(volume, location=None, **kwargs):
            self.lh.p300_multi.current_volume += volume
            if self.lh.p300_multi.current_volume > self.lh.p300_multi.max_volume:
                raise RuntimeError("Pipette over-aspiration beyond max volume")

        def mock_dispense(volume, location, **kwargs):
            # In reverse pipetting, we only dispense the requested volume, not all liquid
            # The pipette can dispense below min_volume, but overhead liquid should remain
            self.lh.p300_multi.current_volume = max(0, self.lh.p300_multi.current_volume - volume)
            
        def mock_drop_tip():
            # When tip is dropped, pipette volume should reset to 0
            self.lh.p300_multi.current_volume = 0
            
        def mock_blow_out(location):
            # When blowing out, pipette volume should reset to 0
            self.lh.p300_multi.current_volume = 0
            
        self.lh.p300_multi.aspirate.side_effect = mock_aspirate
        self.lh.p300_multi.dispense.side_effect = mock_dispense
        self.lh.p300_multi.air_gap.side_effect = mock_air_gap
        self.lh.p300_multi.drop_tip.side_effect = mock_drop_tip
        self.lh.p300_multi.blow_out.side_effect = mock_blow_out

        # Act - perform reverse pipetting
        failed_ops = self.lh.distribute(
            volumes=volumes,
            source_well=self.source_well,
            destination_wells=destination_wells,
            new_tip="never",
            overhead_liquid=True,
            add_air_gap=True,
            blow_out_to="",  # Empty string prevents blow-out
        )

        # Assert - verify reverse pipetting behavior
        self.assertEqual(len(failed_ops), 0, "No operations should fail")
        
        # Verify that blow_out was never called (key characteristic of reverse pipetting)
        self.lh.p300_multi.blow_out.assert_not_called()
        
        # Verify aspirate was called (should aspirate overhead liquid each time)
        self.assertGreater(self.lh.p300_multi.aspirate.call_count, 0)
        
        # Verify dispense was called for each destination
        self.assertEqual(self.lh.p300_multi.dispense.call_count, len(volumes) + 1)
        
        # Verify pipette behavior (in reverse pipetting, overhead liquid is aspirated initially)
        # The key is that blow_out is not called, so any remaining liquid stays in the tip
        self.assertGreaterEqual(
            self.lh.p300_multi.current_volume, 
            0,
            "Pipette should have some liquid or be empty, but never negative"
        )
        self.assertEqual(
            self.total_aspiration - sum(volumes),
            self.lh.p300_multi.min_volume,
            "Pipette should have the overhead liquid remaining (min_volume)"
        )
        for command in self.lh.protocol_api.commands():
            print(command)

    def test_reverse_pipetting_with_once_tip_change(self):
        """Test reverse pipetting with new_tip='once' - single tip used for all operations"""
        volumes = [15, 12, 8, 5, 3]  # All volumes ≤ 20µL will use P20 single channel
        destination_wells = self.dest_wells[:5]
        
        # Mock the P20 pipette to track current_volume and tip usage (not P300)
        self.lh.p20.current_volume = 0
        self.lh.p20.has_tip = False
        
        def mock_pick_up_tip():
            self.lh.p20.has_tip = True
            
        def mock_aspirate(volume, location, **kwargs):
            self.lh.p20.current_volume += volume
            
        def mock_dispense(volume, location, **kwargs):
            # In reverse pipetting, retain overhead liquid
            # Dispense can go below min_volume, but we simulate retaining some overhead
            self.lh.p20.current_volume = max(0, self.lh.p20.current_volume - volume)
            
        self.lh.p20.pick_up_tip.side_effect = mock_pick_up_tip
        self.lh.p20.aspirate.side_effect = mock_aspirate
        self.lh.p20.dispense.side_effect = mock_dispense

        # Act - perform reverse pipetting
        failed_ops = self.lh.distribute(
            volumes=volumes,
            source_well=self.source_well,
            destination_wells=destination_wells,
            new_tip="once",
            overhead_liquid=True,
            blow_out_to="",  # Empty string prevents blow-out
        )

        # Assert
        self.assertEqual(len(failed_ops), 0, "No operations should fail")
        
        # Verify single tip pickup (characteristic of new_tip='once') for P20
        self.assertEqual(self.lh.p20.pick_up_tip.call_count, 1)
        
        # Verify no blow-out occurs (key characteristic of reverse pipetting)
        self.lh.p20.blow_out.assert_not_called()
        
        # Verify P20 was used (not P300) for these small volumes
        self.lh.p300_multi.dispense.assert_not_called()
        self.assertEqual(self.lh.p20.dispense.call_count, len(volumes))
        
        # Verify pipette behavior in reverse pipetting
        self.assertGreaterEqual(
            self.lh.p20.current_volume, 
            0,
            "Pipette volume should never be negative"
        )

    def test_reverse_pipetting_multi_dispense_operations(self):
        """Test reverse pipetting with multi-dispense from single source to multiple destinations"""
        volume = 40  # Same volume to all destinations to enable multi-dispense
        destination_wells = self.dest_wells[:8]  # Full column for multi-channel
        
        # Mock the pipette behavior
        self.lh.p300_multi.current_volume = 0
        
        def mock_aspirate(volume, location, **kwargs):
            self.lh.p300_multi.current_volume += volume
            
        def mock_dispense(volume, location, **kwargs):
            # Multi-dispense: dispense to multiple locations, can go below min_volume
            self.lh.p300_multi.current_volume = max(0, self.lh.p300_multi.current_volume - volume)
            
        self.lh.p300_multi.aspirate.side_effect = mock_aspirate
        self.lh.p300_multi.dispense.side_effect = mock_dispense

        # Act
        failed_ops = self.lh.distribute(
            volumes=volume,  # Same volume for all wells
            source_well=self.source_well,
            destination_wells=destination_wells,
            new_tip="once",
            overhead_liquid=True,
            blow_out_to="",  # No blow-out for reverse pipetting
        )

        # Assert
        self.assertEqual(len(failed_ops), 0)
        
        # Verify no blow-out in reverse pipetting
        self.lh.p300_multi.blow_out.assert_not_called()
        
        # Verify multi-channel operation occurred
        self.assertGreater(self.lh.p300_multi.aspirate.call_count, 0)
        self.assertGreater(self.lh.p300_multi.dispense.call_count, 0)
        
        # Verify overhead liquid behavior (key aspect of reverse pipetting)
        self.assertGreaterEqual(self.lh.p300_multi.current_volume, 0)

    def test_reverse_pipetting_with_p20_single_channel(self):
        """Test reverse pipetting behavior with P20 single channel pipette"""
        volumes = [5, 8, 12, 15, 18]  # Volumes suitable for p20
        destination_wells = self.dest_wells[:5]
        
        # Mock p20 behavior
        self.lh.p20.current_volume = 0
        
        def mock_aspirate(volume, location, **kwargs):
            self.lh.p20.current_volume += volume
            
        def mock_dispense(volume, location, **kwargs):
            # Retain overhead liquid in reverse pipetting, but dispense can go below min_volume
            self.lh.p20.current_volume = max(0, self.lh.p20.current_volume - volume)
            
        self.lh.p20.aspirate.side_effect = mock_aspirate
        self.lh.p20.dispense.side_effect = mock_dispense

        # Act
        failed_ops = self.lh.distribute(
            volumes=volumes,
            source_well=self.source_well,
            destination_wells=destination_wells,
            new_tip="never",
            overhead_liquid=True,
            blow_out_to="",  # No blow-out for reverse pipetting
        )

        # Assert
        self.assertEqual(len(failed_ops), 0)
        
        # Verify p20 was used (not p300_multi)
        self.lh.p300_multi.dispense.assert_not_called()
        self.assertGreater(self.lh.p20.dispense.call_count, 0)
        
        # Verify no blow-out in reverse pipetting
        self.lh.p20.blow_out.assert_not_called()
        
        # Verify overhead liquid retention concept
        self.assertGreaterEqual(self.lh.p20.current_volume, 0)

    def test_reverse_pipetting_vs_normal_pipetting_comparison(self):
        """Compare reverse pipetting (no blow-out) vs normal pipetting (with blow-out)"""
        volume = 60
        destination_wells = self.dest_wells[:3]
        
        # Test normal pipetting first
        self.lh.p300_multi.reset_mock()
        failed_ops_normal = self.lh.distribute(
            volumes=volume,
            source_well=self.source_well,
            destination_wells=destination_wells,
            new_tip="once",
            overhead_liquid=True,
            blow_out_to="trash",  # Normal pipetting with blow-out
        )
        
        normal_blow_out_calls = self.lh.p300_multi.blow_out.call_count
        
        # Reset and test reverse pipetting
        self.lh.p300_multi.reset_mock()
        failed_ops_reverse = self.lh.distribute(
            volumes=volume,
            source_well=self.source_well,
            destination_wells=destination_wells,
            new_tip="once",
            overhead_liquid=True,
            blow_out_to="",  # Reverse pipetting without blow-out
        )
        
        reverse_blow_out_calls = self.lh.p300_multi.blow_out.call_count
        
        # Assert the key difference
        self.assertGreater(normal_blow_out_calls, 0, "Normal pipetting should have blow-out calls")
        self.assertEqual(reverse_blow_out_calls, 0, "Reverse pipetting should have no blow-out calls")
        
        # Both should succeed
        self.assertEqual(len(failed_ops_normal), 0)
        self.assertEqual(len(failed_ops_reverse), 0)

    def test_reverse_pipetting_error_handling(self):
        """Test that reverse pipetting properly handles edge cases and errors"""
        # Test with invalid blow_out_to parameter but should work with empty string
        volumes = [25, 30]
        destination_wells = self.dest_wells[:2]
        
        # This should work - empty string is valid for reverse pipetting
        failed_ops = self.lh.distribute(
            volumes=volumes,
            source_well=self.source_well,
            destination_wells=destination_wells,
            new_tip="never",
            overhead_liquid=True,
            blow_out_to="",  # Empty string for reverse pipetting
        )
        
        self.assertEqual(len(failed_ops), 0)
        self.lh.p300_multi.blow_out.assert_not_called()

    def test_reverse_pipetting_overhead_liquid_aspiration_verification(self):
        """Test that reverse pipetting actually aspirates more liquid than dispensed (overhead liquid)"""
        volume = 50  # Request 50µL
        destination_wells = self.dest_wells[:1]
        
        # Track all aspirate and dispense calls with actual volumes
        aspirated_volumes = []
        dispensed_volumes = []
        
        def mock_aspirate(volume, location, **kwargs):
            aspirated_volumes.append(volume)
            self.lh.p300_multi.current_volume += volume
            
        def mock_dispense(volume, location, **kwargs):
            dispensed_volumes.append(volume)
            self.lh.p300_multi.current_volume = max(0, self.lh.p300_multi.current_volume - volume)
            
        self.lh.p300_multi.current_volume = 0
        self.lh.p300_multi.aspirate.side_effect = mock_aspirate
        self.lh.p300_multi.dispense.side_effect = mock_dispense

        # Act - perform reverse pipetting
        failed_ops = self.lh.distribute(
            volumes=volume,
            source_well=self.source_well,
            destination_wells=destination_wells,
            new_tip="once",
            overhead_liquid=True,
            blow_out_to="",  # No blow-out for reverse pipetting
        )

        # Assert
        self.assertEqual(len(failed_ops), 0, "Operation should succeed")
        
        # Verify overhead liquid: total aspirated > total dispensed
        total_aspirated = sum(aspirated_volumes)
        total_dispensed = sum(dispensed_volumes)
        
        self.assertGreater(
            total_aspirated, 
            total_dispensed,
            f"Total aspirated ({total_aspirated}µL) should be greater than total dispensed ({total_dispensed}µL) due to overhead liquid"
        )
        
        # Verify the requested volume was dispensed
        self.assertEqual(
            total_dispensed, 
            volume,
            f"Total dispensed should equal requested volume ({volume}µL)"
        )
        
        # Verify overhead liquid amount is reasonable (typically 10-20% overhead)
        overhead_percentage = ((total_aspirated - total_dispensed) / total_dispensed) * 100
        self.assertGreaterEqual(
            overhead_percentage, 
            5,  # At least 5% overhead
            f"Overhead liquid should be at least 5% of dispensed volume, got {overhead_percentage:.1f}%"
        )
        
        # Verify no blow-out occurred
        self.lh.p300_multi.blow_out.assert_not_called()

    def test_reverse_pipetting_tip_capacity_edge_case(self):
        """Test reverse pipetting when volume equals tip capacity - should split into volleys with overhead"""
        volume = 300  # Exactly at P300 capacity
        destination_wells = self.dest_wells[:1]
        
        # Track aspirate and dispense operations
        aspirated_volumes = []
        dispensed_volumes = []
        
        def mock_aspirate(volume, location, **kwargs):
            aspirated_volumes.append(volume)
            self.lh.p300_multi.current_volume += volume
            
        def mock_dispense(volume, location, **kwargs):
            dispensed_volumes.append(volume)
            self.lh.p300_multi.current_volume = max(0, self.lh.p300_multi.current_volume - volume)
            
        self.lh.p300_multi.current_volume = 0
        self.lh.p300_multi.aspirate.side_effect = mock_aspirate
        self.lh.p300_multi.dispense.side_effect = mock_dispense

        # Act
        failed_ops = self.lh.distribute(
            volumes=volume,
            source_well=self.source_well,
            destination_wells=destination_wells,
            new_tip="once",
            overhead_liquid=True,
            blow_out_to="",
        )

        # Assert
        self.assertEqual(len(failed_ops), 0, "Operation should succeed")
        
        # When volume equals capacity, it should split into multiple volleys
        # Each volley should have overhead liquid
        total_aspirated = sum(aspirated_volumes)
        total_dispensed = sum(dispensed_volumes)
        
        self.assertGreater(
            total_aspirated, 
            total_dispensed,
            f"Even at tip capacity, total aspirated ({total_aspirated}µL) should be greater than dispensed ({total_dispensed}µL)"
        )
        
        # Verify the full requested volume was dispensed
        self.assertEqual(
            total_dispensed, 
            volume,
            f"Total dispensed should equal requested volume ({volume}µL)"
        )
        
        # Should have multiple aspirate calls (volleys) due to overhead liquid requirement
        self.assertGreaterEqual(
            len(aspirated_volumes), 
            2,
            "Should split into multiple volleys when volume equals capacity and overhead liquid is required"
        )
        
        # Each individual aspirate should not exceed tip capacity
        for aspirated_vol in aspirated_volumes:
            self.assertLessEqual(
                aspirated_vol, 
                self.lh.p300_multi.max_volume,
                f"Individual aspirate volume ({aspirated_vol}µL) should not exceed tip capacity"
            )
        
        # Verify no blow-out
        self.lh.p300_multi.blow_out.assert_not_called()

    def test_reverse_pipetting_large_volume_multi_volley_with_overhead(self):
        """Test reverse pipetting for volumes > tip capacity maintains overhead liquid in each volley"""
        volume = 450  # Requires multiple volleys even without overhead
        destination_wells = self.dest_wells[:1]
        
        aspirated_volumes = []
        dispensed_volumes = []
        
        def mock_aspirate(volume, location, **kwargs):
            aspirated_volumes.append(volume)
            self.lh.p300_multi.current_volume += volume
            
        def mock_dispense(volume, location, **kwargs):
            dispensed_volumes.append(volume)
            self.lh.p300_multi.current_volume = max(0, self.lh.p300_multi.current_volume - volume)
            
        self.lh.p300_multi.current_volume = 0
        self.lh.p300_multi.aspirate.side_effect = mock_aspirate
        self.lh.p300_multi.dispense.side_effect = mock_dispense

        # Act
        failed_ops = self.lh.distribute(
            volumes=volume,
            source_well=self.source_well,
            destination_wells=destination_wells,
            new_tip="once",
            overhead_liquid=True,
            blow_out_to="",
        )

        # Assert
        self.assertEqual(len(failed_ops), 0, "Operation should succeed")
        
        # Verify overhead liquid maintained across multiple volleys
        total_aspirated = sum(aspirated_volumes)
        total_dispensed = sum(dispensed_volumes)
        
        self.assertGreater(
            total_aspirated, 
            total_dispensed,
            f"Multi-volley operation: total aspirated ({total_aspirated}µL) should be greater than dispensed ({total_dispensed}µL)"
        )
        
        # Verify correct total volume dispensed
        self.assertEqual(total_dispensed, volume, "Total dispensed should match requested volume")
        
        # Should have multiple volleys
        self.assertGreaterEqual(len(aspirated_volumes), 2, "Should require multiple volleys")
        
        # Each aspirate should be within capacity limits
        for aspirated_vol in aspirated_volumes:
            self.assertLessEqual(aspirated_vol, self.lh.p300_multi.max_volume)
        
        # Verify no blow-out
        self.lh.p300_multi.blow_out.assert_not_called()

    def test_reverse_pipetting_p20_overhead_liquid_verification(self):
        """Test overhead liquid aspiration for P20 pipette operations"""
        volumes = [8, 12, 15]  # Small volumes for P20
        destination_wells = self.dest_wells[:3]
        
        aspirated_volumes = []
        dispensed_volumes = []
        
        def mock_aspirate(volume, location, **kwargs):
            aspirated_volumes.append(volume)
            self.lh.p20.current_volume += volume
            
        def mock_dispense(volume, location, **kwargs):
            dispensed_volumes.append(volume)
            self.lh.p20.current_volume = max(0, self.lh.p20.current_volume - volume)
            
        self.lh.p20.current_volume = 0
        self.lh.p20.aspirate.side_effect = mock_aspirate
        self.lh.p20.dispense.side_effect = mock_dispense

        # Act
        failed_ops = self.lh.distribute(
            volumes=volumes,
            source_well=self.source_well,
            destination_wells=destination_wells,
            new_tip="once",
            overhead_liquid=True,
            blow_out_to="",
        )

        # Assert
        self.assertEqual(len(failed_ops), 0, "All operations should succeed")
        
        # Verify overhead liquid for P20 operations
        total_aspirated = sum(aspirated_volumes)
        total_dispensed = sum(dispensed_volumes)
        
        self.assertGreater(
            total_aspirated,
            total_dispensed,
            f"P20 operations: total aspirated ({total_aspirated}µL) should be greater than dispensed ({total_dispensed}µL)"
        )
        
        # Verify correct volumes dispensed
        self.assertEqual(total_dispensed, sum(volumes), "Should dispense exactly the requested volumes")
        
        # Verify P20 was used (not P300)
        self.lh.p300_multi.aspirate.assert_not_called()
        self.assertGreater(len(aspirated_volumes), 0, "P20 should have aspirated")
        
        # Verify no blow-out
        self.lh.p20.blow_out.assert_not_called()


class TestLiquidHandlerAllocate(unittest.TestCase):
    def setUp(self):
        # Initialize LiquidHandler with simulation mode
        self.lh = LiquidHandler(simulation=True, load_default=False)
        self.lh.p300_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_300ul", "7")
        )
        self.lh.single_p300_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_300ul", "6")
        )
        self.lh.single_p20_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_20ul", "11")
        )

        # Mock pipettes
        self.lh.p300_multi = MagicMock()
        self.lh.p20 = MagicMock()
        self.lh.p20.min_volume = 1
        self.lh.p20.max_volume = 20
        self.lh.p300_multi.min_volume = 20
        self.lh.p300_multi.max_volume = 300

        # Mock labware
        self.mock_labware = self.lh.load_labware(
            "nest_96_wellplate_100ul_pcr_full_skirt", 9, "mock labware"
        )
        self.mock_reservoir = self.lh.load_labware(
            "nest_12_reservoir_15ml", 2, "mock reservoir source"
        )
        self.dest_wells = self.mock_labware.wells()

        # Create mock wells
        self.source_well = self.mock_reservoir.wells("A1")[0]

    def test_allocate_single_channel_volume_split(self):
        test_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 8, "test")
        random.seed(42)
        indexes = [1, 8, 16, 20, 5, 88, 12, 2]
        well_count = len(indexes)
        p20_volumes = [random.randint(2, 20) for _ in range(well_count)]
        p300_volumes = [random.randint(20, 200) for _ in range(well_count)]

        with self.subTest("Allocate p20 volumes"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=[self.mock_labware.wells()[i] for i in indexes],
                destination_wells=[test_labware.wells()[i] for i in sorted(indexes)],
                volumes=p20_volumes,
            )
            self.assertEqual(len(p300_multi), 0, "p300_multi should be empty")
            self.assertEqual(len(p300), 0, "p300 should be empty")
            self.assertEqual(len(p20), well_count, f"p20 should have {well_count} elements")

        with self.subTest("Allocate p300 volumes"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=[self.mock_labware.wells()[i] for i in indexes],
                destination_wells=[test_labware.wells()[i] for i in sorted(indexes)],
                volumes=p300_volumes,
            )
            self.assertEqual(len(p300_multi), 0, "p300_multi should be empty")
            self.assertEqual(len(p300), well_count, f"p300 should have {well_count} elements")
            self.assertEqual(len(p20), 0, "p20 should be empty")

    def test_allocate_multiple_source_and_destination_labware(self):
        test_labware_1 = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 8, "test1")
        test_labware_2 = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 10, "test2")

        # Create source wells from multiple labware
        source_wells = [test_labware_1.wells("A1"), test_labware_2.wells("A1")]
        destination_wells = [test_labware_1.wells("B1"), test_labware_2.wells("B1")]
        volumes = [10, 15]

        with self.subTest("Multiple labware in both source and destination"):
            with self.assertRaises(
                ValueError,
                msg="Should raise ValueError for multiple labware in source or destination",
            ):
                self.lh._allocate_liquid_handling_steps(
                    source_wells=source_wells, destination_wells=destination_wells, volumes=volumes
                )

        with self.subTest("Multiple labware in source only"):
            source_wells = [test_labware_1.wells("A1"), test_labware_2.wells("A1")]
            destination_wells = [test_labware_1.wells("B1"), test_labware_1.wells("C1")]
            with self.assertRaises(
                ValueError, msg="Should raise ValueError for multiple labware in source"
            ):
                self.lh._allocate_liquid_handling_steps(
                    source_wells=source_wells, destination_wells=destination_wells, volumes=volumes
                )

        with self.subTest("Multiple labware in destination only"):
            source_wells = [test_labware_1.wells("A1"), test_labware_1.wells("A2")]
            destination_wells = [test_labware_1.wells("B1"), test_labware_2.wells("B1")]
            with self.assertRaises(
                ValueError, msg="Should raise ValueError for multiple labware in destination"
            ):
                self.lh._allocate_liquid_handling_steps(
                    source_wells=source_wells, destination_wells=destination_wells, volumes=volumes
                )

    def test_allocate_column_wise_operations_reservoir_with_equal_volumes(self):
        # Load labware
        test_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 8, "test")

        # Define source and destination wells
        destination_wells = test_labware.wells()
        source_wells = [self.mock_reservoir.wells("A1")[0]] * len(destination_wells)

        # Define equal volumes for each well in a column
        equal_volumes = [50] * len(destination_wells)

        with self.subTest("Column-wise operations with equal volumes - source to destination"):
            # Perform the allocation
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=source_wells,
                destination_wells=destination_wells,
                volumes=equal_volumes,
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(
                len(p300_multi),
                len(test_labware.columns()),
                "p300_multi should handle column-wise operations",
            )
            self.assertEqual(len(p300), 0, "p300 should be empty")
            self.assertEqual(len(p20), 0, "p20 should be empty")

        with self.subTest("Column-wise operations with equal volumes - source to destination"):
            # Perform the allocation
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=source_wells + source_wells,
                destination_wells=destination_wells + destination_wells,
                volumes=equal_volumes + equal_volumes,
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(
                len(p300_multi),
                2 * len(test_labware.columns()),
                "p300_multi should handle column-wise operations",
            )
            self.assertEqual(len(p300), 0, "p300 should be empty")
            self.assertEqual(len(p20), 0, "p20 should be empty")

        with self.subTest("Column-wise operations with equal volumes - destination to source"):
            # Perform the allocation
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=destination_wells,
                destination_wells=source_wells,
                volumes=equal_volumes,
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(
                len(p300_multi),
                len(test_labware.columns()),
                "p300_multi should handle column-wise operations",
            )
            self.assertEqual(len(p300), 0, "p300 should be empty")
            self.assertEqual(len(p20), 0, "p20 should be empty")

        # Let's add noise to see if the operations remain as planned
        random.seed(21)
        indexes = [1, 8, 5, 2, 3, 11, 10, 4]
        well_count = len(indexes)
        p20_volumes = [random.randint(2, 20) for _ in range(well_count)]
        p300_volumes = [random.randint(21, 200) for _ in range(well_count)]

        with self.subTest("Add noise with p20 compatible volumes"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=[self.mock_reservoir.wells()[i] for i in indexes] + source_wells,
                destination_wells=[test_labware.wells()[i] for i in sorted(indexes)]
                + destination_wells,
                volumes=p20_volumes + equal_volumes,
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(
                len(p300_multi),
                len(test_labware.columns()),
                "p300_multi should handle column-wise operations",
            )
            self.assertEqual(len(p300), 0, "p300 should be empty")
            self.assertEqual(len(p20), well_count, "p20 should not be empty")

        with self.subTest("Add noise with p300 compatible volumes"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=[self.mock_reservoir.wells()[i] for i in indexes] + source_wells,
                destination_wells=[test_labware.wells()[i] for i in sorted(indexes)]
                + destination_wells,
                volumes=p300_volumes + equal_volumes,
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(
                len(p300_multi),
                len(test_labware.columns()),
                "p300_multi should handle column-wise operations",
            )
            self.assertEqual(len(p20), 0, "p20 should be empty")
            self.assertEqual(len(p300), well_count, "p300 should not be empty")

    def test_allocate_column_wise_operations_between_plates(self):
        test_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 8, "test")
        test_labware2 = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 4, "test2")

        volumes = [50] * 8
        source_column = test_labware2.columns()[1]
        dest_column = test_labware.columns()[2]

        extra_volumes = [random.randint(21, 200) for _ in range(96)]

        with self.subTest("Add noise with p20 compatible volumes"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=source_column, destination_wells=dest_column, volumes=volumes
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(len(p300_multi), 1, "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 0, "p300 should be empty")
            self.assertEqual(len(p20), 0, "p20 should be empty")

        with self.subTest("Add noise with p20 compatible volumes"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=dest_column, destination_wells=source_column, volumes=volumes
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(len(p300_multi), 1, "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 0, "p300 should be empty")
            self.assertEqual(len(p20), 0, "p20 should be empty")

        with self.subTest("Add noise with p20 compatible volumes"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=source_column + test_labware2.wells(),
                destination_wells=dest_column + test_labware.wells(),
                volumes=volumes + extra_volumes,
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(len(p300_multi), 1, "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 96, "p300 should not be empty")
            self.assertEqual(len(p20), 0, "p20 should be empty")

        with self.subTest("Add noise with p20 compatible volumes"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=source_column + source_column + test_labware2.wells(),
                destination_wells=dest_column + dest_column + test_labware.wells(),
                volumes=volumes + volumes + extra_volumes,
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(len(p300_multi), 2, "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 96, "p300 should not be empty")
            self.assertEqual(len(p20), 0, "p20 should be empty")

    def test_allocate_with_p300_bottom_row_access(self):
        test_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 3, "test")

        volumes = [random.randint(21, 200) for _ in range(8)]
        source_column = test_labware.columns()[1]
        dest_column = test_labware.columns()[2]

        with self.subTest("Test the bottom row access"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=source_column, destination_wells=dest_column, volumes=volumes
            )

            # P300 single mode should access all but bottom two rows
            self.assertEqual(len(p300_multi), 0, "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 6, "p300 should not be empty")
            self.assertEqual(len(p20), 2, "p20 should not be empty")

        with self.subTest("Test the bottom row access"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=source_column + source_column,
                destination_wells=dest_column + dest_column,
                volumes=volumes + volumes,
            )

            # P300 single mode should access all but bottom two rows
            self.assertEqual(len(p300_multi), 0, "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 12, "p300 should not be empty")
            self.assertEqual(len(p20), 4, "p20 should not be empty")

        with self.subTest("Test the bottom row access"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=dest_column, destination_wells=source_column, volumes=volumes
            )

            # P300 single mode should access all but bottom two rows
            self.assertEqual(len(p300_multi), 0, "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 6, "p300 should not be empty")
            self.assertEqual(len(p20), 2, "p20 should not be empty")


class TestLiquidHandlerPool(unittest.TestCase):
    def setUp(self):
        # Initialize LiquidHandler with simulation mode
        self.lh = LiquidHandler(simulation=True, load_default=False)
        self.lh.p300_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_300ul", "7")
        )
        self.lh.single_p300_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_300ul", "6")
        )
        self.lh.single_p20_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_20ul", "11")
        )

        # Mock pipettes
        self.lh.p300_multi = MagicMock()
        self.lh.p20 = MagicMock()
        self.lh.p20.min_volume = 1
        self.lh.p20.max_volume = 20
        self.lh.p300_multi.min_volume = 20
        self.lh.p300_multi.max_volume = 300

        # Mock labware
        self.mock_labware = self.lh.load_labware(
            "nest_96_wellplate_100ul_pcr_full_skirt", 9, "mock labware"
        )
        self.mock_reservoir = self.lh.load_labware(
            "nest_12_reservoir_15ml", 2, "mock reservoir source"
        )
        self.dest_wells = self.mock_labware.wells()

        # Create mock wells
        self.source_well = self.mock_reservoir.wells("A1")[0]

    def test_pool_single_volume(self):
        # Arrange
        volume = 10

        # Act
        self.lh.pool(
            volumes=volume,
            source_wells=self.mock_labware.wells(),  # 96x
            destination_well=self.mock_reservoir.wells()[0],
            add_air_gap=False,
            new_tip="once",
        )

        # Assert
        self.assertEqual(self.lh.p20.dispense.call_count, 48) # re-using tips, 10 uL fits 2x in 20 uL tip
        self.assertEqual(self.lh.p20.aspirate.call_count, 96)
        self.lh.p300_multi.aspirate.assert_not_called()
        self.lh.p300_multi.dispense.assert_not_called()

    def test_pool_single_volume_with_tip_change(self):
        # Arrange
        volume = 10

        # Act
        self.lh.pool(
            volumes=volume,
            source_wells=self.mock_labware.wells(),  # 96x
            destination_well=self.mock_reservoir.wells()[0],
            add_air_gap=False,
            new_tip="always",
        )

        # Assert
        self.assertEqual(self.lh.p20.dispense.call_count, 96)
        self.assertEqual(self.lh.p20.aspirate.call_count, 96)
        self.lh.p300_multi.aspirate.assert_not_called()
        self.lh.p300_multi.dispense.assert_not_called()

    def test_pool_air_gap(self):
        # Arrange
        volume = 10

        # Act
        self.lh.pool(
            volumes=volume,
            source_wells=self.mock_labware.wells(),  # 96x
            destination_well=self.mock_reservoir.wells()[0],
            add_air_gap=True,
            new_tip="always",
        )

        # Assert
        self.assertEqual(self.lh.p20.dispense.call_count, 96)
        self.assertEqual(self.lh.p20.aspirate.call_count, 96)
        self.assertEqual(self.lh.p20.air_gap.call_count, 96)
        self.lh.p300_multi.aspirate.assert_not_called()
        self.lh.p300_multi.dispense.assert_not_called()

    def test_pool_multiple_volumes(self):
        # Arrange
        volumes = [5, 10, 15, 19, 25, 30, 35, 40]

        # Act & Assert
        with self.subTest("Without air gap"):
            self.lh.pool(
                volumes=volumes,
                source_wells=self.mock_labware.wells()[:8],
                destination_well=self.mock_reservoir.wells()[0],
                new_tip="always",
                add_air_gap=False,
            )

            self.assertEqual(self.lh.p20.dispense.call_count, 4)
            self.assertEqual(self.lh.p20.aspirate.call_count, 4)
            self.assertEqual(self.lh.p300_multi.dispense.call_count, 4)
            self.assertEqual(self.lh.p300_multi.aspirate.call_count, 4)
            self.lh.p300_multi.reset_mock()
            self.lh.p20.reset_mock()

        with self.subTest("With air gap"):
            self.lh.pool(
                volumes=volumes,
                source_wells=self.mock_labware.wells()[:8],
                destination_well=self.mock_reservoir.wells()[0],
                new_tip="always",
                add_air_gap=True,
            )
            self.assertEqual(self.lh.p20.dispense.call_count, 4)
            self.assertEqual(self.lh.p20.aspirate.call_count, 4)
            self.assertEqual(self.lh.p20.air_gap.call_count, 4)
            self.assertEqual(self.lh.p300_multi.dispense.call_count, 4)
            self.assertEqual(self.lh.p300_multi.aspirate.call_count, 4)
            self.assertEqual(self.lh.p300_multi.air_gap.call_count, 4)
            self.lh.p300_multi.reset_mock()
            self.lh.p20.reset_mock()

    def test_pool_invalid_new_tip(self):
        # Arrange
        volume = 10
        new_tip = "invalid_option"

        # Act & Assert
        with self.assertRaises(ValueError) as context:
            self.lh.pool(
                volumes=volume,
                source_wells=self.mock_labware.wells(),
                destination_well=self.mock_reservoir.wells()[0],
                new_tip=new_tip,
            )
        self.assertIn("invalid value for the optional argument 'new_tip'", str(context.exception))

    def test_pool_volume_below_minimum(self):
        # Arrange
        volume = 0.1  # Below p20.min_volume

        # Act & Assert
        with self.assertLogs(level="WARNING") as log:
            self.lh.pool(
                volumes=volume,
                source_wells=self.mock_labware.wells(),
                destination_well=self.mock_reservoir.wells()[0],
                new_tip="never",
            )
        self.assertIn("Volume too low, requested operation ignored", log.output[0])
        self.lh.p20.dispense.assert_not_called()

    def test_pool_with_large_volume(self):
        # Arrange
        volume = 80  # Exceeds p20.max_volume, should use p300_multi

        # Act
        self.lh.pool(
            volumes=volume,
            source_wells=self.mock_labware.wells(),
            destination_well=self.mock_reservoir.wells()[0],
            new_tip="once",
        )

        # Assert
        self.lh.p300_multi.aspirate.assert_called()
        self.lh.p300_multi.dispense.assert_called()
        self.lh.p20.aspirate.assert_not_called()
        self.lh.p20.dispense.assert_not_called()

    def test_pool_with_small_volume(self):
        # Arrange
        volume = 10

        # Act
        self.lh.pool(
            volumes=volume,
            source_wells=self.mock_labware.wells(),
            destination_well=self.mock_reservoir.wells()[0],
            new_tip="always",
        )

        # Assert
        self.lh.p300_multi.aspirate.assert_not_called()
        self.lh.p300_multi.dispense.assert_not_called()
        self.lh.p20.aspirate.assert_called()
        self.lh.p20.dispense.assert_called()

    def test_pool_to_trash(self):
        # Arrange
        volume = 30

        # Act
        self.lh.pool(
            volumes=volume,
            source_wells=self.mock_labware.wells(),
            destination_well=self.lh.trash,
            new_tip="once",
        )

        # Assert
        self.lh.p300_multi.aspirate.assert_called()
        self.lh.p300_multi.dispense.assert_called()
        self.lh.p20.aspirate.assert_not_called()
        self.lh.p20.dispense.assert_not_called()

    def test_pool_with_invalid_destination_well(self):
        # Arrange
        volume = 10
        invalid_destination = [
            self.mock_reservoir.wells()[0],
            self.mock_reservoir.wells()[1],
        ]  # Invalid as it should be a single well

        # Act & Assert
        with self.assertRaises(TypeError) as _:
            self.lh.pool(
                volumes=volume,
                source_wells=self.mock_labware.wells(),
                destination_well=invalid_destination,
                new_tip="once",
            )


class TestLiquidHandlerStamp(unittest.TestCase):
    def setUp(self):
        # Initialize LiquidHandler with simulation mode
        self.lh = LiquidHandler(simulation=True, load_default=False)
        self.lh.p300_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_300ul", "7")
        )
        self.lh.single_p300_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_300ul", "6")
        )
        self.lh.single_p20_tips.append(
            self.lh.protocol_api.load_labware("opentrons_96_tiprack_20ul", "11")
        )

        # Mock pipettes
        self.lh.p300_multi = MagicMock()
        self.lh.p20 = MagicMock()
        self.lh.p20.min_volume = 1
        self.lh.p20.max_volume = 20
        self.lh.p300_multi.min_volume = 20
        self.lh.p300_multi.max_volume = 300

        # Mock labware
        self.mock_labware = self.lh.load_labware(
            "nest_96_wellplate_100ul_pcr_full_skirt", 9, "mock labware"
        )
        self.mock_reservoir = self.lh.load_labware(
            "nest_12_reservoir_15ml", 2, "mock reservoir source"
        )
        self.dest_wells = self.mock_labware.wells()

        # Create mock wells
        self.source_well = self.mock_reservoir.wells("A1")[0]

    def test_stamp_plate_with_multichannel_pipette(self):
        test_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 3, "test")
        expected_volume = 25
        self.lh.stamp(expected_volume, self.mock_labware, test_labware)

        # Assert
        self.assertEqual(self.lh.p300_multi.dispense.call_count, 12)

        self.lh.p20.aspirate.assert_not_called()
        self.lh.p20.dispense.assert_not_called()


class TestLoadDefaultLabware(unittest.TestCase):
    def setUp(self):
        self.lh = LiquidHandler(simulation=True, load_default=False)

    @patch("builtins.open", create=True)
    @patch("json.load")
    def test_load_default_labware_success(self, mock_json_load, mock_open_func):
        # Mock JSON data to simulate the file content
        mock_json_data = {
            "labware": {},
            "multichannel_tips": {"7": "opentrons_96_tiprack_300ul"},
            "single_channel_tips": {
                "6": "opentrons_96_tiprack_300ul",
                "11": "opentrons_96_tiprack_20ul",
            },
            "modules": {
                "4": "temperature module gen2",
                "10": "heaterShakerModuleV1",
                "9": "magnetic module gen2",
            },
        }

        # Serialize the mock data as JSON to simulate the file content
        mock_file_content = json.dumps(mock_json_data)

        mock_open_func.return_value = mock_open(read_data=json.dumps(mock_json_data)).return_value
        mock_json_load.return_value = mock_json_data

        # Patch both open and json.load

        with (
            patch("builtins.open", mock_open(read_data=mock_file_content)) as _,
            patch("json.load", return_value=mock_json_data) as _,
        ):
            self.lh.load_labware = unittest.mock.Mock()
            self.lh.load_tips = unittest.mock.Mock()
            self.lh.load_module = unittest.mock.Mock()

            self.lh.load_default_labware()

            self.lh.load_labware.assert_not_called()

            self.assertEqual(self.lh.load_tips.call_count, 3)
            self.lh.load_tips.assert_any_call(
                "opentrons_96_tiprack_300ul", "6", single_channel=True
            )
            self.lh.load_tips.assert_any_call(
                "opentrons_96_tiprack_20ul", "11", single_channel=True
            )
            self.lh.load_tips.assert_any_call(
                "opentrons_96_tiprack_300ul", "7", single_channel=False
            )

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_load_default_labware_missing_file(self, mock_open_func):
        with self.assertLogs(level="ERROR") as log:
            self.lh.load_default_labware()
        self.assertIn("No default layout file found. No default labware loaded", log.output[0])

    def test_load_tips(self):
        pcr_plate = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 9)
        reservoir = self.lh.load_labware("nest_12_reservoir_15ml", 2)
        self.lh.p300_multi.dispense = MagicMock()

        # Test that operations fail when no tips are available
        volumes = [50] * 96
        source_wells = [reservoir.wells()[0]] * 96
        destination_wells = pcr_plate.wells()
        ops = list(zip(source_wells, destination_wells, volumes, range(96)))
        failed_ops = self.lh.transfer(
            volumes=volumes,
            source_wells=source_wells,
            destination_wells=destination_wells,
            new_tip="always",
            touch_tip=False,
            trash_tips=True,
            add_air_gap=False,
            overhead_liquid=0,
        )

        # Verify failed operations are reported correctly
        self.assertEqual(len(failed_ops), len(list(ops)))
        for i, (source, dest, volume, idx, reason) in enumerate(failed_ops):
            self.assertEqual(source, ops[i][0])
            self.assertEqual(dest, ops[i][1])
            self.assertEqual(volume, ops[i][2])
            self.assertEqual(idx, ops[i][3])
            self.assertEqual(reason, "out_of_tips")

        # Load tips and verify operations succeed
        self.lh.load_tips("opentrons_96_tiprack_300ul", 7, single_channel=False)
        self.lh.load_tips("opentrons_96_tiprack_300ul", 6, single_channel=True)

        failed_ops = self.lh.transfer(
            volumes=[50] * 96,
            source_wells=[reservoir.wells()[0]] * 96,
            destination_wells=pcr_plate.wells(),
        )

        # Verify no operations failed
        self.assertEqual(len(failed_ops), 0)
        self.assertEqual(self.lh.p300_multi.dispense.call_count, 12)


class TestFailedOperationsReporting(unittest.TestCase):
    def setUp(self):
        self.lh = LiquidHandler(simulation=True, load_default=False)
        self.lh.load_tips("opentrons_96_tiprack_300ul", "7", single_channel=False)
        self.lh.load_tips("opentrons_96_tiprack_300ul", "6", single_channel=True)
        self.lh.load_tips("opentrons_96_tiprack_20ul", "11", single_channel=True)

        # Mock pipettes
        self.lh.p300_multi = MagicMock()
        self.lh.p20 = MagicMock()
        self.lh.p20.min_volume = 1
        self.lh.p20.max_volume = 20
        self.lh.p300_multi.min_volume = 20
        self.lh.p300_multi.max_volume = 300

        # Mock labware
        self.source_plate = self.lh.load_labware(
            "nest_96_wellplate_100ul_pcr_full_skirt", 9, "source plate"
        )
        self.dest_plate = self.lh.load_labware(
            "nest_96_wellplate_100ul_pcr_full_skirt", 3, "destination plate"
        )

    def test_volume_too_low_reporting(self):
        # Test that operations with volumes below minimum are reported correctly
        volumes = [0.5, 25, 0.8, 30]  # 0.5 and 0.8 are below minimum
        source_wells = self.source_plate.wells()[:4]
        dest_wells = self.dest_plate.wells()[:4]

        failed_ops = self.lh.transfer(
            volumes=volumes,
            source_wells=source_wells,
            destination_wells=dest_wells,
        )

        # Verify failed operations
        self.assertEqual(len(failed_ops), 2)
        self.assertEqual(failed_ops[0][0], source_wells[0])  # source
        self.assertEqual(failed_ops[0][1], dest_wells[0])  # destination
        self.assertEqual(failed_ops[0][2], 0.5)  # volume
        self.assertEqual(failed_ops[0][3], 0)  # index
        self.assertEqual(failed_ops[0][4], "volume_too_low")  # reason

        self.assertEqual(failed_ops[1][0], source_wells[2])
        self.assertEqual(failed_ops[1][1], dest_wells[2])
        self.assertEqual(failed_ops[1][2], 0.8)
        self.assertEqual(failed_ops[1][3], 2)
        self.assertEqual(failed_ops[1][4], "volume_too_low")

    def test_out_of_tips_reporting(self):
        lh = LiquidHandler(simulation=True, load_default=False)

        # Mock labware
        source_plate = lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 9, "source plate")
        dest_plate = lh.load_labware(
            "nest_96_wellplate_100ul_pcr_full_skirt", 3, "destination plate"
        )

        volumes = [25, 30, 15, 10]
        source_wells = source_plate.wells()[:4]
        dest_wells = dest_plate.wells()[:4]

        failed_ops = lh.transfer(
            volumes=volumes,
            source_wells=source_wells,
            destination_wells=dest_wells,
        )

        # Verify all operations failed due to out of tips
        self.assertEqual(len(failed_ops), 4)
        for i, (source, dest, volume, idx, reason) in enumerate(failed_ops):
            self.assertEqual(source, source_wells[i])
            self.assertEqual(dest, dest_wells[i])
            self.assertEqual(volume, volumes[i])
            self.assertEqual(idx, i)
            self.assertEqual(reason, "out_of_tips")

    def test_mixed_failure_reporting(self):
        # Test scenario with both volume too low and out of tips failures
        lh = LiquidHandler(simulation=True, load_default=False)
        source_plate = lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 9, "source plate")
        dest_plate = lh.load_labware(
            "nest_96_wellplate_100ul_pcr_full_skirt", 3, "destination plate"
        )

        volumes = [0.5, 25, 0.8, 30]  # 0.5 and 0.8 are below minimum
        source_wells = source_plate.wells()[:4]
        dest_wells = dest_plate.wells()[:4]

        failed_ops = lh.transfer(
            volumes=volumes,
            source_wells=source_wells,
            destination_wells=dest_wells,
        )

        # Verify all operations failed with correct reasons
        self.assertEqual(len(failed_ops), 4)

        # First operation: volume too low
        self.assertEqual(failed_ops[0][2], 0.5)
        self.assertEqual(failed_ops[0][3], 0)
        self.assertEqual(failed_ops[0][4], "volume_too_low")

        # Second operation: out of tips
        self.assertEqual(failed_ops[1][2], 25)
        self.assertEqual(failed_ops[1][3], 1)
        self.assertEqual(failed_ops[1][4], "out_of_tips")

        # Third operation: volume too low
        self.assertEqual(failed_ops[2][2], 0.8)
        self.assertEqual(failed_ops[2][3], 2)
        self.assertEqual(failed_ops[2][4], "volume_too_low")

        # Fourth operation: out of tips
        self.assertEqual(failed_ops[3][2], 30)
        self.assertEqual(failed_ops[3][3], 3)
        self.assertEqual(failed_ops[3][4], "out_of_tips")

    def test_pipette_error_reporting(self):
        # Mock a pipette error during operation
        def raise_error(*args, **kwargs):
            raise Exception("Pipette malfunction")

        self.lh.p300_multi.aspirate.side_effect = raise_error
        self.lh.p20.aspirate.side_effect = raise_error

        volumes = [25, 30]
        source_wells = self.source_plate.wells()[:2]
        dest_wells = self.dest_plate.wells()[:2]

        failed_ops = self.lh.transfer(
            volumes=volumes,
            source_wells=source_wells,
            destination_wells=dest_wells,
        )

        # Verify operations failed with pipette error
        self.assertEqual(len(failed_ops), 2)
        for i, (source, dest, volume, idx, reason) in enumerate(failed_ops):
            self.assertEqual(source, source_wells[i])
            self.assertEqual(dest, dest_wells[i])
            self.assertEqual(volume, volumes[i])
            self.assertEqual(idx, i)
            self.assertEqual(reason, "pipette_error: Pipette malfunction")

    def test_failed_operations_in_distribute(self):
        # Test failed operations reporting in distribute method

        volumes = [0.5, 25, 0.8, 30]  # Mix of valid and invalid volumes
        source_well = self.source_plate.wells()[0]
        dest_wells = self.dest_plate.wells()[:4]

        failed_ops = self.lh.distribute(
            volumes=volumes,
            source_well=source_well,
            destination_wells=dest_wells,
        )

        # Verify failed operations
        self.assertEqual(len(failed_ops), 2)

        # Check volume too low failures
        volume_too_low = [op for op in failed_ops if op[4] == "volume_too_low"]
        self.assertEqual(len(volume_too_low), 2)
        self.assertEqual(volume_too_low[0][2], 0.5)
        self.assertEqual(volume_too_low[1][2], 0.8)

    def test_failed_operations_in_pool(self):
        # Test failed operations reporting in pool method

        volumes = [0.5, 25, 0.8, 30]  # Mix of valid and invalid volumes
        source_wells = self.source_plate.wells()[:4]
        dest_well = self.dest_plate.wells()[0]

        failed_ops = self.lh.pool(
            volumes=volumes,
            source_wells=source_wells,
            destination_well=dest_well,
        )

        # Verify failed operations
        self.assertEqual(len(failed_ops), 2)

        # Check volume too low failures
        volume_too_low = [op for op in failed_ops if op[4] == "volume_too_low"]
        self.assertEqual(len(volume_too_low), 2)
        self.assertEqual(volume_too_low[0][2], 0.5)
        self.assertEqual(volume_too_low[1][2], 0.8)


class TestDeckLayout(unittest.TestCase):
    def setUp(self):
        self.lh = LiquidHandler(simulation=True, load_default=False)

    def test_load_deck_layout_from_dict(self):
        # Test loading deck layout directly from dictionary
        layout = {
            "modules": {"1": "temperature module gen2"},
            "multichannel_tips": {"2": "opentrons_96_tiprack_300ul"},
            "single_channel_tips": {"3": "opentrons_96_tiprack_20ul"},
            "labware": {"4": "nest_96_wellplate_100ul_pcr_full_skirt"},
        }

        self.lh = LiquidHandler(simulation=True, load_default=False, deck_layout=layout)

        # Verify modules were loaded
        self.assertIsNotNone(self.lh.temperature_module)

        # Verify tips were loaded
        self.assertEqual(len(self.lh.p300_tips), 1)
        self.assertEqual(len(self.lh.single_p20_tips), 1)

        # Verify labware was loaded
        self.assertIsNotNone(self.lh.protocol_api.deck["4"])

    def test_load_deck_layout_overrides_default(self):
        # Test that deck_layout parameter overrides load_default
        layout = {
            "modules": {"1": "temperature module gen2"},
            "multichannel_tips": {"2": "opentrons_96_tiprack_300ul"},
            "single_channel_tips": {"3": "opentrons_96_tiprack_20ul"},
            "labware": {"4": "nest_96_wellplate_100ul_pcr_full_skirt"},
        }

        with patch.object(LiquidHandler, "load_default_labware") as mock_load_default:
            self.lh = LiquidHandler(simulation=True, load_default=True, deck_layout=layout)
            mock_load_default.assert_not_called()

    def test_load_deck_layout_empty_sections(self):
        # Test loading deck layout with empty or missing sections
        layout = {
            "modules": {},
            "multichannel_tips": {},
            "single_channel_tips": {},
            "labware": {"4": "nest_96_wellplate_100ul_pcr_full_skirt"},
        }

        self.lh = LiquidHandler(simulation=True, load_default=False, deck_layout=layout)

        # Verify only labware was loaded
        self.assertIsNone(self.lh.temperature_module)
        self.assertEqual(len(self.lh.p300_tips), 0)
        self.assertEqual(len(self.lh.single_p20_tips), 0)
        self.assertIsNotNone(self.lh.protocol_api.deck["4"])

    def test_load_deck_layout_missing_sections(self):
        # Test loading deck layout with missing sections
        layout = {"labware": {"4": "nest_96_wellplate_100ul_pcr_full_skirt"}}

        self.lh = LiquidHandler(simulation=True, load_default=False, deck_layout=layout)

        # Verify only labware was loaded
        self.assertIsNone(self.lh.temperature_module)
        self.assertEqual(len(self.lh.p300_tips), 0)
        self.assertEqual(len(self.lh.single_p20_tips), 0)
        self.assertIsNotNone(self.lh.protocol_api.deck["4"])

    def test_load_deck_layout_invalid_file(self):
        # Test handling of invalid file path
        with self.assertRaises(FileNotFoundError):
            self.lh = LiquidHandler(
                simulation=True, load_default=False, deck_layout="nonexistent.json"
            )

    def test_load_deck_layout_warning_with_default(self):
        # Test that warning is issued when both load_default and deck_layout are provided
        layout = {"labware": {"4": "nest_96_wellplate_100ul_pcr_full_skirt"}}

        with self.assertLogs(level="WARNING") as log:
            self.lh = LiquidHandler(simulation=True, load_default=True, deck_layout=layout)

        self.assertIn("Both load_default=True and deck_layout provided", log.output[0])


if __name__ == "__main__":
    unittest.main()
