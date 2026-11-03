"""Deterministische Volumen-, Karton- und Transporterberechnung.

Das Volumen wird NICHT vom Sprachmodell geschätzt, sondern über eine feste
Tabelle mit Standardvolumen pro Kategorie (wie bei Umzugsfirmen üblich).
"""

from dataclasses import dataclass

# Standardvolumen in m³ pro Kategorie (grobe Richtwerte von Umzugsfirmen).
# "sonstiges" ist der Fallback für unbekannte Kategorien.
CATEGORY_VOLUMES_M3: dict[str, float] = {
    "sofa 2-sitzer": 1.5,
    "sofa 3-sitzer": 2.0,
    "sessel": 0.8,
    "esstisch": 1.0,
    "couchtisch": 0.5,
    "stuhl": 0.2,
    "bett doppelbett": 2.0,
    "bett einzelbett": 1.0,
    "kleiderschrank": 2.5,
    "kommode": 0.8,
    "bücherregal": 1.2,
    "regal": 1.0,
    "schreibtisch": 1.0,
    "fernseher": 0.3,
    "kühlschrank": 1.2,
    "waschmaschine": 1.0,
    "geschirrspüler": 1.0,
    "lampe": 0.1,
    "spiegel": 0.2,
    "teppich": 0.3,
    "karton": 0.1,
    "sonstiges": 0.5,
}

BOX_VOLUME_M3 = 0.1  # Standard-Umzugskarton (ca. 60x40x40 cm)

# Transportergrößen nach Gesamtvolumen (grenzwerte in m³, inkl. Lademaß-Puffer).
TRANSPORT_SIZES: list[tuple[float, str]] = [
    (8.0, "PKW-Anhänger / kleiner Transporter (z.B. VW Caddy)"),
    (20.0, "Transporter mittel (z.B. Mercedes Sprinter / Ford Transit, lang)"),
    (35.0, "LKW 7,5t"),
    (float("inf"), "LKW 7,5t+ oder mehrere Fahrten nötig"),
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
        return CATEGORY_VOLUMES_M3.get(self.category_key, CATEGORY_VOLUMES_M3["sonstiges"])

    @property
    def total_volume_m3(self) -> float:
        return round(self.unit_volume_m3 * self.count, 3)


def compute_total_volume(items: list[InventoryItem]) -> float:
    return round(sum(item.total_volume_m3 for item in items), 2)


def compute_box_count(items: list[InventoryItem]) -> int:
    """Grobe Kartonschätzung: kleine/lose Gegenstände (Kategorie 'karton',
    'sonstiges', 'lampe', 'spiegel', 'teppich') werden zu Standardkartons
    zusammengefasst; alle anderen sind eigenständige Stücke."""
    small_categories = {"karton", "sonstiges", "lampe", "spiegel", "teppich"}
    small_volume = sum(
        item.total_volume_m3 for item in items if item.category_key in small_categories
    )
    return max(0, round(small_volume / BOX_VOLUME_M3))


def recommend_transport(total_volume_m3: float) -> str:
    for threshold, label in TRANSPORT_SIZES:
        if total_volume_m3 <= threshold:
            return label
    return TRANSPORT_SIZES[-1][1]
