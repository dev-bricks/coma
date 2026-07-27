# COMAS — COMmunication for Autonomous Subagents

> Die **Lebenszyklus-Schicht** für Agenten: Wie entsteht ein Agent als eigener
> Prozess, und wie bleibt man mit ihm in Kontakt, solange er läuft?

Genau eine Verantwortung. COMAS sperrt nichts, verwaltet keine Rechte und hält
kein Gedächtnis. Es arbeitet mit Dateien und Prozessen — **ohne Konto, ohne Netz,
ohne Cluster**. Null Abhängigkeiten, nur Standardbibliothek.

Konzept, Begründung und Abgrenzung: [`KONZEPT.md`](KONZEPT.md).

| Schicht | Frage | Zuständig |
|---|---|---|
| **Lebenszyklus** | Wie entsteht ein Agent, wie rede ich mit ihm? | **COMAS** |
| Anspruch | Wer darf was anfassen? | `team-lock` → `lock-master` → Roshambo |
| Gedächtnis | Wurde das schon versucht, wie ging es aus? | Roshambo |

Die Verben trennen sauber: COMAS spricht `spawn`, `send`, `poll`, `result`. Ein
Koordinator spricht `claim`, `release`, `remember`, `recall`, `decide`, `status`.
Keine Überschneidung.

## Wozu

**COMAS umgeht keine Sicherheitsgrenze.** Es nutzt dokumentierte CLI-Flags
(`--permission-mode`, `--allowedTools` und Verwandte), um einen Client-Bug zu
umschiffen, nicht um eine Prüfung zu deaktivieren.

