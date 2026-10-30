"""Unit tests for the .epf binary frame protocol."""
import unittest
from PIL import Image, ImageDraw
import support  # noqa: F401
from render import epf


class TestEpfProtocol(unittest.TestCase):
    def setUp(self):
        self.width = 792
        self.height = 272
        self.stride = 99
        self.bytes_per_page = self.stride * self.height

        # Create 3 synthetic 1-bit test pages
        self.pages = []
        for i in range(3):
            im = Image.new("1", (self.width, self.height), 1)
            draw = ImageDraw.Draw(im)
            draw.rectangle([10 * i, 10 * i, 100 + 10 * i, 100 + 10 * i], fill=0)
            self.pages.append(im)

        self.cat_ids = [0x11223344, 0x55667788]
        self.cat_offsets = [0, 2]
        self.cat_sizes = [2, 1]
        self.cat_pill_widths = [120, 140]
        self.sub_ids = [0xA1B2C3D4, 0xE5F60718, 0x99887766]

    def test_roundtrip_encode_decode(self):
        encoded = epf.encode_epf(
            pages=self.pages,
            cat_ids=self.cat_ids,
            cat_offsets=self.cat_offsets,
            cat_sizes=self.cat_sizes,
            cat_pill_widths=self.cat_pill_widths,
            sub_ids=self.sub_ids,
            display_model="crowpanel_579",
            width=self.width,
            height=self.height,
            rotate_sec=15,
            quiet_hours=False,
            alert_interrupt=True,
            content_hash=0x123456789ABCDEF0,
        )

        # Expected size: Header (64) + 2 Cats (32) + 3 Pages (48) + 3*26928 (80784) + CRC-32 (4) = 80932 bytes
        expected_size = 64 + (2 * 16) + (3 * 16) + (3 * self.bytes_per_page) + 4
        self.assertEqual(len(encoded), expected_size)

        stream = epf.decode_epf(encoded)
        self.assertEqual(stream.header.magic, epf.MAGIC)
        self.assertEqual(stream.header.version, 3)
        self.assertEqual(stream.header.model_id, 0x0579)
        self.assertEqual(stream.header.width, 792)
        self.assertEqual(stream.header.height, 272)
        self.assertEqual(stream.header.stride, 99)
        self.assertEqual(stream.header.page_count, 3)
        self.assertEqual(stream.header.cat_count, 2)
        self.assertEqual(stream.header.rotate_sec, 15)
        self.assertTrue(stream.header.flags & epf.FLAG_ALERT_INTERRUPT)
        self.assertFalse(stream.header.flags & epf.FLAG_QUIET_HOURS)
        self.assertEqual(stream.header.content_hash, 0x123456789ABCDEF0)

        # Verify categories
        self.assertEqual(len(stream.categories), 2)
        self.assertEqual(stream.categories[0].cat_id, 0x11223344)
        self.assertEqual(stream.categories[0].offset_page, 0)
        self.assertEqual(stream.categories[0].page_count, 2)
        self.assertEqual(stream.categories[0].pill_width, 120)

        self.assertEqual(stream.categories[1].cat_id, 0x55667788)
        self.assertEqual(stream.categories[1].offset_page, 2)
        self.assertEqual(stream.categories[1].page_count, 1)
        self.assertEqual(stream.categories[1].pill_width, 140)

        # Verify pages
        self.assertEqual(len(stream.pages), 3)
        self.assertEqual(stream.pages[0].sub_id, 0xA1B2C3D4)
        self.assertEqual(stream.pages[0].cat_id, 0x11223344)
        self.assertEqual(stream.pages[0].cat_index, 0)
        self.assertEqual(stream.pages[0].sub_index, 0)

        self.assertEqual(stream.pages[1].sub_id, 0xE5F60718)
        self.assertEqual(stream.pages[1].cat_id, 0x11223344)
        self.assertEqual(stream.pages[1].cat_index, 0)
        self.assertEqual(stream.pages[1].sub_index, 1)

        self.assertEqual(stream.pages[2].sub_id, 0x99887766)
        self.assertEqual(stream.pages[2].cat_id, 0x55667788)
        self.assertEqual(stream.pages[2].cat_index, 1)
        self.assertEqual(stream.pages[2].sub_index, 0)

        # Verify page slicing and image extraction
        for i, original_im in enumerate(self.pages):
            slice_bytes = stream.page_slice(i)
            # Physical scanlines on crowpanel_579 are FLIP_LEFT_RIGHT packed for 80µs memcpy
            expected_hw = original_im.transpose(Image.Transpose.FLIP_LEFT_RIGHT).tobytes()
            self.assertEqual(slice_bytes, expected_hw)
            # extract_page_image reconstructs the original upright PIL image
            reconstructed_im = epf.extract_page_image(stream, i)
            self.assertEqual(reconstructed_im.tobytes(), original_im.tobytes())

    def test_crc_corruption_detection(self):
        encoded = epf.encode_epf(
            pages=self.pages,
            cat_ids=self.cat_ids,
            cat_offsets=self.cat_offsets,
            cat_sizes=self.cat_sizes,
            cat_pill_widths=self.cat_pill_widths,
            sub_ids=self.sub_ids,
            content_hash=0x42,
        )

        # Corrupt one byte in the scanlines
        corrupted = bytearray(encoded)
        corrupted[200] ^= 0xFF

        with self.assertRaises(ValueError) as ctx:
            epf.decode_epf(bytes(corrupted))
        self.assertIn("CRC-32 checksum mismatch", str(ctx.exception))

    def test_invalid_magic_detection(self):
        encoded = bytearray(epf.encode_epf(
            pages=self.pages,
            cat_ids=self.cat_ids,
            cat_offsets=self.cat_offsets,
            cat_sizes=self.cat_sizes,
            cat_pill_widths=self.cat_pill_widths,
            sub_ids=self.sub_ids,
        ))
        encoded[0:4] = b"XXXX"
        # Recompute CRC over corrupted body so magic check is tested
        import zlib, struct
        crc = zlib.crc32(encoded[:-4]) & 0xFFFFFFFF
        encoded[-4:] = struct.pack(">I", crc)

        with self.assertRaises(ValueError) as ctx:
            epf.decode_epf(bytes(encoded))
        self.assertIn("Invalid magic", str(ctx.exception))

    def test_extract_page_epf(self):
        encoded = epf.encode_epf(
            pages=self.pages,
            cat_ids=self.cat_ids,
            cat_offsets=self.cat_offsets,
            cat_sizes=self.cat_sizes,
            cat_pill_widths=self.cat_pill_widths,
            sub_ids=self.sub_ids,
            rotate_sec=20,
        )

        # Extract page index 1 (part of category 0)
        single_raw = epf.extract_page_epf(encoded, 1)
        single_stream = epf.decode_epf(single_raw)

        self.assertEqual(single_stream.header.page_count, 1)
        self.assertEqual(single_stream.header.cat_count, 1)
        self.assertEqual(single_stream.header.rotate_sec, 20)
        self.assertEqual(single_stream.pages[0].sub_id, self.sub_ids[1])
        self.assertEqual(single_stream.categories[0].cat_id, self.cat_ids[0])
        self.assertEqual(epf.extract_page_image(single_stream, 0).tobytes(), self.pages[1].tobytes())

    def test_slice_out_of_bounds(self):
        encoded = epf.encode_epf(
            pages=self.pages,
            cat_ids=self.cat_ids,
            cat_offsets=self.cat_offsets,
            cat_sizes=self.cat_sizes,
            cat_pill_widths=self.cat_pill_widths,
            sub_ids=self.sub_ids,
        )
        stream = epf.decode_epf(encoded)
        with self.assertRaises(IndexError):
            stream.page_slice(99)
        with self.assertRaises(IndexError):
            epf.extract_page_epf(encoded, 99)

    def test_model_skus(self):
        models = [("crowpanel_579", 0x0579), ("crowpanel_420", 0x0420), ("crowpanel_750", 0x0750)]
        for name, expected_id in models:
            enc = epf.encode_epf(
                pages=self.pages[:1],
                cat_ids=[0x1],
                cat_offsets=[0],
                cat_sizes=[1],
                cat_pill_widths=[100],
                sub_ids=[0x2],
                display_model=name,
            )
            dec = epf.decode_epf(enc)
            self.assertEqual(dec.header.model_id, expected_id)

    def test_orientation_180_flag(self):
        enc = epf.encode_epf(
            pages=self.pages[:1],
            cat_ids=[0x1],
            cat_offsets=[0],
            cat_sizes=[1],
            cat_pill_widths=[100],
            sub_ids=[0x2],
            orientation_180=True,
        )
        dec = epf.decode_epf(enc)
        self.assertTrue(dec.header.flags & epf.FLAG_ORIENTATION_180)

        single = epf.extract_page_epf(enc, 0)
        dec_single = epf.decode_epf(single)
        self.assertTrue(dec_single.header.flags & epf.FLAG_ORIENTATION_180)

    def test_deflated_pages_round_trip(self):
        # For firmware that asked (deflate=1): each page raw deflate, its length in its page
        # record, and the file exactly the size the fit rule counts (file_size).
        args = dict(cat_ids=[1, 2], cat_offsets=[0, 1], cat_sizes=[1, len(self.pages) - 1],
                    cat_pill_widths=[100, 100], sub_ids=list(range(len(self.pages))))
        plain = epf.encode_epf(pages=self.pages, **args)
        enc = epf.encode_epf(pages=self.pages, deflate=True, **args)
        dec = epf.decode_epf(enc)
        self.assertTrue(dec.header.flags & epf.FLAG_DEFLATE)
        self.assertLess(len(enc), len(plain))
        for i in range(len(self.pages)):
            self.assertEqual(dec.page_slice(i), epf.decode_epf(plain).page_slice(i), "the same pixels")
        self.assertEqual(len(enc), epf.file_size(2, [length for _, length in dec.spans]))
        # One page of it stays deflated, and still reads.
        single = epf.decode_epf(epf.extract_page_epf(enc, 1))
        self.assertTrue(single.header.flags & epf.FLAG_DEFLATE)
        self.assertEqual(single.page_slice(0), dec.page_slice(1))

    def test_a_deflated_page_that_lies_is_refused(self):
        enc = bytearray(epf.encode_epf(pages=self.pages[:1], cat_ids=[1], cat_offsets=[0], cat_sizes=[1],
                                       cat_pill_widths=[100], sub_ids=[2], deflate=True))
        rec = epf.HEADER_SIZE + epf.CAT_RECORD_SIZE + 12
        enc[rec + 3] += 1
        body = bytes(enc[:-4])
        import zlib
        enc[-4:] = (zlib.crc32(body) & 0xFFFFFFFF).to_bytes(4, "big")
        with self.assertRaises(ValueError):
            epf.decode_epf(bytes(enc))


if __name__ == "__main__":
    unittest.main()

