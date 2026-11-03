"""Lädt Konfiguration aus .env."""

import os

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes"}


MUSE_SPARK_PROVIDER = os.getenv("MUSE_SPARK_PROVIDER", "baseten").strip().lower()

# Meta Model API (SAM 3.1 immer hierüber, da Meta-Modelle zentral genutzt
# werden müssen; Muse Spark optional auch hierüber wenn PROVIDER=meta).
META_BASE_URL = "https://api.meta.ai/v1"
META_API_KEY = os.getenv("META_API_KEY", "")
META_SAM_MODEL = os.getenv("META_SAM_MODEL", "sam-3.1")
META_MUSE_SPARK_MODEL = os.getenv("META_MUSE_SPARK_MODEL", "muse-spark-1.3")

# Baseten (Muse Spark Open, Standard wegen Open-Weights-Bonuspreis).
BASETEN_BASE_URL = "https://inference.baseten.co/v1"
BASETEN_API_KEY = os.getenv("BASETEN_API_KEY", "")
# Hackathon-Leitfaden nennt "meta-models/muse-spark-open-1026", die Meta-Doku
# "meta-models/muse-spark-open" - welcher Name verfügbar ist, wird zur
# Laufzeit per client.models.list() geprüft (siehe api_clients.py).
BASETEN_MUSE_SPARK_MODEL = os.getenv("BASETEN_MUSE_SPARK_MODEL", "meta-models/muse-spark-open-1026")

# Solange kein API-Key gesetzt ist, laufen die Clients im Mock-Modus, damit
# der Rest der Pipeline schon getestet werden kann.
MOCK_MODE = _get_bool("MOCK_MODE", default=not (META_API_KEY or BASETEN_API_KEY))
