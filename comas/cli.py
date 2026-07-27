"""Kommandozeile: ``comas`` bzw. ``python -m comas``.

Der Ersatz fuer ``START-LOCAL-AGENT.bat`` ist ``comas run``. Alles andere sind
Lese- und Pruefbefehle fuer Orchestratoren.

``--dry-run`` baut das Kommando und zeigt es, ohne etwas zu starten — damit laesst
sich pruefen, was ein Lauf ausloesen wuerde, bevor Tokens fliessen.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .adapters import (
    NO_RESTRICTION,
    AdapterError,
    ClaudeAdapter,
    adapter_names,
    describe_adapters,
    get_adapter,
)
from .channels import from_agent, to_agent
from .manifest import MANIFEST_FILENAME, ManifestError, check_all, check_manifest, vendor
from .poll import job_view, overview, read_console_log, read_result, read_status
from .protocol import JobBoard, ProtocolError
from .runner import JobRunner


def _reconfigure_stdout() -> None:
    """Auf Windows ist die Konsole cp1252 — echte Umlaute brauchen UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):  # pragma: no cover - exotische Streams
            pass


def _tools_argument(value: str) -> Any:
    """``--allowed-tools`` von der Kommandozeile deuten.

    ``-`` bedeutet „Flag weglassen", der Leerstring „alle Built-ins abschalten",
    sonst eine Komma-Liste.
    """
    if value == "-":
        return NO_RESTRICTION
    if value == "":
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


#: Vorlage aus einem Preset uebernehmen, damit Einzelangaben davor gelten koennen.
_PRESET_FIELDS = (
    "model",
    "permission_mode",
    "allowed_tools",
    "available_tools",
    "allow_mcp",
    "persist_sessions",
)


def _adapter_from_args(args: argparse.Namespace) -> Any:
    """Adapter aus den CLI-Argumenten bauen: Preset als Grundlage, Flags darueber."""
    if args.adapter != ClaudeAdapter.name:
        flags: dict[str, Any] = {}
        for field in ("model", "timeout", "cwd", "output_format"):
            value = getattr(args, field, None)
            if value is not None:
                flags[field] = value
        if args.adapter == "codex":
            if args.effort:
                flags["effort"] = args.effort
            if args.write:
                flags["write"] = True
            if args.persist_sessions:
                flags["persist_sessions"] = True
        elif args.adapter == "agy":
            if args.add_dir:
                flags["add_dirs"] = args.add_dir
            if args.skip_permissions is not None:
                flags["skip_permissions"] = args.skip_permissions
        elif args.adapter == "kimi":
            if args.session:
                flags["session"] = args.session
            if args.continue_conversation:
                flags["continue_conversation"] = True
        return get_adapter(args.adapter, **flags)

    base: dict[str, Any] = {}
    if args.preset:
        preset = ClaudeAdapter.preset(args.preset)
        base = {field: getattr(preset, field) for field in _PRESET_FIELDS}

    flags: dict[str, Any] = {}
    if args.model:
        flags["model"] = args.model
    if args.permission_mode:
        flags["permission_mode"] = args.permission_mode
    if args.allowed_tools is not None:
        flags["allowed_tools"] = _tools_argument(args.allowed_tools)
    if args.tools is not None:
        flags["available_tools"] = _tools_argument(args.tools)
    if args.fallback_model:
        flags["fallback_model"] = args.fallback_model
    if args.max_budget_usd is not None:
        flags["max_budget_usd"] = args.max_budget_usd
    if args.output_format:
        flags["output_format"] = args.output_format
    if args.allow_mcp:
        flags["allow_mcp"] = True
    if args.persist_sessions:
        flags["persist_sessions"] = True
    if args.safe_mode:
        flags["safe_mode"] = True
    if args.timeout:
        flags["timeout"] = args.timeout
    if args.cwd:
        flags["cwd"] = args.cwd
    return ClaudeAdapter(**{**base, **flags})


