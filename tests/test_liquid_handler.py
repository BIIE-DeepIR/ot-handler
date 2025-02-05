import json
import time
import unittest
import logging
import math
import random
from unittest.mock import MagicMock, patch, mock_open
from ..liquid_handler import LiquidHandler
from opentrons.protocol_api import Labware, Well
from opentrons.protocol_api.labware import OutOfTipsError

class TestLiquidHandlerDistribute(unittest.TestCase):
    def setUp(self):
        # Initialize LiquidHandler with simulation mode
        self.lh = LiquidHandler(simulation=True, load_default=False)
        self.lh.p300_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_300ul', "7"))
        self.lh.single_p300_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_300ul', "6"))
        self.lh.single_p20_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_20ul', "11"))
        
        # Mock pipettes
        self.lh.p300_multi = MagicMock()
        self.lh.p20 = MagicMock()
        self.lh.p20.min_volume = 1
        self.lh.p20.max_volume = 20
        self.lh.p300_multi.min_volume = 20
        self.lh.p300_multi.max_volume = 300
        
        # Mock labware
        self.mock_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 9, "mock labware")
        self.mock_reservoir = self.lh.load_labware("nest_12_reservoir_15ml", 2, "mock reservoir source")
        self.dest_wells = self.mock_labware.wells()
        
        # Create mock wells
        self.source_well = self.mock_reservoir.wells("A1")[0]
        
    def test_distribute_variable_volumes_first_row(self):
        second_row_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 5, "second row")
        first_row_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 3, "first row")
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
                    new_tip="once"
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
                    new_tip="always"
                )
                self.lh.p300_multi.dispense.assert_not_called()
                self.assertGreaterEqual(self.lh.p20.dispense.call_count, sum([math.ceil(v / self.lh.p20.max_volume) for v in volumes if v]))
                self.lh.p300_multi.reset_mock()
                self.lh.p20.reset_mock()

        for i, volumes in enumerate(p300_single_volumes):
            with self.subTest(volumes=volumes):
                self.lh.distribute(
                    volumes=volumes,
                    source_well=self.source_well,
                    destination_wells=first_row_labware.columns()[i],
                    new_tip="always"
                )
                self.assertEqual(self.lh.p300_multi.dispense.call_count, len([v for v in volumes if v > 20]))
                self.lh.p20.dispense.assert_not_called()
                self.lh.p300_multi.reset_mock()
                self.lh.p20.reset_mock()

        for i, volumes in enumerate(both_volumes):
            with self.subTest(volumes=volumes):
                self.lh.distribute(
                    volumes=volumes,
                    source_well=self.source_well,
                    destination_wells=first_row_labware.columns()[i],
                    new_tip="once"
                )
                self.lh.p300_multi.dispense.assert_called()
                self.lh.p20.dispense.assert_called()
                self.lh.p300_multi.reset_mock()
                self.lh.p20.reset_mock()
        
    def test_distribute_variable_volumes_second_row(self):
        # On the second row, single mode multichannel should be able to access anywhere
        second_row_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 5, "second row")
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
                    new_tip="once"
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
                    new_tip="always"
                )
                self.lh.p300_multi.dispense.assert_not_called()
                self.assertGreaterEqual(self.lh.p20.dispense.call_count, sum([math.ceil(v / self.lh.p20.max_volume) for v in volumes if v]))
                self.lh.p300_multi.reset_mock()
                self.lh.p20.reset_mock()

        for i, volumes in enumerate(p300_single_volumes):
            with self.subTest(volumes=volumes):
                self.lh.distribute(
                    volumes=volumes,
                    source_well=self.source_well,
                    destination_wells=second_row_labware.columns()[i],
                    new_tip="never"
                )
                self.assertEqual(self.lh.p300_multi.dispense.call_count, len([v for v in volumes if v > 20]))
                self.lh.p20.dispense.assert_not_called()
                self.lh.p300_multi.reset_mock()
                self.lh.p20.reset_mock()

        for i, volumes in enumerate(both_volumes):
            with self.subTest(volumes=volumes):
                self.lh.distribute(
                    volumes=volumes,
                    source_well=self.source_well,
                    destination_wells=second_row_labware.columns()[i],
                    new_tip="once"
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
            overhead_liquid=False
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
                new_tip=new_tip
            )
        self.assertIn("invalid value for the optional argument 'new_tip'", str(context.exception))
        
    def test_distribute_volume_below_minimum(self):
        # Arrange
        volume = 0.1  # Below p20.min_volume
        
        # Act & Assert
        with self.assertLogs(level='WARNING') as log:
            self.lh.distribute(
                volumes=volume,
                source_well=self.source_well,
                destination_wells=[self.dest_wells[0]],
                new_tip="never"
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
        with patch.object(self.lh, 'transfer', wraps=self.lh.transfer) as mock_transfer:
            self.lh.distribute(
                volumes=volumes,
                source_well=self.source_well,
                destination_wells=destination_wells,
                new_tip="always"
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
            overhead_liquid=False
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
            overhead_liquid=False
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
                overhead_liquid=False
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
                overhead_liquid=False
            )

            # Assert
            # Ensure p300_multi is used for both the main volume and the remainder
            self.assertEqual(self.lh.p300_multi.dispense.call_count, 2*len(wells))
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
            mix_after=mix_after
        )

        # Assert
        self.lh.p300_multi.mix.assert_called_once_with(
            repetitions=mix_after[0],
            volume=mix_after[1],
            location=test_labware.columns()[0][0]
        )
        self.lh.p300_multi.dispense.assert_called()
        self.lh.p20.dispense.assert_not_called()
        self.lh.p300_multi.mix.reset_mock()
        self.lh.p300_multi.dispense.reset_mock()

    def test_distribute_with_mix_after_exceed_pipette_range(self):
        # Arrange
        volume = 50
        mix_after = (3, 1)  # 3 repetitions of 1µL each, which should fail because out of volume range
        test_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 3, "test")

        # Act
        self.lh.distribute(
            volumes=volume,
            source_well=self.source_well,
            destination_wells=test_labware.columns()[0],
            new_tip="once",
            overhead_liquid=False,
            mix_after=mix_after
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
            overhead_liquid=False
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
            overhead_liquid=False
        )
        self.lh.p300_multi.dispense.assert_called()
        self.lh.p20.dispense.assert_not_called()

