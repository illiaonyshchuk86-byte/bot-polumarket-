"""Tests for the professional market-maker core logic (the four defenses)."""

from __future__ import annotations

from polybot.config import ProMmConfig
from polybot.strategy.pro_mm import MMQuoteInput, ProMarketMaker


def mk(**over) -> ProMarketMaker:
    base = dict(
        base_half_spread_cents=2.0,
        min_half_spread_cents=1.0,
        vol_spread_coeff=1.0,
        inventory_skew_cents_per_share=0.05,
        max_inventory_shares=200.0,
        base_size=20.0,
        min_size=5.0,
        vol_window_secs=120.0,
        jump_kill_cents=3.0,
        clamp_to_reward_zone=True,
        starting_cash_usd=1000.0,
    )
    base.update(over)
    return ProMarketMaker(ProMmConfig(**base))


def test_symmetric_quote_at_zero_inventory():
    mm = mk(clamp_to_reward_zone=False)
    q = mm.quote(MMQuoteInput(mid=0.50, sigma_cents=0.0, jump_cents=0.0, inventory=0.0))
    assert q is not None
    # 2c half-spread around 0.50 -> 0.48 / 0.52
    assert abs(q.bid_price - 0.48) < 1e-9
    assert abs(q.ask_price - 0.52) < 1e-9


def test_defense1_jump_kill_pulls_quotes():
    mm = mk()
    q = mm.quote(MMQuoteInput(mid=0.50, sigma_cents=0.0, jump_cents=5.0, inventory=0.0))
    assert q is None  # recent range 5c > 3c kill threshold


def test_defense2_inventory_skew_shifts_center_down_when_long():
    mm = mk(clamp_to_reward_zone=False, inventory_skew_cents_per_share=0.05)
    q = mm.quote(MMQuoteInput(mid=0.50, sigma_cents=0.0, jump_cents=0.0, inventory=100.0))
    # skew = 0.05c * 100 = 5c -> center 0.45; quotes 0.43 / 0.47
    assert abs(q.bid_price - 0.43) < 1e-9
    assert abs(q.ask_price - 0.47) < 1e-9


def test_defense2_inventory_cap_stops_buying_when_long():
    mm = mk()
    q = mm.quote(MMQuoteInput(mid=0.50, sigma_cents=0.0, jump_cents=0.0, inventory=200.0))
    assert q.bid_size == 0.0   # at +cap: don't buy more
    assert q.ask_size > 0.0    # still willing to sell down


def test_defense3_spread_floor_respected():
    mm = mk(base_half_spread_cents=0.2, min_half_spread_cents=1.0, clamp_to_reward_zone=False)
    q = mm.quote(MMQuoteInput(mid=0.50, sigma_cents=0.0, jump_cents=0.0, inventory=0.0))
    # floor 1c -> 0.49 / 0.51 even though base asked for 0.2c
    assert abs(q.bid_price - 0.49) < 1e-9
    assert abs(q.ask_price - 0.51) < 1e-9


def test_vol_widens_spread():
    mm = mk(clamp_to_reward_zone=False, base_half_spread_cents=2.0, vol_spread_coeff=1.0)
    q = mm.quote(MMQuoteInput(mid=0.50, sigma_cents=3.0, jump_cents=0.0, inventory=0.0))
    # half-spread = 2 + 1*3 = 5c -> 0.45 / 0.55
    assert abs(q.bid_price - 0.45) < 1e-9
    assert abs(q.ask_price - 0.55) < 1e-9


def test_dollar_sizing():
    mm = mk(clamp_to_reward_zone=False, target_notional_usd=1000.0,
            base_size=20.0, max_inventory_shares=100000.0)
    q = mm.quote(MMQuoteInput(mid=0.50, sigma_cents=0.0, jump_cents=0.0, inventory=0.0))
    assert abs(q.bid_size - 2000.0) < 1e-6   # $1000 / 0.50 = 2000 shares
    assert abs(q.ask_size - 2000.0) < 1e-6


def test_price_range_filter_skips_extremes():
    mm = mk(min_mid=0.05, max_mid=0.95)
    assert mm.quote(MMQuoteInput(mid=0.002, sigma_cents=0, jump_cents=0, inventory=0)) is None
    assert mm.quote(MMQuoteInput(mid=0.50, sigma_cents=0, jump_cents=0, inventory=0)) is not None


def test_reward_zone_clamp_but_not_below_floor():
    mm = mk(base_half_spread_cents=5.0, min_half_spread_cents=1.0, clamp_to_reward_zone=True)
    q = mm.quote(MMQuoteInput(
        mid=0.50, sigma_cents=0.0, jump_cents=0.0, inventory=0.0,
        rewards_max_spread_cents=2.0,
    ))
    # clamped to reward band 2c (< base 5c) -> 0.48 / 0.52
    assert abs(q.bid_price - 0.48) < 1e-9
    assert abs(q.ask_price - 0.52) < 1e-9
