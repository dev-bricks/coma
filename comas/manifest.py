"""Das Manifest fuer mitgelieferte Kopien — mit **Pruefbefehl**, nicht nur Beschreibung.

Konsumenten binden COMAS als mitgelieferte Kopie ein (kein PyPI-Zwang, kein
Editable-Install ueber Ordnergrenzen) und aktualisieren ueber ein Manifest. Ein
Manifest, das nur sagt „hier steckt COMAS 0.1 drin", merkt nicht, wenn 0.3 noetig
waere — und schon gar nicht, wenn jemand in die Kopie hineingeschrieben hat.

Vorbild ist ``_scripts/check_editable_installs.py``: Es macht genau diese Art
stiller Drift sichtbar. Zwei Dinge kommen hinzu:

1. **Inhalts-Hashes je Datei.** Eine Versionsnummer erkennt nur „Kopie zu alt".
   Sie erkennt nicht „Kopie lokal veraendert" — und das ist die gefaehrlichere
   Richtung, weil ein Update sie stillschweigend ueberschreibt.
2. **Exitcode.** Bei Drift liefert der Pruefbefehl ``1``. Das ist der Unterschied
   zwischen einem Pruefbefehl und einem Bericht: nur so kann ein Loop, ein Hook
   oder eine CI daran scheitern.

Format (``comas-vendor.json``, neben der Kopie oder an beliebiger Stelle)::

    {
      "schema": "comas.vendor.v1",
      "module": "comas",
      "version": "0.1.0",
      "vendored_at": "2026-07-26T12:00:00",
      "source": "C:/_Local_DEV/repos/comas/comas",
      "path": "third_party/comas",
      "files": {"spawn.py": "sha256:…", "adapters/claude.py": "sha256:…"}
    }

``path`` ist **relativ zur Manifestdatei** — damit bleibt das Manifest gueltig,
wenn das Konsumentenprojekt umzieht.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .status import now, write_json

SCHEMA = "comas.vendor.v1"
MODULE_NAME = "comas"
#: Uebliche Dateiname der Manifestdatei im Konsumentenprojekt.
MANIFEST_FILENAME = "comas-vendor.json"

_VERSION_RE = re.compile(r"""^__version__\s*=\s*["']([^"']+)["']""", re.MULTILINE)
_SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git"}


class ManifestError(ValueError):
    """Das Manifest ist unbrauchbar (fehlt, falsches Schema, kaputtes JSON)."""


# --------------------------------------------------------------------- Hilfen


def package_dir() -> Path:
    """Das Verzeichnis dieses Pakets — die Standardquelle beim Vergleich."""
    return Path(__file__).resolve().parent


def iter_module_files(root: str | os.PathLike[str]) -> list[str]:
    """Alle nachverfolgten Dateien unter ``root``, relative Posix-Pfade, sortiert.

    Nachverfolgt werden ``*.py``. Caches werden uebersprungen; sie gehoeren nicht
    zum Modul und wuerden bei jedem Import als Drift auffallen.
    """
    base = Path(root)
    if not base.is_dir():
        raise ManifestError(f"Quellverzeichnis nicht gefunden: {base}")
    files = []
    for path in base.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.relative_to(base).parts):
            continue
        if path.is_file():
            files.append(path.relative_to(base).as_posix())
    return sorted(files)


def file_digest(path: str | os.PathLike[str]) -> str:
    """``sha256:<hex>`` einer Datei.

    Zeilenenden werden **normalisiert** (CRLF/CR -> LF). Sonst meldete jede
    Kopie zwischen Windows und git-``core.autocrlf`` Drift, die inhaltlich keine
    ist — ein Pruefbefehl, der falschen Alarm gibt, wird abgeschaltet.
    """
    data = Path(path).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest_tree(root: str | os.PathLike[str]) -> dict[str, str]:
    base = Path(root)
    return {rel: file_digest(base / rel) for rel in iter_module_files(base)}


def read_version(source_dir: str | os.PathLike[str]) -> str | None:
    """``__version__`` aus ``__init__.py`` lesen, ohne das Modul zu importieren.

    Nicht importieren: die Quelle kann ein fremder Checkout mit anderer
    Python-Version oder halb geschriebenem Zustand sein.
    """
    init = Path(source_dir) / "__init__.py"
    if not init.is_file():
        return None
    match = _VERSION_RE.search(init.read_text(encoding="utf-8", errors="replace"))
    return match.group(1) if match else None


def version_key(version: str) -> tuple[Any, ...]:
    """Version in eine vergleichbare Form bringen — ohne Fremdbibliothek.

    Numerische Teile werden als Zahl verglichen, alles andere als Text. Reicht
    fuer ``0.1.0`` bis ``12.3.4``; exotische Schemata (``1.0rc1``) vergleichen
    sich textuell und damit im Zweifel „kleiner".
    """
    parts: list[Any] = []
    for chunk in re.split(r"[.\-_+]", version.strip()):
        parts.append((0, int(chunk)) if chunk.isdigit() else (1, chunk))
    return tuple(parts)


# --------------------------------------------------------------------- Manifest


def build_manifest(
    *,
    vendored_path: str,
    source_dir: str | os.PathLike[str] | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Ein Manifest fuer eine mitgelieferte Kopie erzeugen."""
    source = Path(source_dir) if source_dir else package_dir()
    resolved_version = version or read_version(source) or "0"
    return {
        "schema": SCHEMA,
        "module": MODULE_NAME,
        "version": resolved_version,
        "vendored_at": now(),
        "source": source.as_posix(),
        "path": vendored_path,
        "files": digest_tree(source),
    }


