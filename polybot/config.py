"""Configuration loading for polybot.

Config comes from a YAML file (structure mirrors config/config.example.yaml).
A few operational values (db path, log level) may be overridden via environment
variables, which is convenient for CI and containers.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ApiConfig(BaseModel):
    gamma_base: str = "https://gamma-api.polymarket.com"
    clob_base: str = "https://clob.polymarket.com"
    data_base: str = "https://data-api.polymarket.com"
    ws_market: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    timeout_seconds: float = 15.0
    max_retries: int = 3


class CollectorConfig(BaseModel):
    poll_interval_seconds: int = 10
    max_markets: int = 25
    min_volume_usd: float = 1000.0


class PaperConfig(BaseModel):
    starting_cash_usd: float = 1000.0
    taker_fee_bps: float = 0.0
    extra_slippage_bps: float = 10.0


class RiskConfig(BaseModel):
    max_position_usd_per_market: float = 100.0
    max_total_exposure_usd: float = 500.0
    daily_loss_cap_usd: float = 50.0


class ArbScannerConfig(BaseModel):
    min_edge_cents: float = 1.0


class NaiveMmConfig(BaseModel):
    half_spread_cents: float = 2.0
    order_size: float = 20.0


class StrategyConfig(BaseModel):
    arb_scanner: ArbScannerConfig = Field(default_factory=ArbScannerConfig)
    naive_mm: NaiveMmConfig = Field(default_factory=NaiveMmConfig)


class Config(BaseModel):
    api: ApiConfig = Field(default_factory=ApiConfig)
    collector: CollectorConfig = Field(default_factory=CollectorConfig)
    paper: PaperConfig = Field(default_factory=PaperConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)

    # Operational (env-overridable, not part of the YAML schema by default).
    db_path: str = "data/polybot.db"
    log_level: str = "INFO"


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Load configuration from YAML, applying environment overrides.

    If no YAML file is found, sensible defaults are used so the tool still runs.
    """
    config_path = Path(path or os.getenv("POLYBOT_CONFIG", "config/config.yaml"))

    raw: dict = {}
    if config_path.is_file():
        with config_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

    config = Config.model_validate(raw)

    # Environment overrides for operational values.
    config.db_path = os.getenv("POLYBOT_DB_PATH", config.db_path)
    config.log_level = os.getenv("POLYBOT_LOG_LEVEL", config.log_level)

    return config
