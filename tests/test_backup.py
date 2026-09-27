import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import backup


class BackupTests(unittest.TestCase):
    def test_local_archive_contains_keys_and_runtime_state_but_not_build_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            backup_root = Path(temp_dir) / "archives"
            (root / "keys").mkdir(parents=True)
            (root / "target").mkdir()
            (root / ".cache").mkdir()
            (root / "autonomous").mkdir()
            (root / "keys" / "signing.pem").write_text("private-key", encoding="utf-8")
            (root / "research_store.json").write_text('{"records":[]}', encoding="utf-8")
            (root / "target" / "build.bin").write_bytes(b"build")
            (root / ".cache" / "cache.bin").write_bytes(b"cache")
            (root / "autonomous" / "supervisor.lock").write_bytes(b"")

            config_path = Path(temp_dir) / "config.json"
            with patch.object(backup, "config_path", return_value=config_path):
                backup.initialize(root, backup_root)
                config = {
                    "project_root": str(root),
                    "backup_root": str(backup_root),
                    "retention": 30,
                }
                archive_path = backup.create_backup(config)

                with zipfile.ZipFile(archive_path) as archive_file:
                    manifest = backup.verify_archive(archive_file)
                    names = set(archive_file.namelist())
                self.assertIn("keys/signing.pem", names)
                self.assertIn("research_store.json", names)
                self.assertNotIn("target/build.bin", names)
                self.assertNotIn(".cache/cache.bin", names)
                self.assertNotIn("autonomous/supervisor.lock", names)
                self.assertEqual(manifest["file_count"], 2)

                restored_archive, restored_files = backup.restore_test(config)
                self.assertEqual(restored_archive, archive_path)
                self.assertEqual(restored_files, 2)

    def test_init_rejects_backup_folder_inside_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            root.mkdir()
            with patch.object(
                backup, "config_path", return_value=Path(temp_dir) / "config.json"
            ):
                with self.assertRaisesRegex(RuntimeError, "outside the project tree"):
                    backup.initialize(root, root / "backups")

    def test_manifest_rejects_zip_slip_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "bad.zip"
            manifest = {
                "format_version": 1,
                "file_count": 1,
                "files": [{"path": "../outside.txt", "size": 0, "sha256": "e3b0c442"}],
            }
            with zipfile.ZipFile(archive_path, "w") as archive_file:
                archive_file.writestr(backup.MANIFEST_NAME, json.dumps(manifest))
            with zipfile.ZipFile(archive_path) as archive_file:
                with self.assertRaisesRegex(RuntimeError, "Unsafe archive path"):
                    backup.verify_archive(archive_file)


if __name__ == "__main__":
    unittest.main()
