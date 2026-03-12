#!/usr/bin/env python3
"""
import_csv_funds.py – Phase 6.2B Data Enrichment
=================================================
Parses the five German-language CSV fund files and merges them into
funds_database.json, de-duplicating by ISIN.

Existing hand-curated entries always win (first-seen policy).

Usage:
    cd /home/mrick/FundsPortfolio
    python scripts/import_csv_funds.py           # dry-run: print summary only
    python scripts/import_csv_funds.py --write   # write funds_database.json
"""

import csv
import json
import os
import sys
import argparse
from datetime import date
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
FUND_DB_PATH = os.path.join(PROJECT_ROOT, "funds_database.json")

CSV_FILES = {
    "FundsInitDB_de_de": os.path.join(PROJECT_ROOT, "FundsInitDB_de_de.csv"),
    "aktienfonds_50":    os.path.join(PROJECT_ROOT, "aktienfonds_50.csv"),
    "etfs_50":           os.path.join(PROJECT_ROOT, "etfs_50.csv"),
    "mischfonds_50":     os.path.join(PROJECT_ROOT, "mischfonds_50.csv"),
    "rentenfonds_50":    os.path.join(PROJECT_ROOT, "rentenfonds_50.csv"),
}


# ---------------------------------------------------------------------------
# Field mapping: Fondstyp / Kategorie → asset_class, categories, region
# ---------------------------------------------------------------------------
FONDSTYP_MAP: List[Tuple[str, str, List[str], str]] = [
    # (prefix, asset_class, categories, region)
    # --- Aktienfonds ---
    ("Aktienfonds – Europa",          "equity", ["european_equity"],                  "europe"),
    ("Aktienfonds Europa",            "equity", ["european_equity"],                  "europe"),
    ("Aktienfonds International",     "equity", ["global_equity"],                    "global"),
    ("Aktienfonds Deutschland",       "equity", ["german_equity"],                    "germany"),
    ("Aktienfonds Euroland",          "equity", ["eurozone_equity"],                  "eurozone"),
    ("Aktienfonds Südostasien",       "equity", ["asian_equity"],                     "asia"),
    ("Aktienfonds Emerging Markets",  "equity", ["emerging_markets"],                 "emerging_markets"),
    ("Aktienfonds Branchen/Themen",   "equity", ["thematic_equity"],                  "global"),
    # --- ETFs ---
    ("ETF – MSCI Europe ESG",         "equity", ["etf", "european_equity", "esg"],   "europe"),
    ("ETF – MSCI Europe SRI",         "equity", ["etf", "european_equity", "esg"],   "europe"),
    ("ETF – MSCI Europe Small Cap",   "equity", ["etf", "small_cap"],                "europe"),
    ("ETF – MSCI Europe",             "equity", ["etf", "european_equity"],           "europe"),
    ("ETF – STOXX Europe 600 Technology", "equity", ["etf", "technology"],           "europe"),
    ("ETF – STOXX Europe 600 ESG",    "equity", ["etf", "european_equity", "esg"],   "europe"),
    ("ETF – STOXX Europe 600 ESG-X",  "equity", ["etf", "european_equity", "esg"],   "europe"),
    ("ETF – STOXX Europe 600",        "equity", ["etf", "european_equity"],           "europe"),
    ("ETF – EURO STOXX 50 ESG",       "equity", ["etf", "eurozone_equity", "esg"],   "eurozone"),
    ("ETF – EURO STOXX 50",           "equity", ["etf", "eurozone_equity"],           "eurozone"),
    ("ETF – FTSE Europe",             "equity", ["etf", "european_equity"],           "europe"),
    # --- Mischfonds ---
    ("Mischfonds – Europa",           "mixed",  ["balanced", "european_mixed"],       "europe"),
    ("Mischfonds",                    "mixed",  ["balanced"],                          "global"),
    # --- Rentenfonds ---
    ("Rentenfonds – Geldmarkt",       "bond",   ["money_market"],                     "europe"),
    ("Rentenfonds – Hochverzinslich", "bond",   ["high_yield_bonds"],                 "europe"),
    ("Rentenfonds – Flexibel",        "bond",   ["flexible_bonds"],                   "europe"),
    ("Rentenfonds – Europa",          "bond",   ["european_bonds"],                   "europe"),
    ("Rentenfonds International",     "bond",   ["global_bonds"],                     "global"),
    ("Rentenfonds Europa",            "bond",   ["european_bonds"],                   "europe"),
    # --- FundsInitDB Kategorie values ---
    ("Wertsicherungsfonds",           "mixed",  ["capital_protection"],               "global"),
    ("Geldmarktnahe Fonds",           "bond",   ["money_market"],                     "europe"),
    ("Indexfonds (ETFs)",             "equity", ["etf"],                              "global"),
    ("Vermögensverwaltende Fonds",    "mixed",  ["multi_asset"],                      "global"),
]


