"""Minimal-Test der beiden APIs, wie in der Aufgabenstellung gefordert:
1) SAM 3.1 auf einem Einzelbild
2) Muse Spark 1.3 (Meta) mit einem Bild
3) Baseten models.list() + ein Testaufruf

Aufruf:
    python scripts/minimal_api_test.py path/zu/einem/foto.jpg

Ohne API-Keys in .env läuft das Skript im MOCK_MODE und zeigt nur, dass der
Code fehlerfrei durchläuft - für den echten Test müssen META_API_KEY bzw.
BASETEN_API_KEY in .env gesetzt sein.
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.api_clients import ApiNotConfiguredError, BASE_OBJECT_TERMS, MuseSparkClient, SamClient


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/minimal_api_test.py <bild.jpg>")
        sys.exit(1)

    image_path = sys.argv[1]
    if not Path(image_path).exists():
        print(f"Bild nicht gefunden: {image_path}")
        sys.exit(1)

    print(f"MOCK_MODE = {config.MOCK_MODE}")
    print(f"MUSE_SPARK_PROVIDER = {config.MUSE_SPARK_PROVIDER}")
    print()

    print("=== 1) SAM 3.1 Einzelbild-Test ===")
    try:
        sam = SamClient()
        for term in BASE_OBJECT_TERMS[:3]:
            hits = sam.find_objects(image_path, term)
            print(f"  '{term}': {len(hits)} Treffer -> {hits}")
    except ApiNotConfiguredError as e:
        print(f"  Übersprungen: {e}")

    print()
    print("=== 2) Muse Spark Vision-Test ===")
    try:
        muse = MuseSparkClient()
        desc = muse.describe_object(image_path, term_hint="sofa")
        print(f"  Beschreibung: {desc}")
    except ApiNotConfiguredError as e:
        print(f"  Übersprungen: {e}")

    print()
    print("=== 3) Baseten models.list() + Testaufruf ===")
    if config.MOCK_MODE:
        print("  Übersprungen (MOCK_MODE aktiv, kein BASETEN_API_KEY).")
    else:
        from openai import OpenAI

        client = OpenAI(base_url=config.BASETEN_BASE_URL, api_key=config.BASETEN_API_KEY)
        models = [m.id for m in client.models.list().data]
        print(f"  Verfügbare Modelle: {models}")
        plan = muse.generate_packing_plan({"Testraum": [desc]})
        print(f"  Packplan-Testaufruf: {plan[:300]}")


if __name__ == "__main__":
    main()
