"""
Decision Engine - preference-aware filtering, scoring, selection,
allocation, and explainability.
"""

from __future__ import annotations

from typing import Dict, List, Any, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class DecisionEngine:
    """
    Preference-aware portfolio recommender.

    Uses existing fund fields and falls back to proxy metrics when price
    history is missing.
    """

    def __init__(
        self,
        min_candidates: int = 12,
        top_k: int = 15,
        final_fund_count: int = 5,
        max_per_provider: int = 2,
        max_per_category: int = 3,
    ):
        self.min_candidates = min_candidates
        self.top_k = top_k
        self.final_fund_count = final_fund_count
        self.max_per_provider = max_per_provider
        self.max_per_category = max_per_category

    def recommend(
        self, user_answers: Dict[str, Any], funds: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        trace = {"filters": [], "relaxations": [], "used_fallback_risk": False}

        def note_filter(
            name: str, before: int, after: int, details: Optional[Dict[str, Any]] = None
        ):
            trace["filters"].append(
                {
                    "name": name,
                    "before": before,
                    "after": after,
                    "details": details or {},
                }
            )

        risk_profile, used_fallback = self._map_risk_profile(user_answers)
        trace["used_fallback_risk"] = used_fallback

        working = list(funds)

        # 1) Basic eligibility
        before = len(working)
        working = [
            f
            for f in working
            if f.get("isin") and f.get("name") and f.get("yearly_fee") is not None
        ]
        note_filter("required_fields", before, len(working))

        # 2) ESG filter
        before = len(working)
        working = self._apply_esg_filter(working, user_answers)
        note_filter(
            "esg_filter",
            before,
            len(working),
            {"preference": user_answers.get("esg_preference")},
        )

        # 3) ETF filter
        before = len(working)
        working = self._apply_etf_filter(working, user_answers)
        note_filter(
            "etf_filter",
            before,
            len(working),
            {"preference": user_answers.get("etf_preference")},
        )

        # 4) Risk band filter
        pre_risk = list(working)
        before = len(working)
        working = self._apply_risk_band_filter(working, risk_profile)
        note_filter("risk_band", before, len(working), {"risk_profile": risk_profile})

        # 5) Relaxation if too few candidates
        if len(working) < self.min_candidates:
            relaxed = self._apply_relaxed_risk_band(
                pre_risk, user_answers, risk_profile
            )
            trace["relaxations"].append(
                {
                    "name": "risk_band_relaxation",
                    "before": len(working),
                    "after": len(relaxed),
                    "details": {"risk_profile": risk_profile},
                }
            )
            working = relaxed

        # Ensure we can return at least final_fund_count recommendations
        if (
            len(working) < self.final_fund_count
            and len(pre_risk) >= self.final_fund_count
        ):
            trace["relaxations"].append(
                {
                    "name": "final_fund_floor",
                    "before": len(working),
                    "after": len(pre_risk),
                    "details": {"risk_profile": risk_profile},
                }
            )
            working = pre_risk

        if not working:
            return {
                "recommendations": [],
                "risk_profile": risk_profile,
                "portfolio_metrics": {},
                "explanations": {"summary": "No eligible funds after filtering."},
                "decision_trace": trace,
            }

        # 6) Score and select
        scored = self._score_funds(working, user_answers, risk_profile)
        selected = self._select_funds(scored)

        # 7) Allocate weights
        allocations = self._allocate_weights(selected, user_answers, risk_profile)

        # 8) Build recommendations and explanations
        recommendations, explanations = self._build_recommendations(
            selected, allocations, user_answers, risk_profile
        )

        # 9) Portfolio metrics
        metrics = self._compute_portfolio_metrics(recommendations, risk_profile)

        # Summary string for UI
        summary = self._build_summary(user_answers, risk_profile, metrics, trace)
        explanations["summary"] = summary

        return {
            "recommendations": recommendations,
            "risk_profile": risk_profile,
            "portfolio_metrics": metrics,
            "explanations": explanations,
            "decision_trace": trace,
        }

    # --- Mapping ---
    def _map_risk_profile(self, user_answers: Dict[str, Any]) -> Tuple[str, bool]:
        """
        Map questionnaire answers to a 3-tier risk profile.
        Returns (profile, used_fallback).
        """
        approach = str(user_answers.get("risk_approach", "")).lower()
        loss = str(user_answers.get("loss_tolerance", "")).lower()

        base = {
            "conservative": 1,
            "moderate_low": 2,
            "moderate": 3,
            "aggressive": 4,
        }.get(approach)
        if base is None:
            return "BALANCED", True

        modifier = 1 if loss == "high_loss_tolerance" else 0
        score = base + modifier

        if score <= 2:
            return "DEFENSIVE", False
        if score <= 3:
            return "BALANCED", False
        return "OPPORTUNITY", False

    # --- Filters ---
    def _apply_esg_filter(
        self, funds: List[Dict[str, Any]], user_answers: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        pref = user_answers.get("esg_preference", "no_requirement")
        if pref == "no_requirement":
            return funds
        threshold = 1 if pref == "esg_basic" else 2

        def esg_score(f: Dict[str, Any]) -> int:
            label = str(f.get("esg_label", "")).upper()
            if f.get("esg_article_9") is True:
                return 3
            if f.get("esg_article_8") is True:
                return 2
            if label in ("SFDR_ARTICLE_9", "HIGH"):
                return 3
            if label in ("SFDR_ARTICLE_8", "MEDIUM"):
                return 2
            if label == "LOW":
                return 0
            return 0

        return [f for f in funds if esg_score(f) >= threshold]

    def _apply_etf_filter(
        self, funds: List[Dict[str, Any]], user_answers: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        pref = user_answers.get("etf_preference", "no_preference")
        if pref != "etf_only":
            return funds
        return [f for f in funds if bool(f.get("is_etf"))]

    def _apply_risk_band_filter(
        self, funds: List[Dict[str, Any]], risk_profile: str
    ) -> List[Dict[str, Any]]:
        band = self._risk_band_for_profile(risk_profile)

        def risk_value(f: Dict[str, Any]) -> Optional[float]:
            if f.get("srri") is not None:
                return float(f.get("srri"))
            if f.get("risk_level") is not None:
                return float(f.get("risk_level"))
            return None

        out = []
        for f in funds:
            val = risk_value(f)
            if val is None:
                continue
            if band["min"] <= val <= band["max"]:
                out.append(f)
        return out

    def _apply_relaxed_risk_band(
        self,
        funds: List[Dict[str, Any]],
        user_answers: Dict[str, Any],
        risk_profile: str,
    ) -> List[Dict[str, Any]]:
        band = self._risk_band_for_profile(risk_profile)
        relaxed = {"min": max(1, band["min"] - 1), "max": band["max"] + 1}

        def risk_value(f: Dict[str, Any]) -> Optional[float]:
            if f.get("srri") is not None:
                return float(f.get("srri"))
            if f.get("risk_level") is not None:
                return float(f.get("risk_level"))
            return None

        out = []
        for f in funds:
            val = risk_value(f)
            if val is None:
                continue
            if relaxed["min"] <= val <= relaxed["max"]:
                out.append(f)
        return out

    def _risk_band_for_profile(self, risk_profile: str) -> Dict[str, float]:
        if risk_profile == "DEFENSIVE":
            return {"min": 1, "max": 3, "center": 2.0}
        if risk_profile == "OPPORTUNITY":
            return {"min": 5, "max": 7, "center": 6.0}
        return {"min": 3, "max": 5, "center": 4.0}

    # --- Scoring & Selection ---
    def _score_funds(
        self,
        funds: List[Dict[str, Any]],
        user_answers: Dict[str, Any],
        risk_profile: str,
    ) -> List[Dict[str, Any]]:
        fees = [self._as_float(f.get("yearly_fee", 0.0)) for f in funds]
        sharpes = [self._as_float(f.get("sharpe_ratio", 0.0)) for f in funds]
        band = self._risk_band_for_profile(risk_profile)

        def norm(
            value: float, vmin: float, vmax: float, higher_is_better: bool = True
        ) -> float:
            if vmax == vmin:
                return 50.0
            score = (value - vmin) / (vmax - vmin) * 100.0
            if not higher_is_better:
                score = 100.0 - score
            return max(0.0, min(100.0, score))

        fee_min, fee_max = min(fees or [0.0]), max(fees or [0.0])
        sharpe_min, sharpe_max = min(sharpes or [0.0]), max(sharpes or [0.0])

        def risk_value(f: Dict[str, Any]) -> float:
            if f.get("srri") is not None:
                return float(f.get("srri"))
            if f.get("risk_level") is not None:
                return float(f.get("risk_level"))
            return band["center"]

        scored = []
        for f in funds:
            fee_score = norm(
                self._as_float(f.get("yearly_fee", 0.0)),
                fee_min,
                fee_max,
                higher_is_better=False,
            )
            sharpe = self._as_float(f.get("sharpe_ratio", 0.0))
            perf_score = (
                norm(sharpe, sharpe_min, sharpe_max, higher_is_better=True)
                if sharpe > 0
                else 50.0
            )
            r_val = risk_value(f)
            risk_alignment = max(0.0, 100.0 - (abs(r_val - band["center"]) * 25.0))

            base = (0.4 * perf_score) + (0.3 * risk_alignment) + (0.3 * fee_score)
            boosts = self._preference_boosts(f, user_answers)
            final_score = base + sum(boosts.values())

            f_scored = dict(f)
            f_scored["_scores"] = {
                "base": round(base, 2),
                "perf": round(perf_score, 2),
                "risk_alignment": round(risk_alignment, 2),
                "fee": round(fee_score, 2),
                "boosts": boosts,
                "final": round(final_score, 2),
            }
            scored.append(f_scored)

        scored.sort(
            key=lambda x: (
                x["_scores"]["final"],
                x.get("sharpe_ratio", 0.0),
                -float(x.get("yearly_fee", 0.0) or 0.0),
                x.get("isin", ""),
            ),
            reverse=True,
        )
        return scored

    def _preference_boosts(
        self, fund: Dict[str, Any], user_answers: Dict[str, Any]
    ) -> Dict[str, float]:
        boosts: Dict[str, float] = {}
        if user_answers.get("etf_preference") == "prefer_etf" and fund.get("is_etf"):
            boosts["ETF"] = 5.0

        esg_pref = user_answers.get("esg_preference", "no_requirement")
        if esg_pref != "no_requirement":
            label = str(fund.get("esg_label", "")).upper()
            if label in ("HIGH", "SFDR_ARTICLE_9"):
                boosts["ESG"] = 3.0
            elif label in ("MEDIUM", "SFDR_ARTICLE_8"):
                boosts["ESG"] = 1.5

        preferred_regions = set(user_answers.get("preferred_regions") or [])
        if preferred_regions and fund.get("region") in preferred_regions:
            boosts["Region"] = 3.0

        preferred_themes = set(user_answers.get("preferred_themes") or [])
        if (
            preferred_themes
            and "none" not in preferred_themes
            and fund.get("theme") in preferred_themes
        ):
            boosts["Theme"] = 3.0

        return boosts

    def _select_funds(self, scored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        pool = scored[: self.top_k]
        selected: List[Dict[str, Any]] = []
        provider_count: Dict[str, int] = {}
        category_count: Dict[str, int] = {}

        def category_for(f: Dict[str, Any]) -> str:
            return str(f.get("asset_class") or "other").lower()

        for f in pool:
            provider = f.get("provider") or "unknown"
            category = category_for(f)
            if provider_count.get(provider, 0) >= self.max_per_provider:
                continue
            if category_count.get(category, 0) >= self.max_per_category:
                continue
            selected.append(f)
            provider_count[provider] = provider_count.get(provider, 0) + 1
            category_count[category] = category_count.get(category, 0) + 1
            if len(selected) >= self.final_fund_count:
                break

        if len(selected) < self.final_fund_count:
            # Relax caps
            for f in pool:
                if f in selected:
                    continue
                selected.append(f)
                if len(selected) >= self.final_fund_count:
                    break

        return selected

    # --- Allocation ---
    def _allocate_weights(
        self,
        selected: List[Dict[str, Any]],
        user_answers: Dict[str, Any],
        risk_profile: str,
    ) -> Dict[str, float]:
        n = len(selected)
        if n == 0:
            return {}
        weights = {f["isin"]: 1.0 / n for f in selected}

        # Risk-profile tilt by asset class
        if risk_profile in ("DEFENSIVE", "OPPORTUNITY"):
            for f in selected:
                isin = f["isin"]
                asset = str(f.get("asset_class") or "").lower()
                if asset == "equity":
                    weights[isin] *= 0.8 if risk_profile == "DEFENSIVE" else 1.2
                elif asset == "bond":
                    weights[isin] *= 1.2 if risk_profile == "DEFENSIVE" else 0.8

        # Preference tilts
        preferred_regions = set(user_answers.get("preferred_regions") or [])
        preferred_themes = set(user_answers.get("preferred_themes") or [])
        for f in selected:
            isin = f["isin"]
            if preferred_regions and f.get("region") in preferred_regions:
                weights[isin] += 0.02
            if (
                preferred_themes
                and "none" not in preferred_themes
                and f.get("theme") in preferred_themes
            ):
                weights[isin] += 0.02

        # Clip and normalize
        weights = self._normalize(weights)
        weights = self._clip_weights(weights, 0.05, 0.35)
        weights = self._normalize(weights)
        return weights

    @staticmethod
    def _clip_weights(
        weights: Dict[str, float], wmin: float, wmax: float
    ) -> Dict[str, float]:
        return {k: max(wmin, min(wmax, v)) for k, v in weights.items()}

    @staticmethod
    def _normalize(weights: Dict[str, float]) -> Dict[str, float]:
        total = sum(weights.values())
        if total <= 0:
            n = len(weights)
            return {k: 1.0 / n for k in weights}
        return {k: v / total for k, v in weights.items()}

    @staticmethod
    def _as_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    # --- Output ---
    def _build_recommendations(
        self,
        selected: List[Dict[str, Any]],
        weights: Dict[str, float],
        user_answers: Dict[str, Any],
        risk_profile: str,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        explanations: Dict[str, Any] = {"per_fund": {}}
        recs: List[Dict[str, Any]] = []

        for f in selected:
            isin = f["isin"]
            alloc = round(weights.get(isin, 0.0) * 100, 2)

            reasons = []
            if f.get("is_etf"):
                reasons.append("ETF structure supports lower costs and transparency.")
            if user_answers.get("esg_preference") in ("esg_basic", "esg_enhanced"):
                reasons.append("Meets your ESG requirement.")
            preferred_regions = set(user_answers.get("preferred_regions") or [])
            if preferred_regions and f.get("region") in preferred_regions:
                reasons.append("Matches your regional preference.")
            preferred_themes = set(user_answers.get("preferred_themes") or [])
            if (
                preferred_themes
                and "none" not in preferred_themes
                and f.get("theme") in preferred_themes
            ):
                reasons.append("Matches your thematic preference.")

            score_info = f.get("_scores", {})
            reasons.append(
                "Risk alignment and cost efficiency score: "
                f"{score_info.get('base', 'n/a')}."
            )

            explanations["per_fund"][isin] = reasons

            recs.append(
                {
                    "isin": isin,
                    "name": f.get("name"),
                    "allocation_percent": alloc,
                    "asset_class": f.get("asset_class"),
                    "yearly_fee": f.get("yearly_fee", 0.0),
                    "provider": f.get("provider"),
                    "region": f.get("region"),
                    "theme": f.get("theme"),
                    "is_etf": f.get("is_etf"),
                    "esg_label": f.get("esg_label"),
                    "rationale": " ".join(reasons[:2])
                    if reasons
                    else "Aligned with your preferences.",
                    "explanations": reasons,
                }
            )

        # Fix rounding to sum 100
        total = sum(r["allocation_percent"] for r in recs)
        diff = round(100.0 - total, 2)
        if recs and abs(diff) > 0:
            recs[0]["allocation_percent"] = round(
                recs[0]["allocation_percent"] + diff, 2
            )

        return recs, explanations

    def _compute_portfolio_metrics(
        self, recommendations: List[Dict[str, Any]], risk_profile: str
    ) -> Dict[str, Any]:
        if not recommendations:
            return {}

        weighted_fee = 0.0
        total_weight = 0.0
        region_exposure: Dict[str, float] = {}
        theme_exposure: Dict[str, float] = {}
        etf_share = 0.0

        for r in recommendations:
            w = (r.get("allocation_percent", 0.0) or 0.0) / 100.0
            total_weight += w
            weighted_fee += w * float(r.get("yearly_fee", 0.0) or 0.0)

            region = r.get("region") or "unknown"
            theme = r.get("theme") or "none"
            region_exposure[region] = region_exposure.get(region, 0.0) + w
            theme_exposure[theme] = theme_exposure.get(theme, 0.0) + w

            if r.get("is_etf"):
                etf_share += w

        if total_weight <= 0:
            total_weight = 1.0

        # Approximate SRRI proxy from risk profile
        srri_proxy = {"DEFENSIVE": 3, "BALANCED": 4, "OPPORTUNITY": 6}.get(
            risk_profile, 4
        )

        return {
            "risk_profile": risk_profile,
            "srri_proxy": srri_proxy,
            "weighted_fee": round(weighted_fee, 3),
            "region_exposures": {k: round(v, 3) for k, v in region_exposure.items()},
            "theme_exposures": {k: round(v, 3) for k, v in theme_exposure.items()},
            "etf_share": round(etf_share, 3),
        }

    def _build_summary(
        self,
        user_answers: Dict[str, Any],
        risk_profile: str,
        metrics: Dict[str, Any],
        trace: Dict[str, Any],
    ) -> str:
        parts = [
            f"Risk profile: {risk_profile}.",
            f"Weighted fee estimate: {metrics.get('weighted_fee', 'n/a')}%.",
        ]
        if user_answers.get("esg_preference") in ("esg_basic", "esg_enhanced"):
            parts.append("ESG filters applied.")
        if user_answers.get("etf_preference") == "etf_only":
            parts.append("ETF-only filter applied.")
        if user_answers.get("preferred_regions"):
            parts.append("Regional preferences considered.")
        if user_answers.get("preferred_themes") and "none" not in user_answers.get(
            "preferred_themes"
        ):
            parts.append("Thematic preferences considered.")
        if trace.get("used_fallback_risk"):
            parts.append("Risk profile fallback applied.")
        if trace.get("relaxations"):
            parts.append("Risk filters were relaxed to ensure enough eligible funds.")
        return " ".join(parts)
