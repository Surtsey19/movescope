"""Erzeugt Testmaterial (Fotos + Videos) mit Muse Image für Küche und Bad,
damit SAM-3.1-Erkennung für Kategorien getestet werden kann, die im
bisherigen Wohnzimmer-Testvideo nicht vorkommen (Kühlschrank, Herd,
Waschmaschine, Tisch/Stühle, Schrank, Spiegel, ...).

API: Meta Model API (https://api.meta.ai/v1), Modell muse-image-1.0,
POST /v1/images/generations (OpenAI-SDK-kompatibel). $0.01 pro Bild (fix).

Ablauf:
1. 4 Fotos generieren (Küche x2 Blickwinkel, Bad x2 Blickwinkel).
2. Aus je 2 Fotos eines Raums ein 10s/30fps-MP4 bauen: langsamer
   Kameraschwenk + leichter Zoom (Ken-Burns-Effekt) pro Bild, mit weicher
   Überblendung dazwischen, damit es wie ein Handyvideo wirkt.
3. Video-Encoding: zuerst OpenCV mit H.264-Fourcc ('avc1') versuchen,
   bei Fehlschlag auf imageio-ffmpeg zurückfallen (bringt eigenes ffmpeg
   mit, kein System-Codec nötig).

Aufruf: python tools/generate_test_media.py
"""

import base64
import sys
from pathlib import Path
from typing import Callable, Iterator

import cv2
import numpy as np
from openai import OpenAI
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src import config  # noqa: E402

OUT_DIR = PROJECT_ROOT / "test_media"
IMAGE_MODEL = "muse-image-1.0"
IMAGE_SIZE = "1792x1024"  # Querformat, laut Doku nur Richtwert für das Seitenverhältnis
COST_PER_IMAGE_USD = 0.01

VIDEO_SIZE = (1280, 720)  # typische Handyvideo-Auflösung (Querformat)
VIDEO_FPS = 30
VIDEO_DURATION_S = 10

PROMPTS: dict[str, str] = {
    "kitchen_a": (
        "Realistic smartphone photo, eye level, of a typical small German "
        "apartment kitchen in daylight. Visible: white cabinets, fridge, "
        "stove with oven, microwave, coffee machine, kettle, toaster, "
        "wooden dining table with four chairs, fruit bowl, pots and pans, "
        "wine rack with bottles, herbs on the windowsill. No people, no text."
    ),
    "kitchen_b": (
        "Realistic smartphone photo, eye level, of the same typical small "
        "German apartment kitchen in daylight, seen from a different angle "
        "facing the dining table and the window. Visible: white cabinets, "
        "fridge, stove with oven, microwave, coffee machine, kettle, "
        "toaster, wooden dining table with four chairs, fruit bowl, pots "
        "and pans, wine rack with bottles, herbs on the windowsill. No "
        "people, no text."
    ),
    "bathroom_a": (
        "Realistic smartphone photo, eye level, of a typical German "
        "apartment bathroom in daylight. Visible: washbasin with mirror "
        "cabinet, toilet, bathtub with shower curtain, washing machine, "
        "towel rack with towels, laundry basket, small shelf with "
        "toiletries, bath mat, plant. No people, no text."
    ),
    "bathroom_b": (
        "Realistic smartphone photo, eye level, of the same typical German "
        "apartment bathroom in daylight, seen from a different angle. "
        "Visible: washbasin with mirror cabinet, toilet, bathtub with "
        "shower curtain, washing machine, towel rack with towels, laundry "
        "basket, small shelf with toiletries, bath mat, plant. No people, "
        "no text."
    ),
}

ROOMS: dict[str, tuple[str, str]] = {
    "kitchen": ("kitchen_a", "kitchen_b"),
    "bathroom": ("bathroom_a", "bathroom_b"),
}


def generate_image(client: OpenAI, name: str, prompt: str) -> tuple[Path, dict]:
    response = client.images.generate(
        model=IMAGE_MODEL,
        prompt=prompt,
        size=IMAGE_SIZE,
        n=1,
        response_format="b64_json",
        output_format="png",
    )
    image_bytes = base64.b64decode(response.data[0].b64_json)
    out_path = OUT_DIR / f"{name}.png"
    out_path.write_bytes(image_bytes)

    usage = getattr(response, "usage", None)
    usage_dict = {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
    } if usage else {}
    return out_path, usage_dict


def ken_burns_crop(
    img_rgb: np.ndarray,
    t: float,
    zoom_start: float = 1.0,
    zoom_end: float = 1.15,
    pan_start: float = 0.42,
    pan_end: float = 0.58,
    vcenter: float = 0.5,
) -> np.ndarray:
    """Schneidet einen Ausschnitt aus dem Bild, der über t in [0,1] langsam
    hineinzoomt und seitlich schwenkt (einfacher Ken-Burns-Effekt)."""
    h, w = img_rgb.shape[:2]
    zoom = zoom_start + (zoom_end - zoom_start) * t
    crop_w, crop_h = w / zoom, h / zoom
    center_x = (pan_start + (pan_end - pan_start) * t) * w
    center_y = vcenter * h

    x0 = min(max(center_x - crop_w / 2, 0), w - crop_w)
    y0 = min(max(center_y - crop_h / 2, 0), h - crop_h)
    x1, y1 = x0 + crop_w, y0 + crop_h

    return img_rgb[int(y0):int(y1), int(x0):int(x1)]