def write_manifest(
    manifest_file: str | os.PathLike[str], manifest: dict[str, Any]
) -> Path:
    path = Path(manifest_file)
    write_json(path, manifest)
    return path


def read_manifest(manifest_file: str | os.PathLike[str]) -> dict[str, Any]:
    path = Path(manifest_file)
    if not path.is_file():
        raise ManifestError(f"Manifest nicht gefunden: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ManifestError(f"Manifest ist kein gueltiges JSON: {path} ({error})") from error
    if not isinstance(data, dict):
        raise ManifestError(f"Manifest ist kein Objekt: {path}")
    if data.get("schema") != SCHEMA:
        raise ManifestError(
            f"unbekanntes Schema {data.get('schema')!r} in {path} — erwartet {SCHEMA!r}"
        )
    if not isinstance(data.get("files"), dict):
        raise ManifestError(f"Manifest ohne 'files'-Abschnitt: {path}")
    return data


def vendor(
    manifest_file: str | os.PathLike[str],
    vendored_path: str,
    *,
    source_dir: str | os.PathLike[str] | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Manifest bauen und schreiben. Kopiert **nichts** — das macht der Konsument."""
    manifest = build_manifest(
        vendored_path=vendored_path, source_dir=source_dir, version=version
    )
    write_manifest(manifest_file, manifest)
    return manifest


# ----------------------------------------------------------------------- Pruefung

#: Befund-Arten. ``info`` zaehlt nicht als Drift.
KIND_MODIFIED = "modified"
KIND_MISSING = "missing"
KIND_EXTRA = "extra"
KIND_OUTDATED = "outdated"
KIND_DRIFTED = "drifted"
KIND_INFO = "info"

_DRIFT_KINDS = (KIND_MODIFIED, KIND_MISSING, KIND_EXTRA, KIND_OUTDATED, KIND_DRIFTED)


@dataclass(frozen=True)
class Finding:
    kind: str
    detail: str
    hint: str = ""

    @property
    def is_drift(self) -> bool:
        return self.kind in _DRIFT_KINDS

    def __str__(self) -> str:
        label = "OK     " if self.kind == KIND_INFO else f"{self.kind.upper():<8}"
        text = f"{label} {self.detail}"
        return f"{text}\n         Fix: {self.hint}" if self.hint else text


@dataclass
class CheckReport:
    manifest_file: Path
    vendored_dir: Path
    manifest_version: str
    source_dir: Path | None = None
    source_version: str | None = None
    findings: list[Finding] = field(default_factory=list)

    @property
    def drift(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.is_drift]

    @property
    def ok(self) -> bool:
        return not self.drift

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def render(self) -> str:
        lines = [
            f"Manifest : {self.manifest_file}",
            f"Kopie    : {self.vendored_dir}  (COMAS {self.manifest_version})",
        ]
        if self.source_dir is not None:
            lines.append(
                f"Quelle   : {self.source_dir}  (COMAS {self.source_version or '?'})"
            )
        lines.append("")
        lines.extend(str(finding) for finding in self.findings)
        lines.append("")
        if self.ok:
            lines.append("Kein Drift. Die mitgelieferte Kopie ist aktuell und unveraendert.")
        else:
            lines.append(f"{len(self.drift)} Befund(e) — die Kopie stimmt nicht.")
        return "\n".join(lines)


def check_manifest(
    manifest_file: str | os.PathLike[str],
    *,
    source_dir: str | os.PathLike[str] | None = None,
) -> CheckReport:
    """Eine mitgelieferte Kopie gegen ihr Manifest und die Quelle pruefen.

    Drei Fragen, drei Antworten:

    * Ist die Kopie **unveraendert**? (Hash Kopie gegen Manifest)
    * Ist die Kopie **vollstaendig**? (fehlende und zusaetzliche Dateien)
    * Ist die Kopie **aktuell**? (Version und Hash gegen die Quelle, falls
      erreichbar)

    Ist die Quelle nicht erreichbar, wird nur die Integritaet geprueft und das
    als ``info`` vermerkt — statt vorzugeben, die Aktualitaet sei bestaetigt.
    """
    path = Path(manifest_file)
    manifest = read_manifest(path)
    vendored_dir = (path.parent / manifest.get("path", ".")).resolve()
    manifest_files: dict[str, str] = dict(manifest["files"])
    report = CheckReport(
        manifest_file=path,
        vendored_dir=vendored_dir,
        manifest_version=str(manifest.get("version", "?")),
    )

    # 1. Integritaet der Kopie
    if not vendored_dir.is_dir():
        report.findings.append(
            Finding(
                KIND_MISSING,
                f"Kopie fehlt vollstaendig: {vendored_dir}",
                f"COMAS nach {vendored_dir} kopieren oder 'path' im Manifest korrigieren",
            )
        )
        return report

    for relative, expected in sorted(manifest_files.items()):
        target = vendored_dir / relative
        if not target.is_file():
            report.findings.append(
                Finding(KIND_MISSING, f"{relative} fehlt in der Kopie", "COMAS neu kopieren")
            )
            continue
        actual = file_digest(target)
        if actual != expected:
            report.findings.append(
                Finding(
                    KIND_MODIFIED,
                    f"{relative} wurde in der Kopie veraendert",
                    "Aenderung in die Quelle zurueckfuehren, dann neu kopieren "
                    "(ein Update ueberschreibt sie sonst still)",
                )
            )

    try:
        present = set(iter_module_files(vendored_dir))
    except ManifestError:  # pragma: no cover - oben schon abgefangen
        present = set()
    for relative in sorted(present - set(manifest_files)):
        report.findings.append(
            Finding(
                KIND_EXTRA,
                f"{relative} liegt in der Kopie, steht aber nicht im Manifest",
                "Datei entfernen oder Manifest neu schreiben (comas vendor)",
            )
        )

    # 2. Aktualitaet gegen die Quelle
    candidate = Path(source_dir) if source_dir else Path(str(manifest.get("source", "")))
    if not str(candidate) or not candidate.is_dir():
        report.findings.append(
            Finding(
                KIND_INFO,
                f"Quelle nicht erreichbar ({candidate or 'keine angegeben'}) — "
                "nur Integritaet geprueft, nicht Aktualitaet",
                "",
            )
        )
        return report

    report.source_dir = candidate
    report.source_version = read_version(candidate)
    if report.source_version and report.manifest_version != "?":
        if version_key(report.source_version) > version_key(report.manifest_version):
            report.findings.append(
                Finding(
                    KIND_OUTDATED,
                    f"Quelle ist COMAS {report.source_version}, die Kopie "
                    f"{report.manifest_version}",
                    "COMAS neu kopieren und Manifest neu schreiben (comas vendor)",
                )
            )

    source_digests = digest_tree(candidate)
    for relative, digest in sorted(source_digests.items()):
        if relative not in manifest_files:
            report.findings.append(
                Finding(
                    KIND_DRIFTED,
                    f"{relative} ist in der Quelle neu und fehlt in der Kopie",
                    "COMAS neu kopieren",
                )
            )
        elif manifest_files[relative] != digest:
            report.findings.append(
                Finding(
                    KIND_DRIFTED,
                    f"{relative} hat sich in der Quelle geaendert",
                    "COMAS neu kopieren (Version wurde nicht angehoben)",
                )
            )
    for relative in sorted(set(manifest_files) - set(source_digests)):
        report.findings.append(
            Finding(
                KIND_DRIFTED,
                f"{relative} gibt es in der Quelle nicht mehr",
                "COMAS neu kopieren",
            )
        )

    if not report.drift:
        report.findings.append(
            Finding(KIND_INFO, f"{len(manifest_files)} Datei(en) geprueft, alles gleich")
        )
    return report


def find_manifests(root: str | os.PathLike[str]) -> list[Path]:
    """Manifestdateien unter ``root`` finden — fuer ``comas check`` ohne Argument."""
    base = Path(root)
    return sorted(
        path
        for path in base.rglob(MANIFEST_FILENAME)
        if not any(part in _SKIP_DIRS for part in path.parts)
    )


def check_all(
    root: str | os.PathLike[str], *, source_dir: str | os.PathLike[str] | None = None
) -> list[CheckReport]:
    return [
        check_manifest(path, source_dir=source_dir) for path in find_manifests(root)
    ]
