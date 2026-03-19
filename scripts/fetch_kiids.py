#!/usr/bin/env python3
"""
KIID Retriever – Batch fetch KIID URLs via iShares search redirects
Supports manual QS validation via logging + reporting

Usage:
    python scripts/fetch_kiids.py --isin-file isins.txt --sample 20 --output reports/
"""

import argparse
import json
import logging
import re
import requests
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple
from urllib.parse import urljoin

# Configure logging
log_handlers = [logging.StreamHandler()]
log_dir = Path("logs")
try:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_handlers.insert(0, logging.FileHandler(log_dir / "kiid_retriever.log"))
except OSError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=log_handlers,
)
logger = logging.getLogger(__name__)


class KIIDRetriever:
    """Retrieve KIID URLs from fund provider websites via search redirects"""

    def __init__(self, timeout=10, delay=1.0):
        """
        Args:
            timeout: HTTP request timeout in seconds
            delay: Delay between requests (rate limiting)
        """
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "FundsPortfolio/1.0 (KIID Retriever)"}
        )

    def _looks_like_pdf(self, resp: requests.Response) -> bool:
        content_type = (resp.headers.get("Content-Type") or "").lower()
        if "pdf" in content_type:
            return True
        return resp.content[:4] == b"%PDF"

    def _extract_pdf_url(self, html: str, base_url: str) -> str | None:
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

        preferred = None
        for keyword in ("kiid", "kid"):
            for candidate in candidates:
                if keyword in candidate.lower():
                    preferred = candidate
                    break
            if preferred:
                break

        return urljoin(base_url, preferred or candidates[0])

    def _resolve_pdf_url(self, url: str) -> str | None:
        if not url:
            return None

        if url.lower().endswith(".pdf"):
            return url

        try:
            resp = self.session.get(url, timeout=self.timeout)
        except requests.RequestException:
            return None

        if resp.status_code != 200:
            return None

        if self._looks_like_pdf(resp):
            return resp.url

        return self._extract_pdf_url(resp.text or "", resp.url)

    def get_kiid_url_ishares(self, isin: str) -> Tuple[str, str]:
        """
        Try to retrieve KIID URL via iShares UK search redirect (302)

        Returns:
            (kiid_url, status) where status is 'success', 'redirect_failed', or 'error'
        """
        try:
            url = f"https://www.ishares.com/uk/individual/en/search?searchTerm={isin}"
            resp = self.session.get(url, allow_redirects=False, timeout=self.timeout)

            if resp.status_code in (301, 302):
                location = resp.headers.get("Location")
                if location:
                    resolved = self._resolve_pdf_url(location)
                    if resolved:
                        return resolved, "success"
                return None, "redirect_failed"
            elif resp.status_code == 200:
                # Sometimes page loads directly
                if self._looks_like_pdf(resp):
                    return resp.url, "success"
                resolved = self._extract_pdf_url(resp.text or "", resp.url)
                if resolved:
                    return resolved, "success"
                return None, "redirect_failed"
            else:
                logger.warning(f"{isin}: Unexpected status {resp.status_code}")
                return None, "error"

        except requests.Timeout:
            logger.error(f"{isin}: Request timeout")
            return None, "timeout"
        except requests.RequestException as e:
            logger.error(f"{isin}: Request error: {e}")
            return None, "error"

    def get_kiid_url_vanguard(self, isin: str) -> Tuple[str, str]:
        """Try Vanguard search (fallback)"""
        try:
            url = f"https://www.vanguard.com/en/individual/search?searchTerm={isin}"
            resp = self.session.get(url, allow_redirects=False, timeout=self.timeout)

            if resp.status_code in (301, 302):
                location = resp.headers.get("Location")
                if location:
                    resolved = self._resolve_pdf_url(location)
                    if resolved:
                        return resolved, "success"
                return None, "not_found"
            if resp.status_code == 200:
                if self._looks_like_pdf(resp):
                    return resp.url, "success"
                resolved = self._extract_pdf_url(resp.text or "", resp.url)
                if resolved:
                    return resolved, "success"
            return None, "not_found"
        except Exception as e:
            logger.error(f"{isin} (Vanguard): {e}")
            return None, "error"

    def retrieve_batch(self, isins: List[str], max_retries=2) -> Dict:
        """
        Retrieve KIID URLs for batch of ISINs

        Returns:
            {
                'verified': [{'isin': ..., 'kiid_url': ...}, ...],
                'pending': [{'isin': ..., 'reason': ...}, ...],
                'failed': [{'isin': ..., 'error': ...}, ...]
            }
        """
        results = {"verified": [], "pending": [], "failed": []}

        for i, isin in enumerate(isins, 1):
            logger.info(f"[{i}/{len(isins)}] Retrieving {isin}...")

            # Try iShares first
            kiid_url, status = self.get_kiid_url_ishares(isin)

            if status == "success":
                results["verified"].append(
                    {"isin": isin, "kiid_url": kiid_url, "provider": "iShares"}
                )
                logger.info("  ✓ Found (iShares)")

            elif status == "redirect_failed":
                # Try Vanguard as fallback
                kiid_url, status2 = self.get_kiid_url_vanguard(isin)
                if status2 == "success":
                    results["verified"].append(
                        {"isin": isin, "kiid_url": kiid_url, "provider": "Vanguard"}
                    )
                    logger.info("  ✓ Found (Vanguard)")
                else:
                    results["pending"].append(
                        {
                            "isin": isin,
                            "reason": (
                                "Search redirect not found (manual review needed)"
                            ),
                        }
                    )
                    logger.warning("  ⚠ Pending manual review")

            else:
                results["failed"].append(
                    {"isin": isin, "error": f"iShares search: {status}"}
                )
                logger.error(f"  ✗ Failed ({status})")

            # Rate limiting
            if i < len(isins):
                time.sleep(self.delay)

        return results


