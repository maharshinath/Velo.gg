"""
Download missing team logos from VLR (via vlr.orlandomm.net API) and refresh team_data paths.

Usage (from server/):
  python scripts/fetch_logos.py
  python scripts/fetch_logos.py --dry-run
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import pandas as pd
import requests

SERVER_DIR = Path(__file__).resolve().parents[1]
LOGO_DIR = SERVER_DIR / "static" / "logos"
TEAM_DATA_PATH = SERVER_DIR / "csv" / "team_data.csv"
KAGGLE_DIR = SERVER_DIR / "data" / "kaggle"
VLR_API = "https://vlr.orlandomm.net/api/v1/teams/{team_id}"

# Canonical team name merges (same as update_dataset.py)
TEAM_ALIASES = {
    "Mega Minors": "NRG",
    "NRG Esports": "NRG",
    "Talon Esports": "TALON",
    "Envy": "ENVY",
}

# Prefer existing filenames when slug does not match
LOGO_FILE_OVERRIDES = {
    "EDward Gaming": "edward-gaming-logo.png",
    "KRÜ Esports": "kru-logo.png",
    "LEVIATÁN": "leviatan-logo.png",
    "Gen.G": "gen.g-logo.png",
    "Xi Lai Gaming": "xilai-logo.png",
    "JDG Esports": "jd-gaming-logo.png",
    "Made in Thailand": "made-in-thailand-logo.png",
}


def normalize_name(name: str) -> str:
    return TEAM_ALIASES.get(name.strip(), name.strip())


def slugify_team(team: str) -> str:
    slug = team.lower().replace(".", "").replace("'", "")
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def logo_filename(team: str) -> str:
    if team in LOGO_FILE_OVERRIDES:
        return LOGO_FILE_OVERRIDES[team]
    return f"{slugify_team(team)}-logo.png"


def build_vlr_id_lookup() -> dict[str, int]:
    lookup: dict[str, int] = {}
    for path in sorted(KAGGLE_DIR.glob("vct_*/ids/teams_ids.csv")):
        df = pd.read_csv(path)
        df = df.dropna(subset=["Team ID"])
        for team, team_id in zip(df["Team"], df["Team ID"]):
            name = str(team).strip()
            lookup[name] = int(team_id)
            canonical = normalize_name(name)
            lookup.setdefault(canonical, int(team_id))
    return lookup


def fetch_logo_url(team_id: int) -> str | None:
    try:
        resp = requests.get(VLR_API.format(team_id=team_id), timeout=20)
        resp.raise_for_status()
        logo = resp.json().get("data", {}).get("info", {}).get("logo")
        if logo and logo.startswith("//"):
            return "https:" + logo
        return logo
    except requests.RequestException:
        return None


def download_logo(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        if "image" not in resp.headers.get("Content-Type", "") and not url.endswith(".png"):
            return False
        dest.write_bytes(resp.content)
        return True
    except requests.RequestException:
        return False


# White-on-transparent logos from VLR disappear on the app's white logo plates
LIGHT_LOGO_TEAMS = {
    "NRG",
    "Evil Geniuses",
    "GIANTX",
    "Karmine Corp",
    "Team Liquid",
    "Gen.G",
    "Gentle Mates",
    "ZETA DIVISION",
    "Global Esports",
    "DetonatioN FocusMe",
}


def _logo_pixel_counts(src) -> tuple[int, int, int]:
    light = dark = transparent = 0
    for r, g, b, a in src.getdata():
        if a < 10:
            transparent += 1
            continue
        if r > 200 and g > 200 and b > 200:
            light += 1
        elif r < 50 and g < 50 and b < 50:
            dark += 1
    return light, dark, transparent


def fix_light_logo(dest: Path, *, force: bool = False) -> None:
    """Keep logos readable: dark marks on a white plate, white marks on a dark plate."""
    try:
        from PIL import Image
    except ImportError:
        return

    try:
        src = Image.open(dest).convert("RGBA")
    except OSError:
        return

    light, dark, transparent = _logo_pixel_counts(src)
    n = src.size[0] * src.size[1]
    opaque = max(1, n - transparent)

    # Black mark baked onto a near-black plate (e.g. Paper Rex) — lift onto white
    if transparent == 0 and light == 0 and dark == n:
        out = Image.new("RGBA", src.size, (255, 255, 255, 255))
        src_px = src.load()
        out_px = out.load()
        for y in range(src.size[1]):
            for x in range(src.size[0]):
                r, g, b, _a = src_px[x, y]
                if r < 8 and g < 8 and b < 8:
                    out_px[x, y] = (0, 0, 0, 255)
        out.save(dest, optimize=True)
        return

    auto_light = light > max(dark * 2, opaque * 0.35)
    if not force and not auto_light and (light == 0 or dark > light // 4):
        return

    bg = Image.new("RGBA", src.size, (17, 17, 17, 255))
    bg.paste(src, (0, 0), src)
    bg.save(dest, optimize=True)


def normalize_existing_logos() -> int:
    """Re-process all PNGs so light marks stay visible on white UI plates."""
    fixed = 0
    for dest in sorted(LOGO_DIR.glob("*.png")):
        before = dest.read_bytes()
        fix_light_logo(dest, force=False)
        # Also force known light-logo filenames
        name = dest.name.lower()
        if any(
            key in name
            for key in (
                "nrg",
                "evil-geniuses",
                "giantx",
                "karmine",
                "liquid",
                "gen.g",
                "gentle-mates",
                "zeta",
                "global-esports",
                "detonation",
                "heretics-logo",
                "fut-logo",
                "secret-logo",
                "vitality-logo",
                "nova-logo",
                "titan-logo",
                "mibr",
                "x10",
            )
        ):
            fix_light_logo(dest, force=True)
        if dest.read_bytes() != before:
            fixed += 1
    return fixed


def main(dry_run: bool) -> None:
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    team_data = pd.read_csv(TEAM_DATA_PATH)
    vlr_lookup = build_vlr_id_lookup()

    downloaded = 0
    skipped = 0
    failed = []

    for _, row in team_data.iterrows():
        team = normalize_name(str(row["Team"]))
        filename = logo_filename(team)
        dest = LOGO_DIR / filename
        image_path = f"/static/logos/{filename}"

        if dest.exists() and dest.stat().st_size > 500:
            skipped += 1
            # Re-normalize so light marks stay visible after UI plate changes
            fix_light_logo(dest, force=team in LIGHT_LOGO_TEAMS)
            team_data.loc[team_data["Team"] == row["Team"], "Image Path"] = image_path
            continue

        team_id = vlr_lookup.get(team) or vlr_lookup.get(str(row["Team"]).strip())
        if not team_id:
            failed.append((team, "no VLR id"))
            continue

        if dry_run:
            print(f"[dry-run] would fetch {team} (id={team_id}) -> {filename}")
            continue

        url = fetch_logo_url(team_id)
        if not url:
            failed.append((team, "no logo url"))
            continue

        if download_logo(url, dest):
            fix_light_logo(dest, force=team in LIGHT_LOGO_TEAMS)
            downloaded += 1
            team_data.loc[team_data["Team"] == row["Team"], "Image Path"] = image_path
            print(f"OK  {team} -> {filename}")
        else:
            failed.append((team, "download failed"))

        time.sleep(0.3)

    if not dry_run:
        # Merge alias rows: drop Talon Esports if TALON exists
        team_data["Team"] = team_data["Team"].map(
            lambda t: TEAM_ALIASES.get(str(t).strip(), str(t).strip())
        )
        team_data = team_data.drop_duplicates(subset=["Team"], keep="first")
        team_data["Image Path"] = team_data["Team"].map(
            lambda t: f"/static/logos/{logo_filename(t)}"
        )
        team_data.to_csv(TEAM_DATA_PATH, index=False)
        normalized = normalize_existing_logos()
        print(f"Normalized existing logos: {normalized}")

    print(f"\nDownloaded: {downloaded}, already had: {skipped}, failed: {len(failed)}")
    for team, reason in failed:
        print(f"  FAIL {team}: {reason}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch team logos from VLR")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
