"""Deterministic volume, box, and van-size calculation.

Volume is NOT estimated by the language model - it comes from a fixed
table of standard volumes per category (the same approach real moving
companies use).
"""

from dataclasses import dataclass

# Standard volumes in m3 per category (rough industry rules of thumb).
# "other" is the fallback for unrecognized categories.
CATEGORY_VOLUMES_M3: dict[str, float] = {
    "sofa 2-seater": 1.5,
    "sofa 3-seater": 2.0,
    "corner sofa": 2.8,
    "armchair": 0.8,
    "dining table": 1.0,
    "coffee table": 0.5,
    "chair": 0.2,
    "double bed": 2.0,
    "single bed": 1.0,
    "wardrobe": 2.5,
    "dresser": 0.8,
    "bookshelf": 1.2,
    "shelf": 1.0,
    "desk": 1.0,
    "tv": 0.3,
    "fridge": 1.2,
    "washing machine": 1.0,
    "dishwasher": 1.0,
    "lamp": 0.1,
    "floor lamp": 0.2,
    "blanket": 0.15,
    "mirror": 0.2,
    "rug": 0.3,
    "microwave": 0.1,
    "coffee machine": 0.05,
    "kettle": 0.03,
    "toaster": 0.05,
    "box": 0.1,
    "other": 0.5,
}

BOX_VOLUME_M3 = 0.1  # standard moving box (approx. 60x40x40 cm)

# Van/truck size by total volume (thresholds in m3, with loading-space buffer).
TRANSPORT_SIZES: list[tuple[float, str]] = [
    (8.0, "Car trailer / small van (e.g. VW Caddy)"),
    (20.0, "Medium van (e.g. Mercedes Sprinter / Ford Transit, long)"),
    (35.0, "7.5t truck"),
    (float("inf"), "7.5t+ truck or multiple trips needed"),
]


@dataclass
class InventoryItem:
    room: str
    name: str
    category: str
    count: int
    fragile: bool
    customs_relevant: bool
    customs_note: str = ""

    @property
    def category_key(self) -> str:
        return self.category.strip().lower()

    @property
    def unit_volume_m3(self) -> float:
        return CATEGORY_VOLUMES_M3.get(self.category_key, CATEGORY_VOLUMES_M3["other"])

    @property
    def total_volume_m3(self) -> float:
        return round(self.unit_volume_m3 * self.count, 3)


def compute_total_volume(items: list[InventoryItem]) -> float:
    return round(sum(item.total_volume_m3 for item in items), 2)


def compute_box_count(items: list[InventoryItem]) -> int:
    """Rough box estimate: small/loose items (category 'box', 'other',
    'lamp', 'mirror', 'rug') are bundled into standard moving boxes; all
    other categories are counted as standalone pieces."""
    small_categories = {"box", "other", "lamp", "mirror", "rug"}
    small_volume = sum(
        item.total_volume_m3 for item in items if item.category_key in small_categories
    )
    return max(0, round(small_volume / BOX_VOLUME_M3))


def recommend_transport(total_volume_m3: float) -> str:
    for threshold, label in TRANSPORT_SIZES:
        if total_volume_m3 <= threshold:
            return label
    return TRANSPORT_SIZES[-1][1]
