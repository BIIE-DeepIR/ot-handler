"""Checks for the behaviour fixed and added in 0.3.x, on the real simulator.

Layout used throughout: 300 ul racks in slots 10 and 11 (shared by both
pipette modes), a 20 ul rack in slot 9, labware in slots 1-6. Nothing stands in
front of the 300 ul racks, so Opentrons' partial-tip collision check stays quiet.
"""

import threading
import unittest
from unittest.mock import MagicMock

from ot_handler.liquid_handler import (  # before opentrons: numpy.trapz alias
    LIQUID_SUBMERGE_MM,
    OT2_MAX_API_LEVEL,
    TUBE_DISPENSE_DEPTH_MM,
    TUBE_MIN_CLEARANCE_MM,
    LiquidHandler,
)
import opentrons.protocol_api as papi  # noqa: E402
from opentrons.protocol_api.labware import Well  # noqa: E402
from opentrons.protocol_engine.errors import ProtocolCommandFailedError  # noqa: E402
from opentrons.protocols.api_support.types import APIVersion  # noqa: E402

PLATE = "nest_96_wellplate_200ul_flat"
TUBES = "opentrons_15_tuberack_falcon_15ml_conical"
RESERVOIR = "nest_12_reservoir_15ml"
DEEP_PLATE = "nest_96_wellplate_2ml_deep"  # has innerLabwareGeometry


def handler(**kwargs):
    lh = LiquidHandler(simulation=True, load_default=False, **kwargs)
    lh.load_tips("opentrons_96_tiprack_300ul", 10)
    lh.load_tips("opentrons_96_tiprack_300ul", 11)
    lh.load_tips("opentrons_96_tiprack_20ul", 9, single_channel=True)
    return lh


def used_tips(rack):
    return [w.well_name for w in rack.wells() if not w.has_tip]


def where(location):
    """(well name, z) of a pipetting location; z is None when the bare well was passed."""
    if isinstance(location, Well):
        return location.well_name, None
    return location.labware.as_well().well_name, location.point.z


def spy(pipette, method):
    """Record every call's location (and the tip volume before it), then run the real method."""
    calls = []
    original = getattr(pipette, method)

    def wrapped(*args, **kwargs):
        location = kwargs.get("location", args[1] if len(args) > 1 else args[0] if args else None)
        calls.append({"where": where(location), "volume_before": pipette.current_volume, **kwargs})
        return original(*args, **kwargs)

    setattr(pipette, method, wrapped)
    return calls


class TestApiLevel(unittest.TestCase):
    def test_default_is_the_ot2_ceiling_or_lower(self):
        lh = handler()
        self.assertEqual(lh.api_version, min(papi.MAX_SUPPORTED_VERSION, OT2_MAX_API_LEVEL))
        self.assertLessEqual(lh.api_version, APIVersion(2, 28))

    def test_explicit_level_is_honoured(self):
        self.assertEqual(handler(api_version="2.21").api_version, APIVersion(2, 21))


class TestInputLengths(unittest.TestCase):
    def test_mismatched_lengths_raise_before_anything_moves(self):
        lh = handler()
        a, d = lh.load_labware(PLATE, 4), lh.load_labware(PLATE, 5)
        dispenses = spy(lh.p300_multi, "dispense")
        with self.assertRaises(ValueError):
            lh.transfer([30, 40, 50], a.wells()[:3], d.wells()[:2])
        self.assertEqual(dispenses, [])

    def test_one_element_lists_broadcast(self):
        lh = handler()
        a, d = lh.load_labware(PLATE, 4), lh.load_labware(PLATE, 5)
        dispenses = spy(lh.p300_multi, "dispense")
        self.assertEqual(lh.transfer([30], [a["A1"]], d.wells()[:4]), [])
        self.assertEqual([c["where"][0] for c in dispenses], ["A1", "B1", "C1", "D1"])