In einer **Remote-Control-Session** reicht Claude Code `--dangerously-skip-permissions`
nicht an den Remote-Client durch (offene Issues
[#71518](https://github.com/anthropics/claude-code/issues/71518),
[#29214](https://github.com/anthropics/claude-code/issues/29214)). Folge: Jeder
Tool-Aufruf fragt nach — auch bei Subagenten. Ist niemand am Rechner, **stehen sie
still**: unbeaufsichtigte Agenten warten auf Klicks, die niemand gibt.

Die Lösung ist nicht, mehr Regeln in eine Allowlist zu schreiben, sondern den
Agenten **gar nicht erst in der RC-Session leben zu lassen**: ein eigener lokaler
Prozess ausserhalb dieser Session, Kommunikation über das Dateisystem. Welche
Werkzeuge dieser Prozess nutzen darf, entscheidet weiterhin der Permission-Mode —
COMAS setzt ihn nur an einer Stelle, an der er tatsächlich ankommt.

## Schnellstart

```python
from comas import JobBoard, JobRunner

board = JobBoard(r"C:\Users\du\_agentjobs")
board.submit("meinjob", "# Auftrag\n\nSchreibe das Ergebnis nach OUT/meinjob.result.md.\n")

result = JobRunner(board).run("meinjob")
print(result["status"]["state"], result["result_written"])
```

Oder von der Kommandozeile:

```bat
comas --root C:\Users\du\_agentjobs run meinjob
comas --root C:\Users\du\_agentjobs run meinjob --dry-run   :: nur zeigen, nichts starten
comas --root C:\Users\du\_agentjobs status meinjob
comas --root C:\Users\du\_agentjobs result meinjob
```

**`--dry-run` zuerst.** Es baut das vollständige Kommando und zeigt es, ohne dass
ein Token fließt.

## Das Protokoll

```
IN/    <jobid>.md                       Auftrag (Freitext-Markdown)
OUT/   <jobid>.result.md                Ergebnis
       comas.<jobid>.json               Status      — nur der Runner schreibt
       comas.<jobid>.from-agent.jsonl   Fortschritt — nur der Agent schreibt
       comas.<jobid>.to-agent.jsonl     Nachrichten — nur der Orchestrator schreibt
       comas.<jobid>.console.log        stdout/stderr des Laufs
DONE/  <jobid>.md                       erledigter Auftrag
```

**Ein Schreiber je Datei — kein Locking nötig, Kollision strukturell unmöglich.**
Gelesen werden darf von allen. Das ist keine Vorsichtsmaßnahme, sondern eine
Lektion: Eine geteilte Logdatei in OneDrive hat schon einmal zu Konfliktkopien
geführt (Ticket `T-20260621-44`).

`.jsonl` für die Kanäle, weil Anhängen atomar ist — ein Schreiber muss nicht erst
lesen, parsen und neu schreiben.

Die Auftragsdatei ist **freies Markdown** und enthält den vollständigen Prompt.
Der Agent bekommt nur einen **Zeiger** darauf; er liest die Datei selbst und
schreibt sein Ergebnis selbst als Datei. Damit hängt die Rückgabe weder an der
stdout-Größe noch am Encoding.

### Fernsteuern, lokal ausführen

Eine RC-Session kann Aufträge schreiben und Ergebnisse abholen, ohne den Agenten
selbst zu hosten:

```python
from comas import JobBoard, read_result, wait_for_finish

board = JobBoard(root)
paths = board.submit("meinjob", auftrag_markdown)   # 1. Auftrag schreiben
# 2. Lokal läuft irgendwann: comas run meinjob
status = wait_for_finish(paths, timeout=3600)        # 3. Statusdatei beobachten
if status["exit_code"] == 0:
    print(read_result(paths))
```

`wait_for_finish` beobachtet die **Statusdatei**, nicht den Prozess. Genau deshalb
funktioniert es aus einem fremden Prozess, einer anderen Session oder über
OneDrive von einem anderen Rechner.

### Nachrichten während des Laufs

```python
from comas import from_agent, to_agent

to_agent(paths).append({"kind": "hint", "text": "Nimm Variante B."})   # Orchestrator
for record in from_agent(paths).read():                                # Agent-Meldungen
    print(record)
```

Der Rollen-Parameter ist Dokumentation mit Zähnen: `to_agent(paths).append(…, role="agent")`
wirft, statt eine Konfliktkopie zu erzeugen.

## Die Spawn-Schicht

Ein Adapter weiß genau zwei Dinge: wie das Kommando für seine CLI aussieht und
welche Umgebung sie braucht. Er startet **nichts** — das macht der `Spawner`.
Deshalb ist der Kommandobau ohne Prozessstart prüfbar.

```python
from comas import ClaudeAdapter, Spawner

adapter = ClaudeAdapter(model="sonnet", permission_mode="dontAsk",
                        allowed_tools=["Read", "Write"], max_budget_usd=2.0)
print(adapter.build_cmd("Sag Hallo"))   # nur die Argumentliste, nichts läuft

spawner = Spawner(adapter)
result = spawner.run("Sag Hallo", log_file="lauf.log")
handle = spawner.start("Sag Hallo", log_file="lauf.log")   # nicht blockierend
while handle.poll() is None:
    ...
```

### Adapter

| Adapter | Ziel | Stand |
|---|---|---|
| `claude` | Claude Code CLI | **verifiziert** — Flags gegen `claude --help` 2.1.220 geprüft, echter Durchlauf belegt |
| `codex` | native `codex exec` | **Verifiziert** — CLI 0.145.0, read-only/workspace-write, Ergebnisdatei via `--output-last-message` |
| `agy` | Antigravity/Gemini | **Verifiziert** — agy 1.1.7, stdout und Exitcode live geprüft; Job-Ergebnisdatei bleibt kanonisch |
| `kimi` | Kimi Code CLI | **Gerüst** — CLI 0.17.1 gefunden, aber ohne konfiguriertes Modell kein Prompt-Lauf |

`verified` ist keine Kosmetik: Der `Spawner` **weigert sich**, einen Gerüst-Adapter
zu starten, solange nicht ausdrücklich `allow_unverified=True` gesetzt ist. So ist
Adapterwissen dokumentiert und getestet, ohne dass ein ungetesteter Aufrufweg
unbemerkt in einen unbeaufsichtigten Lauf gerät.

```bat
comas adapters      :: zeigt Stand, gefundene Binary und die Fallstricke je Adapter
```

### Der Permission-Mode bleibt Parameter

`dontAsk` und `bypassPermissions` sind **verschiedene Sicherheitsprofile**, nicht
zwei Namen für dasselbe:

- **`dontAsk`** fragt nie, sondern **verweigert**. Zusammen mit einer expliziten
  Werkzeugliste kann ein Agent damit strukturell nicht hängenbleiben. Für
  unbeaufsichtigte Läufe die bessere Wahl — und deshalb der Standard.
- **`bypassPermissions`** kann in Sonderfällen weiterhin nachfragen. In einer
  RC-Session heißt das: Der Agent steht, bis jemand klickt.

„Verweigert und meldet das" ist besser als „wartet auf einen Klick, den niemand
gibt". Fest verdrahtet bekäme ein Konsument stillschweigend das falsche Profil.

**Was `dontAsk` *nicht* zusätzlich verengt (geprüft 2026-07-26, CLI 2.1.220):** Ein
`Write` auf einen absoluten Pfad **außerhalb** des Arbeitsverzeichnisses wurde
nicht verweigert — der Selbsttest lief mit cwd im COMAS-Repo und schrieb nach
OneDrive, Exit 0. Deshalb setzt COMAS kein `cwd` von sich aus; `subprocess` erbt
das des Aufrufers, wie im Bestand. Wer den Arbeitsbereich festlegen will,
übergibt `cwd=` bzw. `--cwd`.

Ebenfalls **nicht modelliert: `--add-dir`.** Das Flag existiert
(`--add-dir <directories...>`, variadisch) und ist über `extra_args` erreichbar.
Kein eigener Parameter, weil nicht verifiziert ist, ob mehrere Verzeichnisse als
wiederholtes Flag oder als Werteliste zu übergeben sind — und Pfade können Kommas
enthalten, die Komma-Verbindung der Werkzeuglisten ist hier also kein Ausweg. Eine
geratene Kodierung wäre schlimmer als keine.

Drei benannte Profile, jedes mit belegter Herkunft:

```python
ClaudeAdapter.preset("unattended")   # Standard: dontAsk + explizite Werkzeugliste
ClaudeAdapter.preset("read_only")    # dontAsk + Read,Glob,Grep
ClaudeAdapter.preset("bat_compat")   # die verifizierte Startschale: bypassPermissions
```

### Werkzeuglisten: zwei Flags, zwei Bedeutungen

`--tools` begrenzt, welche Built-ins überhaupt **existieren**; `--allowedTools`
gibt sie **vorab frei**. Verschiedene Dinge, deshalb zwei Parameter:

```python
ClaudeAdapter(allowed_tools=["Read"], available_tools=["Read", "Bash"])
# --tools Read,Bash --allowedTools Read
#   -> Bash ist da, aber nicht freigegeben: unter dontAsk wird es verweigert.
```

| Wert | Wirkung |
|---|---|
| `["Read", "Write"]` | Liste, komma-verbunden als **ein** Argument |
| `MIRROR` (Standard für `available_tools`) | spiegelt `allowed_tools` |
| `NO_RESTRICTION` / `None` | Flag entfällt ganz |
| `[]` bei `available_tools` | `--tools ""` — alle Built-ins abschalten |

MCP lässt sich über `--tools` nicht abschalten (dort stehen nur Built-ins);
dafür gibt es `--disallowedTools mcp__*`, standardmäßig gesetzt (`allow_mcp=True`
hebt es auf).

## Harte Lektionen, die im Code stecken

Diese vier stammen aus der Referenzimplementierung und sind hier keine
Ratschläge, sondern Verhalten:

1. **Der Prompt bleibt kurz und zeichenarm.** Lauf 1 des Selbsttests starb
   **still** — kein Ergebnis, Status auf `running`, Fenster weg. Ursache: JSON mit
   `\"` im Prompt; **CMD kennt keine Backslash-Escapes**, der Befehl zerriss. Alle
   Anweisungen gehören in die Auftragsdatei, der Prompt zeigt nur darauf.
   *In Python entfällt diese Gefahr* — `subprocess` übergibt die Argumente ohne
   Shell. **Ausnahme:** Wird eine CLI über einen `.CMD`-Shim aufgerufen (npm legt
   solche für `codex` und `kimi` an), parst Windows die Zeile erneut durch
   `cmd.exe` — dann gilt die Lektion wieder. Deshalb nennen die Gerüst-Adapter die
   absoluten `.exe`- bzw. `node`-Aufrufwege.
2. **Keine eingebetteten Interpreter-Einzeiler in der Startschale** — gleiches
   Quoting-Problem. Der Statusschreiber ist ein eigenes Modul und bleibt als
   `python -m comas.status` argv-kompatibel zur Vorlage aufrufbar.
3. **Immer `> log 2>&1`.** Jeder Lauf schreibt `comas.<jobid>.console.log`; der
   `Spawner` leitet stdout und stderr zusammen dorthin und liest danach das Ende
   zurück. Ein stiller Tod darf nicht möglich sein.
4. **Die Argumentreihenfolge ist eine Sicherheitseigenschaft.** `--tools`,
   `--allowedTools` und `--disallowedTools` sind **variadisch** (`<tools...>`).
   Ein positionaler Prompt hinter einem solchen Flag würde als Werkzeugname
   verschluckt. COMAS setzt den Prompt darum direkt nach `-p` und verbindet alle
   Werkzeuglisten komma-getrennt zu einem Argument.

Ebenfalls erzwungen: `--output-format stream-json` setzt `--verbose` mit. Die CLI
lehnt `stream-json` unter `-p` ohne `--verbose` ab; wer nur eines setzt, baut eine
Option, die zur Laufzeit stirbt.

## Mitgelieferte Kopien: Manifest **mit Prüfbefehl**

Konsumenten binden COMAS als mitgelieferte Kopie ein und aktualisieren über ein
Manifest. Ein Manifest, das nur sagt „hier steckt COMAS 0.1 drin", merkt nicht,
wenn 0.3 nötig wäre — und schon gar nicht, wenn jemand in die Kopie
hineingeschrieben hat.

```bat
:: Manifest schreiben (kopiert nichts -- das macht der Konsument)
comas vendor .\comas-vendor.json --path vendor\comas --source C:\_Local_DEV\repos\comas\comas

:: Prüfen. Exitcode 1 bei Drift -- daran kann ein Hook oder eine CI scheitern.
comas check .\comas-vendor.json
```

Drei Fragen, drei Antworten:

| Befund | Bedeutung |
|---|---|
| `MODIFIED` | Die Kopie wurde lokal verändert — ein Update überschreibt das still |
| `MISSING` / `EXTRA` | Die Kopie ist unvollständig bzw. enthält Fremddateien |
| `OUTDATED` | Die Quelle hat eine höhere Version |
| `DRIFTED` | Die Quelle hat sich geändert, **ohne** die Version anzuheben |
| `INFO` | Quelle nicht erreichbar: nur Integrität geprüft, nicht Aktualität |

Vorbild ist `_scripts/check_editable_installs.py`, das genau diese Art stiller
Drift sichtbar macht. Zwei Dinge kommen hinzu: **Inhalts-Hashes** (eine
Versionsnummer erkennt nur „zu alt", nicht „verändert") und ein **Exitcode** — das
ist der Unterschied zwischen einem Prüfbefehl und einem Bericht. Zeilenenden
werden beim Hashen normalisiert, sonst meldete jede Kopie zwischen Windows und
`core.autocrlf` falschen Alarm.

## Lock-Schnittstelle: definiert, nicht implementiert

COMAS sperrt nichts. Es ruft Claims über eine schmale Schnittstelle auf, nicht
gegen ein konkretes Modul — dann ist der späteren Wechsel ein Zeilenwechsel im
Stack-Manifest statt eines Umbaus:

- `comalock` = COMAS + `lock-master` (lokal, offline)
- `comaroshambo` = COMAS + Roshambo (verteilt, Cloud)

```python
from comas import LockBackend, claimed   # LockBackend ist ein Protocol

with claimed(mein_backend, "pfad/zum/projekt", kind="project"):
    JobRunner(board).run("meinjob")
```

Es gibt hier **keinen** Import von `lock-master`, `team-lock` oder Roshambo, und
das ist Absicht, kein fehlender Schritt: COMAS muss abhängigkeitsfrei und
offline-fähig bleiben. Ein Test prüft das nach. Der Standard ist `NullLock` —
gewährt alles, merkt sich nichts.

## Kommandozeile

| Befehl | Zweck |
|---|---|
| `run [jobid]` | Job starten (Ersatz für `START-LOCAL-AGENT.bat`); ohne ID der älteste |
| `run … --dry-run` | Kommando bauen und zeigen, nichts starten |
| `cmd <prompt>` | Kommando für einen freien Prompt zeigen |
| `submit <jobid>` | Auftrag in `IN/` ablegen (`--file` oder stdin) |
| `status <jobid>` · `list` | Zustand eines Jobs bzw. aller Jobs |
| `result <jobid>` · `log <jobid>` | Ergebnisdatei bzw. Konsolenlog ausgeben |
| `send <jobid> <text>` · `inbox <jobid>` | Nachricht an den Agenten bzw. dessen Meldungen |
| `adapters` | Adapter, Stand, gefundene Binary, Fallstricke |
| `check` · `vendor` | Manifest prüfen bzw. schreiben |

`--json` gibt es überall, `--root` bestimmt das Jobverzeichnis.

## Tests

```bat
python -m pytest -q      :: 228 Tests
```

**Kein Test startet einen echten Prozess.** `subprocess` wird überall ersetzt; das
ist Absicht, nicht Bequemlichkeit — ein Test, der `claude` startet, kostet Tokens,
braucht Netz und wird beim ersten Ausfall abgeschaltet. Geprüft wird der
Kommandobau gegen erwartete Argumentlisten, nach dem Vorbild von
`swarm-ai/tests/test_runner.py`.

Drei Grenzen des Moduls sind ebenfalls als Test hinterlegt, damit sie beim
nächsten Umbau nicht still verloren gehen: kein Import von `llmauto`/`swarm-ai`
(COMAS ist eine **Extraktion**, keine Abhängigkeit), keine Fremdbibliothek, ein
Schreiber je Datei.

## Herkunft

Die Spawn-Schicht ist eine **Extraktion**, kein Neubau. Drei Stellen bauten vorher
unabhängig voneinander `claude`-Subprozessaufrufe:

| Quelle | Beitrag |
|---|---|
| `llmauto/core/runner.py:17-51` | Der Keim: Wrapper-Klasse, `--fallback-model`, `--continue`, `--allowedTools`, konfigurierbarer Permission-Mode |
| `swarm-ai/tools/runner.py:16-226` | `--max-budget-usd`, `--tools`, `--disallowedTools mcp__*`, `--no-session-persistence`, Validierung, Parallellauf |
| `swarm-ai/experiments/dungeon/…_live.py:283-323` | `--output-format stream-json`, `--verbose`, `--safe-mode`, `CLAUDECODE`-Bereinigung |
| `_control-center/START-LOCAL-AGENT.bat:72` | Standardkonfiguration und Zeiger-Prompt |
| `_control-center/_agentjobs/comas_status.py` | Statusschreiber |

Nicht Teil des Moduls und absichtlich lokal: `_control-center/_agentjobs/` und
`START-LOCAL-AGENT.bat`. Die Startschale ist die Umgehung eines Client-Bugs, keine
allgemeine Fähigkeit.

`ellmos-agent-bridge` ist **kein** Konkurrent und kein künftiger COMAS-Importeur:
Es verwaltet Partner-Metadaten und trifft Empfehlungen, startet aber nichts.

## Stand

Version 0.1.0, in Entwicklung. Lizenz: MIT (Entscheidung 2026-07-26 — COMAS startet
lokale Prozesse und schreibt Dateien, hat also keine Netzfläche; eine Copyleft-Klausel
mit Netzauslöser wie AGPL §13 würde hier nie greifen). Das öffentliche Quellrepository
ist `https://github.com/dev-bricks/comas`; der `.MODULES`-Eintrag bleibt ein
Plan-D-Pointer auf die lokalen Klone und dieses Repository. Die zentrale Registry
`comas-reg.json` und weitere Produkt-/Release-Gates bleiben davon getrennte offene
Punkte.
