# MoveScope

Turns a phone video of a room into a complete relocation plan, including
an inventory list for Swiss customs (move from Germany to Switzerland).

Project for the Meta Global AI Developer Hackathon (Indie Track).

## Pipeline

1. Read the video, extract ~1 frame/second (max. 15 frames per room)
2. SAM 3.1: locate furniture/objects per frame (Meta Model API)
3. Muse Spark (vision): per object, derive name, category, fragile, customs note
4. Muse Spark merges duplicate detections across frames into real physical objects
5. Volume computed deterministically from a Python category table (not estimated by the LLM)
6. Muse Spark: room-by-room packing plan
7. Export: inventory table, summary, packing plan, customs inventory list (PDF + CSV)
8. Streamlit UI: upload video → progress → results with downloads

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# fill in your own API keys in .env
```

## Run

```powershell
streamlit run src/app.py
```

## Model choice

Switchable via the `.env` setting `MUSE_SPARK_PROVIDER`:
- `meta` – Meta Model API (SAM 3.1, Muse Spark)
- `baseten` – Muse Spark Open via Baseten (default, open-weights bonus prize)

## Dev tooling

- `scripts/minimal_api_test.py` – quick sanity check against the real APIs
- `scripts/browser_test.py` – Playwright smoke test of the Streamlit UI
- `tools/generate_test_media.py` – generates synthetic room photos/videos via Muse Image
- `tools/record_demo.py` / `tools/build_demo_video.py` – records and assembles the demo video

Install dev dependencies with `pip install -r requirements-dev.txt`.