class TestSharedTipRacks(unittest.TestCase):
    def test_single_and_multichannel_share_a_rack_without_partial_columns(self):
        lh = handler()
        a, d = lh.load_labware(PLATE, 4), lh.load_labware(PLATE, 5)
        rack = lh.p300_tips[0]
        self.assertIn(rack, lh.single_p300_tips)

        # Three single-tip steps work column 1 up from row H.
        lh.transfer([50, 60, 70], a.wells()[:3], d.wells()[:3], new_tip="always")
        self.assertEqual(used_tips(rack), ["F1", "G1", "H1"])

        # The 8-channel skips the part-used column and takes a full one.
        lh.transfer([50] * 8, a.columns()[1], d.columns()[1])
        self.assertEqual(used_tips(rack), ["F1", "G1", "H1"] + [f"{r}2" for r in "ABCDEFGH"])

        # Single-tip mode finishes column 1 before it opens column 3 - never column 2.
        lh.transfer([50] * 6, a.wells()[8:14], d.wells()[8:14], new_tip="always")
        self.assertEqual(
            used_tips(rack), [f"{r}1" for r in "ABCDEFGH"] + [f"{r}2" for r in "ABCDEFGH"] + ["H3"]
        )

        # And the 8-channel skips column 3, which single-tip mode has started.
        lh.transfer([50] * 8, a.columns()[2], d.columns()[2])
        self.assertEqual(used_tips(rack)[-8:], [f"{r}4" for r in "ABCDEFGH"])

    def test_front_row_racks_serve_the_multichannel_only(self):
        lh = LiquidHandler(simulation=True, load_default=False)
        front = lh.load_tips("opentrons_96_tiprack_300ul", 1)
        back = lh.load_tips("opentrons_96_tiprack_300ul", 10)
        explicit_front = lh.load_tips("opentrons_96_tiprack_300ul", 2, single_channel=True)
        self.assertEqual(lh.p300_tips, [front, back, explicit_front])
        self.assertEqual(lh.single_p300_tips, [back, explicit_front])


class TestLiquidTracking(unittest.TestCase):
    def heights(self, call, well):
        """(aspiration height above the bottom, None): one fixed location, never a moving
        aspirate - end_location is a Flex feature that draws air on the OT-2."""
        self.assertNotIn("end_location", call)
        bottom = well.bottom().point.z
        return call["where"][1] - bottom, None

    def test_single_well_follows_the_meniscus_down(self):
        lh = handler()
        src, dst = lh.load_labware(DEEP_PLATE, 4), lh.load_labware(DEEP_PLATE, 5)
        self.assertEqual(lh.load_liquids(src, {"A1": 500}), [])
        level = float(src["A1"].current_liquid_height())
        aspirates = spy(lh.p300_multi, "aspirate")
        self.assertEqual(lh.transfer([150], [src["A1"]], [dst["A1"]], add_air_gap=False, overhead_liquid=False), [])
        start, _ = self.heights(aspirates[-1], src["A1"])
        # Under where the meniscus ends up after the draw: lower than the pre-draw point.
        self.assertLess(start, level - LIQUID_SUBMERGE_MM)
        self.assertGreater(start, level - LIQUID_SUBMERGE_MM - 10)
        self.assertAlmostEqual(float(src["A1"].current_liquid_volume()), 350, delta=1)

    def test_multichannel_takes_the_lowest_level_in_the_column(self):
        lh = handler()
        src, dst = lh.load_labware(DEEP_PLATE, 4), lh.load_labware(DEEP_PLATE, 5)
        column = [f"{r}1" for r in "ABCDEFGH"]
        lh.load_liquids(src, {w: (300 if w == "D1" else 600) for w in column})
        lowest = float(src["D1"].current_liquid_height())
        aspirates = spy(lh.p300_multi, "aspirate")
        wells = [src[w] for w in column]
        self.assertEqual(lh.transfer([100] * 8, wells, [dst[w] for w in column], overhead_liquid=False), [])
        start, _ = self.heights(aspirates[-1], src["A1"])
        self.assertLess(start, lowest - LIQUID_SUBMERGE_MM)
        self.assertAlmostEqual(float(src["H1"].current_liquid_volume()), 500, delta=1)

    def test_eight_tips_in_one_trough_well_draw_eight_times_the_volume(self):
        lh = handler()
        trough, dst = lh.load_labware(RESERVOIR, 4), lh.load_labware(DEEP_PLATE, 5)
        lh.load_liquids(trough, {"A1": 10000})
        column = [dst[f"{r}1"] for r in "ABCDEFGH"]
        self.assertEqual(lh.transfer([100] * 8, [trough["A1"]] * 8, column, overhead_liquid=False), [])
        self.assertAlmostEqual(float(trough["A1"].current_liquid_volume()), 9200, delta=5)

    def test_a_plate_filled_during_the_run_is_tracked_once_marked_empty(self):
        lh = handler()
        src, mid, dst = (lh.load_labware(DEEP_PLATE, s) for s in (4, 5, 6))
        lh.load_liquids(src, {"A1": 500})
        lh.load_liquids(mid, {"A1": 0})
        self.assertEqual(lh.transfer([200], [src["A1"]], [mid["A1"]]), [])
        aspirates = spy(lh.p300_multi, "aspirate")
        self.assertEqual(lh.transfer([100], [mid["A1"]], [dst["A1"]], add_air_gap=False), [])
        start, _ = self.heights(aspirates[-1], mid["A1"])
        self.assertIsNotNone(start)
        self.assertGreaterEqual(start, TUBE_MIN_CLEARANCE_MM)

    def test_a_nearly_empty_well_stops_above_the_bottom(self):
        lh = handler()
        src, dst = lh.load_labware(DEEP_PLATE, 4), lh.load_labware(DEEP_PLATE, 5)
        lh.load_liquids(src, {"A1": 60})
        aspirates = spy(lh.p300_multi, "aspirate")
        self.assertEqual(lh.transfer([50], [src["A1"]], [dst["A1"]], add_air_gap=False), [])
        start, _ = self.heights(aspirates[-1], src["A1"])
        self.assertGreaterEqual(start, TUBE_MIN_CLEARANCE_MM)

    def test_unrecorded_wells_are_aspirated_as_before(self):
        lh = handler()
        src, dst = lh.load_labware(DEEP_PLATE, 4), lh.load_labware(DEEP_PLATE, 5)
        aspirates = spy(lh.p300_multi, "aspirate")
        self.assertEqual(lh.transfer([150], [src["A1"]], [dst["A1"]]), [])
        self.assertEqual(aspirates[-1]["where"], ("A1", None))
        self.assertNotIn("end_location", aspirates[-1])


