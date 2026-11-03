"""Einmaliges Playwright-Skript, um die Streamlit-App im Browser zu
testen. Nicht Teil der Pipeline - nur für das manuelle Verifizieren der
UI mit echten API-Calls."""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8766"
VIDEO_PATH = str(Path(__file__).resolve().parent.parent / "data" / "Wohnzimmer.mov")
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "_screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        page.goto(URL)
        page.wait_for_selector("text=MoveScope", timeout=20000)
        page.screenshot(path=str(SCREENSHOT_DIR / "01_loaded.png"))
        print("Seite geladen.")

        page.fill('input[aria-label="Raumname"]', "Wohnzimmer")
        page.keyboard.press("Enter")
        page.set_input_files('input[type="file"]', VIDEO_PATH)
        page.wait_for_timeout(2000)
        page.screenshot(path=str(SCREENSHOT_DIR / "02_video_uploaded.png"))

        add_button = page.get_by_role("button", name="Raum hinzufügen")
        add_button.wait_for(state="visible", timeout=10000)
        add_button.click()
        page.wait_for_selector("text=Raum 'Wohnzimmer' hinzugefügt", timeout=10000)
        print("Raum hinzugefügt.")
        page.screenshot(path=str(SCREENSHOT_DIR / "03_room_added.png"))

        analyze_button = page.get_by_role("button", name="🚀 Räume analysieren")
        analyze_button.click()
        print("Analyse gestartet, warte auf Ergebnis (bis zu 8 Minuten)...")

        t0 = time.time()
        page.wait_for_selector("text=Ergebnisse", timeout=8 * 60 * 1000)
        print(f"Ergebnisse nach {time.time() - t0:.0f}s sichtbar.")
        page.wait_for_timeout(3000)
        page.screenshot(path=str(SCREENSHOT_DIR / "04_results.png"), full_page=True)

        if console_errors:
            print("Konsolen-Fehler:")
            for e in console_errors:
                print(f"  - {e}")
        else:
            print("Keine Konsolen-Fehler.")

        browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FEHLER: {e}")
        sys.exit(1)
