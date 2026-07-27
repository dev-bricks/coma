# COMA — COMmunication for Autonomous Subagents

> Modul-Konzept. Beschlossen von Lukas Geiger am 2026-07-26, erarbeitet in Session
> „OPUS WORKSTATION". Status: **Modul gebaut** (`coma` 0.1.0, 2026-07-26) — die
> Spawn-Schicht ist aus den drei bestehenden Implementierungen extrahiert, 227 Tests
> laufen ohne Prozessstart, ein echter Durchlauf über die Python-Schicht ist belegt.
> Referenzimplementierung (`.bat`) existiert weiter und bleibt lokal.
> Siehe `README.md`, „Offen" unten und den Ergebnisbericht
> `_agentjobs/OUT/coma-modul-bauen.result.md`.

## Was COMA ist

Die **Lebenszyklus-Schicht** für Agenten: Wie entsteht ein Agent als eigener Prozess,
und wie bleibt man mit ihm in Kontakt, solange er läuft?

Genau eine Verantwortung. COMA sperrt nichts, verwaltet keine Rechte und hält kein
Gedächtnis.

| Schicht | Frage | Zuständig |
|---|---|---|
| **Lebenszyklus** | Wie entsteht ein Agent, wie rede ich mit ihm? | **COMA** |
| Anspruch | Wer darf was anfassen? | `team-lock` → `lock-master` → Roshambo |
| Gedächtnis | Wurde das schon versucht, wie ging es aus? | Roshambo |

Die Verben trennen sauber: COMA spricht `spawn`, `send`, `poll`, `result`.
Roshambo-MCP spricht `claim`, `release`, `remember`, `recall`, `decide`, `status`.
Keine Überschneidung — hätten zwei Systeme dieselbe Aufgabe, überlappte ihr Vokabular.

## Warum es COMA braucht — der belegte Anlass