class TestDeepTubes(unittest.TestCase):
    def test_p300_dispenses_just_below_the_rim(self):
        lh = handler()
        a, t = lh.load_labware(PLATE, 4), lh.load_labware(TUBES, 5)
        dispenses = spy(lh.p300_multi, "dispense")
        self.assertEqual(lh.transfer([100], [a["A1"]], [t["A1"]]), [])
        ((name, z),) = [c["where"] for c in dispenses]
        self.assertEqual(name, "A1")
        self.assertAlmostEqual(z, t["A1"].top().point.z - TUBE_DISPENSE_DEPTH_MM)

    def test_p300_never_aspirates_from_a_tube(self):
        lh = handler()
        a, t = lh.load_labware(PLATE, 4), lh.load_labware(TUBES, 5)
        multi, single, p20 = lh._allocate_liquid_handling_steps([t["A1"]], [a["A1"]], [100])
        self.assertEqual((len(multi), len(single), len(p20)), (0, 0, 1))
        multi, single, p20 = lh._allocate_liquid_handling_steps([a["A1"]], [t["A1"]], [100])
        self.assertEqual((len(multi), len(single), len(p20)), (0, 1, 0))

    def test_p20_tracks_the_liquid_level_when_it_is_known(self):
        lh = handler()
        a, t = lh.load_labware(PLATE, 4), lh.load_labware(TUBES, 5)
        aspirates = spy(lh.p20, "aspirate")
        bottom = t["A1"].bottom().point.z

        # Unknown level: the bottom, as before.
        self.assertEqual(lh.transfer([15], [t["A1"]], [a["A1"]]), [])
        self.assertEqual(aspirates[-1]["where"], ("A1", None))

        # Known level: a few mm under the meniscus, well off the bottom, following it down.
        lh.set_well_volume(t["B1"], 5000)
        self.assertEqual(lh.transfer([15, 15], [t["B1"]] * 2, [a["B1"], a["C1"]]), [])
        heights = [c["where"][1] - bottom for c in aspirates[-2:]]
        self.assertGreater(heights[0], 30)
        self.assertLess(heights[0], t["B1"].depth)
        self.assertLessEqual(heights[1], heights[0])
        self.assertGreaterEqual(min(heights), TUBE_MIN_CLEARANCE_MM)

    def test_mix_after_into_a_tube_is_skipped_for_the_p300(self):
        lh = handler()
        a, t = lh.load_labware(PLATE, 4), lh.load_labware(TUBES, 5)
        mixes = spy(lh.p300_multi, "mix")
        self.assertEqual(lh.transfer([100], [a["A1"]], [t["A1"]], mix_after=(3, 50)), [])
        self.assertEqual(mixes, [])