def _add_adapter_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--adapter", default=ClaudeAdapter.name, choices=adapter_names(),
        help="welche CLI gestartet wird (Standard: claude)",
    )
    parser.add_argument(
        "--preset", choices=("unattended", "read_only", "bat_compat"),
        help="benanntes claude-Profil als Grundlage",
    )
    parser.add_argument("--model", help="Modell, z. B. opus, sonnet, haiku")
    parser.add_argument("--fallback-model", help="Ausweichmodell bei Ueberlast")
    parser.add_argument(
        "--permission-mode",
        help="dontAsk (verweigert, haengt nie) oder bypassPermissions u. a.",
    )
    parser.add_argument(
        "--allowed-tools",
        help="Komma-Liste vorab freigegebener Werkzeuge; '-' laesst das Flag weg",
    )
    parser.add_argument(
        "--tools",
        help="Komma-Liste verfuegbarer Built-ins; '' schaltet alle ab, '-' laesst das Flag weg",
    )
    parser.add_argument("--max-budget-usd", type=float, help="Kostendeckel des Laufs")
    parser.add_argument(
        "--output-format", choices=("text", "json", "stream-json"),
        help="stream-json setzt --verbose automatisch mit",
    )
    parser.add_argument("--allow-mcp", action="store_true", help="MCP-Werkzeuge zulassen")
    parser.add_argument(
        "--persist-sessions", action="store_true", help="Sitzung auf Platte speichern"
    )
    parser.add_argument(
        "--safe-mode", action="store_true", help="alle Anpassungen der CLI abschalten"
    )
    parser.add_argument("--timeout", type=int, help="Zeitgrenze in Sekunden")
    parser.add_argument("--cwd", help="Arbeitsverzeichnis des Agenten")
    parser.add_argument(
        "--effort",
        choices=("low", "medium", "high", "xhigh", "max", "ultra"),
        help="Codex reasoning effort",
    )
    parser.add_argument(
        "--write", action="store_true",
        help="Codex workspace-write statt read-only",
    )
    parser.add_argument(
        "--add-dir", action="append", default=[],
        help="zusätzliche Agy-Arbeitswurzel (wiederholbar)",
    )
    parser.add_argument(
        "--skip-permissions",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Agy-Berechtigungsabfragen überspringen",
    )
    parser.add_argument("--session", help="Kimi-Sitzungs-ID")
    parser.add_argument(
        "--continue-conversation", action="store_true",
        help="bestehende Kimi-Sitzung fortsetzen",
    )
    parser.add_argument(
        "--allow-unverified", action="store_true",
        help="nicht live gepruefte Adapter (codex, agy, kimi) trotzdem starten",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="comas",
        description=(
            "COMAS — Lebenszyklus-Schicht fuer Agenten: starten, beobachten, abholen."
        ),
    )
    parser.add_argument("--version", action="version", version=f"comas {__version__}")
    parser.add_argument(
        "--root", default=".",
        help="Jobverzeichnis mit IN/ OUT/ DONE/ (Standard: aktuelles Verzeichnis)",
    )
    parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Job starten (Ersatz fuer START-LOCAL-AGENT.bat)")
    run.add_argument("job_id", nargs="?", help="ohne Angabe: aeltester Auftrag in IN/")
    run.add_argument(
        "--dry-run", action="store_true", help="Kommando nur zeigen, nichts starten"
    )
    _add_adapter_options(run)

    cmd = subparsers.add_parser("cmd", help="Kommando fuer einen freien Prompt zeigen")
    cmd.add_argument("prompt", help="der Prompt")
    _add_adapter_options(cmd)

    submit = subparsers.add_parser("submit", help="Auftrag in IN/ ablegen")
    submit.add_argument("job_id")
    submit.add_argument("--file", help="Markdown-Datei; ohne Angabe von stdin")
    submit.add_argument("--overwrite", action="store_true")

    status = subparsers.add_parser("status", help="Status eines Jobs")
    status.add_argument("job_id")

    subparsers.add_parser("list", help="alle bekannten Jobs")

    result = subparsers.add_parser("result", help="Ergebnisdatei ausgeben")
    result.add_argument("job_id")

    log = subparsers.add_parser("log", help="Konsolenlog ausgeben")
    log.add_argument("job_id")
    log.add_argument("--tail-bytes", type=int, default=200_000)

    send = subparsers.add_parser("send", help="Nachricht an den Agenten anhaengen")
    send.add_argument("job_id")
    send.add_argument("text", help="Freitext oder JSON-Objekt")

    inbox = subparsers.add_parser("inbox", help="Meldungen des Agenten lesen")
    inbox.add_argument("job_id")
    inbox.add_argument("--tail", type=int, default=0, help="nur die letzten N")

    subparsers.add_parser("adapters", help="verfuegbare CLI-Adapter")

    check = subparsers.add_parser(
        "check", help="mitgelieferte Kopien gegen Manifest und Quelle pruefen"
    )
    check.add_argument(
        "manifest", nargs="?",
        help=f"Manifestdatei; ohne Angabe wird unter --root nach {MANIFEST_FILENAME} gesucht",
    )
    check.add_argument("--source", help="Quellverzeichnis des comas-Pakets")

    vendor_cmd = subparsers.add_parser("vendor", help="Manifest fuer eine Kopie schreiben")
    vendor_cmd.add_argument("manifest", help="Zielpfad der Manifestdatei")
    vendor_cmd.add_argument(
        "--path", required=True, help="Pfad der Kopie, relativ zur Manifestdatei"
    )
    vendor_cmd.add_argument("--source", help="Quellverzeichnis des comas-Pakets")
    vendor_cmd.add_argument("--module-version", help="Version, sonst aus der Quelle")

    return parser


