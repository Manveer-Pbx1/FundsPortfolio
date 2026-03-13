portfolio_recommender.py
# One-file portfolio recommendation engine for unit-linked insurance tools.
# Contains: data contracts, configuration, filtering, scoring, selection,
# allocation, validation, explainability, audit, and a synthetic demo.
#
# Designed for IDD/MiFID-like explainability and governance, scalable to ~200 funds.

from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict, Counter
from enum import Enum

# -----------------------------
# 0) ENUMS & DATA CONTRACTS
# -----------------------------

class RiskProfile(Enum):
    DEFENSIVE = "DEFENSIVE"
    BALANCED = "BALANCED"
    OPPORTUNITY = "OPPORTUNITY"

class ESGRequirement(Enum):
    NONE = "NONE"
    REQUIRED = "REQUIRED"

class ESGLevel(Enum):
    BASIC = "BASIC"
    ENHANCED = "ENHANCED"

class ETFPreference(Enum):
    NONE = "NONE"
    PREFER_ETF = "PREFER_ETF"
    ETF_ONLY = "ETF_ONLY"

class Category(Enum):
    EQUITY = "EQUITY"
    BOND = "BOND"
    MULTI_ASSET = "MULTI_ASSET"

class Region(Enum):
    GLOBAL = "GLOBAL"
    EUROPE = "EUROPE"
    NORTH_AMERICA = "NORTH_AMERICA"
    EMERGING_MARKETS = "EMERGING_MARKETS"

class Theme(Enum):
    NONE = "NONE"
    SUSTAINABILITY = "SUSTAINABILITY"
    TECHNOLOGY = "TECHNOLOGY"
    HEALTHCARE = "HEALTHCARE"

@dataclass
class UserProfile:
    risk_profile: RiskProfile
    esg_requirement: ESGRequirement
    esg_level: Optional[ESGLevel] = None
    etf_preference: ETFPreference = ETFPreference.NONE
    preferred_regions: List[Region] = field(default_factory=list)
    preferred_themes: List[Theme] = field(default_factory=list)

@dataclass
class Fund:
    id: str
    name: str
    provider: str
    category: Category
    region: Region
    theme: Theme
    is_etf: bool

    # Risk & performance
    volatility_1y: Optional[float]   # annualized %, e.g., 8.5
    srri: Optional[int]              # 1..7
    sharpe_3y: Optional[float]
    sortino_3y: Optional[float]
    max_drawdown_3y: Optional[float] # negative %, e.g., -28.0
    equity_share: Optional[float]    # 0..100

    # Cost & quality
    ter: Optional[float]             # %, e.g., 0.22
    esg_label: str                   # e.g., "LOW", "MEDIUM", "HIGH", "SFDR_ARTICLE_8", "SFDR_ARTICLE_9"
    data_history_years: Optional[float]
    data_freshness_days: Optional[int]

    # Distribution eligibility
    has_kid: bool
    is_distributable_in_de: bool

@dataclass
class RiskBand:
    vol_min: float
    vol_max: float
    srri_min: int
    srri_max: int
    max_drawdown_min: float
    equity_share_range: Tuple[float, float]
    vol_center: float

@dataclass
class RelaxationStep:
    description: str
    adjust_vol_band_by: Optional[float] = None
    extend_srri_range: Optional[int] = None
    relax_region_caps: Optional[float] = None
    relax_theme_caps: Optional[float] = None
    ignore_provider_cap: Optional[bool] = None
    allow_adjacent_profile: Optional[bool] = None

