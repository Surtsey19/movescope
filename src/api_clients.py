"""Clients für SAM 3.1 (Segmentierung) und Muse Spark (Vision/Text).

Beide APIs sind OpenAI-SDK-kompatibel (siehe Meta-Hackathon-Doku):
- Meta Model API: base_url=https://api.meta.ai/v1 (SAM 3.1 + Muse Spark)
- Baseten:         base_url=https://inference.baseten.co/v1 (Muse Spark Open)

SAM 3.1 wird pro Einzelbild aufgerufen (nicht per Video-Upload), weil wir die
Bildanzahl bereits in frame_extraction.py auf max. 15 Bilder/Raum begrenzen,
um die API-Kosten im Griff zu behalten. Ein SAM-Request fragt nach genau
einer Objektart (z.B. "sofa") - für mehrere Objektarten sind mehrere
Requests nötig (siehe BASE_OBJECT_TERMS unten).

Objekt-Tracking über mehrere Frames (stabile object_id) ist bei
Video-Uploads möglich, bei Einzelbild-Requests aber nicht gegeben. Die
Dedup-Entscheidung aus der Aufgabenstellung ("wenn Tracking nicht stabil:
nur Einzelbilder + Doppelungen per Muse Spark zusammenführen") ist hier
bereits getroffen: Dedup passiert semantisch über
MuseSparkClient.merge_duplicate_detections() (siehe dort).

Die Kategorie wird per JSON-Schema-Enum auf die Schlüssel von
volume.CATEGORY_VOLUMES_M3 festgelegt, damit die anschließende
Volumenberechnung (deterministisch, siehe volume.py) immer einen gültigen
Tabelleneintrag findet.
"""

import base64
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from openai import OpenAI
from PIL import Image

from . import config
from .volume import CATEGORY_VOLUMES_M3

_ALLOWED_CATEGORIES = list(CATEGORY_VOLUMES_M3.keys())

# Generische Objektbegriffe für SAM-Anfragen - bewusst auf Englisch.
# Live getestet (siehe Testmaterial in test_media/): SAM 3.1 reagiert auf
# deutsche Begriffe unzuverlässig (z.B. "waschmaschine": 0 Treffer trotz
# sichtbarer Waschmaschine im Bild, "tisch"/"stuhl"/"kühlschrank" ebenso
# 0 Treffer), während die englischen Äquivalente ("washing machine",
# "table", "chair", "fridge") zuverlässig treffen. Das deutsche
# Wohnzimmer-Video hatte den Bug zunächst verdeckt, weil "sofa" und
# "lampe" als Zufallstreffer fast identisch zum Englischen sind.
# Muse Spark verfeinert aus dem SAM-Treffer später die genaue deutsche
# Kategorie (z.B. "table" -> "Esstisch").
BASE_OBJECT_TERMS: list[str] = [
    "sofa", "armchair", "table", "chair", "bed", "wardrobe", "dresser",
    "shelf", "desk", "tv", "fridge", "washing machine", "dishwasher",
    "lamp", "mirror", "rug", "microwave", "coffee machine", "kettle",
    "toaster",
]

_FRAME_RE = re.compile(r"^<(\d+)f>(.*)$")
_BOX_RE = re.compile(
    r"<\|box;x1=(-?\d+);y1=(-?\d+);x2=(-?\d+);y2=(-?\d+);w=(-?\d+);h=(-?\d+)(?:;[^|]*)?\|>"
)
_ENTRY_SPLIT_RE = re.compile(r",(?=-?\d+<)")
_ENTRY_ID_RE = re.compile(r"^(-?\d+)")


class ApiNotConfiguredError(RuntimeError):
    """Wird geworfen, wenn ein echter (nicht-Mock) Call versucht wird, aber
    der API-Key fehlt."""


def _image_to_data_url(image_path: str) -> str:
    mime, _ = mimetypes.guess_type(image_path)
    mime = mime or "image/jpeg"
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def parse_sam_output(output_text: str) -> list[dict[str, Any]]:
    """Parst die SAM-3.1-Spezialtoken-Ausgabe in eine Liste von
    {frame, object_id, box=(x1,y1,x2,y2)}. Maskendaten werden ignoriert, da
    wir nur die Bounding Box zum Croppen brauchen. Leerer Text (kein
    Treffer) gibt eine leere Liste zurück."""
    results: list[dict[str, Any]] = []
    if not output_text or not output_text.strip():
        return results

    for line in output_text.strip().splitlines():
        frame_match = _FRAME_RE.match(line.strip())
        if not frame_match:
            continue
        frame_idx = int(frame_match.group(1))
        rest = frame_match.group(2)

        for entry in _ENTRY_SPLIT_RE.split(rest):
            id_match = _ENTRY_ID_RE.match(entry)
            box_match = _BOX_RE.search(entry)
            if not id_match or not box_match:
                continue
            x1, y1, x2, y2, _w, _h = (int(v) for v in box_match.groups())
            results.append({
                "frame": frame_idx,
                "object_id": int(id_match.group(1)),
                "box": (x1, y1, x2, y2),
            })
    return results