def _emit(args: argparse.Namespace, payload: Any, text: str) -> None:
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(text)


def _cmd_run(args: argparse.Namespace) -> int:
    adapter = _adapter_from_args(args)
    runner = JobRunner(
        JobBoard(args.root), adapter, allow_unverified=args.allow_unverified
    )
    if args.dry_run:
        plan = runner.dry_run(args.job_id)
        _emit(args, plan, plan["rendered"])
        return 0
    result = runner.run(args.job_id)
    lines = [
        f"Job      : {result['job_id']}",
        f"Adapter  : {result['adapter']}  Modell: {result['model'] or '-'}",
        f"Exitcode : {result['returncode']}  Dauer: {result['duration_s']:.1f}s",
        f"Status   : {result['status'].get('state')}",
        f"Ergebnis : {result['result_file']}"
        + ("" if result["result_written"] else "  (NICHT geschrieben)"),
        f"Log      : {result['log_file']}",
    ]
    if result["archived"]:
        lines.append(f"Archiv   : {result['archived']}")
    else:
        lines.append("Archiv   : nicht verschoben, Auftrag bleibt in IN/ liegen")
    _emit(args, result, "\n".join(lines))
    return 0 if result["success"] else 1


def _cmd_cmd(args: argparse.Namespace) -> int:
    adapter = _adapter_from_args(args)
    spec = adapter.build_spec(args.prompt)
    payload = {
        "adapter": spec.adapter,
        "verified": spec.verified,
        "argv": list(spec.argv),
        "executable": spec.executable,
        "cwd": spec.cwd,
        "timeout": spec.timeout,
        "notes": list(spec.notes),
    }
    _emit(args, payload, spec.rendered())
    return 0


def _cmd_submit(args: argparse.Namespace) -> int:
    markdown = (
        Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    )
    paths = JobBoard(args.root).submit(args.job_id, markdown, overwrite=args.overwrite)
    _emit(args, paths.as_dict(), f"Auftrag abgelegt: {paths.job_file}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    paths = JobBoard(args.root).paths(args.job_id)
    status = read_status(paths)
    if status is None:
        _emit(args, {}, f"kein Status fuer {args.job_id!r} in {paths.out_dir}")
        return 1
    view = job_view(paths)
    text = "\n".join(f"{key:<12}: {value}" for key, value in view.items())
    _emit(args, {"status": status, "view": view}, text)
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    rows = overview(JobBoard(args.root))
    if not rows:
        _emit(args, [], f"keine Jobs unter {args.root}")
        return 0
    header = f"{'JOB':<28} {'ZUSTAND':<9} {'RC':>4}  {'MODELL':<10} ERGEBNIS"
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row['job_id']:<28} {str(row['state'] or '-'):<9} "
            f"{str(row['exit_code'] if row['exit_code'] is not None else '-'):>4}  "
            f"{str(row['model'] or '-'):<10} {'ja' if row['has_result'] else 'nein'}"
        )
    _emit(args, rows, "\n".join(lines))
    return 0