class TestFrontRow(unittest.TestCase):
    def test_rule_applies_to_labware_on_a_module(self):
        lh = handler()
        lh.load_module("temperature module gen2", 1)
        block = lh.load_labware("opentrons_96_aluminumblock_generic_pcr_strip_200ul", 1)
        a = lh.load_labware(PLATE, 4)
        _, single, p20 = lh._allocate_liquid_handling_steps([a["A1"]], [block["H1"]], [100])
        self.assertEqual((len(single), len(p20)), (0, 1))
        _, single, p20 = lh._allocate_liquid_handling_steps([a["A1"]], [block["A1"]], [100])
        self.assertEqual((len(single), len(p20)), (1, 0))


class TestBlowOut(unittest.TestCase):
    def test_leftover_goes_back_to_its_own_source(self):
        lh = handler()
        a, d = lh.load_labware(PLATE, 4), lh.load_labware(PLATE, 5)
        blow_outs = spy(lh.p300_multi, "blow_out")
        lh.transfer([30, 30, 30], [a["A1"], a["B1"], a["C1"]], [d["A1"]] * 3, blow_out_to="source")
        self.assertEqual([c["where"][0] for c in blow_outs], ["A1", "B1", "C1"])


class TestMix(unittest.TestCase):
    def test_full_columns_are_found_wherever_they_sit_in_the_list(self):
        lh = handler()
        p = lh.load_labware(PLATE, 4)
        multi = spy(lh.p300_multi, "mix")
        p20 = spy(lh.p20, "mix")
        row_wise = [w for row in p.rows() for w in row[:2]]  # A1, A2, B1, B2, ...
        lh.mix(row_wise, 2, 50)
        self.assertEqual([c["where"][0] for c in multi], ["A1", "A2"])
        self.assertEqual(p20, [])

    def test_tube_and_front_row_wells_go_to_the_p20(self):
        lh = handler()
        t, front, p = (
            lh.load_labware(TUBES, 5),
            lh.load_labware(PLATE, 1),
            lh.load_labware(PLATE, 4),
        )
        multi = spy(lh.p300_multi, "mix")
        p20 = spy(lh.p20, "mix")
        lh.mix([t["A1"], front["H1"], p["A1"]], 2, 50)
        self.assertEqual([(c["where"][0], c["volume"]) for c in multi], [("A1", 50)])
        self.assertEqual([(c["where"][0], c["volume"]) for c in p20], [("A1", 20), ("H1", 20)])
        self.assertFalse(lh.p300_multi.has_tip)
        self.assertFalse(lh.p20.has_tip)
        self.assertFalse(lh.single_tip_mode)

    def test_empty_list_is_a_no_op(self):
        handler().mix([], 2, 50)


class TestMultiLabware(unittest.TestCase):
    def test_mix_after_reaches_every_source_plate(self):
        lh = handler()
        a, b, d = lh.load_labware(PLATE, 4), lh.load_labware(PLATE, 5), lh.load_labware(PLATE, 6)
        mixes = spy(lh.p300_multi, "mix")
        lh.transfer([50, 50], [a["A1"], b["A1"]], [d["A1"], d["B1"]], mix_after=(2, 30))
        self.assertEqual(sorted(c["where"][0] for c in mixes), ["A1", "B1"])