def map_fondstyp(raw: str) -> Tuple[str, List[str], str]:
    """Map German Fondstyp/Kategorie string to (asset_class, categories, region)."""
    raw = raw.strip()
    for prefix, asset_class, categories, region in FONDSTYP_MAP:
        if raw.startswith(prefix):
            return asset_class, list(categories), region
    # Fallback
    return "other", [raw.lower().replace(" ", "_")], "global"


# ---------------------------------------------------------------------------
# Risk level mapping
# ---------------------------------------------------------------------------
RISIKOKLASSE_MAP: Dict[str, int] = {
    "niedrig":     2,
    "mittel":      3,
    "hoch":        5,
    "sehr hoch":   5,
    "sehr niedrig": 1,
}


def map_risk_level(raw: str) -> int:
    """Convert German text or numeric string to integer risk level (1–5)."""
    raw = raw.strip()
    try:
        val = int(raw)
        return max(1, min(5, val))
    except ValueError:
        pass
    return RISIKOKLASSE_MAP.get(raw.lower(), 3)


# ---------------------------------------------------------------------------
# ESG flag helper
# ---------------------------------------------------------------------------
def is_esg_checked(val: str) -> bool:
    return val.strip().lower() in {"ü", "true", "yes", "x", "1"}


# ---------------------------------------------------------------------------
# Sanitise ISIN – basic check: non-empty, ≤18 chars, alphanumeric
# ---------------------------------------------------------------------------
def sanitise_isin(raw: str) -> Optional[str]:
    isin = raw.strip().upper()
    if not isin or len(isin) > 18 or not isin.replace("-", "").isalnum():
        return None
    return isin


# ---------------------------------------------------------------------------
# Parser: FundsInitDB_de_de.csv   (semicolon-delimited)
# Columns: Nr.;Kategorie;Fondsname;;ISIN;Art8;Art9;Risiko
# Note: the ISIN is in the 4th data column (index 3 after Fondsname split)
# ---------------------------------------------------------------------------
def parse_fundsinitdb(filepath: str, source_name: str) -> List[Dict]:
    funds = []
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=";")
        header = next(reader)  # skip header
        for row in reader:
            if not row or len(row) < 4:
                continue
            # row layout: Nr. | Kategorie | Fondsname | ISIN | Art8 | Art9 | Risiko
            kategorie = row[1].strip() if len(row) > 1 else ""
            name      = row[2].strip() if len(row) > 2 else ""
            isin_raw  = row[3].strip() if len(row) > 3 else ""
            art8      = row[4].strip() if len(row) > 4 else ""
            art9      = row[5].strip() if len(row) > 5 else ""
            risk_raw  = row[6].strip() if len(row) > 6 else "3"

            isin = sanitise_isin(isin_raw)
            if not isin or not name:
                continue

            asset_class, categories, region = map_fondstyp(kategorie)
            risk_level = map_risk_level(risk_raw)

            funds.append({
                "isin":          isin,
                "name":          name,
                "provider":      _derive_provider(name),
                "kiid_url":      None,
                "asset_class":   asset_class,
                "region":        region,
                "categories":    categories,
                "risk_level":    risk_level,
                "yearly_fee":    None,
                "esg_article_8": is_esg_checked(art8),
                "esg_article_9": is_esg_checked(art9),
                "notes":         None,
                "source":        source_name,
            })
    return funds


# ---------------------------------------------------------------------------
# Parser: generic comma-delimited files (aktienfonds, etfs, mischfonds, rentenfonds)
# Columns: Name des Fonds,ISIN,Fondstyp,Risikoklasse,Ausgebende Gesellschaft,
#          Link zum KIID/Factsheet,Besonderheiten
# ---------------------------------------------------------------------------
def parse_generic_csv(filepath: str, source_name: str) -> List[Dict]:
    funds = []
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name      = row.get("Name des Fonds", "").strip()
            isin_raw  = row.get("ISIN", "").strip()
            fondstyp  = row.get("Fondstyp", "").strip()
            risiko    = row.get("Risikoklasse", "Mittel").strip()
            provider  = row.get("Ausgebende Gesellschaft", "").strip()
            kiid_url  = row.get("Link zum KIID/Factsheet", "").strip() or None
            notes     = row.get("Besonderheiten", "").strip() or None

            isin = sanitise_isin(isin_raw)
            if not isin or not name:
                continue

            asset_class, categories, region = map_fondstyp(fondstyp)
            risk_level = map_risk_level(risiko)

            funds.append({
                "isin":          isin,
                "name":          name,
                "provider":      provider or _derive_provider(name),
                "kiid_url":      kiid_url,
                "asset_class":   asset_class,
                "region":        region,
                "categories":    categories,
                "risk_level":    risk_level,
                "yearly_fee":    None,
                "esg_article_8": False,
                "esg_article_9": False,
                "notes":         notes,
                "source":        source_name,
            })
    return funds


