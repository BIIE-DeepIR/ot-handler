#!/usr/bin/env python3
"""
Simple test to validate the tip_reuse_limit functionality in the LiquidHandler transfer method.
This test creates mock pipettes and wells to simulate the behavior without requiring the full Opentrons setup.
"""

import unittest
from unittest.mock import MagicMock, Mock

# Mock the Opentrons imports to avoid dependency issues
import sys
from unittest.mock import MagicMock

class MockOpentrons:
    protocol_api = MagicMock()
    types = MagicMock()
    
    class ProtocolCommandFailedError(Exception):
        pass

sys.modules['opentrons'] = MockOpentrons()
sys.modules['opentrons.protocol_api'] = MockOpentrons.protocol_api
sys.modules['opentrons.types'] = MockOpentrons.types
sys.modules['opentrons.protocol_api.labware'] = MagicMock()
sys.modules['opentrons.protocol_api.labware.Labware'] = MagicMock()

# Now import our LiquidHandler
from ot_handler.liquid_handler import LiquidHandler


class TestTipReuseLimit(unittest.TestCase):
    def setUp(self):
        # Initialize LiquidHandler with simulation mode
        self.lh = LiquidHandler(simulation=True, load_default=False)
        
        # Mock pipettes with tracking capabilities
        self.lh.p300_multi = MagicMock()
        self.lh.p20 = MagicMock()
        self.lh.p300_multi.min_volume = 20
        self.lh.p300_multi.max_volume = 300
        self.lh.p300_multi.has_tip = False
        self.lh.p300_multi.current_volume = 0
        self.lh.p20.min_volume = 1
        self.lh.p20.max_volume = 20
        self.lh.p20.has_tip = False
        self.lh.p20.current_volume = 0
        
        # Create mock wells
        self.source_wells = []
        self.dest_wells = []
        
        for i in range(5):
            source_well = MagicMock()
            source_well.well_name = f"A{i+1}"
            source_well.parent = MagicMock()
            source_well.parent.load_name = "mock_plate"
            source_well.top = MagicMock(return_value=MagicMock())
            self.source_wells.append(source_well)
            
            dest_well = MagicMock()
            dest_well.well_name = f"B{i+1}"
            dest_well.parent = MagicMock()
            dest_well.parent.load_name = "mock_plate"
            dest_well.top = MagicMock(return_value=MagicMock())
            self.dest_wells.append(dest_well)
        
        # Mock trash
        self.lh.trash = MagicMock()
        
        # Mock tips
        self.lh.p300_tips = [MagicMock()]
        self.lh.single_p300_tips = [MagicMock()]
        self.lh.single_p20_tips = [MagicMock()]

    def test_transfer_with_tip_reuse_limit_forces_tip_change(self):
        """Test that tip_reuse_limit forces tip changes even when new_tip='never'"""
        
        # Test parameters - 5 transfers with tip_reuse_limit=2
        volumes = [50] * 5
        source_wells = self.source_wells[:5]
        destination_wells = self.dest_wells[:5] 
        tip_reuse_limit = 2
        
        # Mock the pipette to track tip changes
        tip_changes = []
        def mock_pick_up_tip():
            tip_changes.append('pick_up')
            self.lh.p300_multi.has_tip = True
            
        def mock_drop_tip():
            tip_changes.append('drop')
            self.lh.p300_multi.has_tip = False
            
        self.lh.p300_multi.pick_up_tip.side_effect = mock_pick_up_tip
        self.lh.p300_multi.drop_tip.side_effect = mock_drop_tip
        
        # Act - perform transfer with tip_reuse_limit
        failed_operations = self.lh.transfer(
            volumes=volumes,
            source_wells=source_wells,
            destination_wells=destination_wells,
            new_tip="never",  # This would normally never change tips
            tip_reuse_limit=tip_reuse_limit,
            trash_tips=True
        )
        
        # Assert - Should have picked up tips at least 3 times due to reuse limit
        # First tip pickup + 2 forced changes (after 2nd and 4th operations)
        pick_up_count = tip_changes.count('pick_up')
        drop_count = tip_changes.count('drop')
        
        self.assertGreaterEqual(pick_up_count, 3, 
                              f"Expected at least 3 tip pickups due to reuse limit, got {pick_up_count}")
        self.assertGreaterEqual(drop_count, 2, 
                              f"Expected at least 2 tip drops due to reuse limit, got {drop_count}")
        
        # Should have no failed operations
        self.assertEqual(len(failed_operations), 0, f"Unexpected failed operations: {failed_operations}")
        
        print(f"✓ Test passed - Tip changes: {tip_changes}")
        print(f"  Pick up count: {pick_up_count}, Drop count: {drop_count}")

    def test_transfer_with_tip_reuse_limit_none_no_forced_changes(self):
        """Test that tip_reuse_limit=None doesn't force any extra tip changes"""
        
        # Test parameters - 5 transfers with no tip_reuse_limit
        volumes = [50] * 3
        source_wells = self.source_wells[:3]
        destination_wells = self.dest_wells[:3]
        
        # Mock the pipette to track tip changes
        tip_changes = []
        def mock_pick_up_tip():
            tip_changes.append('pick_up')
            self.lh.p300_multi.has_tip = True
            
        def mock_drop_tip():
            tip_changes.append('drop')
            self.lh.p300_multi.has_tip = False
            
        self.lh.p300_multi.pick_up_tip.side_effect = mock_pick_up_tip
        self.lh.p300_multi.drop_tip.side_effect = mock_drop_tip
        
        # Act - perform transfer without tip_reuse_limit
        failed_operations = self.lh.transfer(
            volumes=volumes,
            source_wells=source_wells,
            destination_wells=destination_wells,
            new_tip="never",  # Should only pick up tip once since no reuse limit
            tip_reuse_limit=None,
            trash_tips=True
        )
        
        # Assert - Should have picked up tip only once with new_tip="never"
        pick_up_count = tip_changes.count('pick_up')
        
        self.assertEqual(pick_up_count, 1, 
                        f"Expected exactly 1 tip pickup with new_tip='never', got {pick_up_count}")
        
        # Should have no failed operations
        self.assertEqual(len(failed_operations), 0, f"Unexpected failed operations: {failed_operations}")
        
        print(f"✓ Test passed - Tip changes: {tip_changes}")
        print(f"  Pick up count: {pick_up_count} (as expected with new_tip='never')")


if __name__ == '__main__':
    # Run the tests
    unittest.main(verbosity=2)