# MoveScope

Aus einem Handyvideo eines Raums wird eine fertige Umzugsplanung inklusive
Inventarliste für den Schweizer Zoll (Umzug von Deutschland in die Schweiz).

Projekt für den Meta Global AI Developer Hackathon (Indie Track).

## Pipeline

1. Video einlesen, ca. 1 Bild/Sekunde extrahieren (max. 15 Bilder pro Raum)
2. SAM 3.1: Möbel/Gegenstände segmentieren und über die Bilder verfolgen
3. Muse Spark (Vision): pro Objekt Name, Kategorie, zerbrechlich, Zoll-Hinweis
4. Volumen deterministisch aus Kategorie-Tabelle in Python berechnen
5. Muse Spark: Packplan Raum für Raum
6. Export: Inventartabelle, Zusammenfassung, Packplan, Zoll-Inventarliste (PDF + CSV)
7. Streamlit-UI: Video hochladen → Fortschritt → Ergebnisse mit Downloads

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# .env mit den eigenen API-Keys befüllen
```

## Starten

```powershell
streamlit run src/app.py
```

## Modellwahl

Per `.env`-Einstellung `MUSE_SPARK_PROVIDER` umschaltbar zwischen:
- `meta` – Meta Model API (SAM 3.1, Muse Spark)
- `baseten` – Muse Spark Open über Baseten (Standard, Bonuspreis Open-Weights)

## Status

Projekt im Aufbau (Hackathon-Deadline: 05.11., 03:00 Uhr).