# ---------------------------------------------------------------------------
# Derive provider name from fund name (heuristic fallback)
# ---------------------------------------------------------------------------
KNOWN_PROVIDERS = [
    "iShares", "Vanguard", "Amundi", "DWS", "Deka", "SPDR", "Xtrackers",
    "Lyxor", "Comgest", "Fidelity", "Schroders", "Invesco", "BlackRock",
    "JPMorgan", "Allianz", "UBS", "BNP Paribas", "Pictet", "Nordea",
    "Carmignac", "Flossbach", "Ökoworld", "Templeton", "Franklin",
    "ComStage", "HSBC", "BGF", "AB ", "MFS", "T. Rowe", "Janus Henderson",
    "Neuberger", "Legg Mason", "Morgan Stanley", "Goldman Sachs",
    "Threadneedle", "Aviva", "AXA", "BNY Mellon", "RobecoSAM", "Robeco",
    "Credit Suisse", "M&G", "Capital Group", "Dimensional", "Acatis",
    "Ethna", "Swisscanto", "Provinzial", "SK ", "LIGA", "SCOR", "Lazard",
    "Antecedo", "BayernInvest", "Goyer",
]


def _derive_provider(name: str) -> str:
    for p in KNOWN_PROVIDERS:
        if p.lower() in name.lower():
            return p.strip()
    # Use first two words as fallback
    words = name.split()
    return " ".join(words[:2]) if len(words) >= 2 else words[0] if words else "Unknown"


# ---------------------------------------------------------------------------
# Merge: existing DB first (curated wins), then CSV rows
# ---------------------------------------------------------------------------
def merge_funds(existing: List[Dict], csv_batches: List[Tuple[str, List[Dict]]]) -> Tuple[List[Dict], Dict]:
    seen_isins: Dict[str, str] = {}  # isin → source
    result: List[Dict] = []
    skipped: Dict[str, List[str]] = {}  # source → list of skipped ISINs

    # 1. Lock in existing curated entries
    for fund in existing:
        isin = fund.get("isin", "").upper()
        if isin and isin not in seen_isins:
            seen_isins[isin] = "curated"
            result.append(fund)

    # 2. Add CSV imports, skipping duplicates
    for source_name, funds in csv_batches:
        skipped[source_name] = []
        for fund in funds:
            isin = fund.get("isin", "").upper()
            if not isin:
                continue
            if isin in seen_isins:
                skipped[source_name].append(isin)
            else:
                seen_isins[isin] = source_name
                result.append(fund)

    return result, skipped


# ---------------------------------------------------------------------------
# Load existing funds_database.json
# ---------------------------------------------------------------------------
def load_existing_db(path: str) -> Tuple[List[Dict], Dict]:
    if not os.path.exists(path):
        return [], {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("funds_database", []), data.get("metadata", {})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Import fund CSVs into funds_database.json")
    parser.add_argument("--write", action="store_true", help="Write the merged database to disk")
    args = parser.parse_args()

    # Load existing
    existing_funds, existing_meta = load_existing_db(FUND_DB_PATH)
    print(f"Existing curated funds (pre-import): {len(existing_funds)}")

    # Parse each CSV
    csv_batches: List[Tuple[str, List[Dict]]] = []
    for name, path in CSV_FILES.items():
        if not os.path.exists(path):
            print(f"  WARNING: {path} not found – skipping.")
            continue
        if name == "FundsInitDB_de_de":
            funds = parse_fundsinitdb(path, name)
        else:
            funds = parse_generic_csv(path, name)
        print(f"  Parsed {name}: {len(funds)} funds")
        csv_batches.append((name, funds))

    # Merge
    merged, skipped = merge_funds(existing_funds, csv_batches)

    # Report
    print(f"\nTotal after de-duplication: {len(merged)} funds")
    total_skipped = sum(len(v) for v in skipped.values())
    print(f"Duplicate ISINs skipped: {total_skipped}")
    for src, isins in skipped.items():
        if isins:
            print(f"  [{src}] skipped {len(isins)}: {', '.join(isins[:5])}{'...' if len(isins) > 5 else ''}")

    # Asset class breakdown
    breakdown: Dict[str, int] = {}
    for f in merged:
        key = f.get("asset_class", "other")
        breakdown[key] = breakdown.get(key, 0) + 1
    print("\nAsset class breakdown:")
    for cls, count in sorted(breakdown.items()):
        print(f"  {cls:<10} {count:>4}")

    if not args.write:
        print("\nDRY RUN – use --write to apply changes to funds_database.json")
        return

    # Build new metadata
    new_metadata = {
        "version":     "2.0",
        "last_updated": str(date.today()),
        "total_funds": len(merged),
        "data_source": (
            "Curated + CSV import: "
            "FundsInitDB_de_de, aktienfonds_50, etfs_50, mischfonds_50, rentenfonds_50"
        ),
    }

    output = {
        "funds_database": merged,
        "metadata":       new_metadata,
    }

    with open(FUND_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Written {len(merged)} funds to {FUND_DB_PATH}")
    print(f"  version: {new_metadata['version']}, last_updated: {new_metadata['last_updated']}")


if __name__ == "__main__":
    main()
