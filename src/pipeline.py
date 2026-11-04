"""Connects frame extraction, SAM 3.1 localization, Muse Spark description,
and volume calculation into a per-room pipeline.

SAM 3.1 is called per single image and per object term (BASE_OBJECT_TERMS)
(no video upload, to keep the image count/cost controlled via
frame_extraction.py). Since this means there's no stable object ID across
frames, duplicates are merged via name+category - the fallback strategy
the task brief anticipates when reliable tracking isn't available.
"""

from pathlib import Path
from typing import Any

from PIL import Image

from .api_clients import BASE_OBJECT_TERMS, MuseSparkClient, SamClient
from .frame_extraction import extract_frames
from .volume import InventoryItem


def _crop(image_path: str, box_px: tuple[int, int, int, int], out_path: str) -> str:
    x1, y1, x2, y2 = box_px
    with Image.open(image_path) as img:
        img_w, img_h = img.size
        left = max(0, min(x1, img_w - 1))
        top = max(0, min(y1, img_h - 1))
        right = max(left + 1, min(x2, img_w))
        bottom = max(top + 1, min(y2, img_h))
        crop = img.crop((left, top, right, bottom))
        crop.save(out_path)
    return out_path


def process_room_video(
    room_name: str,
    video_path: str,
    work_dir: str,
    sam_client: SamClient | None = None,
    muse_client: MuseSparkClient | None = None,
    object_terms: list[str] | None = None,
) -> list[InventoryItem]:
    """Processes one room's video and returns the merged inventory list
    for that room."""
    sam_client = sam_client or SamClient()
    muse_client = muse_client or MuseSparkClient()
    object_terms = object_terms or BASE_OBJECT_TERMS

    room_dir = Path(work_dir) / room_name
    frames_dir = room_dir / "frames"
    crops_dir = room_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    frame_paths = extract_frames(video_path, str(frames_dir))

    descriptions: list[dict[str, Any]] = []
    for frame_idx, frame_path in enumerate(frame_paths):
        for term in object_terms:
            hits = sam_client.find_objects(frame_path, term)
            for hit in hits:
                crop_path = str(crops_dir / f"f{frame_idx}_{term}_{hit['object_id']}.jpg")
                _crop(frame_path, hit["box"], crop_path)
                desc = muse_client.describe_object(crop_path, term_hint=term)
                descriptions.append(desc)

    # Dedup via Muse Spark (see module docstring): the same physical
    # object is often described slightly differently across frames, so a
    # plain string comparison isn't enough.
    merged = muse_client.merge_duplicate_detections(descriptions)

    items = [
        InventoryItem(
            room=room_name,
            name=data["name"],
            category=data["category"],
            count=data["count"],
            fragile=data["fragile"],
            customs_relevant=data["customs_relevant"],
            customs_note=data.get("customs_note", ""),
        )
        for data in merged
    ]
    return items
