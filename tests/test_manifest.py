# -*- coding: utf-8 -*-
"""Manifest und Pruefbefehl.

Der Kern: Ein Manifest, das nur eine Version nennt, merkt zwei Driftarten nicht —
eine zu alte Kopie und eine lokal veraenderte. Beide werden hier geprueft, und
beide muessen einen Exitcode ungleich null erzeugen.
"""
import json

import pytest

from comas.manifest import (
    KIND_DRIFTED,
    KIND_EXTRA,
    KIND_MISSING,
    KIND_MODIFIED,
    KIND_OUTDATED,
    MANIFEST_FILENAME,
    SCHEMA,
    ManifestError,
    build_manifest,
    check_all,
    check_manifest,
    file_digest,
    find_manifests,
    iter_module_files,
    package_dir,
    read_version,
    vendor,
    version_key,
)


def make_source(root, version="0.1.0"):
    """Ein Miniatur-COMAS als Quelle."""
    source = root / "quelle" / "comas"
    (source / "adapters").mkdir(parents=True)
    (source / "__init__.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8"
    )
    (source / "spawn.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (source / "adapters" / "claude.py").write_text("FLAGS = []\n", encoding="utf-8")
    return source


def copy_tree(source, target):
    import shutil

    shutil.copytree(source, target)
    return target


def kinds(report):
    return [finding.kind for finding in report.findings]


class TestHelpers:
    def test_iter_module_files_is_sorted_and_relative(self, tmp_path):
        source = make_source(tmp_path)
        assert iter_module_files(source) == [
            "__init__.py",
            "adapters/claude.py",
            "spawn.py",
        ]

    def test_pycache_is_skipped(self, tmp_path):
        source = make_source(tmp_path)
        (source / "__pycache__").mkdir()
        (source / "__pycache__" / "x.py").write_text("x", encoding="utf-8")
        assert "__pycache__/x.py" not in iter_module_files(source)

    def test_missing_source_raises(self, tmp_path):
        with pytest.raises(ManifestError, match="Quellverzeichnis"):
            iter_module_files(tmp_path / "nichts")

    def test_digest_ignores_line_endings(self, tmp_path):
        unix = tmp_path / "a.py"
        windows = tmp_path / "b.py"
        unix.write_bytes(b"eins\nzwei\n")
        windows.write_bytes(b"eins\r\nzwei\r\n")
        assert file_digest(unix) == file_digest(windows)

    def test_digest_notices_real_changes(self, tmp_path):
        path = tmp_path / "a.py"
        path.write_bytes(b"eins\n")
        first = file_digest(path)
        path.write_bytes(b"zwei\n")
        assert file_digest(path) != first

    def test_read_version_without_import(self, tmp_path):
        assert read_version(make_source(tmp_path, "1.2.3")) == "1.2.3"
        assert read_version(tmp_path / "nichts") is None

    def test_version_key_orders_numerically(self):
        assert version_key("0.10.0") > version_key("0.9.0")
        assert version_key("1.0.0") > version_key("0.99.99")
        assert version_key("0.1.0") == version_key("0.1.0")

    def test_package_dir_points_at_the_real_module(self):
        assert (package_dir() / "spawn.py").is_file()


class TestBuildAndRead:
    def test_manifest_shape(self, tmp_path):
        source = make_source(tmp_path)
        manifest = build_manifest(vendored_path="third_party/comas", source_dir=source)
        assert manifest["schema"] == SCHEMA
        assert manifest["module"] == "comas"
        assert manifest["version"] == "0.1.0"
        assert manifest["path"] == "third_party/comas"
        assert set(manifest["files"]) == {
            "__init__.py",
            "adapters/claude.py",
            "spawn.py",
        }
        assert all(digest.startswith("sha256:") for digest in manifest["files"].values())

    def test_vendor_writes_the_file(self, tmp_path):
        source = make_source(tmp_path)
        target = tmp_path / "konsument" / MANIFEST_FILENAME
        vendor(target, "vendor/comas", source_dir=source)
        assert json.loads(target.read_text(encoding="utf-8"))["path"] == "vendor/comas"

    def test_broken_manifest_is_reported(self, tmp_path):
        path = tmp_path / MANIFEST_FILENAME
        path.write_text("{kaputt", encoding="utf-8")
        with pytest.raises(ManifestError, match="JSON"):
            check_manifest(path)

    def test_wrong_schema_is_reported(self, tmp_path):
        path = tmp_path / MANIFEST_FILENAME
        path.write_text(json.dumps({"schema": "fremd", "files": {}}), encoding="utf-8")
        with pytest.raises(ManifestError, match="Schema"):
            check_manifest(path)

    def test_missing_manifest_is_reported(self, tmp_path):
        with pytest.raises(ManifestError, match="nicht gefunden"):
            check_manifest(tmp_path / "fehlt.json")


class TestCheck:
    @pytest.fixture
    def scene(self, tmp_path):
        """Quelle, Kopie und Manifest — der saubere Ausgangszustand."""
        source = make_source(tmp_path)
        consumer = tmp_path / "konsument"
        consumer.mkdir()
        copy_tree(source, consumer / "vendor" / "comas")
        manifest_file = consumer / MANIFEST_FILENAME
        vendor(manifest_file, "vendor/comas", source_dir=source)
        return {
            "source": source,
            "consumer": consumer,
            "manifest": manifest_file,
            "copy": consumer / "vendor" / "comas",
        }

    def test_clean_copy_has_no_drift(self, scene):
        report = check_manifest(scene["manifest"])
        assert report.ok
        assert report.exit_code == 0
        assert "Kein Drift" in report.render()

    def test_locally_modified_copy_is_caught(self, scene):
        (scene["copy"] / "spawn.py").write_text("def run():\n    return 99\n", encoding="utf-8")
        report = check_manifest(scene["manifest"])
        assert KIND_MODIFIED in kinds(report)
        assert report.exit_code == 1
        assert "spawn.py" in report.render()

    def test_missing_file_in_copy_is_caught(self, scene):
        (scene["copy"] / "spawn.py").unlink()
        report = check_manifest(scene["manifest"])
        assert KIND_MISSING in kinds(report)
        assert not report.ok

    def test_extra_file_in_copy_is_caught(self, scene):
        (scene["copy"] / "eigenes.py").write_text("x = 1\n", encoding="utf-8")
        report = check_manifest(scene["manifest"])
        assert KIND_EXTRA in kinds(report)
        assert not report.ok

    def test_missing_copy_directory_is_caught(self, scene):
        import shutil

        shutil.rmtree(scene["copy"])
        report = check_manifest(scene["manifest"])
        assert KIND_MISSING in kinds(report)
        assert not report.ok

    def test_newer_source_version_is_caught(self, scene):
        (scene["source"] / "__init__.py").write_text(
            '__version__ = "0.3.0"\n', encoding="utf-8"
        )
        report = check_manifest(scene["manifest"])
        assert KIND_OUTDATED in kinds(report)
        assert report.source_version == "0.3.0"
        assert report.manifest_version == "0.1.0"
        assert not report.ok

    def test_changed_source_without_version_bump_is_caught(self, scene):
        # Die gefaehrliche Variante: Version gleich, Inhalt anders.
        (scene["source"] / "spawn.py").write_text("def run():\n    return 2\n", encoding="utf-8")
        report = check_manifest(scene["manifest"])
        assert KIND_DRIFTED in kinds(report)
        assert KIND_OUTDATED not in kinds(report)
        assert not report.ok

    def test_new_file_in_source_is_caught(self, scene):
        (scene["source"] / "locks.py").write_text("X = 1\n", encoding="utf-8")
        report = check_manifest(scene["manifest"])
        assert KIND_DRIFTED in kinds(report)

    def test_removed_file_in_source_is_caught(self, scene):
        (scene["source"] / "spawn.py").unlink()
        report = check_manifest(scene["manifest"])
        assert KIND_DRIFTED in kinds(report)

    def test_unreachable_source_only_checks_integrity(self, scene):
        import shutil

        shutil.rmtree(scene["source"])
        report = check_manifest(scene["manifest"])
        # Keine Drift-Behauptung, aber ein ehrlicher Hinweis.
        assert report.ok
        assert "nicht erreichbar" in report.render()

    def test_source_can_be_overridden(self, scene, tmp_path):
        other = make_source(tmp_path / "anders", "9.9.9")
        report = check_manifest(scene["manifest"], source_dir=other)
        assert KIND_OUTDATED in kinds(report)

    def test_manifest_survives_a_moved_consumer(self, scene, tmp_path):
        """``path`` ist relativ — der Konsument darf umziehen."""
        import shutil

        moved = tmp_path / "woanders"
        shutil.move(str(scene["consumer"]), str(moved))
        report = check_manifest(moved / MANIFEST_FILENAME)
        assert report.ok

    def test_find_and_check_all(self, scene):
        found = find_manifests(scene["consumer"].parent)
        assert scene["manifest"] in found
        reports = check_all(scene["consumer"].parent)
        assert reports and all(report.ok for report in reports)
