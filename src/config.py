"""Loads configuration from .env."""

import os

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes"}


MUSE_SPARK_PROVIDER = os.getenv("MUSE_SPARK_PROVIDER", "baseten").strip().lower()

# Meta Model API (SAM 3.1 always goes through this, since Meta models must
# be used centrally; Muse Spark optionally through this too if PROVIDER=meta).
META_BASE_URL = "https://api.meta.ai/v1"
META_API_KEY = os.getenv("META_API_KEY", "")
META_SAM_MODEL = os.getenv("META_SAM_MODEL", "sam-3.1")
META_MUSE_SPARK_MODEL = os.getenv("META_MUSE_SPARK_MODEL", "muse-spark-1.3")

# Baseten (Muse Spark Open, default due to the open-weights bonus prize).
BASETEN_BASE_URL = "https://inference.baseten.co/v1"
BASETEN_API_KEY = os.getenv("BASETEN_API_KEY", "")
# The hackathon guide names "meta-models/muse-spark-open-1026", the Meta
# docs name "meta-models/muse-spark-open" - which one is actually available
# is checked at runtime via client.models.list() (see api_clients.py).
BASETEN_MUSE_SPARK_MODEL = os.getenv("BASETEN_MUSE_SPARK_MODEL", "meta-models/muse-spark-open-1026")

# As long as no API key is set, the clients run in mock mode so the rest
# of the pipeline can already be tested.
MOCK_MODE = _get_bool("MOCK_MODE", default=not (META_API_KEY or BASETEN_API_KEY))