In einer **Remote-Control-Session** reicht Claude Code `--dangerously-skip-permissions`
nicht an den Remote-Client durch. Belegt durch die offenen Issues
[#71518](https://github.com/anthropics/claude-code/issues/71518) und
[#29214](https://github.com/anthropics/claude-code/issues/29214).

Folge: Jeder Tool-Aufruf fragt nach — auch bei Subagenten. Ist niemand am Rechner,
**stehen sie still**. Am 2026-07-26 real passiert: zwei Agenten warteten stundenlang.

Die Lösung ist nicht, mehr Regeln in eine Allowlist zu schreiben (das erzeugt nur
Klick-Ermüdung und eine Liste, die Zustimmung behauptet, die es nie gab), sondern den
Agenten **gar nicht erst in der RC-Session leben zu lassen**: ein eigener lokaler
Prozess, Kommunikation über das Dateisystem.

**Verifiziert am 2026-07-26:** Selbsttest aus einer laufenden RC-Session heraus
gestartet — Exit 0, keine einzige Berechtigungsabfrage. Danach ein echter Auftrag
(26 min, Opus) vollständig durchgelaufen, ohne dass der Nutzer etwas klicken musste.

## Warum eigenes Modul

- **llmauto** würde COMA importieren (es ist heute claude-only; die Multi-CLI-Fähigkeit
  kommt aus COMA).
- **swarm-ai** würde COMA importieren (spawnt heute selbst per `subprocess`).
- **Roshambo** würde COMA importieren — es koordiniert Agenten, erzeugt aber keine.

Drei Konsumenten aus drei Richtungen. Läge COMA in einem davon, müssten die anderen
zwei davon abhängen.

## Der entscheidende Trennungsgrund: Offline

Roshambo hängt an CockroachDB Cloud und AWS Bedrock. COMA arbeitet mit Dateien und
Prozessen — **ohne Konto, ohne Netz, ohne Cluster**.

Fällt die Cloud aus, muss der lokale Agentenbetrieb weiterlaufen. Ein Koordinator,
dessen Prozess-Substrat am selben Netz hängt wie er selbst, hat keinen Rückfallweg.
COMA ist deshalb das Substrat, auf dem Roshambo aufsetzt — nicht sein Konkurrent.

**`ellmos-agent-bridge` ist ebenfalls kein Konkurrent und kein künftiger
COMA-Importeur** — es verwaltet Partner-Metadaten (Fähigkeiten, Kosten,
Erreichbarkeit, Konfigurationsdateien) und trifft Empfehlungen, startet aber
nichts: im ganzen Paket kein einziger `subprocess`-Aufruf. Belegt in
`_agentjobs/OUT/coma-agentbridge-grenze.result.md`. Entsteht später eine Kopplung,
ist die einzig saubere Richtung agent-bridge → COMA, nie umgekehrt.

## Grenze: was Modul ist und was lokal bleibt

Damit das Modul nicht mit einer Maschine verwachsen geboren wird:

**Modul (allgemein, veröffentlichbar):**
- Das COMA-Protokoll (Verzeichnis- und Dateikonvention, siehe unten)
- Der Statusschreiber (`coma_status.py`)
- Die Spawn-Schicht mit **CLI-Adaptern**: claude, codex, agy, kimi — der Unterschied
  zwischen ihnen ist ein Kommando-Template plus Flags. Diese Adapter werden **aus
  bestehendem Code extrahiert** (`llmauto/core/runner.py`, `swarm-ai/tools/runner.py`,
  das Dungeon-Skript, `START-LOCAL-AGENT.bat`), nicht neu entworfen — sonst entsteht
  eine vierte Parallelimplementierung statt einer Konsolidierung.
- Poll-/Lese-Hilfen für Orchestratoren

**Lokal (Lukas-spezifisch, bleibt im `_control-center`):**
- `_control-center/_agentjobs/` — die konkreten Job-Verzeichnisse
- `START-LOCAL-AGENT.bat` — die Startschale, die aus Remote Control herausführt

Die `.bat` ist Umgehung eines Client-Bugs, keine allgemeine Fähigkeit. Sie gehört nicht
ins Modul.

## Protokoll: ein Schreiber je Datei

```
IN/    <jobid>.md                       Auftrag (Freitext-Markdown)
OUT/   <jobid>.result.md                Ergebnis
       coma.<jobid>.json               Status      — nur der Runner schreibt
       coma.<jobid>.from-agent.jsonl   Fortschritt — nur der Agent schreibt
       coma.<jobid>.to-agent.jsonl     Nachrichten — nur der Orchestrator schreibt
       coma.<jobid>.console.log        stdout/stderr des Laufs
DONE/  <jobid>.md                       erledigter Auftrag
```

**Ein Schreiber je Datei — kein Locking nötig, Kollision strukturell unmöglich.**
Gelesen werden darf von allen. Das ist keine Vorsichtsmaßnahme, sondern eine Lektion:
Eine geteilte Logdatei in OneDrive hat schon einmal zu Konfliktkopien geführt
(Ticket `T-20260621-44`, `_TICKETS/_logs/INTAKE-TRIAGE-LOG.txt`, seitdem deprecated).

`.jsonl` für die Kanäle, weil Anhängen atomar ist — ein Schreiber muss nicht erst
lesen, parsen und neu schreiben.

Bei mehreren Subagenten kommt eine zentrale Registry dazu (`coma-reg.json`, nur der
Operator schreibt) plus je Agent ein eigenes Status-JSON — das Muster aus
`swarm-ai/experiments/dungeon/elephant_path_treasure_hunt_live.py` (`live_<id>.json`
je Agent + `experiment_live.json` zentral).

## Harte Lektionen aus der Referenzimplementierung

**1. Der `-p`-Prompt bleibt kurz und zeichenarm.** Lauf 1 des Selbsttests starb
**still** — kein Ergebnis, Status blieb auf `running`, Fenster weg. Ursache: JSON mit
`\"` im Prompt. **CMD kennt keine Backslash-Escapes**, der Befehl zerriss. Alle
Anweisungen gehören in die Auftragsdatei; der Prompt zeigt nur darauf. (Dieselbe Regel
gilt im Ökosystem bereits für `agy` und `codex`.)

**2. Keine eingebetteten Interpreter-Einzeiler in der Startschale** — gleiches
Quoting-Problem. Statusschreiben liegt deshalb in einer eigenen Datei.

**3. Immer `> log 2>&1`.** Ein stiller Tod darf nicht möglich sein.

**4. `--permission-mode dontAsk` ist für unbeaufsichtigte Läufe die bessere Wahl als
Bypass** (Muster aus swarm-ai): Es fragt nie, sondern **verweigert**. Zusammen mit einer
expliziten Werkzeugliste kann ein Agent damit strukturell nicht hängenbleiben. Bypass
kann in Sonderfällen weiterhin nachfragen. „Verweigert und meldet das" ist besser als
„wartet auf einen Klick, den niemand gibt".

**5. `CLAUDECODE` aus der Umgebung entfernen** ist in swarm-ai üblich, war hier aber
**nicht nötig** — der Bypass wirkte auch ohne. Ob das Leeren überhaupt greift, ist
ungeklärt: Der Testagent maß `CLAUDECODE=1` innerhalb seines eigenen Bash-Aufrufs, und
Claude Code setzt die Variable für seine eigenen Subprozesse selbst. Er hat damit nicht
das geerbte Environment gemessen.

## Gegen eine Schnittstelle programmieren, nicht gegen lock-master

COMA ruft Claims über eine schmale Schnittstelle (`claim` / `release` / `status`) auf,
nicht gegen ein konkretes Modul. Dann ist der spätere Wechsel ein Zeilenwechsel im
Stack-Manifest statt eines Umbaus:

- `comalock` = COMA + lock-master (lokal, offline)
- `comaroshambo` = COMA + Roshambo (verteilt, Cloud)

## Herkunft

Referenzimplementierung entstanden am 2026-07-26 unter
`_control-center/_agentjobs/` + `START-LOCAL-AGENT.bat`; Protokoll dort in `README.md`.
Muster für Spawn und Live-Status aus `swarm-ai`, Claim-Semantik aus
`swarm-ai/tools/team_lock.py` (wird eigenes Modul `team-lock`).

## Not-Aus: WorkflowHooker gehört dazu, nicht daneben [U 2026-07-26]

Der Kanal `to-agent.jsonl` ist **kein Komfortmerkmal, sondern das fehlende Sicherheitsmerkmal**.
Ein Modul, dessen Zweck „läuft unbeaufsichtigt mit umgangener Berechtigungsabfrage" ist, braucht
einen Abbruchweg.

**Selbstprüfung an Prüfpunkten genügt dafür nicht.** Sie greift nur, wenn der Agent einen
Prüfpunkt erreicht — in einer Schleife oder einem langen Aufruf kommt er nie an. **Nur ein Hook
kann tatsächlich stoppen**, und nur `PreToolUse` kann einen Aufruf blockieren.

Das passt zur eigenen Regel von WorkflowHooker: „`PreToolUse` nur für **echte Blocker** —
niemals für Hinweise" (gemessen 287 ms je Tool-Aufruf). Ein Not-Aus ist der legitime Fall
dieser Regel, nicht ihre Ausnahme. Für Hinweise ohne Dringlichkeit bleibt `PostToolUse` mit
enger Bedingung (nur bei geänderter Datei-Mtime) oder die Selbstprüfung.

**Auslieferungsentscheidung:** COMA liefert WorkflowHooker als **Nachlader** mit — nicht als
harte Abhängigkeit, aber mit klarer Empfehlung. Begründung: Nutzer, die nur ein oder zwei
Module übernehmen, bekommen sonst ein Werkzeug für unbeaufsichtigte Läufe **ohne Not-Aus**.
COMA allein ist lauffähig; ohne Hooker fehlt aber die Möglichkeit, einen laufenden Agenten
von außen zu stoppen. Das gehört in die README, nicht ins Kleingedruckte.

Verwandt: WorkflowHooker plant bereits einen `TimeInjector` („Timebeat + ungelesene
Nachrichten") — der Zustellweg ist dort konzeptionell vorgesehen, Status heute
„Gerüst angelegt, nicht implementiert".

## Offen

Stand 2026-07-26, nach dem Bau des Moduls (`coma` 0.1.0, Ergebnisbericht:
`_agentjobs/OUT/coma-modul-bauen.result.md`).

- [x] `ellmos-module.v2.json` — liegt vor, mit Adapter-Abschnitt und Stand je Adapter
- [x] Lock-Schnittstelle definieren — `coma/locks.py`: `LockBackend` (Protocol
      mit `claim`/`release`/`status`), `NullLock`, Kontextmanager `claimed()`.
      **Nur definiert**, nicht implementiert; kein Import von `lock-master`,
      `team-lock` oder Roshambo (per Test abgesichert)
- [~] CLI-Adapter über claude hinaus — `codex`, `agy`, `kimi` liegen als **Gerüst**
      vor: Kommandobau nach den Konventionen aus `~/CLAUDE.md`, getestet, mit
      dokumentierten Fallstricken. **Nicht live geprüft** (`verified = False`);
      der Spawner verweigert sie ohne ausdrückliches `allow_unverified=True`.
      Offen bleibt je Adapter ein echter Durchlauf
- [ ] Zentrale Registry `coma-reg.json` für Mehr-Agenten-Betrieb — nicht gebaut.
      Der Spawner kann bereits nebenläufig starten (`run_many`, `ProcessHandle`,
      `wait_all`), aber es gibt kein zentrales Verzeichnis über mehrere Agenten
- [x] Entscheidung: öffentlich (Sichtbarkeit `public`) — MIT-Lizenz gesetzt am
      2026-07-26. Begründung: COMA startet lokale Prozesse und schreibt
      Dateien, hat keine Netzfläche; eine netzauslösende Copyleft-Klausel wie
      AGPL §13 würde hier nie greifen. Details:
      `_agentjobs/OUT/coma-lizenz-und-metarepo.result.md`. **Tatsächliche
      Veröffentlichung (Push, OneDrive-Spiegelung, Katalog-Eintrag) steht
      weiterhin aus** — bewusst nicht Teil dieses Laufs
- [ ] `llmauto` und `swarm-ai` auf COMA umhängen — ausdrücklich **nicht** Teil
      des Bau-Auftrags; eigener, späterer Schritt. Beide bauen heute weiterhin
      ihre eigenen `claude`-Aufrufe
- [ ] Plan-D-Deploy: Quellkopie nach `.CONTROL/coma/` in OneDrive — kommt separat,
      jetzt, da das Modul steht
- [ ] Widerspruch in der Referenzimplementierung: `_agentjobs/README.md:25`
      dokumentiert `OUT/<jobid>.status` mit Inhalt `"running" -> "done <exitcode>"`.
      Real geschrieben wird `OUT/coma.<jobid>.json`. Das Modul folgt der `.bat`
      und diesem Konzept; die README ist zu korrigieren
