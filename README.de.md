# makeextreme (登峰)

[English](README.md) · [中文](README.zh.md) · Deutsch

Ein kleiner Unterbau für Agenten-Pipelines, deren Stufen im Voraus bekannt sind. Er führt die Stufen einer Aufgabe
nacheinander aus, entscheidet „fertig“ am **Artefakt** (nicht am Exit-Code), setzt nach einem Absturz bei der
letzten grünen Stufe fort und gibt eine nicht umkehrbare Stufe nie von selbst frei.

## Stand

- Version 1.0.0, ein Autor, nur Linux, nur die Python-Standardbibliothek; getestet mit Python 3.11 und 3.14.
- Der Code wurde von einem KI-Agenten (Claude Sonnet 5.5 in Hermes) im Auftrag des Eigentümers geschrieben.
- **Veröffentlicht vor dem unabhängigen Abschluss-Audit.** Das war eine einmalige Ausnahme des Eigentümers am
  2026-11-01. Der M1-Kern hatte fünf Meilenstein-Audits, jeweils durch eine frische Sonnet-5.5-Sitzung mit
  Lesezugriff auf das Repository (dieselbe Modellfamilie wie der Autor, kein anderes Modell); das fünfte bestand
  (0 Blocker, 0 Major, 1 Minor, 3 Plan-Punkte). Ein tieferes Audit folgt noch.
- Mit keinem anderen Werkzeug verglichen, daher keine Rangaussage.

## Was es tut

`python -m makeextreme run <task_dir>` liest `<task_dir>/stages.json` und führt die Stufen der Reihe nach aus:

```json
[{"id": "ocr", "run": "sh bin/ocr.sh",
  "check": "test $(ls ocr | wc -l) -eq $(ls frames | wc -l)", "deps": ["frames", "bin/ocr.sh"]}]
```

- Eine Stufe ist nur fertig, wenn `run` mit 0 endet **und** `check` am echten Ergebnis ebenfalls mit 0 endet.
- Eine fertige Stufe wird beim nächsten Lauf übersprungen, außer ihr Befehl oder der Inhalt einer deklarierten
  Abhängigkeit (`deps`) hat sich geändert.
- Eine Stufe mit `"approval": "required"` (sie muss `deps` angeben) wartet auf `python -m makeextreme approve <task_dir> <stage>`. Die Freigabe ist an die Stufe und den Hash ihres Artefakts gebunden, und eine Freigabe
  erlaubt genau eine Ausführung. Stürzt so eine Stufe ab oder schlägt sie fehl, wird sie *unsicher* und nie
  automatisch wiederholt; erst die Außenwelt prüfen, dann `python -m makeextreme resolve <task_dir> <stage> --done`
  oder `--retry`.

Exit-Codes von `run`: `0` fertig, `2` eine Stufe ist fehlgeschlagen, `3` von einem lebenden Runner gesperrt,
`4` wartet auf Freigabe, `5` eine unsichere Stufe braucht `resolve`, `6` abgelehnt (ein schlüsselähnlicher Wert im
Protokoll), `64` ungültige oder fehlende `stages.json` oder Aufgabenverzeichnis.

## Was gemessen wurde

- 96 Tests (`python -m unittest discover -s tests -p 'test_*.py'`) und 77 Mutanten
  (`python tests/mutants.py all`, etwa 3 Minuten): jeder Mutant lässt mindestens einen Test fehlschlagen.
- **AC10, Video-Pipeline** (`examples/video_pipeline/`): Download, Audio, Transkript, Frames, OCR, Zusammenbau und
  Auslieferung als Stufen. Bei einem 38-Sekunden-Video führte `kill -9` auf den Runner während der OCR (nach 1, 4,
  9 und 17 Frames sowie einmal mit echtem Download von der URL) und ein zweiter `run` dazu, dass alle 7 Artefakte
  byteidentisch zu einem ununterbrochenen Lauf waren, keine fertige Stufe zweimal lief und kein Waisenprozess
  zurückblieb. Drei absichtlich kaputte Runner-Varianten lassen diese Prüfung fehlschlagen
  (`python examples/video_pipeline/ac10_mutants.py`).
- Whisper ist auf der verwendeten Maschine nicht bitgenau deterministisch: derselbe Clip ergab etwa bei jedem 6. bis
  10. Lauf ein anderes Transkript. Das Beispiel legt Transkripte deshalb nach dem Hash ihres Audios ab, und AC10
  zeigt, dass die Wiederaufnahme stimmt, nicht dass die Transkription deterministisch ist.
- **AC9, Hermes-Host** (`examples/hermes_host/ac9.py`): eine Stufe führt `hermes chat --oneshot` unter `env -i`
  aus, die Antwort wird erfasst und geprüft; ein falscher Modellname lässt die Stufe fehlschlagen, und eine Stufe
  ohne `env -i` besteht die Canary-Prüfung nicht.
- **Zeitsteuerung**: `examples/cron_tick.sh <task_dir>` startet pro Cron-Takt einen Worker und berichtet;
  makeextreme hat absichtlich keinen Watchdog.

## Bekannte Grenzen

- `approve` kann nicht erkennen, wer es getippt hat. Es verhindert eine versehentliche Freigabe, keinen Agenten, der
  deine Shell hält.
- Eine Stufe, die `setsid` aufruft und ihre Umgebung leert, wird nach einem Absturz weder gefunden noch beendet;
  ein Kindprozess, der SIGTERM ignoriert, lebt bis zum nächsten `run`.
- Zustand (`task.json`) und Journal (`journal.jsonl`) sind zwei Schreibvorgänge; nach einem Absturz dazwischen kann
  das Journal einen Eintrag zurückliegen. Maßgeblich ist `task.json`.
- Das Entwurfsprotokoll mit allen von den Audits gefundenen Grenzen ist `ARCHITECTURE.md` (auf Chinesisch).

## Lizenz

Apache-2.0, siehe `LICENSE`. `makeextreme/secret_scan.py` ist aus [Longhaul](https://github.com/dacheng-lu/longhaul)
kopiert (Apache-2.0); andere Projekte lieferten nur Ideen (`NOTICE.md`, `docs/SOURCES.md`). Ein weiterer gesehener,
nicht bewerteter wiederaufnehmbarer Pipeline-Runner: [areeves/revenant](https://github.com/areeves/revenant).