class SamClient:
    """Lokalisiert Objekte einer gegebenen Art (z.B. "sofa") in einem
    Einzelbild über SAM 3.1."""

    def __init__(self, mock_mode: bool | None = None):
        self.mock_mode = config.MOCK_MODE if mock_mode is None else mock_mode
        self._client: OpenAI | None = None
        if not self.mock_mode:
            if not config.META_API_KEY:
                raise ApiNotConfiguredError(
                    "META_API_KEY fehlt. Entweder .env ergänzen oder MOCK_MODE=true setzen."
                )
            self._client = OpenAI(base_url=config.META_BASE_URL, api_key=config.META_API_KEY)

    def find_objects(self, image_path: str, term: str) -> list[dict[str, Any]]:
        """Gibt eine Liste von {object_id, box=(x1,y1,x2,y2)} für Treffer
        von `term` im Bild zurück (leer, wenn kein Treffer)."""
        if self.mock_mode:
            return self._mock_find(image_path, term)

        output_chunks: list[str] = []
        with self._client.responses.stream(
            model=config.META_SAM_MODEL,
            input=[{
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": term},
                    {"type": "input_image", "image_url": _image_to_data_url(image_path)},
                ],
            }],
        ) as stream:
            for event in stream:
                if event.type == "response.output_text.delta":
                    output_chunks.append(event.delta)

        parsed = parse_sam_output("".join(output_chunks))
        return [{"object_id": r["object_id"], "box": r["box"]} for r in parsed if r["frame"] == 0]

    @staticmethod
    def _mock_find(image_path: str, term: str) -> list[dict[str, Any]]:
        # Platzhalter ohne echten API-Call: nur der erste Begriff pro Bild
        # "findet" ein Objekt, das das ganze Bild abdeckt.
        if term != BASE_OBJECT_TERMS[0]:
            return []
        with Image.open(image_path) as img:
            w, h = img.size
        return [{"object_id": 0, "box": (0, 0, w, h)}]


_DESCRIBE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "category": {"type": "string", "enum": _ALLOWED_CATEGORIES},
        "fragile": {"type": "boolean"},
        "customs_relevant": {"type": "boolean"},
        "customs_note": {"type": "string"},
    },
    "required": ["name", "category", "fragile", "customs_relevant", "customs_note"],
    "additionalProperties": False,
}