class TestErrors(unittest.TestCase):
    def _flaky_dispense(self, lh, error):
        original = lh.p300_multi.dispense
        state = {"calls": 0}

        def dispense(*args, **kwargs):
            state["calls"] += 1
            if state["calls"] == 1:
                raise error
            return original(*args, **kwargs)

        lh.p300_multi.dispense = dispense

    def test_failed_command_is_reported_and_the_tip_is_emptied_first(self):
        lh = handler()
        a, d = lh.load_labware(PLATE, 4), lh.load_labware(PLATE, 5)
        aspirates = spy(lh.p300_multi, "aspirate")
        self._flaky_dispense(lh, ProtocolCommandFailedError(message="simulated fault"))
        failed = lh.transfer([100, 100], [a["A1"], a["B1"]], [d["A1"], d["B1"]], new_tip="once")
        self.assertEqual([f[3] for f in failed], [0])
        self.assertTrue(failed[0][4].startswith("pipette_error: "), failed[0][4])
        self.assertIn("simulated fault", failed[0][4])
        # The second aspiration started with a fresh tip holding only its 20 ul air
        # gap, not with A1's 120 ul still in it.
        self.assertEqual([c["volume_before"] for c in aspirates], [20.0, 20.0])
        self.assertFalse(lh.p300_multi.has_tip)

    def test_unexpected_error_stops_the_run_with_the_tip_dropped(self):
        lh = handler()
        a, d = lh.load_labware(PLATE, 4), lh.load_labware(PLATE, 5)
        self._flaky_dispense(lh, RuntimeError("connection lost"))
        with self.assertRaises(RuntimeError):
            lh.transfer([100, 100], [a["A1"], a["B1"]], [d["A1"], d["B1"]])
        self.assertFalse(lh.p300_multi.has_tip)


class TestFormerCrashes(unittest.TestCase):
    def test_touch_tip_on_a_reservoir_is_skipped_not_fatal(self):
        lh = handler()
        r, d = lh.load_labware(RESERVOIR, 4), lh.load_labware(PLATE, 5)
        self.assertEqual(lh.transfer([50], [r["A1"]], [d["A1"]], touch_tip=True), [])

    def test_pooling_a_column_into_a_round_well(self):
        lh = handler()
        a, d = lh.load_labware(PLATE, 4), lh.load_labware(PLATE, 5)
        self.assertEqual(lh.pool(25, a.columns()[0], d["A1"]), [])

    def test_several_aliquots_from_one_well_to_the_trash(self):
        lh = handler()
        a = lh.load_labware(PLATE, 4)
        self.assertEqual(lh.transfer([50, 50], [a["A1"], a["A1"]], [lh.trash, lh.trash]), [])

    def test_a_volume_at_the_minimum_is_accepted(self):
        lh = handler()
        a, d = lh.load_labware(PLATE, 4), lh.load_labware(PLATE, 5)
        self.assertEqual(lh.transfer([lh.p20.min_volume], [a["A1"]], [d["A1"]]), [])


class TestModules(unittest.TestCase):
    def test_shake_without_wait_starts_once_and_stops_later(self):
        lh = handler()
        lh.shaker_module = MagicMock()
        stopped = threading.Event()
        lh.shaker_module.deactivate_shaker.side_effect = stopped.set
        lh.shake(500, 0.05, wait=False)
        lh.shaker_module.set_and_wait_for_shake_speed.assert_called_once_with(500)
        self.assertTrue(stopped.wait(2))

    def test_set_temperature_without_wait_does_not_block(self):
        lh = handler()
        lh.temperature_module = MagicMock()
        lh.set_temperature(4, wait=False)
        lh.temperature_module.start_set_temperature.assert_called_once_with(4)
        lh.temperature_module.set_temperature.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class TestRunLog(unittest.TestCase):
    def test_one_file_per_handler_with_everything_it_logged(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/run.log"
            with handler(log_file=path) as lh:
                a, d = lh.load_labware(PLATE, 4), lh.load_labware(PLATE, 5)
                lh.transfer([50], [a["A1"]], [d["A1"]])
                text = lh.run_log_text()
            self.assertIn("Loaded labware", text)
            self.assertIn("Transfer called", text)
            # Closed: no handler left on the logger, file complete.
            self.assertEqual(lh._log_handler, None)
            self.assertIn("Run log closed", open(path).read())
            # Another handler's lines do not leak into this file.
            other = handler()
            other.log.info("not for the first file")
            self.assertNotIn("not for the first file", open(path).read())

    def test_import_configures_no_logging(self):
        import logging

        self.assertEqual(logging.getLogger("ot_handler").handlers, [])
        self.assertEqual(handler().run_log_text(), "")
