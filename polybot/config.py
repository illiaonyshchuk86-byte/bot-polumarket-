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
    max_markets: int = 40
    min_volume_usd: float = 1000.0
    # Keep only the top-N levels of each side of the book when persisting.
    # Caps database growth for long-running daemon collection (0 = no limit).
    max_book_depth: int = 10
    # Track reward-enabled (market-making relevant) markets first, then fill
    # remaining slots by volume.
    prioritize_rewards: bool = True


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


class ProMmConfig(BaseModel):
    """Professional market-maker parameters. ALL tunable knobs live here so the
    core logic in strategy/pro_mm.py never has to change during tuning.

    Prices are dollars (0..1); spread/skew knobs are expressed in CENTS
    (1 cent = $0.01) for readability.
    """

    # --- Spread (defends against "too tight") ---
    base_half_spread_cents: float = 2.0
    min_half_spread_cents: float = 1.0          # hard floor; never quote tighter
    vol_spread_coeff: float = 1.0               # extra half-spread per cent of sigma

    # --- Inventory control (defends against "inventory pile-up") ---
    inventory_skew_cents_per_share: float = 0.05  # shift quote center vs inventory
    max_inventory_shares: float = 200.0           # hard cap (shares)
    max_inventory_usd: float = 0.0                # if > 0, cap inventory by dollars instead
    # Only quote when the midpoint is in this range (skip extreme longshots where
    # dollar-sizing explodes and microstructure is weird).
    min_mid: float = 0.0
    max_mid: float = 1.0

    # --- Sizing ---
    base_size: float = 20.0
    min_size: float = 5.0
    # If > 0, size each quote by dollars instead: shares = target_notional / price.
    # Needed for reward-farming, where qualifying depends on share count.
    target_notional_usd: float = 0.0

    # --- Volatility / jump guard (defends against "run over on moves") ---
    vol_window_secs: float = 120.0
    jump_kill_cents: float = 3.0                # pull all quotes if recent range exceeds this
    # Don't quote a token until this many observations exist, so the volatility
    # estimate is meaningful (no blind quoting at startup).
    warmup_ticks: int = 3

    # --- Reward-zone awareness ---
    clamp_to_reward_zone: bool = True          # keep quotes inside rewards_max_spread (but >= floor)

    # --- Capital ---
    starting_cash_usd: float = 1000.0

    # --- Fill realism (keep the dry-run honest, never rosy) ---
    # Require the market to trade THROUGH a resting quote by this many ticks
    # before counting a fill (0 = a touch fills; higher = more conservative).
    fill_through_ticks: float = 0.0
    # Maker fee in basis points. Polymarket makers pay 0; kept tunable.
    maker_fee_bps: float = 0.0

    # --- Backtest scope (bounds memory/time as the dataset grows) ---
    backtest_lookback_hours: float = 48.0


class StrategyConfig(BaseModel):
    arb_scanner: ArbScannerConfig = Field(default_factory=ArbScannerConfig)
    naive_mm: NaiveMmConfig = Field(default_factory=NaiveMmConfig)
    pro_mm: ProMmConfig = Field(default_factory=ProMmConfig)


class ScreenerConfig(BaseModel):
    """Reward-screener assumptions — how much we'd deploy and our risk thresholds."""

    capital_per_market_usd: float = 1000.0   # capital we'd post per market (each side)
    quote_distance_cents: float = 1.0        # where we'd quote from mid
    min_days_to_resolution: float = 2.0      # resolve sooner than this -> risky/ending
    min_reward_yield_pct: float = 0.20       # %/day reward yield to be "attractive"
    max_vol_cents: float = 3.0               # mid stdev above this -> high adverse-selection risk


class Config(BaseModel):
    api: ApiConfig = Field(default_factory=ApiConfig)
    collector: CollectorConfig = Field(default_factory=CollectorConfig)
    paper: PaperConfig = Field(default_factory=PaperConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    screener: ScreenerConfig = Field(default_factory=ScreenerConfig)

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
