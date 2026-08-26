"""Shared VCT constants."""

ALL_STANDARD_MAPS = [
    "Ascent",
    "Bind",
    "Breeze",
    "Corrode",
    "Fracture",
    "Haven",
    "Icebox",
    "Lotus",
    "Pearl",
    "Split",
    "Summit",
    "Sunset",
    "Abyss",
]

# Maps rotated out of the current competitive pool (V26 Act 5 / Patch 13.04)
# Pool: Abyss, Ascent, Haven, Lotus, Split, Summit, Sunset (Breeze out, Abyss in)
OUT_OF_POOL_MAPS = frozenset({
    "Bind",
    "Breeze",
    "Corrode",
    "Fracture",
    "Icebox",
    "Pearl",
})

# Current competitive map pool — used for Bo3/Bo5 series simulation
COMP_POOL_MAPS = [m for m in ALL_STANDARD_MAPS if m not in OUT_OF_POOL_MAPS]

RECENT_FORM_MATCHES = 15
# Win rate feature uses the same rolling window as recent form (not full 2021–2026 history).
RECENT_WINRATE_MATCHES = RECENT_FORM_MATCHES
RECENT_H2H_MATCHES = 5
RECENT_PLAYER_STAT_MATCHES = 15
RECENT_LAN_MATCHES = 5

ELO_INITIAL = 1500.0
ELO_K_FACTOR = 32.0
# Scale Elo / form updates by series margin (2-0 stronger than 2-1).
ELO_MARGIN_SWEEP = 1.25  # margin >= 2 maps
ELO_MARGIN_CLOSE = 0.85  # margin == 1
H2H_MIN_TRUST_MATCHES = 3
MAP_DIFF_TOP_N = 3
MAP_DIFF_BOTTOM_N = 2
MAP_DIFF_MIN_PLAYED = 2

# Only recommend bets when favorite model probability reaches this gate.
# Holdout: confidence >= 0.65 → ~66.7% accuracy on ~29% of matches.
BETTING_CONFIDENCE_GATE = 0.65