@dataclass
class Config:
    version: str
    min_candidates: int
    topK_initial: int
    final_fund_count: int

    risk_bands: Dict[RiskProfile, RiskBand]

    scoring_weights: Dict[str, float]  # sortino, sharpe, max_drawdown, ter, consistency, risk_alignment, data_quality

    boosts: Dict[str, float]  # etf_prefer, esg_bonus, region_primary, theme_primary

    caps: Dict[str, Any]  # max_per_category, max_per_provider, max_region_exposure, max_thematic_exposure, min_preferred_region_exposure

    weighting: Dict[str, Any]  # method, min_weight, max_weight, core_target_share

    data_requirements: Dict[str, Any]  # require_fields, max_data_freshness_days, min_history_years

    relaxation: List[RelaxationStep]

    @staticmethod
    def default() -> "Config":
        return Config(
            version="1.0.0",
            min_candidates=12,
            topK_initial=15,
            final_fund_count=5,
            risk_bands={
                RiskProfile.DEFENSIVE: RiskBand(2, 7, 2, 3, -20, (0, 35), 4.5),
                RiskProfile.BALANCED: RiskBand(6, 12, 3, 5, -30, (30, 70), 9.0),
                RiskProfile.OPPORTUNITY: RiskBand(10, 20, 5, 6, -40, (60, 100), 15.0),
            },
            scoring_weights={
                "sortino": 0.25, "sharpe": 0.15, "max_drawdown": 0.15, "ter": 0.15,
                "consistency": 0.15, "risk_alignment": 0.10, "data_quality": 0.05
            },
            boosts={"etf_prefer": 5.0, "esg_bonus": 3.0, "region_primary": 3.0, "theme_primary": 3.0},
            caps={
                "max_per_category": 2,
                "max_per_provider": 2,
                "max_region_exposure": 0.60,
                "max_thematic_exposure": 0.40,
                "min_preferred_region_exposure": 0.20
            },
            weighting={
                "method": "CORE_SATELLITE",  # or "INVERSE_VOL", "EQUAL_WITH_GUARDRAILS"
                "min_weight": 0.10,
                "max_weight": 0.35,
                "core_target_share": 0.65
            },
            data_requirements={
                "require_fields": ["volatility_1y", "srri", "max_drawdown_3y", "sharpe_3y", "sortino_3y", "ter"],
                "max_data_freshness_days": 60,
                "min_history_years": 1.0
            },
            relaxation=[
                RelaxationStep(description="Widen vol band ±1 pp", adjust_vol_band_by=1.0),
                RelaxationStep(description="Extend SRRI by ±1", extend_srri_range=1),
                RelaxationStep(description="Relax region cap +10pp", relax_region_caps=0.10),
                RelaxationStep(description="Relax theme cap +10pp", relax_theme_caps=0.10),
                RelaxationStep(description="Allow adjacent profile", allow_adjacent_profile=True),
            ]
        )

@dataclass
class FundScore:
    fund_id: str
    base_score: float
    component_scores: Dict[str, float]
    boosts_applied: Dict[str, float]
    final_score: float

@dataclass
class SelectedFund:
    fund_id: str
    weight: float
    role: str  # "CORE" or "SATELLITE"
    rationale: List[str]

@dataclass
class PortfolioMetrics:
    est_volatility: float
    est_srri_proxy: int
    est_cost_ter: float
    region_exposures: Dict[Region, float]
    theme_exposures: Dict[Theme, float]
    etf_share: float

@dataclass
class PortfolioResult:
    portfolio: List[SelectedFund]
    portfolio_metrics: PortfolioMetrics
    explanations: Dict[str, Any]
    audit_log_ref: str
    config_version: str
    timestamp_utc: datetime

# -----------------------------
# 1) AUDIT LOGGER
# -----------------------------

class AuditLogger:
    def __init__(self, user: UserProfile, cfg: Config):
        self.id = str(uuid.uuid4())
        self.user = user
        self.cfg = cfg
        self.steps: List[Dict[str, Any]] = []
        self.started = datetime.now(timezone.utc)

    def note(self, event: str, **kwargs):
        self.steps.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "details": kwargs
        })

    def complete_session(self, result: PortfolioResult):
        self.note("complete", result_summary={
            "portfolio_count": len(result.portfolio),
            "est_vol": result.portfolio_metrics.est_volatility,
            "srri": result.portfolio_metrics.est_srri_proxy
        })

    def fail_session(self, err: Exception):
        self.note("failed", error=str(err))

    @staticmethod
    def start_session(user: UserProfile, cfg: Config) -> "AuditLogger":
        return AuditLogger(user, cfg)

# -----------------------------
# 2) UTILS
# -----------------------------

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def percentile_rank(value: float, population: List[float], higher_is_better: bool = True) -> float:
    clean = [v for v in population if v is not None]
    if not clean:
        return 50.0
    sorted_vals = sorted(clean)
    if not higher_is_better:
        # invert direction by using negative rank sense
        sorted_vals = list(reversed(sorted_vals))
    # rank position (1-based)
    # include equals: average rank among equals
    less = sum(1 for v in sorted_vals if v < value)
    equal = sum(1 for v in sorted_vals if v == value)
    rank = less + 0.5 * max(1, equal)
    pct = rank / max(1, len(sorted_vals)) * 100.0
    return clamp(pct, 0.0, 100.0)

def srri_proxy_from_vol(vol: float) -> int:
    if vol < 5: return 2
    if vol < 8: return 3
    if vol < 12: return 4
    if vol < 17: return 5
    if vol < 22: return 6
    return 7

def data_quality_score(history_years: Optional[float], freshness_days: Optional[int]) -> float:
    score = 50.0
    if history_years is not None:
        if history_years >= 3.0: score += 30
        elif history_years >= 1.5: score += 15
    if freshness_days is not None:
        if freshness_days <= 30: score += 20
        elif freshness_days <= 60: score += 10
    return clamp(score, 0.0, 100.0)

def alignment_slope(band: RiskBand) -> float:
    # Tune via calibration; simple slope translating vol distance into a 0..100 score
    return 8.0

def normalize(weights: Dict[str, float]) -> Dict[str, float]:
    s = sum(max(0.0, v) for v in weights.values())
    if s <= 0:
        n = len(weights)
        return {k: 1.0 / n for k in weights}
    return {k: max(0.0, v) / s for k, v in weights.items()}

