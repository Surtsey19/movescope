"""Export der Ergebnisse: Inventartabelle (CSV) und Zoll-Inventarliste (PDF)."""

import csv
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.styles import getSampleStyleSheet

from .volume import InventoryItem, compute_box_count, compute_total_volume, recommend_transport

_CELL_STYLE = getSampleStyleSheet()["Normal"].clone("cell")
_CELL_STYLE.fontSize = 9
_CELL_STYLE.leading = 11


def _cell(text: str) -> Paragraph:
    """Zellinhalt als Paragraph statt reinem String, damit lange Texte
    (z.B. Gegenstandsnamen) innerhalb der festen Spaltenbreite umbrechen
    statt über die Spalte hinauszulaufen."""
    return Paragraph(text, _CELL_STYLE)


@dataclass
class MoveDetails:
    full_name: str
    old_address: str
    new_address: str


def export_inventory_csv(items: list[InventoryItem], out_path: str) -> str:
    """Schreibt die Inventartabelle (Raum, Gegenstand, Anzahl, Volumen, zerbrechlich)."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Raum", "Gegenstand", "Kategorie", "Anzahl", "Volumen (m3)", "Zerbrechlich", "Zollrelevant", "Zoll-Hinweis"])
        for item in items:
            writer.writerow([
                item.room,
                item.name,
                item.category,
                item.count,
                item.total_volume_m3,
                "Ja" if item.fragile else "Nein",
                "Ja" if item.customs_relevant else "Nein",
                item.customs_note,
            ])
    return out_path


def export_customs_pdf(items: list[InventoryItem], move: MoveDetails, out_path: str) -> str:
    """Erstellt die Zoll-Inventarliste als PDF für den Umzug Deutschland -> Schweiz."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        out_path, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm, leftMargin=15 * mm, rightMargin=15 * mm
    )
    story = []

    story.append(Paragraph("Umzugsgut-Inventarliste für die Schweizer Zollanmeldung", styles["Title"]))
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph(f"<b>Name:</b> {move.full_name}", styles["Normal"]))
    story.append(Paragraph(f"<b>Bisherige Adresse:</b> {move.old_address}", styles["Normal"]))
    story.append(Paragraph(f"<b>Neue Adresse (Schweiz):</b> {move.new_address}", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "<i>Hinweis: Zusätzlich zu dieser Liste muss das offizielle Formular "
        "18.44 (Anmeldung für Übersiedlungsgut) ausgefüllt werden.</i>",
        styles["Normal"],
    ))
    story.append(Spacer(1, 8 * mm))

    rooms = sorted({item.room for item in items})
    for room in rooms:
        story.append(Paragraph(room, styles["Heading2"]))
        room_items = [i for i in items if i.room == room]
        table_data = [["Gegenstand", "Kategorie", "Anzahl", "Volumen (m3)"]]
        for item in room_items:
            table_data.append([_cell(item.name), _cell(item.category), str(item.count), f"{item.total_volume_m3:.2f}"])
        table = Table(table_data, colWidths=[70 * mm, 45 * mm, 20 * mm, 30 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(table)
        story.append(Spacer(1, 6 * mm))

    customs_items = [i for i in items if i.customs_relevant]
    story.append(Paragraph("Zu verzollende Waren", styles["Heading2"]))
    if customs_items:
        table_data = [["Gegenstand", "Raum", "Anzahl", "Hinweis"]]
        for item in customs_items:
            table_data.append([_cell(item.name), item.room, str(item.count), _cell(item.customs_note or "-")])
        table = Table(table_data, colWidths=[55 * mm, 30 * mm, 20 * mm, 60 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("Keine zu verzollenden Waren identifiziert.", styles["Normal"]))

    story.append(Spacer(1, 8 * mm))
    total_volume = compute_total_volume(items)
    box_count = compute_box_count(items)
    transport = recommend_transport(total_volume)
    story.append(Paragraph(
        f"<b>Gesamtvolumen:</b> {total_volume:.2f} m3 &nbsp;&nbsp; "
        f"<b>Geschätzte Kartons:</b> {box_count} &nbsp;&nbsp; "
        f"<b>Empfohlener Transporter:</b> {transport}",
        styles["Normal"],
    ))

    doc.build(story)
    return out_path
