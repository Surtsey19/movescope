"""Extrahiert Einzelbilder aus einem Raumvideo für die Objekterkennung."""

from pathlib import Path

import cv2


def extract_frames(video_path: str, out_dir: str, target_fps: float = 1.0, max_frames: int = 15) -> list[str]:
    """Extrahiert ca. `target_fps` Bilder pro Sekunde aus dem Video, maximal `max_frames` Bilder.

    Gibt die Pfade der gespeicherten JPG-Dateien zurück, in zeitlicher Reihenfolge.
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Video konnte nicht geöffnet werden: {video_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_interval = max(1, round(video_fps / target_fps))

    saved_paths: list[str] = []
    frame_idx = 0
    saved_count = 0

    while saved_count < max_frames:
        ok, frame = cap.read()
        if not ok:
            break

        if frame_idx % frame_interval == 0:
            file_path = out_path / f"frame_{saved_count:03d}.jpg"
            cv2.imwrite(str(file_path), frame)
            saved_paths.append(str(file_path))
            saved_count += 1

        frame_idx += 1

    cap.release()

    if not saved_paths:
        raise ValueError("Es konnten keine Bilder aus dem Video extrahiert werden.")

    return saved_paths