class TestLiquidHandlerStamp(unittest.TestCase):
    def setUp(self):
        # Initialize LiquidHandler with simulation mode
        self.lh = LiquidHandler(simulation=True, load_default=False)
        self.lh.p300_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_300ul', "7"))
        self.lh.single_p300_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_300ul', "6"))
        self.lh.single_p20_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_20ul', "11"))
        
        # Mock pipettes
        self.lh.p300_multi = MagicMock()
        self.lh.p20 = MagicMock()
        self.lh.p20.min_volume = 1
        self.lh.p20.max_volume = 20
        self.lh.p300_multi.min_volume = 20
        self.lh.p300_multi.max_volume = 300
        
        # Mock labware
        self.mock_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 9, "mock labware")
        self.mock_reservoir = self.lh.load_labware("nest_12_reservoir_15ml", 2, "mock reservoir source")
        self.dest_wells = self.mock_labware.wells()
        
        # Create mock wells
        self.source_well = self.mock_reservoir.wells("A1")[0]

    def test_transfer_multi_aspirate_with_mix_after(self):
        # Arrange
        volume = 50
        mix_after = (3, 20)  # 3 repetitions of 20µL each
        test_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 3, "test")

        # Act
        self.lh.transfer(
            volumes=volume,
            source_wells=test_labware.columns()[2] + test_labware.columns()[3],
            destination_wells=test_labware.columns()[0],
            new_tip="never",
            overhead_liquid=False,
            mix_after=mix_after
        )

        # Assert
        self.lh.p300_multi.mix.assert_called_once_with(
            repetitions=mix_after[0],
            volume=mix_after[1],
            location=test_labware.columns()[0][0]
        )
        self.lh.p300_multi.dispense.assert_called()
        self.lh.p20.dispense.assert_not_called()
        self.lh.p300_multi.drop_tip.assert_not_called()
        self.lh.p300_multi.mix.reset_mock()
        self.lh.p300_multi.dispense.reset_mock()


