"""Nimmt einen echten App-Durchlauf (Küchenvideo, reichhaltigstes Ergebnis)
mit Playwright als Bildschirmvideo auf und loggt Zeitstempel für jeden
Meilenstein. Die Rohaufnahme + das Timestamp-JSON werden danach von
tools/build_demo_video.py zu einem geschnittenen 3-Minuten-Demo
zusammengebaut (Zeitraffer für die Wartezeit, Untertitel-Overlays).

Kein Ton nötig - das fertige Video bekommt eingebrannte Untertitel statt
Sprachausgabe.
"""

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8766"
ROOT = Path(__file__).resolve().parent.parent
VIDEO_PATH = str(ROOT / "test_media" / "kitchen.mp4")
RAW_DIR = ROOT / "data" / "_demo_raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

milestones: dict[str, float] = {}


def mark(name: str, t0: float) -> None:
    milestones[name] = time.time() - t0
    print(f"[{milestones[name]:7.2f}s] {name}")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(RAW_DIR),
            record_video_size={"width": 1280, "height": 720},
            accept_downloads=True,
        )
        page = context.new_page()
        t0 = time.time()

        try:
            _run_flow(page, t0)
        finally:
            # Immer schließen, sonst wird die Videodatei nicht finalisiert
            # und Milestones gehen bei einem Fehler verloren.
            video_path_main = page.video.path()
            context.close()
            browser.close()
            milestones["_video_file"] = str(video_path_main)
            (RAW_DIR / "milestones.json").write_text(
                json.dumps(milestones, indent=2, ensure_ascii=False)
            )
            print(f"\nVideo: {video_path_main}")
            print(f"Milestones: {RAW_DIR / 'milestones.json'}")


def _run_flow(page, t0: float) -> None:
        page.goto(URL)
        page.wait_for_selector("text=MoveScope", timeout=20000)
        mark("page_loaded", t0)

        page.fill('input[aria-label="Name"]', "Max Mustermann")
        page.keyboard.press("Tab")
        page.fill('input[aria-label="Bisherige Adresse (Deutschland)"]', "Musterstr 1, 10115 Berlin, DE")
        page.keyboard.press("Tab")
        page.fill('input[aria-label="Neue Adresse (Schweiz)"]', "Beispielweg 2, 8001 Zuerich, CH")
        page.keyboard.press("Tab")
        page.wait_for_timeout(500)
        mark("address_filled", t0)

        page.fill('input[aria-label="Raumname"]', "Kueche")
        page.keyboard.press("Enter")
        page.set_input_files('input[type="file"]', VIDEO_PATH)
        page.wait_for_timeout(1500)
        mark("video_uploaded", t0)

        add_button = page.get_by_role("button", name="Raum hinzufügen")
        add_button.wait_for(state="visible", timeout=10000)
        add_button.click()
        page.wait_for_selector("text=Raum 'Kueche' hinzugefügt", timeout=10000)
        mark("room_added", t0)

        analyze_button = page.get_by_role("button", name="🚀 Räume analysieren")
        analyze_button.click()
        mark("analyze_clicked", t0)

        page.wait_for_selector("text=Downloads", timeout=20 * 60 * 1000)
        mark("results_visible", t0)

        page.wait_for_timeout(1500)
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(1500)
        mark("table_scrolled", t0)

        page.mouse.wheel(0, 600)
        page.wait_for_timeout(1500)
        mark("metrics_scrolled", t0)

        page.mouse.wheel(0, 700)
        page.wait_for_timeout(2000)
        mark("packing_plan_scrolled", t0)

        page.mouse.wheel(0, 900)
        page.wait_for_timeout(1000)
        mark("downloads_scrolled", t0)

        with page.expect_download() as csv_dl:
            page.get_by_role("button", name="📄 Inventarliste (CSV)").click()
        csv_path = RAW_DIR / "inventarliste.csv"
        csv_dl.value.save_as(str(csv_path))
        page.wait_for_timeout(1000)
        mark("csv_downloaded", t0)

        with page.expect_download() as pdf_dl:
            page.get_by_role("button", name="📑 Zoll-Inventarliste (PDF)").click()
        pdf_path = RAW_DIR / "zoll_inventarliste.pdf"
        pdf_dl.value.save_as(str(pdf_path))
        page.wait_for_timeout(1000)
        mark("pdf_downloaded", t0)

        # Kein page.goto() auf die PDF-Datei: Chromium behandelt lokale
        # PDF-Dateien im automatisierten Modus als Download statt als
        # Inline-Ansicht ("Download is starting"-Fehler). Das PDF wird
        # stattdessen separat per PyMuPDF gerendert (siehe build_demo_video.py).
        mark("end", t0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FEHLER: {e}")
        sys.exit(1)
