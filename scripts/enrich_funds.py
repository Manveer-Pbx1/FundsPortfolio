#!/usr/bin/env python3
"""
Enrich funds_database.json with yearly_fee (from KIID PDFs) and sharpe_ratio.

Usage:
  python scripts/enrich_funds.py --write
  python scripts/enrich_funds.py --limit 20 --write
  python scripts/enrich_funds.py --fees --sharpe --write
  python scripts/enrich_funds.py --refresh-kiid --fees --write

Notes:
- KIID parsing uses pypdf if installed. If missing, fee extraction is skipped.
- Sharpe ratio uses yfinance via PriceFetcher for funds with a ticker (or ISIN if supported).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None

from funds_portfolio.data.price_fetcher import PriceFetcher
from funds_portfolio.portfolio.calculator import PortfolioCalculator


def _load_db(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_db(path: str, data: Dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_ticker_map(path: str) -> Dict[str, str]:
    if not path or not os.path.exists(path):
        return {}

    mapping: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            isin = (row.get("isin") or "").strip().upper()
            ticker = (row.get("ticker") or "").strip()
            if isin and ticker:
                mapping[isin] = ticker
    return mapping


def _apply_ticker_map(fund: Dict, ticker_map: Dict[str, str]) -> bool:
    if fund.get("ticker") not in (None, ""):
        return False

    isin = (fund.get("isin") or "").strip().upper()
    ticker = ticker_map.get(isin)
    if not ticker:
        return False

    fund["ticker"] = ticker
    return True


def _normalize_percent(value: str) -> Optional[float]:
    if value is None:
        return None
    cleaned = value.strip().replace("%", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_fee_from_text(text: str, allow_heuristic: bool) -> Optional[float]:
    if not text:
        return None

    patterns = [
        r"(ongoing charges|ongoing charge|laufende kosten|gesamtkostenquote|total expense ratio|ter)[^\d%]{0,30}([0-9]+[\.,][0-9]+)\s*%",
        r"([0-9]+[\.,][0-9]+)\s*%\s*(ongoing charges|laufende kosten|gesamtkostenquote|total expense ratio|ter)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = (
                match.group(2)
                if match.lastindex and match.lastindex >= 2
                else match.group(1)
            )
            return _normalize_percent(value)

    if not allow_heuristic:
        return None

    # Heuristic: choose the smallest percentage between 0 and 5% if only one is plausible
    candidates = []
    for match in re.finditer(r"([0-9]+[\.,][0-9]+)\s*%", text):
        value = _normalize_percent(match.group(1))
        if value is not None and 0 < value <= 5:
            candidates.append(value)

    if len(candidates) == 1:
        return candidates[0]

    if candidates:
        return min(candidates)

    return None


def _pdf_to_text(pdf_bytes: bytes) -> Optional[str]:
    if PdfReader is None:
        return None

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception:
        return None

    parts: List[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)


def _looks_like_pdf(resp: requests.Response) -> bool:
    content_type = (resp.headers.get("Content-Type") or "").lower()
    if "pdf" in content_type:
        return True
    return resp.content[:4] == b"%PDF"


def _extract_pdf_url_from_html(html: str, base_url: str) -> Optional[str]:
    if not html:
        return None

    candidates = []
    for match in re.finditer(
        r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, flags=re.IGNORECASE
    ):
        candidates.append(match.group(1))

    for match in re.finditer(
        r"(https?://[^\s\"']+\.pdf[^\s\"']*)", html, flags=re.IGNORECASE
    ):
        candidates.append(match.group(1))

    if not candidates:
        return None

    for keyword in ("kiid", "kid"):
        for candidate in candidates:
            if keyword in candidate.lower():
                return urljoin(base_url, candidate)

    return urljoin(base_url, candidates[0])


def _fetch_pdf(url: str, timeout: int) -> Optional[bytes]:
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    if _looks_like_pdf(resp):
        return resp.content

    resolved = _extract_pdf_url_from_html(resp.text or "", resp.url)
    if not resolved:
        return None

    try:
        resp = requests.get(resolved, timeout=timeout)
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    if _looks_like_pdf(resp):
        return resp.content

    return None


def _fetch_kiid_url(isin: str, timeout: int) -> Tuple[Optional[str], str]:
    try:
        ishares_url = (
            f"https://www.ishares.com/uk/individual/en/search?searchTerm={isin}"
        )
        resp = requests.get(ishares_url, allow_redirects=False, timeout=timeout)
        if resp.status_code in (301, 302):
            location = resp.headers.get("Location")
            if location:
                return location, "verified"
        # Vanguard fallback
        vanguard_url = (
            f"https://www.vanguard.com/en/individual/search?searchTerm={isin}"
        )
        resp = requests.get(vanguard_url, allow_redirects=False, timeout=timeout)
        if resp.status_code in (301, 302):
            location = resp.headers.get("Location")
            if location:
                return location, "verified"
        return None, "not_found"
    except requests.RequestException:
        return None, "error"


def _enrich_fee(
    fund: Dict,
    session_timeout: int,
    allow_heuristic: bool,
    pdf_delay: float,
) -> Tuple[Optional[float], Optional[str]]:
    if fund.get("yearly_fee") not in (None, ""):
        return fund.get("yearly_fee"), fund.get("kiid_status")

    kiid_url = fund.get("kiid_url")
    if not kiid_url:
        return None, fund.get("kiid_status")

    pdf_bytes = _fetch_pdf(kiid_url, session_timeout)
    if not pdf_bytes:
        return None, fund.get("kiid_status")

    text = _pdf_to_text(pdf_bytes)
    fee = _extract_fee_from_text(text or "", allow_heuristic)
    time.sleep(pdf_delay)
    return fee, fund.get("kiid_status")


def _enrich_sharpe(
    fund: Dict,
    calculator: PortfolioCalculator,
) -> Optional[float]:
    if fund.get("sharpe_ratio") not in (None, ""):
        return fund.get("sharpe_ratio")

    identifier = fund.get("ticker") or fund.get("isin")
    if not identifier:
        return None

    metrics = calculator.price_fetcher.get_fund_metrics(identifier)
    if not metrics:
        return None

    sharpe = calculator.calculate_sharpe_ratio(
        metrics.get("annualized_return", 0.0),
        metrics.get("annualized_volatility", 0.0),
    )
    return sharpe


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich funds_database.json with yearly_fee and sharpe_ratio"
    )
    parser.add_argument("--db", default="funds_database.json", help="Path to DB")
    parser.add_argument("--write", action="store_true", help="Write updates to disk")
    parser.add_argument("--limit", type=int, default=0, help="Limit funds processed")
    parser.add_argument("--fees", action="store_true", help="Enrich yearly_fee")
    parser.add_argument("--sharpe", action="store_true", help="Enrich sharpe_ratio")
    parser.add_argument(
        "--refresh-kiid",
        action="store_true",
        help="Fetch missing kiid_url values",
    )
    parser.add_argument("--timeout", type=int, default=15, help="HTTP timeout")
    parser.add_argument(
        "--delay", type=float, default=0.5, help="Delay between PDF fetches"
    )
    parser.add_argument(
        "--allow-heuristic-fee",
        action="store_true",
        help="Allow heuristic fee extraction when no explicit label is found",
    )
    parser.add_argument(
        "--risk-free-rate", type=float, default=0.02, help="Risk free rate"
    )
    parser.add_argument(
        "--ticker-map",
        default="assets/data/ticker_map.csv",
        help="Path to ISIN to ticker map",
    )
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit(f"DB not found: {args.db}")

    data = _load_db(args.db)
    funds = data.get("funds_database", [])

    if not args.fees and not args.sharpe:
        args.fees = True
        args.sharpe = True

    if PdfReader is None and args.fees:
        print("WARNING: pypdf not installed; fee extraction will be skipped.")

    ticker_map = _load_ticker_map(args.ticker_map)

    price_fetcher = PriceFetcher()
    calculator = PortfolioCalculator(
        risk_free_rate=args.risk_free_rate, price_fetcher=price_fetcher
    )

    updated_fee = 0
    updated_sharpe = 0
    refreshed_kiid = 0
    updated_ticker = 0

    total = len(funds)
    limit = args.limit if args.limit and args.limit > 0 else total

    funds_to_process = funds
    if args.fees:
        funds_to_process = sorted(
            funds,
            key=lambda f: (
                f.get("yearly_fee") not in (None, ""),
                not f.get("kiid_url"),
                f.get("isin") or "",
            ),
        )

    for idx, fund in enumerate(funds_to_process[:limit], 1):
        isin = fund.get("isin") or "<unknown>"

        if args.refresh_kiid and not fund.get("kiid_url"):
            kiid_url, status = _fetch_kiid_url(isin, args.timeout)
            if kiid_url:
                fund["kiid_url"] = kiid_url
                fund["kiid_status"] = status
                refreshed_kiid += 1

        if ticker_map and _apply_ticker_map(fund, ticker_map):
            updated_ticker += 1

        if args.fees:
            fee, status = _enrich_fee(
                fund,
                session_timeout=args.timeout,
                allow_heuristic=args.allow_heuristic_fee,
                pdf_delay=args.delay,
            )
            if fee is not None and fund.get("yearly_fee") != fee:
                fund["yearly_fee"] = round(float(fee), 4)
                updated_fee += 1
            if status and fund.get("kiid_status") != status:
                fund["kiid_status"] = status

        if args.sharpe:
            sharpe = _enrich_sharpe(fund, calculator)
            if sharpe is not None and fund.get("sharpe_ratio") != sharpe:
                fund["sharpe_ratio"] = round(float(sharpe), 6)
                updated_sharpe += 1

        if idx % 25 == 0:
            print(f"Processed {idx}/{limit}")

    data["funds_database"] = funds
    data.setdefault("metadata", {})["last_enriched"] = time.strftime("%Y-%m-%d")

    print("Enrichment summary:")
    print(f"  fees updated: {updated_fee}")
    print(f"  sharpe updated: {updated_sharpe}")
    print(f"  kiid refreshed: {refreshed_kiid}")
    print(f"  tickers applied: {updated_ticker}")

    if args.write:
        _save_db(args.db, data)
        print(f"Saved updates to {args.db}")
    else:
        print("Dry run only (use --write to persist)")


if __name__ == "__main__":
    main()
