"""Verbindet Frame-Extraktion, SAM-3.1-Lokalisierung, Muse-Spark-Beschreibung
und Volumenberechnung zu einer Pipeline pro Raum.

SAM 3.1 wird pro Einzelbild und pro Objektbegriff (BASE_OBJECT_TERMS)
aufgerufen (kein Video-Upload, um die Bildanzahl/Kosten über
frame_extraction.py kontrolliert zu halten). Da dadurch keine stabile
Objekt-ID über mehrere Frames existiert, werden Doppelungen über Name+
Kategorie zusammengeführt - das ist die in der Aufgabenstellung vorgesehene
Fallback-Strategie, falls Tracking nicht zuverlässig möglich ist.
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
    """Verarbeitet das Video eines Raums und gibt die zusammengeführte
    Inventarliste für diesen Raum zurück."""
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

    # Dedup über Muse Spark (siehe Modul-Docstring): dasselbe physische
    # Objekt wird über mehrere Frames hinweg oft leicht unterschiedlich
    # beschrieben, daher reicht ein reiner String-Vergleich nicht.
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
