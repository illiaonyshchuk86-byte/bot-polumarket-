"""Professional market maker — stable core logic.

This module computes resting quotes from market state. It is intentionally
parameter-free in spirit: every tunable number comes from ProMmConfig, so this
logic should change rarely. Tuning happens in config, not here.

Design defends explicitly against four common MM failures:
  1. Run over on moves  -> jump kill-switch + volatility-widened spread
  2. Inventory pile-up   -> reservation-price skew + hard inventory cap
  3. Too-tight spread    -> hard min-half-spread floor (reward zone can't breach it)
  4. Technical glitches  -> deterministic, side-effect-free quoting (the engine
     owns order state; this function only returns the desired quote)
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import ProMmConfig
from ..domain import Quote


@dataclass
class MMQuoteInput:
    """Everything the maker needs to decide a quote for one token."""

    mid: float                      # current midpoint (dollars, 0..1)
    sigma_cents: float              # short-horizon volatility estimate (cents)
    jump_cents: float               # recent price range over the window (cents)
    inventory: float                # current net position (shares; +long / -short)
    rewards_max_spread_cents: float | None = None
    tick: float = 0.01


def _round_tick(price: float, tick: float) -> float:
    return round(round(price / tick) * tick, 10)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class ProMarketMaker:
    name = "pro_mm"

    def __init__(self, params: ProMmConfig | None = None) -> None:
        self.params = params or ProMmConfig()

    def quote(self, s: MMQuoteInput) -> Quote | None:
        """Return the desired two-sided quote, or None to stand aside."""
        p = self.params

        # --- Defense #1: volatility / jump kill-switch ---
        if s.jump_cents > p.jump_kill_cents:
            return None

        # --- Defense #3: spread floor + volatility widening ---
        half_spread_cents = max(
            p.min_half_spread_cents,
            p.base_half_spread_cents + p.vol_spread_coeff * s.sigma_cents,
        )
        # Reward-zone clamp, but never below the safety floor.
        if p.clamp_to_reward_zone and s.rewards_max_spread_cents:
            half_spread_cents = min(
                half_spread_cents,
                max(p.min_half_spread_cents, s.rewards_max_spread_cents),
            )
        half_spread = half_spread_cents / 100.0

        # --- Defense #2a: inventory skew (reservation price) ---
        skew = (p.inventory_skew_cents_per_share / 100.0) * s.inventory
        reservation = s.mid - skew  # long inventory -> center drops -> ask fills first

        bid = _clamp(_round_tick(reservation - half_spread, s.tick), s.tick, 1 - s.tick)
        ask = _clamp(_round_tick(reservation + half_spread, s.tick), s.tick, 1 - s.tick)
        if ask <= bid:  # keep at least one tick of spread
            ask = min(1 - s.tick, bid + s.tick)

        # --- Defense #2b: hard inventory cap -> quote one side only at the limit ---
        bid_size = p.base_size
        ask_size = p.base_size
        if s.inventory >= p.max_inventory_shares:
            bid_size = 0.0
        if s.inventory <= -p.max_inventory_shares:
            ask_size = 0.0

        # Size floor — never post dust.
        if bid_size < p.min_size:
            bid_size = 0.0
        if ask_size < p.min_size:
            ask_size = 0.0

        if bid_size <= 0 and ask_size <= 0:
            return None
        return Quote(bid_price=bid, bid_size=bid_size, ask_price=ask, ask_size=ask_size)
