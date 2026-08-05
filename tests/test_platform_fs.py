import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import platform_fs


class PlatformFilesystemTests(unittest.TestCase):
    def test_atomic_replace_and_create_are_collision_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            replaced = root / "replace.txt"
            replaced.write_bytes(b"before")
            original_mode = stat.S_IMODE(replaced.stat().st_mode)
            platform_fs.atomic_replace(replaced, b"after", preserve_existing_mode=True)
            self.assertEqual(replaced.read_bytes(), b"after")
            if not platform_fs.IS_WINDOWS:
                self.assertEqual(stat.S_IMODE(replaced.stat().st_mode), original_mode)

            created = root / "created.json"
            platform_fs.atomic_create(created, b"{}\n")
            self.assertEqual(created.read_bytes(), b"{}\n")
            with self.assertRaises(FileExistsError):
                platform_fs.atomic_create(created, b"different\n")
            self.assertEqual(created.read_bytes(), b"{}\n")
            self.assertEqual(list(root.glob(".*.*")), [])

    def test_windows_branch_does_not_require_fchmod_or_directory_fsync(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "state.json"
            target.write_bytes(b"old\n")
            with (
                mock.patch.object(platform_fs, "IS_WINDOWS", True),
                mock.patch.object(
                    platform_fs.os,
                    "fchmod",
                    create=True,
                    side_effect=AssertionError("fchmod must not run on Windows"),
                ),
            ):
                platform_fs.atomic_replace(target, b"new\n", preserve_existing_mode=True)
                platform_fs.atomic_create(root / "new.json", b"{}\n")
                self.assertTrue(platform_fs.mode_matches(target, 0o600))
            self.assertEqual(target.read_bytes(), b"new\n")

        with (
            mock.patch.object(platform_fs, "IS_WINDOWS", True),
            mock.patch.object(platform_fs.os, "open", side_effect=AssertionError("directory open")),
        ):
            platform_fs.sync_directory(Path("ignored"))

    def test_reparse_points_are_treated_as_links(self):
        flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        candidate = mock.Mock()
        candidate.is_symlink.return_value = False
        candidate.lstat.return_value = SimpleNamespace(st_file_attributes=flag)
        with mock.patch.object(stat, "FILE_ATTRIBUTE_REPARSE_POINT", flag, create=True):
            self.assertTrue(platform_fs.is_link_like(candidate))

    def test_link_safe_path_rejects_nested_link_like_component(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "safe" / "junction" / "file.txt"
            with mock.patch.object(
                platform_fs,
                "is_link_like",
                side_effect=lambda path: Path(path).name == "junction",
            ):
                self.assertFalse(platform_fs.is_link_safe_beneath(nested, root))
                self.assertTrue(platform_fs.is_link_safe_beneath(root / "safe" / "file.txt", root))
            self.assertFalse(platform_fs.is_link_safe_beneath(root.parent / "outside.txt", root))

    @unittest.skipIf(os.name == "nt", "Windows symlink creation is privilege-dependent")
    def test_symlink_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.write_text("outside")
            linked = root / "linked"
            linked.symlink_to(outside)
            self.assertTrue(platform_fs.is_link_like(linked))
            with self.assertRaises(OSError):
                platform_fs.atomic_replace(linked, b"changed")
            self.assertEqual(outside.read_text(), "outside")


if __name__ == "__main__":
    unittest.main()
