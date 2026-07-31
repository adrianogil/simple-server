import os
from pathlib import Path
import sys
import tempfile
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


class PathContainmentTests(unittest.TestCase):
    def test_accepts_a_plain_child_name(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = simpleserver.resolve_contained_child(
                directory,
                "safe file.txt",
            )

            self.assertEqual(
                destination,
                os.path.join(os.path.realpath(directory), "safe file.txt"),
            )

    def test_rejects_traversal_absolute_and_nested_names(self):
        invalid_names = (
            "",
            ".",
            "..",
            "../outside.txt",
            "..%2Foutside.txt",
            "/absolute.txt",
            "C:drive-relative.txt",
            "nested/file.txt",
            "nested\\file.txt",
            "null\x00byte.txt",
        )
        with tempfile.TemporaryDirectory() as directory:
            for name in invalid_names:
                with self.subTest(name=name):
                    with self.assertRaises(ValueError):
                        simpleserver.resolve_contained_child(directory, name)

    def test_rejects_a_symlink_that_resolves_outside_root(self):
        with tempfile.TemporaryDirectory() as parent:
            served = Path(parent, "served")
            served.mkdir()
            outside = Path(parent, "outside.txt")
            outside.write_text("outside", encoding="utf-8")
            link = served / "escape.txt"
            try:
                link.symlink_to(outside)
            except OSError as error:
                self.skipTest("symlinks are unavailable: %s" % error)

            with self.assertRaises(ValueError):
                simpleserver.resolve_contained_child(served, link.name)

    def test_rejects_a_parent_symlink_that_resolves_outside_root(self):
        with tempfile.TemporaryDirectory() as parent:
            served = Path(parent, "served")
            served.mkdir()
            outside = Path(parent, "outside")
            outside.mkdir()
            link = served / "escape"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest("symlinks are unavailable: %s" % error)

            with self.assertRaises(ValueError):
                simpleserver.resolve_contained_child(
                    served,
                    "new-file.txt",
                    link,
                )


if __name__ == "__main__":
    unittest.main()
