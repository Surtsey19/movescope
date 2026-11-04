"""MoveScope Streamlit UI: upload video -> progress -> results."""

import sys
import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.api_clients import MuseSparkClient, SamClient
from src.export import MoveDetails, export_customs_pdf, export_inventory_csv
from src.pipeline import process_room_video
from src.volume import compute_box_count, compute_total_volume, recommend_transport

st.set_page_config(page_title="MoveScope", page_icon="📦", layout="wide")

st.title("📦 MoveScope")
st.caption("From a phone video to a complete relocation plan, including a Swiss customs inventory list")

if config.MOCK_MODE:
    st.warning(
        "MOCK_MODE is active (no API key found in .env). The results below "
        "are placeholder data, not real object detection.",
        icon="⚠️",
    )

if "rooms" not in st.session_state:
    st.session_state.rooms = []  # list of {"name": str, "video_path": str}
if "inventory" not in st.session_state:
    st.session_state.inventory = []

with st.sidebar:
    st.header("1. Move details")
    full_name = st.text_input("Name", value="")
    old_address = st.text_input("Previous address (Germany)", value="")
    new_address = st.text_input("New address (Switzerland)", value="")

    st.header("2. Add rooms")
    room_name = st.text_input("Room name", value="", key="room_name_input")
    uploaded_video = st.file_uploader("Video for this room", type=["mp4", "mov", "avi", "m4v"])
    if st.button("Add room", disabled=not (room_name and uploaded_video)):
        tmp_dir = Path(tempfile.gettempdir()) / "movescope"
        tmp_dir.mkdir(exist_ok=True)
        video_path = tmp_dir / f"{room_name}_{uploaded_video.name}"
        video_path.write_bytes(uploaded_video.getvalue())
        st.session_state.rooms.append({"name": room_name, "video_path": str(video_path)})
        st.success(f"Room '{room_name}' added.")

    if st.session_state.rooms:
        st.write("Rooms added:")
        for r in st.session_state.rooms:
            st.write(f"- {r['name']}")

st.header("3. Start analysis")

if not st.session_state.rooms:
    st.info("Add at least one room with a video on the left.")
else:
    if st.button("🚀 Analyze rooms", type="primary"):
        work_dir = Path(tempfile.gettempdir()) / "movescope_work"
        sam_client = SamClient()
        muse_client = MuseSparkClient()

        all_items = []
        progress = st.progress(0.0, text="Starting analysis...")
        for i, room in enumerate(st.session_state.rooms):
            progress.progress(
                i / len(st.session_state.rooms),
                text=f"Analyzing room: {room['name']} ...",
            )
            items = process_room_video(
                room["name"], room["video_path"], str(work_dir),
                sam_client=sam_client, muse_client=muse_client,
            )
            all_items.extend(items)
        progress.progress(1.0, text="Done.")

        st.session_state.inventory = all_items
        st.success(f"{len(all_items)} object types detected across all rooms.")

if st.session_state.inventory:
    items = st.session_state.inventory
    st.header("4. Results")

    rows = [{
        "Room": i.room, "Item": i.name, "Category": i.category,
        "Count": i.count, "Volume (m³)": i.total_volume_m3,
        "Fragile": "Yes" if i.fragile else "No",
        "Customs relevant": "Yes" if i.customs_relevant else "No",
    } for i in items]
    st.dataframe(rows, use_container_width=True)

    total_volume = compute_total_volume(items)
    box_count = compute_box_count(items)
    transport = recommend_transport(total_volume)

    col1, col2, col3 = st.columns(3)
    col1.metric("Total volume", f"{total_volume:.2f} m³")
    col2.metric("Estimated boxes", box_count)
    col3.metric("Recommended vehicle", transport)

    with st.spinner("Creating packing plan..."):
        inventory_by_room: dict[str, list[dict]] = {}
        for i in items:
            inventory_by_room.setdefault(i.room, []).append(
                {"name": i.name, "category": i.category, "count": i.count}
            )
        muse_client = MuseSparkClient()
        packing_plan = muse_client.generate_packing_plan(inventory_by_room)

    st.subheader("Packing plan")
    st.text(packing_plan)

    st.subheader("Downloads")
    out_dir = Path(tempfile.gettempdir()) / "movescope_output"
    out_dir.mkdir(exist_ok=True)

    csv_path = export_inventory_csv(items, str(out_dir / "inventory.csv"))
    st.download_button(
        "📄 Inventory list (CSV)", data=Path(csv_path).read_bytes(),
        file_name="inventory.csv", mime="text/csv",
    )

    if full_name and old_address and new_address:
        move = MoveDetails(full_name, old_address, new_address)
        pdf_path = export_customs_pdf(items, move, str(out_dir / "customs_inventory.pdf"))
        st.download_button(
            "📑 Customs inventory list (PDF)", data=Path(pdf_path).read_bytes(),
            file_name="customs_inventory.pdf", mime="application/pdf",
        )
    else:
        st.info("Enter name and both addresses on the left to generate the customs PDF.")