def generate_room_frames(
    img_a: np.ndarray, img_b: np.ndarray, out_size: tuple[int, int], fps: int, duration_s: int
) -> Iterator[np.ndarray]:
    """Liefert RGB-Frames: Ken-Burns auf Bild A, weiche Überblendung zu
    Ken-Burns auf Bild B, dann Ken-Burns auf Bild B. So wirkt es wie ein
    Handyvideo, das zwei Blickwinkel desselben Raums abläuft."""
    out_w, out_h = out_size
    total = fps * duration_s
    crossfade = int(fps * 1.5)
    seg1 = (total - crossfade) // 2
    seg3 = total - seg1 - crossfade
    a_active = max(1, seg1 + crossfade - 1)
    b_active = max(1, crossfade + seg3 - 1)

    for i in range(total):
        if i < seg1:
            t_a = i / a_active
            frame = ken_burns_crop(img_a, t_a)
            yield cv2.resize(frame, (out_w, out_h))
        elif i < seg1 + crossfade:
            t_a = i / a_active
            j = i - seg1
            t_b = j / b_active
            fa = cv2.resize(ken_burns_crop(img_a, t_a), (out_w, out_h)).astype(np.float32)
            fb = cv2.resize(ken_burns_crop(img_b, t_b), (out_w, out_h)).astype(np.float32)
            alpha = j / max(1, crossfade - 1)
            yield (fa * (1 - alpha) + fb * alpha).astype(np.uint8)
        else:
            j = i - seg1
            t_b = j / b_active
            frame = ken_burns_crop(img_b, t_b)
            yield cv2.resize(frame, (out_w, out_h))


def write_video_opencv(frames_factory: Callable[[], Iterator[np.ndarray]], out_path: Path, fps: int, size: tuple[int, int]) -> bool:
    """Versucht, H.264-MP4 direkt mit OpenCV zu schreiben. Gibt False zurück,
    wenn der Codec nicht verfügbar ist oder das Ergebnis ungültig aussieht."""
    for fourcc_str in ("avc1", "h264"):
        fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
        writer = cv2.VideoWriter(str(out_path), fourcc, fps, size)
        if not writer.isOpened():
            writer.release()
            continue

        for frame_rgb in frames_factory():
            writer.write(cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR))
        writer.release()

        if out_path.exists() and out_path.stat().st_size > 10_000:
            check = cv2.VideoCapture(str(out_path))
            ok = check.isOpened() and check.get(cv2.CAP_PROP_FRAME_COUNT) > 0
            check.release()
            if ok:
                return True
        out_path.unlink(missing_ok=True)
    return False


def write_video_imageio(frames_factory: Callable[[], Iterator[np.ndarray]], out_path: Path, fps: int) -> None:
    import imageio  # benötigt imageio-ffmpeg (bringt eigenes ffmpeg-Binary mit)

    writer = imageio.get_writer(str(out_path), fps=fps, codec="libx264", format="FFMPEG")
    try:
        for frame_rgb in frames_factory():
            writer.append_data(frame_rgb)
    finally:
        writer.close()


def write_room_video(img_a: np.ndarray, img_b: np.ndarray, out_path: Path) -> str:
    def frames_factory() -> Iterator[np.ndarray]:
        return generate_room_frames(img_a, img_b, VIDEO_SIZE, VIDEO_FPS, VIDEO_DURATION_S)

    if write_video_opencv(frames_factory, out_path, VIDEO_FPS, VIDEO_SIZE):
        return "opencv (H.264)"

    write_video_imageio(frames_factory, out_path, VIDEO_FPS)
    return "imageio-ffmpeg (H.264)"


def main() -> None:
    if not config.META_API_KEY:
        print("META_API_KEY fehlt in .env - Bildgenerierung über die Meta Model API nicht möglich.")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = OpenAI(base_url=config.META_BASE_URL, api_key=config.META_API_KEY)

    print("=== 1) Bilder generieren (Muse Image, $0.01/Bild) ===")
    image_paths: dict[str, Path] = {}
    total_cost = 0.0
    for name, prompt in PROMPTS.items():
        print(f"  Generiere {name}.png ...")
        path, usage = generate_image(client, name, prompt)
        image_paths[name] = path
        total_cost += COST_PER_IMAGE_USD
        usage_str = f" (tokens: {usage})" if usage.get("input_tokens") is not None else ""
        print(f"    -> {path}{usage_str}")

    print()
    print("=== 2) Videos bauen (Ken-Burns + Überblendung, 10s/30fps) ===")
    video_paths: dict[str, Path] = {}
    for room, (name_a, name_b) in ROOMS.items():
        img_a = np.array(Image.open(image_paths[name_a]).convert("RGB"))
        img_b = np.array(Image.open(image_paths[name_b]).convert("RGB"))
        out_path = OUT_DIR / f"{room}.mp4"
        backend = write_room_video(img_a, img_b, out_path)
        video_paths[room] = out_path
        print(f"  {out_path} ({backend})")

    print()
    print("=== Ergebnis ===")
    print("Bilder:")
    for name, path in image_paths.items():
        print(f"  {path}")
    print("Videos:")
    for room, path in video_paths.items():
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"  {path} ({size_mb:.1f} MB)")
    print(f"\nAPI-Kosten: {len(image_paths)} Bilder x ${COST_PER_IMAGE_USD:.2f} = ${total_cost:.2f}")
    print("(Videos entstehen lokal aus den Bildern, keine weiteren API-Calls.)")


if __name__ == "__main__":
    main()
