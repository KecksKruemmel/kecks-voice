<div align="center">

# KecksVoice

Lokales Push-to-Talk-Diktieren für Windows. Taste halten, sprechen, loslassen,
und der Text landet im aktiven Fenster. Ohne Cloud, ohne Konto, ohne API-Key.

![KecksVoice Screenshot](docs/screenshot.png)

</div>

## Funktionen

- **Push-to-Talk:** frei wählbare Taste, zum Beispiel die rechte Shift-Taste.
- **Lokale Spracherkennung** mit [faster-whisper](https://github.com/SYSTRAN/faster-whisper) auf der CPU.
- **Fügt direkt ein:** in jedes Programm, die Zwischenablage bleibt erhalten.
- **Räumt auf:** Füllwörter wie „äh“ und „ähm“ werden entfernt.
- **Optionale Nachbearbeitung:** Ein lokales [Ollama](https://ollama.com)-Modell glättet Selbstkorrekturen.
- **Kleine Statusanzeige** am unteren Bildschirmrand mit Pegel während der Aufnahme.
- **Verlauf:** Ein Klick kopiert einen früheren Text erneut.
- **Infobereich und Autostart:** läuft im Hintergrund.
- **Darstellung:** Dunkel oder Glas (Acrylic-Effekt unter Windows 11).
- **Pegelanzeige:** zeigt live, ob das Mikrofon etwas hört.
- Deutsch, Englisch oder automatische Spracherkennung.

## Schnellstart

Voraussetzungen: Windows 10/11, Python 3.10+ und ein Mikrofon.

```bat
git clone https://github.com/<dein-name>/kecks-voice.git
cd kecks-voice
python -m pip install -r requirements.txt
python kecksvoice.py
```

Beim ersten Start lädt faster-whisper das gewählte Modell einmalig von Hugging Face herunter.
Danach läuft alles offline.

### Als EXE bauen

```bat
build.bat
```

Danach liegt `dist\KecksVoice.exe` bereit. Die Datei braucht kein installiertes Python.

## Bedienung

| Aktion | So geht's |
|---|---|
| Diktieren | Aufnahme-Taste **halten**, sprechen, **loslassen** |
| Taste ändern | Auf die Tastenkappe klicken, neue Taste drücken (Esc bricht ab) |
| Text erneut kopieren | Im *Verlauf* auf einen Eintrag klicken |
| Fenster schließen | Die App läuft im Infobereich weiter, *Beenden* schließt sie ganz |

### Modelle

| Modell | Geschwindigkeit | Genauigkeit |
|---|---|---|
| Tiny / Base | sehr schnell | okay |
| **Small** (Standard) | schnell | gut |
| Medium | langsamer | sehr gut |
| Large | langsam | am besten |

### Nachbearbeitung mit Ollama (optional)

1. [Ollama](https://ollama.com) installieren.
2. Das Modell holen: `ollama pull llama3.2`.
3. In KecksVoice *Nachbearbeitung mit Ollama* einschalten.

Aus „Wir treffen uns um drei, nein, um vier“ wird dann „Wir treffen uns um vier.“

## Konfiguration

Die Einstellungen liegen in `kecksvoice.json` neben der App und werden automatisch angelegt:

```json
{
  "hotkey": "right ctrl",
  "model": "small",
  "language": "auto",
  "ollama": false,
  "ollama_model": "llama3.2",
  "autostart": false,
  "theme": "dark"
}
```

## Datenschutz

- Audio verlässt nie deinen Rechner und wird nicht gespeichert.
- Der Verlauf existiert nur im Arbeitsspeicher und ist nach dem Beenden weg.
- Netzwerkzugriff gibt es nur beim einmaligen Modell-Download und, falls aktiviert, zu Ollama auf `localhost`.

## Lizenz

[MIT](LICENSE)