def _cmd_result(args: argparse.Namespace) -> int:
    paths = JobBoard(args.root).paths(args.job_id)
    text = read_result(paths)
    if text is None:
        _emit(args, {}, f"keine Ergebnisdatei: {paths.result_file}")
        return 1
    _emit(args, {"job_id": args.job_id, "result": text}, text)
    return 0


def _cmd_log(args: argparse.Namespace) -> int:
    paths = JobBoard(args.root).paths(args.job_id)
    text = read_console_log(paths, tail_bytes=args.tail_bytes)
    if not text:
        _emit(args, {}, f"kein Log: {paths.console_log}")
        return 1
    _emit(args, {"job_id": args.job_id, "log": text}, text)
    return 0


def _cmd_send(args: argparse.Namespace) -> int:
    paths = JobBoard(args.root).paths(args.job_id)
    try:
        payload = json.loads(args.text)
        if not isinstance(payload, dict):
            payload = {"message": payload}
    except ValueError:
        payload = {"message": args.text}
    record = to_agent(paths).append(payload)
    _emit(args, record, f"gesendet an {paths.to_agent_file}: {record}")
    return 0


def _cmd_inbox(args: argparse.Namespace) -> int:
    paths = JobBoard(args.root).paths(args.job_id)
    channel = from_agent(paths)
    records = channel.tail(args.tail) if args.tail else channel.read()
    text = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
    _emit(args, records, text or f"keine Meldungen in {paths.from_agent_file}")
    return 0


def _cmd_adapters(args: argparse.Namespace) -> int:
    rows = describe_adapters()
    lines = []
    for row in rows:
        mark = "geprueft" if row["verified"] else "GERUEST"
        lines.append(f"{row['name']:<8} [{mark}]  {row['display_name']}")
        lines.append(f"         Binary: {row['resolved'] or row['executable'] + ' (nicht gefunden)'}")
        for note in row["notes"]:
            lines.append(f"         - {note}")
    _emit(args, rows, "\n".join(lines))
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    if args.manifest:
        reports = [check_manifest(args.manifest, source_dir=args.source)]
    else:
        reports = check_all(args.root, source_dir=args.source)
        if not reports:
            _emit(args, [], f"keine {MANIFEST_FILENAME} unter {args.root} gefunden")
            return 0
    payload = [
        {
            "manifest": str(report.manifest_file),
            "vendored_dir": str(report.vendored_dir),
            "manifest_version": report.manifest_version,
            "source_version": report.source_version,
            "ok": report.ok,
            "findings": [
                {"kind": finding.kind, "detail": finding.detail, "hint": finding.hint}
                for finding in report.findings
            ],
        }
        for report in reports
    ]
    _emit(args, payload, "\n\n".join(report.render() for report in reports))
    return 0 if all(report.ok for report in reports) else 1


def _cmd_vendor(args: argparse.Namespace) -> int:
    manifest = vendor(
        args.manifest,
        args.path,
        source_dir=args.source,
        version=args.module_version,
    )
    _emit(
        args,
        manifest,
        f"Manifest geschrieben: {args.manifest}\n"
        f"COMAS {manifest['version']}, {len(manifest['files'])} Datei(en), "
        f"Kopie erwartet unter {manifest['path']}",
    )
    return 0


_COMMANDS = {
    "run": _cmd_run,
    "cmd": _cmd_cmd,
    "submit": _cmd_submit,
    "status": _cmd_status,
    "list": _cmd_list,
    "result": _cmd_result,
    "log": _cmd_log,
    "send": _cmd_send,
    "inbox": _cmd_inbox,
    "adapters": _cmd_adapters,
    "check": _cmd_check,
    "vendor": _cmd_vendor,
}


def main(argv: Sequence[str] | None = None) -> int:
    _reconfigure_stdout()
    args = build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except (AdapterError, ProtocolError, ManifestError) as error:
        print(f"[comas] {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"[comas] Dateifehler: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - Skripteinstieg
    raise SystemExit(main())