_MERGE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "category": {"type": "string", "enum": _ALLOWED_CATEGORIES},
                    "count": {"type": "integer"},
                    "fragile": {"type": "boolean"},
                    "customs_relevant": {"type": "boolean"},
                    "customs_note": {"type": "string"},
                },
                "required": ["name", "category", "count", "fragile", "customs_relevant", "customs_note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}


class MuseSparkClient:
    """Vision+Text-Modell: beschreibt Objekte und erstellt Packpläne.
    Umschaltbar zwischen Meta API und Baseten über MUSE_SPARK_PROVIDER."""

    def __init__(self, mock_mode: bool | None = None):
        self.mock_mode = config.MOCK_MODE if mock_mode is None else mock_mode
        self.provider = config.MUSE_SPARK_PROVIDER
        self._client: OpenAI | None = None
        self._model: str | None = None
        if not self.mock_mode:
            if self.provider == "meta":
                if not config.META_API_KEY:
                    raise ApiNotConfiguredError("META_API_KEY fehlt (oder MOCK_MODE=true setzen).")
                self._client = OpenAI(base_url=config.META_BASE_URL, api_key=config.META_API_KEY)
                self._model = config.META_MUSE_SPARK_MODEL
            else:
                if not config.BASETEN_API_KEY:
                    raise ApiNotConfiguredError("BASETEN_API_KEY fehlt (oder MOCK_MODE=true setzen).")
                self._client = OpenAI(base_url=config.BASETEN_BASE_URL, api_key=config.BASETEN_API_KEY)
                self._model = self._resolve_baseten_model()

    def _resolve_baseten_model(self) -> str:
        """Prüft, welcher Modellname verfügbar ist: der aus dem
        Hackathon-Leitfaden ("...-1026") oder der aus der Meta-Doku (ohne
        Suffix)."""
        configured = config.BASETEN_MUSE_SPARK_MODEL
        try:
            available = {m.id for m in self._client.models.list().data}
        except Exception:
            return configured
        if configured in available:
            return configured
        fallback = "meta-models/muse-spark-open"
        if fallback in available:
            return fallback
        return configured

    def describe_object(self, image_crop_path: str, term_hint: str = "") -> dict[str, Any]:
        """Beschreibt einen Objekt-Ausschnitt: Name, Kategorie, zerbrechlich,
        Zoll-relevant."""
        if self.mock_mode:
            return self._mock_describe(image_crop_path, term_hint)

        hint = f" (SAM-Erkennung deutet auf: {term_hint})" if term_hint else ""
        prompt = (
            "Beschreibe den Gegenstand im Bild für eine Umzugsinventarliste"
            f"{hint}. Antworte ausschließlich als JSON mit den Feldern: "
            "name (deutsch, kurzer konkreter Name, z.B. 'Graues Ecksofa'), "
            "category (MUSS GENAU einer dieser Werte sein: "
            f"{', '.join(_ALLOWED_CATEGORIES)} - wähle den am besten "
            "passenden, sonst 'sonstiges'), fragile (bool), "
            "customs_relevant (bool, z.B. true bei Alkohol/Tabak/Waffen), "
            "customs_note (kurzer Hinweis oder leerer String)."
        )
        content = self._chat(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _image_to_data_url(image_crop_path)}},
                ],
            }],
            reasoning_effort="low",
            max_tokens=2000,
            json_schema=_DESCRIBE_SCHEMA,
        )
        return self._parse_json_content(content)

    def merge_duplicate_detections(self, detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Fasst rohe Einzelbild-Erkennungen zu einer Liste tatsächlich
        unterschiedlicher physischer Gegenstände zusammen. Nötig, weil SAM
        pro Einzelbild ohne Tracking läuft: dasselbe Möbelstück wird über
        mehrere Frames hinweg mehrfach erkannt, oft mit leicht
        unterschiedlicher Beschreibung (z.B. "Graues Sofa" vs. "Ecksofa
        hellgrau"). Das ist die in der Aufgabenstellung vorgesehene
        Fallback-Strategie bei fehlendem/instabilem SAM-Tracking."""
        if not detections:
            return []
        if self.mock_mode:
            return self._mock_merge(detections)

        prompt = (
            "Die folgenden Objekterkennungen stammen aus mehreren "
            "Einzelbildern desselben Raums, aufgenommen beim Durchlaufen des "
            "Raums mit dem Handy. Viele Erkennungen zeigen vermutlich "
            "dasselbe physische Möbelstück aus verschiedenen Blickwinkeln "
            "bzw. mit leicht unterschiedlicher Beschreibung. Fasse sie zu "
            "einer Liste tatsächlich unterschiedlicher physischer "
            "Gegenstände zusammen. 'count' = Anzahl der REALEN physischen "
            "Objekte in diesem Raum (nicht Anzahl der Erkennungen). "
            "category MUSS GENAU einer dieser Werte sein: "
            f"{', '.join(_ALLOWED_CATEGORIES)} - wähle pro Gegenstand den "
            "am besten passenden, sonst 'sonstiges'. "
            f"Erkennungen:\n{json.dumps(detections, ensure_ascii=False)}"
        )
        content = self._chat(
            messages=[{"role": "user", "content": prompt}],
            reasoning_effort="medium",
            max_tokens=4000,
            json_schema=_MERGE_SCHEMA,
        )
        parsed = self._parse_json_content(content)
        items = parsed.get("items")
        if not items:
            return self._mock_merge(detections)
        return items

    def generate_packing_plan(self, inventory_by_room: dict[str, list[dict]]) -> str:
        """Erstellt einen Packplan Raum für Raum als Text."""
        if self.mock_mode:
            return self._mock_packing_plan(inventory_by_room)

        prompt = (
            "Erstelle einen kurzen, praktischen Packplan Raum für Raum für "
            "einen Umzug von Deutschland in die Schweiz, basierend auf dieser "
            f"Inventarliste (JSON): {json.dumps(inventory_by_room, ensure_ascii=False)}"
        )
        content = self._chat(
            messages=[{"role": "user", "content": prompt}],
            reasoning_effort="medium",
            max_tokens=8000,
        )
        return content

    def _chat(
        self,
        messages: list[dict[str, Any]],
        reasoning_effort: str,
        max_tokens: int,
        json_schema: dict | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "extra_body": {"reasoning_effort": reasoning_effort},
        }
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "object_description", "schema": json_schema, "strict": True},
            }
        response = self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    @staticmethod
    def _parse_json_content(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {
                "name": "Unbekannter Gegenstand",
                "category": "sonstiges",
                "fragile": False,
                "customs_relevant": False,
                "customs_note": "",
            }

    @staticmethod
    def _mock_describe(image_crop_path: str, term_hint: str) -> dict[str, Any]:
        stem = Path(image_crop_path).stem
        category = term_hint or "sonstiges"
        return {
            "name": f"{category.capitalize()} ({stem})",
            "category": category,
            "fragile": False,
            "customs_relevant": False,
            "customs_note": "",
        }

    @staticmethod
    def _mock_merge(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Naiver Fallback (Mock-Modus oder leere Modell-Antwort): exakte
        # Übereinstimmung von Name+Kategorie zählt als dasselbe Objekt.
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for desc in detections:
            key = (desc["name"], desc["category"])
            if key not in merged:
                merged[key] = {**desc, "count": 0}
            merged[key]["count"] += 1
        return list(merged.values())

    @staticmethod
    def _mock_packing_plan(inventory_by_room: dict[str, list[dict]]) -> str:
        lines = ["Packplan (Mock-Daten, noch keine echte API verbunden):"]
        for room, items in inventory_by_room.items():
            lines.append(f"\n{room}:")
            for item in items:
                lines.append(f"  - {item.get('name', 'Gegenstand')} sorgfältig verpacken")
        return "\n".join(lines)