class TestLiquidHandlerAllocate(unittest.TestCase):
    def setUp(self):
        # Initialize LiquidHandler with simulation mode
        self.lh = LiquidHandler(simulation=True, load_default=False)
        self.lh.p300_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_300ul', "7"))
        self.lh.single_p300_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_300ul', "6"))
        self.lh.single_p20_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_20ul', "11"))
        
        # Mock pipettes
        self.lh.p300_multi = MagicMock()
        self.lh.p20 = MagicMock()
        self.lh.p20.min_volume = 1
        self.lh.p20.max_volume = 20
        self.lh.p300_multi.min_volume = 20
        self.lh.p300_multi.max_volume = 300
        
        # Mock labware
        self.mock_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 9, "mock labware")
        self.mock_reservoir = self.lh.load_labware("nest_12_reservoir_15ml", 2, "mock reservoir source")
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
                volumes=p20_volumes
            )
            self.assertEqual(len(p300_multi), 0, "p300_multi should be empty")
            self.assertEqual(len(p300), 0, "p300 should be empty")
            self.assertEqual(len(p20), well_count, f"p20 should have {well_count} elements")

        with self.subTest("Allocate p300 volumes"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=[self.mock_labware.wells()[i] for i in indexes],
                destination_wells=[test_labware.wells()[i] for i in sorted(indexes)],
                volumes=p300_volumes
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
            with self.assertRaises(ValueError, msg="Should raise ValueError for multiple labware in source or destination"):
                self.lh._allocate_liquid_handling_steps(
                    source_wells=source_wells,
                    destination_wells=destination_wells,
                    volumes=volumes
                )

        with self.subTest("Multiple labware in source only"):
            source_wells = [test_labware_1.wells("A1"), test_labware_2.wells("A1")]
            destination_wells = [test_labware_1.wells("B1"), test_labware_1.wells("C1")]
            with self.assertRaises(ValueError, msg="Should raise ValueError for multiple labware in source"):
                self.lh._allocate_liquid_handling_steps(
                    source_wells=source_wells,
                    destination_wells=destination_wells,
                    volumes=volumes
                )

        with self.subTest("Multiple labware in destination only"):
            source_wells = [test_labware_1.wells("A1"), test_labware_1.wells("A2")]
            destination_wells = [test_labware_1.wells("B1"), test_labware_2.wells("B1")]
            with self.assertRaises(ValueError, msg="Should raise ValueError for multiple labware in destination"):
                self.lh._allocate_liquid_handling_steps(
                    source_wells=source_wells,
                    destination_wells=destination_wells,
                    volumes=volumes
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
                volumes=equal_volumes
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(len(p300_multi), len(test_labware.columns()), "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 0, "p300 should be empty")
            self.assertEqual(len(p20), 0, "p20 should be empty")
        
        with self.subTest("Column-wise operations with equal volumes - source to destination"):
            # Perform the allocation
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=source_wells + source_wells,
                destination_wells=destination_wells + destination_wells,
                volumes=equal_volumes + equal_volumes
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(len(p300_multi), 2*len(test_labware.columns()), "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 0, "p300 should be empty")
            self.assertEqual(len(p20), 0, "p20 should be empty")
        
        with self.subTest("Column-wise operations with equal volumes - destination to source"):
            # Perform the allocation
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=destination_wells,
                destination_wells=source_wells,
                volumes=equal_volumes
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(len(p300_multi), len(test_labware.columns()), "p300_multi should handle column-wise operations")
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
                destination_wells=[test_labware.wells()[i] for i in sorted(indexes)] + destination_wells,
                volumes=p20_volumes + equal_volumes
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(len(p300_multi), len(test_labware.columns()), "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 0, "p300 should be empty")
            self.assertEqual(len(p20), well_count, "p20 should not be empty")

        with self.subTest("Add noise with p300 compatible volumes"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=[self.mock_reservoir.wells()[i] for i in indexes] + source_wells,
                destination_wells=[test_labware.wells()[i] for i in sorted(indexes)] + destination_wells,
                volumes=p300_volumes + equal_volumes
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(len(p300_multi), len(test_labware.columns()), "p300_multi should handle column-wise operations")
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
                source_wells=source_column,
                destination_wells=dest_column,
                volumes=volumes
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(len(p300_multi), 1, "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 0, "p300 should be empty")
            self.assertEqual(len(p20), 0, "p20 should be empty")

        with self.subTest("Add noise with p20 compatible volumes"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=dest_column,
                destination_wells=source_column,
                volumes=volumes
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(len(p300_multi), 1, "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 0, "p300 should be empty")
            self.assertEqual(len(p20), 0, "p20 should be empty")

        with self.subTest("Add noise with p20 compatible volumes"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=source_column + test_labware2.wells(),
                destination_wells=dest_column + test_labware.wells(),
                volumes=volumes + extra_volumes
            )

            # Assert that p300_multi is used for column-wise operations
            self.assertEqual(len(p300_multi), 1, "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 96, "p300 should not be empty")
            self.assertEqual(len(p20), 0, "p20 should be empty")

        with self.subTest("Add noise with p20 compatible volumes"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=source_column + source_column + test_labware2.wells(),
                destination_wells=dest_column + dest_column + test_labware.wells(),
                volumes=volumes + volumes + extra_volumes
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
                source_wells=source_column,
                destination_wells=dest_column,
                volumes=volumes
            )

            # P300 single mode should access all but bottom two rows
            self.assertEqual(len(p300_multi), 0, "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 6, "p300 should not be empty")
            self.assertEqual(len(p20), 2, "p20 should not be empty")

        with self.subTest("Test the bottom row access"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=source_column + source_column,
                destination_wells=dest_column + dest_column,
                volumes=volumes + volumes
            )

            # P300 single mode should access all but bottom two rows
            self.assertEqual(len(p300_multi), 0, "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 12, "p300 should not be empty")
            self.assertEqual(len(p20), 4, "p20 should not be empty")

        with self.subTest("Test the bottom row access"):
            p300_multi, p300, p20 = self.lh._allocate_liquid_handling_steps(
                source_wells=dest_column,
                destination_wells=source_column,
                volumes=volumes
            )

            # P300 single mode should access all but bottom two rows
            self.assertEqual(len(p300_multi), 0, "p300_multi should handle column-wise operations")
            self.assertEqual(len(p300), 6, "p300 should not be empty")
            self.assertEqual(len(p20), 2, "p20 should not be empty")

class TestLiquidHandlerPool(unittest.TestCase):
    def setUp(self):
        # Initialize LiquidHandler with simulation mode
        self.lh = LiquidHandler(simulation=True, load_default=False)
        self.lh.p300_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_300ul', "7"))
        self.lh.single_p300_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_300ul', "6"))
        self.lh.single_p20_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_20ul', "11"))
        
        # Mock pipettes
        self.lh.p300_multi = MagicMock()
        self.lh.p20 = MagicMock()
        self.lh.p20.min_volume = 1
        self.lh.p20.max_volume = 20
        self.lh.p300_multi.min_volume = 20
        self.lh.p300_multi.max_volume = 300
        
        # Mock labware
        self.mock_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 9, "mock labware")
        self.mock_reservoir = self.lh.load_labware("nest_12_reservoir_15ml", 2, "mock reservoir source")
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
            new_tip="once"
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
            new_tip="once"
        )
        
        # Assert
        self.assertEqual(self.lh.p20.dispense.call_count, 96)
        self.assertEqual(self.lh.p20.aspirate.call_count, 96)
        self.assertEqual(self.lh.p20.air_gap.call_count, 96)
        self.lh.p300_multi.aspirate.assert_not_called()
        self.lh.p300_multi.dispense.assert_not_called()
        self.lh.p300_multi.air_gap.assert_not_called()

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
                add_air_gap=False
            )
            
            self.assertEqual(self.lh.p20.dispense.call_count, 4)
            self.assertEqual(self.lh.p20.aspirate.call_count, 4)
            self.lh.p20.air_gap.assert_not_called()
            self.lh.p300_multi.air_gap.assert_not_called()
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
                add_air_gap=True
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
                new_tip=new_tip
            )
        self.assertIn("invalid value for the optional argument 'new_tip'", str(context.exception))

    def test_pool_volume_below_minimum(self):
        # Arrange
        volume = 0.1  # Below p20.min_volume
        
        # Act & Assert
        with self.assertLogs(level='WARNING') as log:
            self.lh.pool(
                volumes=volume,
                source_wells=self.mock_labware.wells(),
                destination_well=self.mock_reservoir.wells()[0],
                new_tip="never"
            )
        self.assertIn("Volume too low, requested operation ignored", log.output[0])
        self.lh.p20.dispense.assert_not_called()

    def test_pool_with_large_volume(self):
        # Arrange
        volume = 100  # Exceeds p20.max_volume, should use p300_multi
        
        # Act
        self.lh.pool(
            volumes=volume,
            source_wells=self.mock_labware.wells(),
            destination_well=self.mock_reservoir.wells()[0],
            new_tip="once"
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
            new_tip="once"
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
            new_tip="once"
        )
        
        # Assert
        self.lh.p300_multi.aspirate.assert_called()
        self.lh.p300_multi.dispense.assert_called()
        self.lh.p20.aspirate.assert_not_called()
        self.lh.p20.dispense.assert_not_called()

    def test_pool_with_invalid_destination_well(self):
        # Arrange
        volume = 10
        invalid_destination = [self.mock_reservoir.wells()[0], self.mock_reservoir.wells()[1]]  # Invalid as it should be a single well
        
        # Act & Assert
        with self.assertRaises(TypeError) as context:
            self.lh.pool(
                volumes=volume,
                source_wells=self.mock_labware.wells(),
                destination_well=invalid_destination,
                new_tip="once"
            )


class TestLiquidHandlerStamp(unittest.TestCase):
    def setUp(self):
        # Initialize LiquidHandler with simulation mode
        self.lh = LiquidHandler(simulation=True, load_default=False)
        self.lh.p300_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_300ul', "7"))
        self.lh.single_p300_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_300ul', "6"))
        self.lh.single_p20_tips.append(self.lh.protocol_api.load_labware('opentrons_96_tiprack_20ul', "11"))
        
        # Mock pipettes
        self.lh.p300_multi = MagicMock()
        self.lh.p20 = MagicMock()
        self.lh.p20.min_volume = 1
        self.lh.p20.max_volume = 20
        self.lh.p300_multi.min_volume = 20
        self.lh.p300_multi.max_volume = 300
        
        # Mock labware
        self.mock_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 9, "mock labware")
        self.mock_reservoir = self.lh.load_labware("nest_12_reservoir_15ml", 2, "mock reservoir source")
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

        # Serialize the mock data as JSON to simulate the file content
        mock_file_content = json.dumps(mock_json_data)

        mock_open_func.return_value = mock_open(read_data=json.dumps(mock_json_data)).return_value
        mock_json_load.return_value = mock_json_data

        # Patch both open and json.load
        
        with patch("builtins.open", mock_open(read_data=mock_file_content)) as mocked_open, \
             patch("json.load", return_value=mock_json_data) as mocked_json_load:
            self.lh.load_labware = unittest.mock.Mock()
            self.lh.load_tips = unittest.mock.Mock()
            self.lh.load_module = unittest.mock.Mock()

            self.lh.load_default_labware()

            self.lh.load_labware.assert_not_called()

            self.assertEqual(self.lh.load_tips.call_count, 3)
            self.lh.load_tips.assert_any_call("opentrons_96_tiprack_300ul", "6", single_channel=True)
            self.lh.load_tips.assert_any_call("opentrons_96_tiprack_20ul", "11", single_channel=True)
            self.lh.load_tips.assert_any_call("opentrons_96_tiprack_300ul", "7", single_channel=False)

            self.lh.load_module.assert_any_call("temperature module gen2", "4")
            self.lh.load_module.assert_any_call("heaterShakerModuleV1", "10")
            self.lh.load_module.assert_any_call("magnetic module gen2", "9")

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_load_default_labware_missing_file(self, mock_open_func):
        with self.assertLogs(level='ERROR') as log:
            self.lh.load_default_labware()
        self.assertIn("No default layout file found. No default labware loaded", log.output[0])

    def test_load_tips(self):
        pcr_plate = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 9)
        reservoir = self.lh.load_labware("nest_12_reservoir_15ml", 2)
        self.lh.p300_multi.dispense = MagicMock()
        with self.assertRaises(OutOfTipsError) as context:
            self.lh.transfer(
                volumes=[50]*96,
                source_wells=[reservoir.wells()[0]]*96,
                destination_wells=pcr_plate.wells()
            )
        
        self.lh.load_tips("opentrons_96_tiprack_300ul", 7, single_channel=False)
        self.lh.load_tips("opentrons_96_tiprack_300ul", 6, single_channel=True)
        
        self.lh.transfer(
            volumes=[50]*96,
            source_wells=[reservoir.wells()[0]]*96,
            destination_wells=pcr_plate.wells()
        )
        self.assertEqual(self.lh.p300_multi.dispense.call_count, 12)



class TestTipManagement(unittest.TestCase):
    def setUp(self):
        # Initialize LiquidHandler with simulation mode
        self.lh = LiquidHandler(simulation=True, load_default=False)
        
        # Mock labware
        self.mock_labware = self.lh.load_labware("nest_96_wellplate_100ul_pcr_full_skirt", 9, "mock labware")
        self.mock_reservoir = self.lh.load_labware("nest_12_reservoir_15ml", 2, "mock reservoir source")
    
    def test300ulTips(self):
        self.lh.load_tips("opentrons_96_tiprack_300ul", "7")

        # Within the volume range
        self.lh.distribute(
            250,
            self.mock_reservoir["A1"],
            self.mock_labware.wells(),
            add_air_gap=False,
            overhead_liquid=False
        )

        # Exceeds the volume range
        self.lh.distribute(
            350,
            self.mock_reservoir["A2"],
            self.mock_labware.wells(),
            add_air_gap=False,
            overhead_liquid=False
        )
    
    def test200ulFilterTips(self):
        self.lh.load_tips("opentrons_96_filtertiprack_200ul", "7")

        # Within the volume range
        self.lh.distribute(
            150,
            self.mock_reservoir["A1"],
            self.mock_labware.wells(),
            add_air_gap=False,
            overhead_liquid=False
        )

        # Exceeds the volume range
        self.lh.distribute(
            250,
            self.mock_reservoir["A1"],
            self.mock_labware.wells(),
            add_air_gap=False,
            overhead_liquid=False
        )
    
    def testMaxVolumeSetting(self):
        self.lh = LiquidHandler(simulation=True, load_default=False, max_volume=150)
        self.lh.p300_multi = MagicMock()
        self.lh.p300_multi.min_volume = 20
        self.lh.p300_multi.max_volume = 300
        self.lh.load_tips("opentrons_96_filtertiprack_200ul", "7")

        # Within the volume range
        self.lh.transfer(
            150,
            [self.mock_reservoir["A1"]],
            self.mock_labware.columns()[0],
            add_air_gap=False,
            overhead_liquid=False
        )

        self.assertEqual(self.lh.p300_multi.dispense.call_count, 1)
        self.lh.p300_multi.reset_mock()

        # Within the volume range
        self.lh.transfer(
            200,
            [self.mock_reservoir["A1"]],
            self.mock_labware.columns()[0],
            add_air_gap=False,
            overhead_liquid=False
        )

        self.assertEqual(self.lh.p300_multi.dispense.call_count, 2)

if __name__ == '__main__':
    unittest.main()