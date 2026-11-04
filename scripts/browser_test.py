"""Einmaliges Playwright-Skript, um die Streamlit-App im Browser zu
testen. Nicht Teil der Pipeline - nur für das manuelle Verifizieren der
UI mit echten API-Calls."""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8766"
ROOT = Path(__file__).resolve().parent.parent
VIDEO_PATH = str(ROOT / "test_media" / "bathroom.mp4")  # kürzester bisher gemessene Lauf (~480s)
SCREENSHOT_DIR = ROOT / "data" / "_screenshots"
DOWNLOAD_DIR = ROOT / "data" / "_downloads"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000}, accept_downloads=True)
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        page.goto(URL)
        page.wait_for_selector("text=MoveScope", timeout=20000)
        print("Seite geladen.")

        # Adressdaten zuerst ausfüllen, damit der PDF-Download-Button später erscheint.
        page.fill('input[aria-label="Name"]', "Max Mustermann")
        page.keyboard.press("Tab")
        page.fill('input[aria-label="Bisherige Adresse (Deutschland)"]', "Musterstr 1, 10115 Berlin, DE")
        page.keyboard.press("Tab")
        page.fill('input[aria-label="Neue Adresse (Schweiz)"]', "Beispielweg 2, 8001 Zuerich, CH")
        page.keyboard.press("Tab")
        page.screenshot(path=str(SCREENSHOT_DIR / "01b_adresse.png"))
        print("Adressdaten ausgefüllt.")

        page.fill('input[aria-label="Raumname"]', "Bad")
        page.keyboard.press("Enter")
        page.set_input_files('input[type="file"]', VIDEO_PATH)
        page.wait_for_timeout(2000)

        add_button = page.get_by_role("button", name="Raum hinzufügen")
        add_button.wait_for(state="visible", timeout=10000)
        add_button.click()
        page.wait_for_selector("text=Raum 'Bad' hinzugefügt", timeout=10000)
        print("Raum hinzugefügt.")

        analyze_button = page.get_by_role("button", name="🚀 Räume analysieren")
        analyze_button.click()
        print("Analyse gestartet, warte auf Ergebnis (bis zu 10 Minuten)...")

        t0 = time.time()
        page.wait_for_selector("text=Downloads", timeout=10 * 60 * 1000)
        print(f"Downloads-Bereich nach {time.time() - t0:.0f}s sichtbar.")
        page.wait_for_timeout(1000)
        page.screenshot(path=str(SCREENSHOT_DIR / "04_results.png"), full_page=True)

        with page.expect_download() as csv_dl:
            page.get_by_role("button", name="📄 Inventarliste (CSV)").click()
        csv_path = DOWNLOAD_DIR / "inventarliste.csv"
        csv_dl.value.save_as(str(csv_path))
        print(f"CSV heruntergeladen: {csv_path} ({csv_path.stat().st_size} Bytes)")

        with page.expect_download() as pdf_dl:
            page.get_by_role("button", name="📑 Zoll-Inventarliste (PDF)").click()
        pdf_path = DOWNLOAD_DIR / "zoll_inventarliste.pdf"
        pdf_dl.value.save_as(str(pdf_path))
        pdf_bytes = pdf_path.read_bytes()
        is_valid_pdf = pdf_bytes[:5] == b"%PDF-"
        print(f"PDF heruntergeladen: {pdf_path} ({len(pdf_bytes)} Bytes, gültiger PDF-Header: {is_valid_pdf})")

        page.screenshot(path=str(SCREENSHOT_DIR / "05_after_downloads.png"), full_page=True)

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
