"""Clients for SAM 3.1 (segmentation) and Muse Spark (vision/text).

Both APIs are OpenAI-SDK-compatible (per the Meta hackathon docs):
- Meta Model API: base_url=https://api.meta.ai/v1 (SAM 3.1 + Muse Spark)
- Baseten:         base_url=https://inference.baseten.co/v1 (Muse Spark Open)

SAM 3.1 is called per single image (not via video upload) because we
already cap the image count in frame_extraction.py at max. 15 images/room
to keep API costs under control. One SAM request asks about exactly one
object type (e.g. "sofa") - multiple object types need multiple requests
(see BASE_OBJECT_TERMS below).

Object tracking across frames (a stable object_id) is possible with video
uploads, but not with single-image requests. The dedup decision from the
task brief ("if tracking isn't reliable: segment single images and merge
duplicates via Muse Spark") is already made here: dedup happens
semantically via MuseSparkClient.merge_duplicate_detections() (see there).

The category is constrained via a JSON-schema enum to the keys of
volume.CATEGORY_VOLUMES_M3, so the downstream (deterministic, see
volume.py) volume calculation always finds a valid table entry.
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

# Generic object terms for SAM queries - deliberately in English.
# Live-tested (see test footage in test_media/): SAM 3.1 responds to
# German terms unreliably (e.g. "waschmaschine": 0 hits despite a visible
# washing machine in the frame; "tisch"/"stuhl"/"kühlschrank" likewise
# 0 hits), while the English equivalents ("washing machine", "table",
# "chair", "fridge") hit reliably. The original living-room test video
# had masked this bug because "sofa" and "lampe" happen to be near-
# cognates of English. Muse Spark later refines the SAM hit into the
# exact category (e.g. "table" -> "dining table").
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
    """Raised when a real (non-mock) call is attempted but the API key is
    missing."""


def _image_to_data_url(image_path: str) -> str:
    mime, _ = mimetypes.guess_type(image_path)
    mime = mime or "image/jpeg"
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def parse_sam_output(output_text: str) -> list[dict[str, Any]]:
    """Parses SAM 3.1's special-token output into a list of
    {frame, object_id, box=(x1,y1,x2,y2)}. Mask data is ignored since we
    only need the bounding box for cropping. Empty text (no hit) returns
    an empty list."""
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
    """Locates objects of a given kind (e.g. "sofa") in a single image via
    SAM 3.1."""

    def __init__(self, mock_mode: bool | None = None):
        self.mock_mode = config.MOCK_MODE if mock_mode is None else mock_mode
        self._client: OpenAI | None = None
        if not self.mock_mode:
            if not config.META_API_KEY:
                raise ApiNotConfiguredError(
                    "META_API_KEY is missing. Set it in .env or set MOCK_MODE=true."
                )
            self._client = OpenAI(base_url=config.META_BASE_URL, api_key=config.META_API_KEY)

    def find_objects(self, image_path: str, term: str) -> list[dict[str, Any]]:
        """Returns a list of {object_id, box=(x1,y1,x2,y2)} for hits of
        `term` in the image (empty if no hit)."""
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
        # Placeholder without a real API call: only the first term per
        # image "finds" an object that covers the whole image.
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
    """Vision+text model: describes objects and drafts packing plans.
    Switchable between the Meta API and Baseten via MUSE_SPARK_PROVIDER."""

    def __init__(self, mock_mode: bool | None = None):
        self.mock_mode = config.MOCK_MODE if mock_mode is None else mock_mode
        self.provider = config.MUSE_SPARK_PROVIDER
        self._client: OpenAI | None = None
        self._model: str | None = None
        if not self.mock_mode:
            if self.provider == "meta":
                if not config.META_API_KEY:
                    raise ApiNotConfiguredError("META_API_KEY is missing (or set MOCK_MODE=true).")
                self._client = OpenAI(base_url=config.META_BASE_URL, api_key=config.META_API_KEY)
                self._model = config.META_MUSE_SPARK_MODEL
            else:
                if not config.BASETEN_API_KEY:
                    raise ApiNotConfiguredError("BASETEN_API_KEY is missing (or set MOCK_MODE=true).")
                self._client = OpenAI(base_url=config.BASETEN_BASE_URL, api_key=config.BASETEN_API_KEY)
                self._model = self._resolve_baseten_model()

    def _resolve_baseten_model(self) -> str:
        """Checks which model name is actually available: the one from the
        hackathon guide ("...-1026") or the one from the Meta docs (no
        suffix)."""
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
        """Describes one object crop: name, category, fragile, customs-
        relevant."""
        if self.mock_mode:
            return self._mock_describe(image_crop_path, term_hint)

        hint = f" (SAM detection suggests: {term_hint})" if term_hint else ""
        prompt = (
            "Describe the object in the image for a moving inventory list"
            f"{hint}. Respond ONLY as JSON with the fields: "
            "name (short, concrete name, e.g. 'Gray corner sofa'), "
            "category (MUST be exactly one of these values: "
            f"{', '.join(_ALLOWED_CATEGORIES)} - pick the best match, "
            "otherwise 'other'), fragile (bool), customs_relevant (bool, "
            "e.g. true for alcohol/tobacco/weapons), customs_note (short "
            "note or empty string)."
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
        """Merges raw single-image detections into a list of actually
        distinct physical items. Needed because SAM runs per single image
        without tracking: the same piece of furniture gets detected
        repeatedly across frames, often with a slightly different
        description (e.g. "Gray sofa" vs. "Light gray corner sofa"). This
        is the fallback strategy the task brief anticipates when SAM
        tracking isn't reliable/available."""
        if not detections:
            return []
        if self.mock_mode:
            return self._mock_merge(detections)

        prompt = (
            "The following object detections come from multiple single "
            "frames of the same room, captured while walking through the "
            "room with a phone. Many detections likely show the same "
            "physical piece of furniture from different angles or with a "
            "slightly different description. Merge them into a list of "
            "actually distinct physical items. 'count' = the number of "
            "REAL physical objects in this room (not the number of "
            "detections). category MUST be exactly one of these values: "
            f"{', '.join(_ALLOWED_CATEGORIES)} - pick the best match per "
            "item, otherwise 'other'. "
            f"Detections:\n{json.dumps(detections, ensure_ascii=False)}"
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
        """Drafts a room-by-room packing plan as text."""
        if self.mock_mode:
            return self._mock_packing_plan(inventory_by_room)

        prompt = (
            "Create a short, practical room-by-room packing plan for a "
            "move from Germany to Switzerland, based on this inventory "
            f"list (JSON): {json.dumps(inventory_by_room, ensure_ascii=False)}"
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
                "name": "Unknown item",
                "category": "other",
                "fragile": False,
                "customs_relevant": False,
                "customs_note": "",
            }

    @staticmethod
    def _mock_describe(image_crop_path: str, term_hint: str) -> dict[str, Any]:
        stem = Path(image_crop_path).stem
        category = term_hint or "other"
        return {
            "name": f"{category.capitalize()} ({stem})",
            "category": category,
            "fragile": False,
            "customs_relevant": False,
            "customs_note": "",
        }

    @staticmethod
    def _mock_merge(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Naive fallback (mock mode or empty model response): exact
        # name+category match counts as the same object.
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for desc in detections:
            key = (desc["name"], desc["category"])
            if key not in merged:
                merged[key] = {**desc, "count": 0}
            merged[key]["count"] += 1
        return list(merged.values())

    @staticmethod
    def _mock_packing_plan(inventory_by_room: dict[str, list[dict]]) -> str:
        lines = ["Packing plan (mock data, no real API connected yet):"]
        for room, items in inventory_by_room.items():
            lines.append(f"\n{room}:")
            for item in items:
                lines.append(f"  - pack {item.get('name', 'item')} carefully")
        return "\n".join(lines)