def load_isins(filepath: str) -> List[str]:
    """Load ISIN list from file (one per line, ignoring comments)"""
    isins = []
    with open(filepath, "r") as f:
        for line in f:
            raw = line.split("#", 1)[0]
            isin = raw.strip()
            if isin:
                isins.append(isin.upper())
    return isins


def generate_report(results: Dict, output_dir: str):
    """Generate QS report files"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # JSON report
    report_file = output_dir / f"kiid_retrieval_{timestamp}.json"
    with open(report_file, "w") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "summary": {
                    "verified": len(results["verified"]),
                    "pending": len(results["pending"]),
                    "failed": len(results["failed"]),
                    "total": sum(len(v) for v in results.values()),
                },
                "results": results,
            },
            f,
            indent=2,
        )
    logger.info(f"Report saved: {report_file}")

    # Markdown summary for manual review
    md_file = output_dir / f"kiid_qc_checklist_{timestamp}.md"
    with open(md_file, "w") as f:
        f.write("# KIID Retrieval QC Checklist\n\n")
        f.write(f"**Generated:** {timestamp}\n\n")

        f.write("## Summary\n")
        f.write(f"- ✓ Verified: {len(results['verified'])}\n")
        f.write(f"- ⚠ Pending manual review: {len(results['pending'])}\n")
        f.write(f"- ✗ Failed: {len(results['failed'])}\n\n")

        if results["pending"]:
            f.write("## ISINs for Manual Review\n\n")
            f.write("These ISINs need manual KIID lookup:\n\n")
            for item in results["pending"]:
                f.write(f"- [ ] **{item['isin']}**: {item['reason']}\n")
            f.write(
                "\n**Action:** Search iShares/Vanguard website directly, "
                "verify KIID URL, update `funds_database.json`\n\n"
            )

        if results["failed"]:
            f.write("## Failed ISINs (Investigate)\n\n")
            for item in results["failed"]:
                f.write(f"- **{item['isin']}**: {item['error']}\n")
    logger.info(f"QC checklist: {md_file}")

    # CSV for easy import (optional)
    csv_file = output_dir / f"kiid_verified_{timestamp}.csv"
    with open(csv_file, "w") as f:
        f.write("isin,kiid_url,provider,kiid_status,notes\n")
        for item in results["verified"]:
            f.write(
                f"{item['isin']},{item['kiid_url']},{item['provider']},"
                "verified,Retrieved automatically\n"
            )
    logger.info(f"CSV exported: {csv_file}")


def merge_into_funddb(verified_results: List[Dict], funddb_path: str):
    """
    Merge verified KIID URLs back into funds_database.json

    This requires manual verification that ISIN matches fund in database
    """
    with open(funddb_path, "r") as f:
        funddb = json.load(f)

    # Create lookup by ISIN
    isin_lookup = {fund["isin"]: fund for fund in funddb["funds_database"]}

    # Update with verified KIIDs
    updated_count = 0
    for item in verified_results:
        if item["isin"] in isin_lookup:
            isin_lookup[item["isin"]]["kiid_url"] = item["kiid_url"]
            isin_lookup[item["isin"]]["kiid_status"] = "verified"
            isin_lookup[item["isin"]]["kiid_retrieved_at"] = (
                datetime.utcnow().isoformat()
            )
            updated_count += 1

    # Save backup
    backup_path = funddb_path.replace(
        ".json", f"_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(backup_path, "w") as f:
        json.dump(funddb, f, indent=2)
    logger.info(f"Backup: {backup_path}")

    # Save updated database
    with open(funddb_path, "w") as f:
        json.dump(funddb, f, indent=2)
    logger.info(f"Updated {updated_count} funds in {funddb_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Retrieve KIID URLs via fund provider search redirects"
    )
    parser.add_argument("--isin-file", required=True, help="Path to ISIN list file")
    parser.add_argument(
        "--sample", type=int, default=None, help="Test on first N ISINs only"
    )
    parser.add_argument(
        "--output", default="reports/", help="Output directory for reports"
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Auto-merge verified KIIDs into funds_database.json",
    )
    parser.add_argument(
        "--funddb", default="funds_database.json", help="Path to funds database"
    )
    parser.add_argument(
        "--timeout", type=int, default=10, help="HTTP timeout in seconds"
    )
    parser.add_argument(
        "--delay", type=float, default=1.0, help="Delay between requests (seconds)"
    )

    args = parser.parse_args()

    # Load ISINs
    isins = load_isins(args.isin_file)
    if args.sample:
        isins = isins[: args.sample]

    logger.info(f"Loaded {len(isins)} ISINs")

    # Retrieve KIIDs
    retriever = KIIDRetriever(timeout=args.timeout, delay=args.delay)
    results = retriever.retrieve_batch(isins)

    # Generate reports
    generate_report(results, args.output)

    # Optional: Auto-merge
    if args.merge and results["verified"]:
        confirm = input(
            f"\nMerge {len(results['verified'])} verified KIIDs into {args.funddb}? "
            "(y/n): "
        )
        if confirm.lower() == "y":
            merge_into_funddb(results["verified"], args.funddb)


if __name__ == "__main__":
    main()