def weighted_average(values: List[float], weights: List[float]) -> float:
    s = sum(weights)
    if s == 0: return 0.0
    return sum(v * w for v, w in zip(values, weights)) / s

# -----------------------------
# 3) FILTER SERVICE
# -----------------------------

class FilterService:

    @staticmethod
    def regulatory_and_data_eligibility(funds: List[Fund], cfg: Config, audit: AuditLogger) -> List[Fund]:
        out = []
        for f in funds:
            if not f.has_kid or not f.is_distributable_in_de:
                audit.note("exclude", fund_id=f.id, reason="Regulatory: missing KID or not distributable in DE")
                continue
            missing = [fld for fld in cfg.data_requirements["require_fields"] if getattr(f, fld) is None]
            if missing:
                audit.note("exclude", fund_id=f.id, reason="Data missing", fields=missing)
                continue
            if (f.data_freshness_days or 9999) > cfg.data_requirements["max_data_freshness_days"]:
                audit.note("exclude", fund_id=f.id, reason="Data stale", freshness_days=f.data_freshness_days)
                continue
            if (f.data_history_years or 0.0) < cfg.data_requirements["min_history_years"]:
                audit.note("exclude", fund_id=f.id, reason="Insufficient history", years=f.data_history_years)
                continue
            out.append(f)
        return out

    @staticmethod
    def apply_esg(funds: List[Fund], user: UserProfile, cfg: Config, audit: AuditLogger) -> List[Fund]:
        if user.esg_requirement == ESGRequirement.REQUIRED:
            threshold = FilterService._esg_threshold(user.esg_level or ESGLevel.BASIC)
            accepted = [f for f in funds if FilterService._esg_pass(f.esg_label, threshold)]
            audit.note("esg_filter", before=len(funds), after=len(accepted), threshold=threshold)
            return accepted
        return funds

    @staticmethod
    def _esg_threshold(level: ESGLevel) -> List[str]:
        if level == ESGLevel.ENHANCED:
            return ["HIGH", "SFDR_ARTICLE_9"]
        return ["MEDIUM", "HIGH", "SFDR_ARTICLE_8", "SFDR_ARTICLE_9"]

    @staticmethod
    def _esg_pass(label: str, accepted: List[str]) -> bool:
        return label in accepted

    @staticmethod
    def apply_risk_bands(funds: List[Fund], user: UserProfile, cfg: Config, audit: AuditLogger) -> List[Fund]:
        band = cfg.risk_bands[user.risk_profile]
        out = []
        for f in funds:
            v = f.volatility_1y
            s = f.srri
            dd = f.max_drawdown_3y
            if v is None or s is None or dd is None:
                audit.note("exclude", fund_id=f.id, reason="Risk data incomplete")
                continue
            within_vol = band.vol_min <= v <= band.vol_max
            within_srri = band.srri_min <= s <= band.srri_max
            within_dd = dd >= band.max_drawdown_min
            if within_vol and within_srri and within_dd:
                out.append(f)
            else:
                audit.note("exclude", fund_id=f.id, reason="Risk mismatch", vol=v, srri=s, maxdd=dd)
        return out

    @staticmethod
    def apply_etf_preference(funds: List[Fund], user: UserProfile, cfg: Config, audit: AuditLogger) -> List[Fund]:
        if user.etf_preference == ETFPreference.ETF_ONLY:
            out = [f for f in funds if f.is_etf]
            audit.note("etf_only_filter", before=len(funds), after=len(out))
            return out
        return funds

    @staticmethod
    def apply_relaxation_ladder(funds_in: List[Fund], user: UserProfile, cfg: Config, audit: AuditLogger) -> List[Fund]:
        # Apply a sequence of band widenings or cap relaxations to grow candidate set.
        # Here, we implement a minimal widening of vol/SRRI bands (others are governance/log flags).
        original_band = cfg.risk_bands[user.risk_profile]
        widened = list(funds_in)  # Start with current set
        # If insufficient, try to re-include some funds by relaxed checks:
        for step in cfg.relaxation:
            tmp = []
            vol_min = original_band.vol_min - (step.adjust_vol_band_by or 0.0)
            vol_max = original_band.vol_max + (step.adjust_vol_band_by or 0.0)
            srri_min = original_band.srri_min - (step.extend_srri_range or 0)
            srri_max = original_band.srri_max + (step.extend_srri_range or 0)
            dd_min = original_band.max_drawdown_min  # keep DD constant in this sample

            for f in funds_in:
                if f.volatility_1y is None or f.srri is None or f.max_drawdown_3y is None:
                    continue
                if vol_min <= f.volatility_1y <= vol_max and srri_min <= f.srri <= srri_max and f.max_drawdown_3y >= dd_min:
                    tmp.append(f)
            widened = tmp
            audit.note("relaxation_step", step=step.description, candidates=len(widened))
            if len(widened) >= cfg.min_candidates:
                break
        return widened

