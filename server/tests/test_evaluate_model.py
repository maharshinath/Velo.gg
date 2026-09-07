"""Label helpers for international event accuracy tables."""

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR / "scripts"))

from evaluate_model import _intl_category, _short_intl_label  # noqa: E402


def test_short_intl_labels():
    assert _short_intl_label("Valorant Champions 2025") == "Champions 2025"
    assert _short_intl_label("Valorant Masters Toronto 2025") == "Masters Toronto 2025"
    assert _short_intl_label(
        "Valorant Champions Tour Stage 1: Masters Reykjavík"
    ) == "Masters Reykjavík (S1)"
    assert _intl_category("Valorant Champions 2024") == "Champions"
    assert _intl_category("Valorant Masters London 2026") == "Masters"
    assert _intl_category("Esports World Cup 2026") == "Esports World Cup"
    assert _intl_category("Valorant Champions Tour Stage 2: Masters Copenhagen") == "Masters"
    assert _short_intl_label("Valorant Champions 2026") == "Champions 2026"
    assert _intl_category("Valorant Champions 2026") == "Champions"
