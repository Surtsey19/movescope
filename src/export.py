"""Exports the results: inventory table (CSV) and customs inventory list (PDF)."""

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
    """Cell content as a Paragraph instead of a plain string, so long text
    (e.g. item names) wraps within the fixed column width instead of
    running past the column."""
    return Paragraph(text, _CELL_STYLE)


@dataclass
class MoveDetails:
    full_name: str
    old_address: str
    new_address: str


def export_inventory_csv(items: list[InventoryItem], out_path: str) -> str:
    """Writes the inventory table (room, item, count, volume, fragile)."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Room", "Item", "Category", "Count", "Volume (m3)", "Fragile", "Customs relevant", "Customs note"])
        for item in items:
            writer.writerow([
                item.room,
                item.name,
                item.category,
                item.count,
                item.total_volume_m3,
                "Yes" if item.fragile else "No",
                "Yes" if item.customs_relevant else "No",
                item.customs_note,
            ])
    return out_path


def export_customs_pdf(items: list[InventoryItem], move: MoveDetails, out_path: str) -> str:
    """Creates the customs inventory list as a PDF for a move from Germany to Switzerland."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        out_path, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm, leftMargin=15 * mm, rightMargin=15 * mm
    )
    story = []

    story.append(Paragraph("Household Goods Inventory for Swiss Customs Declaration", styles["Title"]))
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph(f"<b>Name:</b> {move.full_name}", styles["Normal"]))
    story.append(Paragraph(f"<b>Previous address:</b> {move.old_address}", styles["Normal"]))
    story.append(Paragraph(f"<b>New address (Switzerland):</b> {move.new_address}", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "<i>Note: In addition to this list, the official Form 18.44 "
        "(declaration for household goods/relocation effects) must also be "
        "completed.</i>",
        styles["Normal"],
    ))
    story.append(Spacer(1, 8 * mm))

    rooms = sorted({item.room for item in items})
    for room in rooms:
        story.append(Paragraph(room, styles["Heading2"]))
        room_items = [i for i in items if i.room == room]
        table_data = [["Item", "Category", "Count", "Volume (m3)"]]
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
    story.append(Paragraph("Goods to Declare", styles["Heading2"]))
    if customs_items:
        table_data = [["Item", "Room", "Count", "Note"]]
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
        story.append(Paragraph("No goods to declare identified.", styles["Normal"]))

    story.append(Spacer(1, 8 * mm))
    total_volume = compute_total_volume(items)
    box_count = compute_box_count(items)
    transport = recommend_transport(total_volume)
    story.append(Paragraph(
        f"<b>Total volume:</b> {total_volume:.2f} m3 &nbsp;&nbsp; "
        f"<b>Estimated boxes:</b> {box_count} &nbsp;&nbsp; "
        f"<b>Recommended vehicle:</b> {transport}",
        styles["Normal"],
    ))

    doc.build(story)
    return out_path
