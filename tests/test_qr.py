from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from simple_qr import QR_SIZE, qr_matrix, qr_svg


class QrCodeTests(unittest.TestCase):
    def test_matrix_has_expected_version_three_shape_and_finders(self):
        matrix = qr_matrix("http://192.168.1.50:8000/")

        self.assertEqual(len(matrix), QR_SIZE)
        self.assertTrue(all(len(row) == QR_SIZE for row in matrix))
        self.assertTrue(all(type(module) is bool for row in matrix for module in row))
        for x, y in ((3, 3), (QR_SIZE - 4, 3), (3, QR_SIZE - 4)):
            self.assertTrue(matrix[y][x])
            self.assertFalse(matrix[y - 2][x])
            self.assertTrue(matrix[y - 3][x])

    def test_svg_is_inline_and_accessible(self):
        svg = qr_svg("http://127.0.0.1:8000/")

        self.assertIn('<svg class="qr-code"', svg)
        self.assertIn('viewBox="0 0 37 37"', svg)
        self.assertIn('aria-label="QR code for connection URL"', svg)
        self.assertNotIn("<script", svg)
        self.assertNotIn("http://127.0.0.1", svg)

    def test_payload_larger_than_version_capacity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "capacity"):
            qr_matrix("x" * 54)


if __name__ == "__main__":
    unittest.main()
