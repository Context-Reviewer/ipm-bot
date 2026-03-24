from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.artifacts.il2cpp_workspace import (
    GLOBAL_METADATA_MEMBER_PATH,
    LIBIL2CPP_MEMBER_PATH,
    run_il2cpp_workspace,
)
from ipm_bot.artifacts.shared import sha256_bytes


class Il2CppWorkspaceTests(unittest.TestCase):
    def test_run_il2cpp_workspace_stages_required_files_from_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot_dir = _build_snapshot_fixture(
                root,
                metadata_payload=b"metadata-bytes",
                binary_payload=b"libil2cpp-bytes",
            )

            workspace_dir = run_il2cpp_workspace(snapshot_dir, output_root=root / "artifacts")

            self.assertTrue((workspace_dir / "workspace" / "global-metadata.dat").is_file())
            self.assertTrue((workspace_dir / "workspace" / "libil2cpp.so").is_file())
            self.assertTrue((workspace_dir / "manifest.json").is_file())
            self.assertTrue((workspace_dir / "summary.txt").is_file())

    def test_run_il2cpp_workspace_fails_when_metadata_member_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot_dir = _build_snapshot_fixture(
                root,
                metadata_payload=None,
                binary_payload=b"libil2cpp-bytes",
            )

            with self.assertRaises(FileNotFoundError) as context:
                run_il2cpp_workspace(snapshot_dir, output_root=root / "artifacts")

            self.assertIn(GLOBAL_METADATA_MEMBER_PATH, str(context.exception))

    def test_run_il2cpp_workspace_fails_when_libil2cpp_member_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot_dir = _build_snapshot_fixture(
                root,
                metadata_payload=b"metadata-bytes",
                binary_payload=None,
            )

            with self.assertRaises(FileNotFoundError) as context:
                run_il2cpp_workspace(snapshot_dir, output_root=root / "artifacts")

            self.assertIn(LIBIL2CPP_MEMBER_PATH, str(context.exception))

    def test_run_il2cpp_workspace_manifest_has_expected_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_payload = b"metadata-bytes"
            binary_payload = b"libil2cpp-bytes"
            snapshot_dir = _build_snapshot_fixture(
                root,
                metadata_payload=metadata_payload,
                binary_payload=binary_payload,
            )

            workspace_dir = run_il2cpp_workspace(snapshot_dir, output_root=root / "artifacts")
            manifest = json.loads((workspace_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["command_name"], "il2cpp-workspace")
            self.assertEqual(manifest["package_name"], "com.TironiumTech.IdlePlanetMiner")
            self.assertEqual(manifest["architecture"], "arm64-v8a")
            self.assertEqual(
                manifest["staged_files"]["global_metadata"]["sha256"],
                sha256_bytes(metadata_payload),
            )
            self.assertEqual(
                manifest["staged_files"]["global_metadata"]["size_bytes"],
                len(metadata_payload),
            )
            self.assertEqual(
                manifest["staged_files"]["libil2cpp"]["sha256"],
                sha256_bytes(binary_payload),
            )
            self.assertEqual(
                manifest["staged_files"]["libil2cpp"]["size_bytes"],
                len(binary_payload),
            )


def _build_snapshot_fixture(
    root: Path,
    *,
    metadata_payload: bytes | None,
    binary_payload: bytes | None,
) -> Path:
    snapshot_dir = root / "snapshots" / "fixture_snapshot"
    installed_package_dir = snapshot_dir / "context" / "installed_package"
    installed_package_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "manifest.json").write_text(
        json.dumps({"package_name": "com.TironiumTech.IdlePlanetMiner"}, indent=2),
        encoding="utf-8",
    )

    base_apk_path = installed_package_dir / "base.apk"
    split_apk_path = installed_package_dir / "split_config.arm64_v8a.apk"
    with zipfile.ZipFile(base_apk_path, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"manifest")
        if metadata_payload is not None:
            archive.writestr(GLOBAL_METADATA_MEMBER_PATH, metadata_payload)
    with zipfile.ZipFile(split_apk_path, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"manifest")
        if binary_payload is not None:
            archive.writestr(LIBIL2CPP_MEMBER_PATH, binary_payload)
    return snapshot_dir
