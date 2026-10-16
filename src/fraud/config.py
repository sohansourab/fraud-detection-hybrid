"""Typed configuration for the hybrid fraud detection pipeline.

All tunable thresholds, file paths and the random seed are defined in
``configs/default.yaml``. This module only provides typed defaults plus a
small loader so the rest of the code reads values from a single place.

Usage::

    from fraud.config import get_config
    cfg = get_config()
    cfg.mgnrega.max_days_per_cycle
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, get_type_hints

import yaml

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "default.yaml"


@dataclass(frozen=True)
class PathsConfig:
    """Filesystem locations used by the scanner and pipeline."""

    beneficiaries: str = "data/beneficiaries.csv"
    mgnrega: str = "data/transactions_mgnrega.csv"
    pmjay: str = "data/transactions_pmjay.csv"
    labels: str = "data/labels.csv"
    output: str = "output/reports/fraud_report.json"


@dataclass(frozen=True)
class CivilRegistryConfig:
    """Thresholds for Domain 1 (Civil Registry / identity fraud)."""

    dummy_mobile: str = "9999999999"
    min_adult_age: int = 18
    max_normal_age: int = 100
    max_family_size: int = 15
    max_mobile_sharing: int = 3


@dataclass(frozen=True)
class MgnregaConfig:
    """Thresholds for Domain 2 (MGNREGA / labor fraud)."""

    max_days_per_cycle: int = 15
    ghost_project_suffix: str = "_000"
    cartel_threshold: float = 0.80
    min_cartel_appearances: int = 3


@dataclass(frozen=True)
class PmjayConfig:
    """Thresholds for Domain 3 (PM-JAY / medical fraud)."""

    max_general_ward_cost: int = 50000
    blacklisted_hospital: str = "HOSP_999"
    female_only_procedures: list[str] = field(
        default_factory=lambda: ["Hysterectomy"]
    )
    general_procedures: list[str] = field(
        default_factory=lambda: ["General Ward", "General Consultation"]
    )
    procedure_mill_threshold: int = 50


@dataclass(frozen=True)
class CrossDomainConfig:
    """Settings for Rule 25 (multi-scheme velocity)."""

    min_domains: int = 2
    beneficiary_prefix: str = "BEN_"


@dataclass(frozen=True)
class RiskBandsConfig:
    """Upper bounds for the low/medium/high risk bands."""

    low_max: int = 25
    medium_max: int = 50
    high_max: int = 75


@dataclass(frozen=True)
class CrossSchemeConfig:
    """Dedicated cross-scheme injection for Rule 25 (module P2c).

    ``beneficiaries`` people are placed (and flagged) in each scheme listed in
    ``combos``, so Rule 25 has a real multi-scheme basis to fire on.
    """

    beneficiaries: int = 12
    combos: list[list[str]] = field(
        default_factory=lambda: [
            ["Civil Registry", "MGNREGA Labor"],
            ["MGNREGA Labor", "PM-JAY Medical"],
            ["Civil Registry", "PM-JAY Medical"],
        ]
    )


@dataclass(frozen=True)
class UnseenJustUnderLimitConfig:
    """Unseen MGNREGA pattern: payments just below the approval limit (P2e).

    ``count`` payments are appended with ``days == mgnrega.max_days_per_cycle``
    and a wage rate chosen so ``days * rate`` lands in
    ``[fraction_min, fraction_max] * approval_limit`` (so the amount stays
    consistent with days x rate and no existing rule matches).
    """

    count: int = 12
    approval_limit: int = 3500
    fraction_min: float = 0.95
    fraction_max: float = 0.99


@dataclass(frozen=True)
class UnseenWeekendClusterConfig:
    """Unseen PM-JAY pattern: a weekend claim cluster at one hospital (P2e)."""

    count: int = 14
    hospital_id: str = "HOSP_UNSEEN_WKND"
    month: str = "2024-07"
    max_weekends: int = 4


@dataclass(frozen=True)
class UnseenGrowingAmountsConfig:
    """Unseen PM-JAY pattern: claim amounts rising steadily by month (P2e)."""

    count: int = 13
    hospital_id: str = "HOSP_UNSEEN_GROW"
    months: int = 12
    base_amount: int = 30000
    monthly_growth: float = 0.03


@dataclass(frozen=True)
class UnseenConfig:
    """Three injected typologies that no current rule matches (module P2e).

    Each is labelled ``fraud_type=unseen_*`` with an empty ``injected_rule_id``;
    the counts are events at the 0.02 prevalence run. ``enabled=False`` skips all
    three.
    """

    enabled: bool = True
    just_under_limit: UnseenJustUnderLimitConfig = field(
        default_factory=UnseenJustUnderLimitConfig
    )
    weekend_cluster: UnseenWeekendClusterConfig = field(
        default_factory=UnseenWeekendClusterConfig
    )
    growing_amounts: UnseenGrowingAmountsConfig = field(
        default_factory=UnseenGrowingAmountsConfig
    )


@dataclass(frozen=True)
class SimulatorConfig:
    """Injection volumes for the synthetic data simulator (module P2a).

    These are the *generator* knobs: how much fraud to inject so that the
    currently-inert rules (Rule 017 cartel, Rule 021 procedure mill) can fire,
    plus the rate of blank-mobile hard negatives for Rule 013.
    """

    cartel_groups: int = 15
    cartel_group_min_size: int = 4
    cartel_group_max_size: int = 6
    cartel_muster_rolls: int = 6
    procedure_mill_groups: int = 1
    procedure_mill_group_size: int = 60
    blank_mobile_rate: float = 0.02
    # Target fraction of fraud (is_fraud=1) records among scannable records.
    prevalence: float = 0.02
    # Minimum injected events per fraud type (module P2c). After prevalence
    # scaling any type below this is raised to the floor, unless doing so would
    # push total fraud above 1.5 x prevalence x scannable records.
    min_events_per_type: int = 10
    # Dedicated cross-scheme injection for Rule 025.
    cross_scheme: CrossSchemeConfig = field(default_factory=CrossSchemeConfig)
    # Unseen typologies with no matching rule (module P2e).
    unseen: UnseenConfig = field(default_factory=UnseenConfig)


@dataclass(frozen=True)
class MLConfig:
    """Record-level IsolationForest scoring (module P4a).

    Defaults live here rather than in ``configs/default.yaml`` (which is frozen
    for P4a); the loader only overrides keys that are present in the file.
    """

    n_estimators: int = 200
    random_state: int = 42
    # ``auto`` lets IsolationForest pick the cutoff from the data instead of a
    # fixed 5% contamination.
    contamination: str = "auto"
    # Fraction of the *train* split held out (stratified) to choose the score
    # threshold; never the test split.
    val_fraction: float = 0.2
    # Minimum precision the chosen threshold must reach on the validation split.
    precision_target: float = 0.5
    # PM-JAY: number of most common procedures given their own code; the rest
    # are the explicit "other" code 0.
    top_procedures: int = 10


@dataclass(frozen=True)
class HybridConfig:
    """HYBRID combination settings (module P4c).

    The combination is selected on validation rows that exclude the unseen
    typologies, then applied once on test. ``decision_threshold`` turns the
    normalised ``max`` / weighted-sum scores into a flag; both inputs are in
    ``[0, 1]``, so the midpoint is the natural cut. ``severity_max`` is the
    largest rule severity (RULE_025 = 40) used to normalise rule severity.
    """

    decision_threshold: float = 0.5
    weights: list[float] = field(default_factory=lambda: [0.3, 0.5, 0.7])
    severity_max: int = 40


@dataclass(frozen=True)
class Config:
    """Root configuration object."""

    seed: int = 42
    paths: PathsConfig = field(default_factory=PathsConfig)
    civil_registry: CivilRegistryConfig = field(default_factory=CivilRegistryConfig)
    mgnrega: MgnregaConfig = field(default_factory=MgnregaConfig)
    pmjay: PmjayConfig = field(default_factory=PmjayConfig)
    cross_domain: CrossDomainConfig = field(default_factory=CrossDomainConfig)
    risk_bands: RiskBandsConfig = field(default_factory=RiskBandsConfig)
    simulator: SimulatorConfig = field(default_factory=SimulatorConfig)
    ml: MLConfig = field(default_factory=MLConfig)
    hybrid: HybridConfig = field(default_factory=HybridConfig)


def _build(cls: type, data: Any) -> Any:
    """Recursively build a (nested) dataclass from a plain mapping."""
    if not is_dataclass(cls) or not isinstance(data, dict):
        return data
    hints = get_type_hints(cls)
    kwargs = {
        f.name: _build(hints[f.name], data[f.name])
        for f in fields(cls)
        if f.name in data
    }
    return cls(**kwargs)


def load_config(path: str | Path | None = None) -> Config:
    """Load config from ``path`` (default: ``configs/default.yaml``).

    Missing file or missing keys fall back to the dataclass defaults.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        logger.warning("Config file %s not found; using built-in defaults", config_path)
        return Config()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    logger.info("Loaded config from %s", config_path)
    return _build(Config, raw)


_CONFIG: Config | None = None


def get_config() -> Config:
    """Return the process-wide cached configuration."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_config()
    return _CONFIG