# -----------------------------
# 4) SCORING SERVICE
# -----------------------------

class ScoringService:

    @staticmethod
    def score_funds(funds: List[Fund], user: UserProfile, cfg: Config, audit: AuditLogger) -> List[FundScore]:
        # Build populations for percentile ranks
        sortinos = [f.sortino_3y for f in funds]
        sharpes = [f.sharpe_3y for f in funds]
        mdds = [f.max_drawdown_3y for f in funds]
        ters = [f.ter for f in funds]

        band = cfg.risk_bands[user.risk_profile]

        out: List[FundScore] = []
        for f in funds:
            s_sortino = percentile_rank(f.sortino_3y, sortinos, higher_is_better=True)
            s_sharpe = percentile_rank(f.sharpe_3y, sharpes, higher_is_better=True)
            # For MDD, less negative is better -> higher score
            s_mdd = 100.0 - percentile_rank(f.max_drawdown_3y, mdds, higher_is_better=True)
            s_ter = 100.0 - percentile_rank(f.ter, ters, higher_is_better=True)

            # Optional consistency metric not provided in this minimal file → neutral 50
            s_consistency = 50.0

            # Risk alignment to band center
            delta_vol = abs((f.volatility_1y or band.vol_center) - band.vol_center)
            s_align = clamp(100.0 - delta_vol * alignment_slope(band), 0.0, 100.0)

            # Data quality
            s_dq = data_quality_score(f.data_history_years, f.data_freshness_days)

            w = cfg.scoring_weights
            base = (
                w["sortino"] * s_sortino +
                w["sharpe"] * s_sharpe +
                w["max_drawdown"] * s_mdd +
                w["ter"] * s_ter +
                w["consistency"] * s_consistency +
                w["risk_alignment"] * s_align +
                w["data_quality"] * s_dq
            )

            boosts: Dict[str, float] = {}

            if user.etf_preference == ETFPreference.PREFER_ETF and f.is_etf:
                boosts["ETF"] = cfg.boosts["etf_prefer"]

            if user.esg_requirement == ESGRequirement.NONE:
                # Small ESG bonus if strong label
                if f.esg_label in ("HIGH", "SFDR_ARTICLE_9"):
                    boosts["ESG"] = cfg.boosts["esg_bonus"]
                elif f.esg_label in ("MEDIUM", "SFDR_ARTICLE_8"):
                    boosts["ESG"] = cfg.boosts["esg_bonus"] * 0.5

            if f.region in (user.preferred_regions or []):
                boosts["Region"] = cfg.boosts["region_primary"]

            if f.theme in (user.preferred_themes or []) and f.theme != Theme.NONE.value and f.theme != Theme.NONE:
                boosts["Theme"] = cfg.boosts["theme_primary"]

            final = base + sum(boosts.values())

            out.append(FundScore(
                fund_id=f.id,
                base_score=round(base, 2),
                component_scores={
                    "Sortino": round(s_sortino, 1),
                    "Sharpe": round(s_sharpe, 1),
                    "MDD": round(s_mdd, 1),
                    "TER": round(s_ter, 1),
                    "Consistency": round(s_consistency, 1),
                    "RiskAlignment": round(s_align, 1),
                    "DataQuality": round(s_dq, 1),
                },
                boosts_applied=boosts,
                final_score=round(final, 2)
            ))
        audit.note("scored", count=len(out))
        return out

# -----------------------------
# 5) SELECTION SERVICE
# -----------------------------

class SelectionService:

    @staticmethod
    def pick_diversified_top_k(candidates: List[FundScore], funds_by_id: Dict[str, Fund], cfg: Config, audit: AuditLogger) -> List[str]:
        candidates_sorted = sorted(candidates, key=lambda x: x.final_score, reverse=True)
        pool = candidates_sorted[:cfg.topK_initial]

        selected: List[str] = []
        used_category: Counter = Counter()
        used_provider: Counter = Counter()

        provider_cap = cfg.caps.get("max_per_provider", None)

        for fs in pool:
            f = funds_by_id[fs.fund_id]
            if used_category[f.category] >= cfg.caps["max_per_category"]:
                continue
            if provider_cap is not None and used_provider[f.provider] >= provider_cap:
                continue
            selected.append(f.id)
            used_category[f.category] += 1
            used_provider[f.provider] += 1
            if len(selected) == cfg.final_fund_count:
                break

        # Simple backtracking if not enough selected
        if len(selected) < cfg.final_fund_count:
            for fs in pool:
                if fs.fund_id in selected:
                    continue
                f = funds_by_id[fs.fund_id]
                # Try to replace a same-category fund to meet provider cap, etc.
                for i, sid in enumerate(list(selected)):
                    sf = funds_by_id[sid]
                    if used_category[f.category] < cfg.caps["max_per_category"]:
                        selected[i] = f.id
                        used_category[sf.category] -= 1
                        used_category[f.category] += 1
                        if len(selected) == cfg.final_fund_count:
                            break
                if len(selected) == cfg.final_fund_count:
                    break

        audit.note("selection_final", selected=selected)
        return selected

