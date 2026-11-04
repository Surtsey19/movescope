"""Builds the final demo video from the Playwright raw recording
(tools/record_demo.py): title cards + cut/time-lapsed segments of real app
usage, with burned-in English captions instead of a voiceover.

Uses ffmpeg directly (via imageio-ffmpeg, no system ffmpeg needed).
"""

import json
import subprocess
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "_demo_raw"
BUILD_DIR = ROOT / "data" / "_demo_build"
OUT_PATH = ROOT / "test_media" / "movescope_demo.mp4"

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FONT = "C\\:/Windows/Fonts/arial.ttf"
FONT_BOLD = "C\\:/Windows/Fonts/arialbd.ttf"

W, H, FPS = 1280, 720, 25
BG_COLOR = "0x14213d"


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("CMD:", " ".join(cmd))
        print(result.stderr[-3000:])
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode})")


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’")


def title_card(text: str, subtitle: str, duration: float, out_path: Path) -> None:
    title_draw = (
        f"drawtext=fontfile='{FONT_BOLD}':text='{esc(text)}':fontcolor=white:fontsize=42:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-30"
    )
    sub_draw = (
        f"drawtext=fontfile='{FONT}':text='{esc(subtitle)}':fontcolor=0xcccccc:fontsize=22:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+40:line_spacing=8"
    ) if subtitle else None
    vf = title_draw if not sub_draw else f"{title_draw},{sub_draw}"
    run([
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=c={BG_COLOR}:s={W}x{H}:d={duration}:r={FPS}",
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
        str(out_path),
    ])


def caption_filter(caption: str) -> str:
    return (
        f"drawtext=fontfile='{FONT}':text='{esc(caption)}':fontcolor=white:fontsize=24:"
        f"box=1:boxcolor=0x000000@0.65:boxborderw=12:x=(w-text_w)/2:y=h-text_h-34"
    )


def clip_segment(
    raw_video: Path, start: float, end: float, speed: float, caption: str, out_path: Path,
    freeze_hold: float = 0.0,
) -> None:
    """Cuts [start,end] out of the raw recording, speeds up/slows down by
    `speed` (1.0 = normal, >1 = faster), scales to WxH, burns in the
    caption. `freeze_hold`: appends a freeze-frame of the last frame for
    N seconds at the end (to give time to read the caption)."""
    vf_parts = [f"scale={W}:{H}:force_original_aspect_ratio=decrease", f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2"]
    if speed != 1.0:
        vf_parts.append(f"setpts=PTS/{speed}")
    if freeze_hold > 0:
        vf_parts.append(f"tpad=stop_mode=clone:stop_duration={freeze_hold}")
    if caption:
        vf_parts.append(caption_filter(caption))
    vf = ",".join(vf_parts)
    run([
        FFMPEG, "-y",
        "-ss", str(start), "-to", str(end), "-i", str(raw_video),
        "-vf", vf,
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
        str(out_path),
    ])


def image_hold(image_path: Path, duration: float, caption: str, out_path: Path) -> None:
    """Shows a still image (e.g. a rendered PDF page) for `duration` seconds."""
    vf = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=white"
    if caption:
        vf += "," + caption_filter(caption)
    run([
        FFMPEG, "-y",
        "-loop", "1", "-i", str(image_path),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
        str(out_path),
    ])


def concat(segment_paths: list[Path], out_path: Path) -> None:
    list_file = BUILD_DIR / "concat_list.txt"
    list_file.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in segment_paths), encoding="utf-8")
    run([
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy",
        str(out_path),
    ])


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [FFMPEG, "-i", str(path)], capture_output=True, text=True
    )
    for line in result.stderr.splitlines():
        if "Duration:" in line:
            hms = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = hms.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return -1.0


def main() -> None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    milestones = json.loads((RAW_DIR / "milestones.json").read_text(encoding="utf-8"))
    raw_video = ROOT / milestones["_video_file"]
    m = milestones

    segments: list[Path] = []

    def add_title(text: str, subtitle: str, duration: float) -> None:
        p = BUILD_DIR / f"seg_{len(segments):02d}.mp4"
        title_card(text, subtitle, duration, p)
        segments.append(p)

    def add_clip(start: float, end: float, speed: float, caption: str, freeze_hold: float = 0.0) -> None:
        p = BUILD_DIR / f"seg_{len(segments):02d}.mp4"
        clip_segment(raw_video, start, end, speed, caption, p, freeze_hold=freeze_hold)
        segments.append(p)

    def add_image(image_path: Path, duration: float, caption: str) -> None:
        p = BUILD_DIR / f"seg_{len(segments):02d}.mp4"
        image_hold(image_path, duration, caption, p)
        segments.append(p)

    # 1) Intro
    add_title("MoveScope", "from a phone video to a complete relocation plan", 5.0)
    add_title("Germany → Switzerland move", "Inventory list, volume, and customs document – fully automated", 6.0)
    add_title(
        "The pipeline",
        "Video → 15 frames/room → SAM 3.1 segmentation → Muse Spark vision labeling → deterministic volume calculation",
        8.0,
    )

    # 2) Setup: fill in address + add room/video
    add_clip(
        max(0.0, m["page_loaded"]), m["video_uploaded"], 1.0,
        "1. Enter move details, upload a short phone video per room",
        freeze_hold=8.0,
    )

    # 3) Analysis (real wait time heavily sped up, narrated in two phases)
    mid = (m["analyze_clicked"] + m["results_visible"]) / 2
    add_clip(
        m["analyze_clicked"], mid, 22.0,
        "2. SAM 3.1 locates every object in the video – via the Meta Model API",
    )
    add_clip(
        mid, m["results_visible"], 22.0,
        "Muse Spark names and classifies each item",
    )

    # 4) Results
    add_clip(
        m["results_visible"], m["metrics_scrolled"], 0.22,
        "3. Finished inventory list – every object detected individually",
    )
    add_clip(
        m["metrics_scrolled"], m["packing_plan_scrolled"], 0.13,
        "Volume is computed deterministically – never estimated by the language model",
    )
    add_clip(
        m["packing_plan_scrolled"], m["pdf_downloaded"], 0.18,
        "Muse Spark drafts a packing plan, export as CSV and customs PDF",
    )

    # 5) Show the real customs PDF (rendered via PyMuPDF instead of browser
    # navigation, since Chromium treats local PDFs as a download instead of
    # an inline view in headless mode - see record_demo.py)
    pdf_pages = sorted(RAW_DIR.glob("pdf_page_*.png"))
    for i, pg in enumerate(pdf_pages):
        caption = (
            "Official Swiss customs inventory list"
            if i == 0 else
            "Reference to the real Form 18.44 in the document"
        )
        add_image(pg, 12.0, caption)

    # 6) Technical highlights + outro
    add_title(
        "Two real bugs found along the way",
        "Cross-frame duplicate counting fixed via an LLM merge step; a category enum now enforces valid volume mapping",
        8.0,
    )
    add_title(
        "Technical challenge",
        "SAM 3.1 needs English query terms – German terms like \"waschmaschine\" returned 0 hits, \"washing machine\" hit reliably",
        8.0,
    )
    add_title(
        "Baseten Muse Spark Open",
        "Open-weights model as the default backend, switchable to the Meta Model API",
        6.0,
    )
    add_title("github.com/Surtsey19/movescope", "", 6.0)

    concat(segments, OUT_PATH)
    duration = probe_duration(OUT_PATH)
    print(f"\nDone: {OUT_PATH} ({duration:.1f}s, {len(segments)} segments)")


if __name__ == "__main__":
    main()
