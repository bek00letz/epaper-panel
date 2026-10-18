"""Unit and integration tests for identity-based category & sub-item locking."""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon", "app"))

import render.stripmeta as sm
import render.subitems as si


class TestStripMeta(unittest.TestCase):
    def test_v2_encode_decode(self):
        meta = sm.StripMeta(
            offsets=[0, 2, 5],
            sizes=[2, 3, 1],
            pill_widths=[100, 110, 120],
            cat_ids=[0x11112222, 0x33334444, 0x55556666],
            sub_ids=[0xAAAA0001, 0xAAAA0002, 0xBBBB0001, 0xBBBB0002, 0xBBBB0003, 0xCCCC0001],
            quiet=False,
            rotate_seconds=15,
            content_hash=0x1234,
            interrupt=False
        )
        raw = sm.encode(meta)
        decoded = sm.decode(raw, 6)
        self.assertTrue(decoded.has_identity)
        self.assertEqual(decoded.cat_ids, meta.cat_ids)
        self.assertEqual(decoded.sub_ids, meta.sub_ids)
        self.assertEqual(decoded.rotate_seconds, 15)
        self.assertEqual(decoded.page_count, 6)

    def test_v1_backward_compatibility(self):
        # Construct a synthetic v1 metadata stream
        raw_v1 = bytearray([0xA5, 1, 2,  0, 1, 100,  1, 2, 110,  0x00, 0, 30, 0xAB, 0xCD])
        decoded_v1 = sm.decode(bytes(raw_v1), 3)
        self.assertFalse(decoded_v1.has_identity)
        self.assertEqual(decoded_v1.offsets, [0, 1])
        self.assertEqual(decoded_v1.sizes, [1, 2])
        self.assertEqual(decoded_v1.rotate_seconds, 30)

    def test_crc8_integrity(self):
        meta = sm.StripMeta(
            offsets=[0],
            sizes=[1],
            pill_widths=[110],
            cat_ids=[0x12345678],
            sub_ids=[0x9ABCDEF0]
        )
        raw = bytearray(sm.encode(meta))
        # Corrupt CRC byte
        raw[-1] ^= 0xFF
        decoded = sm.decode(bytes(raw), 1)
        # Should gracefully drop identity rather than crash
        self.assertFalse(decoded.has_identity)


class TestSubitemIdentities(unittest.TestCase):
    def test_sports_subitem_inspection(self):
        page_def = {
            'elements': [
                {'id': 'e1', 'type': 'sports_match', 'x': 0, 'y': 0}
            ]
        }
        page_vals = {
            0: [
                {'id': 'espn_401547890', 'home_team': 'Arsenal', 'away_team': 'Chelsea'},
                {'id': 'espn_401547891', 'home_team': 'Liverpool', 'away_team': 'Man City'}
            ]
        }
        sub_count, sub_type, sub_keys, items, feed_ent = si.inspect_category_subitems(page_def, page_vals)
        self.assertEqual(sub_count, 2)
        self.assertEqual(sub_type, 'sports')
        self.assertEqual(sub_keys, ['espn_401547890', 'espn_401547891'])

    def test_flight_tracker_inspection(self):
        page_def = {
            'elements': [
                {'id': 'f1', 'type': 'flight_tracker', 'x': 0, 'y': 0}
            ]
        }
        page_vals = {
            0: [
                {'icao24': 'abc123', 'callsign': 'UAL101'},
                {'icao24': 'def456', 'callsign': 'DAL202'}
            ]
        }
        sub_count, sub_type, sub_keys, items, feed_ent = si.inspect_category_subitems(page_def, page_vals)
        self.assertEqual(sub_count, 2)
        self.assertEqual(sub_type, 'flight')
        self.assertEqual(sub_keys, ['abc123', 'def456'])

    def test_intra_category_collision_disambiguation(self):
        page_def = {
            'elements': [
                {'id': 'e1', 'type': 'sports_match', 'x': 0, 'y': 0}
            ]
        }
        # Two duplicate items
        page_vals = {
            0: [
                {'id': 'same_id'},
                {'id': 'same_id'}
            ]
        }
        sub_count, sub_type, sub_keys, items, feed_ent = si.inspect_category_subitems(page_def, page_vals)
        self.assertEqual(sub_count, 2)
        self.assertEqual(sub_keys[0], 'same_id')
        self.assertEqual(sub_keys[1], 'same_id#2')

    def test_category_shift_simulation(self):
        """Simulate real user incident: Sports is category 8 with 3 matches.
        User pins match 1. A new category is inserted at index 3.
        Sports shifts from category 8 to 9.
        Verify resolution accurately recovers category 9 and sub-item 1."""
        orig_cats = [f'cat_{i}' for i in range(8)] + ['sports']
        orig_sub_keys = [['0'] for _ in range(8)] + [['espn_1', 'espn_2', 'espn_3']]
        orig_cat_ids, orig_sub_ids = si.compute_identities(orig_cats, orig_sub_keys)

        pinned_cat_id = orig_cat_ids[8]
        pinned_sub_id = orig_sub_ids[8 + 1]  # match 1 (espn_2)

        # New category inserted at index 3
        new_cats = orig_cats[:3] + ['transit'] + orig_cats[3:]
        new_sub_keys = orig_sub_keys[:3] + [['0']] + orig_sub_keys[3:]
        new_cat_ids, new_sub_ids = si.compute_identities(new_cats, new_sub_keys)

        self.assertEqual(new_cats.index('sports'), 9)

        # Identity resolution
        found_page = new_sub_ids.index(pinned_sub_id)
        new_sizes = [len(keys) for keys in new_sub_keys]
        new_offsets = []
        run_off = 0
        for sz in new_sizes:
            new_offsets.append(run_off)
            run_off += sz

        found_cat = -1
        found_sub = -1
        for c in range(len(new_cats)):
            off = new_offsets[c]
            sz = new_sizes[c]
            if off <= found_page < off + sz:
                found_cat = c
                found_sub = found_page - off
                break

        self.assertEqual(found_cat, 9)
        self.assertEqual(found_sub, 1)


if __name__ == "__main__":
    unittest.main()