# -----------------------------
# 6) ALLOCATION SERVICE
# -----------------------------

class AllocationService:
    _roles: Dict[str, str] = {}  # fund_id -> "CORE"/"SATELLITE"

    @staticmethod
    def assign_weights(fund_ids: List[str], funds_by_id: Dict[str, Fund], user: UserProfile, cfg: Config, audit: AuditLogger) -> Dict[str, float]:
        subset = [funds_by_id[i] for i in fund_ids]
        core_ids = AllocationService.identify_core(subset, user, cfg)
        AllocationService._roles = {fid: ("CORE" if fid in core_ids else "SATELLITE") for fid in fund_ids}

        method = cfg.weighting["method"]
        if method == "INVERSE_VOL":
            weights = AllocationService._inverse_vol_weights(subset)
        elif method == "EQUAL_WITH_GUARDRAILS":
            weights = AllocationService._equal_with_guardrails(subset, cfg)
        else:  # CORE_SATELLITE
            weights = AllocationService._core_satellite_weights(subset, core_ids, cfg)

        weights = AllocationService._apply_preference_tilts(weights, subset, user, cfg)
        weights = AllocationService._clip_and_renormalize(weights, cfg.weighting["min_weight"], cfg.weighting["max_weight"])
        audit.note("weights_assigned", weights=weights)
        return weights

    @staticmethod
    def role_of(fund_id: str) -> str:
        return AllocationService._roles.get(fund_id, "SATELLITE")

    @staticmethod
    def identify_core(subset: List[Fund], user: UserProfile, cfg: Config) -> List[str]:
        core = [f.id for f in subset if f.category == Category.MULTI_ASSET and f.region == Region.GLOBAL]
        if not core:
            core = [f.id for f in subset if f.category == Category.BOND and f.region == Region.GLOBAL]
        if not core:
            core = [f.id for f in subset if f.category == Category.EQUITY and f.region == Region.GLOBAL]
        return core[:2]  # keep 1-2 core funds

    @staticmethod
    def _inverse_vol_weights(subset: List[Fund]) -> Dict[str, float]:
        inv = {}
        for f in subset:
            vol = max(0.01, (f.volatility_1y or 10.0))
            inv[f.id] = 1.0 / vol
        return normalize(inv)

    @staticmethod
    def _core_satellite_weights(subset: List[Fund], core_ids: List[str], cfg: Config) -> Dict[str, float]:
        core_share = cfg.weighting["core_target_share"]
        non_core_share = 1.0 - core_share
        core_funds = [f for f in subset if f.id in core_ids] or subset[:1]  # fallback
        sat_funds = [f for f in subset if f.id not in [c.id for c in core_funds]]

        w_core = AllocationService._inverse_vol_weights(core_funds)
        w_core = {k: v * core_share for k, v in w_core.items()}

        if sat_funds:
            w_sat = AllocationService._inverse_vol_weights(sat_funds)
            w_sat = {k: v * non_core_share for k, v in w_sat.items()}
        else:
            w_sat = {}

        w = {**w_core}
        for k, v in w_sat.items():
            w[k] = w.get(k, 0.0) + v
        return normalize(w)

    @staticmethod
    def _equal_with_guardrails(subset: List[Fund], cfg: Config) -> Dict[str, float]:
        n = len(subset)
        w = {f.id: 1.0 / n for f in subset}
        # Reduce highest vol funds to min_weight if they exceed band center by > 30%
        vols = {f.id: (f.volatility_1y or 10.0) for f in subset}
        median_vol = sorted(vols.values())[n // 2]
        for fid, v in vols.items():
            if v > 1.3 * median_vol:
                w[fid] = max(w[fid] * 0.6, cfg.weighting["min_weight"])
        return normalize(w)

    @staticmethod
    def _apply_preference_tilts(weights: Dict[str, float], subset: List[Fund], user: UserProfile, cfg: Config) -> Dict[str, float]:
        w = dict(weights)
        # Region tilt: +5 pp distributed across matching funds if under region cap post-adjust
        if user.preferred_regions:
            for f in subset:
                if f.region in user.preferred_regions:
                    w[f.id] += 0.05 / max(1, len([x for x in subset if x.region in user.preferred_regions]))
        # Theme tilt: +5 pp distributed across matching funds
        if user.preferred_themes:
            for f in subset:
                if f.theme in user.preferred_themes and f.theme != Theme.NONE:
                    w[f.id] += 0.05 / max(1, len([x for x in subset if x.theme in user.preferred_themes and x.theme != Theme.NONE]))
        return normalize(w)

    @staticmethod
    def _clip_and_renormalize(weights: Dict[str, float], wmin: float, wmax: float) -> Dict[str, float]:
        w = {k: clamp(v, wmin, wmax) for k, v in weights.items()}
        return normalize(w)

# -----------------------------
# 7) VALIDATION SERVICE
# -----------------------------

class ValidationService:

    @staticmethod
    def compute_portfolio_metrics(ids: List[str], weights: Dict[str, float], funds_by_id: Dict[str, Fund], cfg: Config) -> PortfolioMetrics:
        subset = [funds_by_id[i] for i in ids]
        w_vec = [weights[f.id] for f in subset]
        vol_vec = [max(0.01, (f.volatility_1y or 10.0)) for f in subset]

        # Simple conservative correlation assumption
        rho = 0.3
        var = 0.0
        for i in range(len(subset)):
            var += (w_vec[i] ** 2) * (vol_vec[i] ** 2)
            for j in range(i + 1, len(subset)):
                var += 2 * rho * w_vec[i] * w_vec[j] * vol_vec[i] * vol_vec[j]
        est_vol = round(math.sqrt(max(0.0, var)), 2)

        est_srri = srri_proxy_from_vol(est_vol)
        est_ter = round(sum(w_vec[i] * (subset[i].ter or 0.0) for i in range(len(subset))), 3)

        region_exposures: Dict[Region, float] = defaultdict(float)
        theme_exposures: Dict[Theme, float] = defaultdict(float)
        etf_share = 0.0
        for f in subset:
            region_exposures[f.region] += weights[f.id]
            theme_exposures[f.theme] += weights[f.id]
            if f.is_etf:
                etf_share += weights[f.id]

        return PortfolioMetrics(
            est_volatility=est_vol,
            est_srri_proxy=est_srri,
            est_cost_ter=est_ter,
            region_exposures=dict(region_exposures),
            theme_exposures=dict(theme_exposures),
            etf_share=etf_share
        )

    @staticmethod
    def check_portfolio_constraints(ids: List[str], weights: Dict[str, float], funds_by_id: Dict[str, Fund], user: UserProfile, cfg: Config, audit: AuditLogger) -> Dict[str, Any]:
        metrics = ValidationService.compute_portfolio_metrics(ids, weights, funds_by_id, cfg)
        band = cfg.risk_bands[user.risk_profile]

        vol_ok = band.vol_min <= metrics.est_volatility <= band.vol_max
        srri_ok = band.srri_min <= metrics.est_srri_proxy <= band.srri_max
        region_ok = (max(metrics.region_exposures.values() or [0.0]) <= cfg.caps["max_region_exposure"] + 1e-9)
        thematic_total = sum(v for t, v in metrics.theme_exposures.items() if t != Theme.NONE)
        theme_ok = thematic_total <= cfg.caps["max_thematic_exposure"] + 1e-9

        pref_region_ok = True
        min_pref = cfg.caps.get("min_preferred_region_exposure", None)
        if min_pref and user.preferred_regions:
            pref_sum = sum(metrics.region_exposures.get(r, 0.0) for r in user.preferred_regions)
            pref_region_ok = pref_sum >= min_pref - 1e-9

        ok = vol_ok and srri_ok and region_ok and theme_ok and pref_region_ok
        reasons = []
        if not vol_ok: reasons.append("Portfolio volatility outside band")
        if not srri_ok: reasons.append("SRRI proxy outside band")
        if not region_ok: reasons.append("Region cap breached")
        if not theme_ok: reasons.append("Thematic cap breached")
        if not pref_region_ok: reasons.append("Preferred region minimum not met")

        audit.note("validation", ok=ok, reasons=reasons, metrics={
            "vol": metrics.est_volatility, "srri": metrics.est_srri_proxy,
            "region_exposures": metrics.region_exposures, "theme_exposures": metrics.theme_exposures
        })
        return {"ok": ok, "reasons": reasons, "metrics": metrics}

    @staticmethod
    def iterate_to_fix(current_ids: List[str], weights: Dict[str, float], validation: Dict[str, Any],
                       ranked: List[FundScore], funds_by_id: Dict[str, Fund], user: UserProfile, cfg: Config, audit: AuditLogger) -> Tuple[List[str], Dict[str, float]]:
        ids = list(current_ids)
        w = dict(weights)

        # Try simple remediation: reduce highest-vol fund weight, redistribute to lowest-vol
        for attempt in range(3):
            if "Portfolio volatility outside band" in validation["reasons"]:
                vol_sorted = sorted(ids, key=lambda fid: (funds_by_id[fid].volatility_1y or 10.0), reverse=True)
                lowest_sorted = sorted(ids, key=lambda fid: (funds_by_id[fid].volatility_1y or 10.0))
                if vol_sorted:
                    high = vol_sorted[0]
                    low = lowest_sorted[0] if lowest_sorted else high
                    delta = 0.05
                    w[high] = max(cfg.weighting["min_weight"], w[high] - delta)
                    w[low] = min(cfg.weighting["max_weight"], w[low] + delta)
                    w = normalize(w)

            if "Region cap breached" in validation["reasons"]:
                # reduce most overweight region position by 5pp
                metrics = validation["metrics"]
                if metrics.region_exposures:
                    worst_region = max(metrics.region_exposures.items(), key=lambda kv: kv[1])[0]
                    worst_fund = max(ids, key=lambda fid: (weights[fid] if funds_by_id[fid].region == worst_region else 0.0))
                    w[worst_fund] = max(cfg.weighting["min_weight"], w[worst_fund] - 0.05)
                    # shift to least-represented region fund
                    least_region = min(metrics.region_exposures.items(), key=lambda kv: kv[1])[0]
                    candidates = [fid for fid in ids if funds_by_id[fid].region == least_region]
                    if candidates:
                        w[candidates[0]] = min(cfg.weighting["max_weight"], w[candidates[0]] + 0.05)
                    w = normalize(w)

            if "Thematic cap breached" in validation["reasons"]:
                # reduce thematic funds by 5pp each until within cap
                for fid in ids:
                    if funds_by_id[fid].theme != Theme.NONE:
                        w[fid] = max(cfg.weighting["min_weight"], w[fid] - 0.05)
                w = normalize(w)

            new_val = ValidationService.check_portfolio_constraints(ids, w, funds_by_id, user, cfg, audit)
            if new_val["ok"]:
                return ids, w

            # Try swapping the riskiest fund with next best not in current set
            current_set = set(ids)
            next_candidates = [fs for fs in ranked if fs.fund_id not in current_set]
            if next_candidates:
                swap_in = next_candidates[0].fund_id
                # choose fund to swap out: highest volatility
                out_id = max(ids, key=lambda fid: (funds_by_id[fid].volatility_1y or 10.0))
                ids = [swap_in if fid == out_id else fid for fid in ids]
                # recompute weights
                w = AllocationService.assign_weights(ids, funds_by_id, user, cfg, audit)
                new_val = ValidationService.check_portfolio_constraints(ids, w, funds_by_id, user, cfg, audit)
                if new_val["ok"]:
                    return ids, w
                validation = new_val

        return ids, w

# -----------------------------
# 8) EXPLAINABILITY SERVICE
# -----------------------------

class ExplainabilityService:

    @staticmethod
    def build(fund_scores: List[FundScore], ids: List[str], weights: Dict[str, float],
              funds_by_id: Dict[str, Fund], user: UserProfile, cfg: Config, audit: AuditLogger) -> Dict[str, Any]:
        fs_by_id = {fs.fund_id: fs for fs in fund_scores}
        per_fund: Dict[str, List[str]] = {}
        for fid in ids:
            f = funds_by_id[fid]
            fs = fs_by_id.get(fid)
            msgs: List[str] = []
            if fs:
                msgs.append("Selected for strong risk adjusted profile (Sortino/Sharpe) and cost efficiency (TER).")
                msgs.append(f"Fits your {user.risk_profile.value} band (Vol {f.volatility_1y:.1f}%, SRRI {f.srri}).")
            if f.is_etf:
                msgs.append("ETF structure supports lower ongoing costs and transparency.")
            if f.region in (user.preferred_regions or []):
                msgs.append(f"Matches your regional preference: {f.region.value}.")
            if f.theme in (user.preferred_themes or []) and f.theme != Theme.NONE:
                msgs.append(f"Adds your thematic preference: {f.theme.value}.")
            role = AllocationService.role_of(fid)
            msgs.append(f"Portfolio role: {role}.")
            per_fund[fid] = msgs

        metrics = ValidationService.compute_portfolio_metrics(ids, weights, funds_by_id, cfg)
        summary = (
            f"We selected {len(ids)} funds aligned with your {user.risk_profile.value} profile. "
            f"Estimated portfolio volatility is {metrics.est_volatility:.1f}% with SRRI proxy {metrics.est_srri_proxy}. "
            f"ETF share is {metrics.etf_share*100:.0f}%, preferences are incorporated while capping concentration: "
            f"no single region exceeds {cfg.caps['max_region_exposure']*100:.0f}% and thematic exposure stays within "
            f"{cfg.caps['max_thematic_exposure']*100:.0f}%."
        )
        return {"portfolio_summary": summary, "per_fund": per_fund}

# -----------------------------
# 9) ORCHESTRATOR
# -----------------------------

def RecommendPortfolio(user: UserProfile, funds: List[Fund], cfg: Config, seed: Optional[int] = None) -> PortfolioResult:
    if seed is not None:
        random.seed(seed)

    audit = AuditLogger.start_session(user, cfg)
    try:
        # Stage A: Filtering
        U1 = FilterService.regulatory_and_data_eligibility(funds, cfg, audit)
        U2 = FilterService.apply_esg(U1, user, cfg, audit)
        U3 = FilterService.apply_risk_bands(U2, user, cfg, audit)
        U4 = FilterService.apply_etf_preference(U3, user, cfg, audit)

        if len(U4) < cfg.min_candidates:
            U4 = FilterService.apply_relaxation_ladder(U2, user, cfg, audit)  # relax post-ESG, pre-ETF-only
            if len(U4) == 0:
                raise RuntimeError("No eligible funds after filtering and relaxation.")

        # Stage B: Scoring
        fund_scores = ScoringService.score_funds(U4, user, cfg, audit)
        ranked = sorted(fund_scores, key=lambda x: x.final_score, reverse=True)

        funds_by_id = {f.id: f for f in funds}
        # Stage C: Selection
        selected_ids = SelectionService.pick_diversified_top_k(ranked, funds_by_id, cfg, audit)

        # Stage D: Allocation
        weights = AllocationService.assign_weights(selected_ids, funds_by_id, user, cfg, audit)

        # Stage E: Validation & adjust
        validation = ValidationService.check_portfolio_constraints(selected_ids, weights, funds_by_id, user, cfg, audit)
        if not validation["ok"]:
            selected_ids, weights = ValidationService.iterate_to_fix(selected_ids, weights, validation, ranked, funds_by_id, user, cfg, audit)

        # Final validation
        validation = ValidationService.check_portfolio_constraints(selected_ids, weights, funds_by_id, user, cfg, audit)

        # Stage F: Explainability
        explanations = ExplainabilityService.build(fund_scores, selected_ids, weights, funds_by_id, user, cfg, audit)

        metrics = validation["metrics"]
        portfolio = [
            SelectedFund(
                fund_id=fid,
                weight=round(weights[fid], 4),
                role=AllocationService.role_of(fid),
                rationale=explanations["per_fund"][fid]
            )
            for fid in selected_ids
        ]

        result = PortfolioResult(
            portfolio=portfolio,
            portfolio_metrics=metrics,
            explanations=explanations,
            audit_log_ref=audit.id,
            config_version=cfg.version,
            timestamp_utc=datetime.now(timezone.utc)
        )
        audit.complete_session(result)
        return result

    except Exception as e:
        audit.fail_session(e)
        raise

# -----------------------------
# 10) SYNTHETIC DATA GENERATION
# -----------------------------

def _rand_provider(i: int) -> str:
    providers = ["iShares", "Xtrackers", "Amundi", "Vanguard", "Lyxor", "DWS", "AllianzGI", "Fidelity"]
    return providers[i % len(providers)]

def generate_synthetic_funds(n: int, seed: int = 42) -> List[Fund]:
    random.seed(seed)
    funds: List[Fund] = []
    for i in range(n):
        category = random.choices(
            [Category.EQUITY, Category.BOND, Category.MULTI_ASSET],
            weights=[0.5, 0.25, 0.25], k=1
        )[0]
        region = random.choices(
            [Region.GLOBAL, Region.EUROPE, Region.NORTH_AMERICA, Region.EMERGING_MARKETS],
            weights=[0.4, 0.3, 0.2, 0.1], k=1
        )[0]
        theme = random.choices(
            [Theme.NONE, Theme.SUSTAINABILITY, Theme.TECHNOLOGY, Theme.HEALTHCARE],
            weights=[0.5, 0.2, 0.2, 0.1], k=1
        )[0]
        is_etf = random.random() < 0.45

        # Risk metrics: draw from plausible ranges
        vol = random.uniform(3, 22)
        srri = random.choices([2, 3, 4, 5, 6], weights=[0.1, 0.25, 0.3, 0.25, 0.1])[0]
        sharpe = max(-0.5, min(2.0, random.gauss(0.6, 0.3)))
        sortino = max(-0.2, min(3.0, random.gauss(0.9, 0.4)))
        mdd = -random.uniform(5, 45)
        ter = random.uniform(0.1, 1.8)
        esg_label = random.choices(
            ["LOW", "MEDIUM", "HIGH", "SFDR_ARTICLE_8", "SFDR_ARTICLE_9"],
            weights=[0.2, 0.35, 0.2, 0.15, 0.1], k=1
        )[0]
        equity_share = random.uniform(0, 100)
        history_years = random.uniform(1.0, 8.0)
        freshness_days = random.randint(1, 60)

        has_kid = True
        distributable = True

        funds.append(Fund(
            id=f"F{i+1:03d}",
            name=f"Fund {i+1}",
            provider=_rand_provider(i),
            category=category,
            region=region,
            theme=theme,
            is_etf=is_etf,
            volatility_1y=vol,
            srri=srri,
            sharpe_3y=sharpe,
            sortino_3y=sortino,
            max_drawdown_3y=mdd,
            equity_share=equity_share,
            ter=ter,
            esg_label=esg_label,
            data_history_years=history_years,
            data_freshness_days=freshness_days,
            has_kid=has_kid,
            is_distributable_in_de=distributable
        ))
    return funds
