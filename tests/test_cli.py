from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

original_argv = sys.argv
try:
    sys.argv = [str(SRC_DIR / "simpleserver.py")]
    import simpleserver
finally:
    sys.argv = original_argv


class CommandLineTests(unittest.TestCase):
    def test_default_bind_address_is_externally_accessible(self):
        args, password, local_only = simpleserver.parse_args([])

        self.assertEqual(args, [])
        self.assertIsNone(password)
        self.assertFalse(local_only)
        self.assertEqual(
            simpleserver.resolve_bind_address(args, local_only),
            ("0.0.0.0", 8000),
        )

    def test_local_flag_binds_to_loopback(self):
        args, password, local_only = simpleserver.parse_args(
            ["9000", "/tmp/shared", "--local"],
        )

        self.assertEqual(args, ["9000", "/tmp/shared"])
        self.assertIsNone(password)
        self.assertTrue(local_only)
        self.assertEqual(
            simpleserver.resolve_bind_address(args, local_only),
            ("127.0.0.1", 9000),
        )

    def test_local_flag_overrides_explicit_interface(self):
        args, password, local_only = simpleserver.parse_args(
            ["192.0.2.10:9001", "--password", "secret", "--local"],
        )

        self.assertEqual(args, ["192.0.2.10:9001"])
        self.assertEqual(password, "secret")
        self.assertTrue(local_only)
        self.assertEqual(
            simpleserver.resolve_bind_address(args, local_only),
            ("127.0.0.1", 9001),
        )

    def test_explicit_interface_is_preserved_without_local_flag(self):
        args, password, local_only = simpleserver.parse_args(
            ["192.0.2.10:9002"],
        )

        self.assertEqual(args, ["192.0.2.10:9002"])
        self.assertIsNone(password)
        self.assertFalse(local_only)
        self.assertEqual(
            simpleserver.resolve_bind_address(args, local_only),
            ("192.0.2.10", 9002),
        )


if __name__ == "__main__":
    unittest.main()
