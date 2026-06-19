"""polybot command-line interface.

Commands:
  collect    Poll public APIs and store order-book snapshots.
  backtest   Replay stored snapshots through a strategy.
  paper-run  Run a strategy live against real books, in simulation only.

No command places a real order.
"""

from __future__ import annotations

import logging

import typer

from .config import load_config
from .paper.session import SessionReport
from .strategy import REGISTRY

app = typer.Typer(add_completion=False, help="Polymarket data + paper-trading foundation.")


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _print_report(report: SessionReport) -> None:
    typer.echo("─" * 60)
    typer.echo(f"  Starting cash : ${report.starting_cash:,.2f}")
    typer.echo(f"  Final equity  : ${report.final_equity:,.2f}")
    typer.echo(f"  Net PnL       : ${report.net_pnl():,.2f}")
    typer.echo(f"  Realized PnL  : ${report.realized_pnl:,.2f}")
    typer.echo(f"  Fees paid     : ${report.fees_paid:,.2f}")
    typer.echo(f"  Fills         : {report.num_fills}")
    typer.echo(f"  Risk blocks   : {report.risk_blocks}")
    typer.echo(f"  Kill switch   : {'TRIPPED' if report.killed else 'ok'}")
    if report.signals:
        typer.echo(f"  Signals ({len(report.signals)}):")
        for sig in report.signals[:50]:
            typer.echo(f"    {sig}")
        if len(report.signals) > 50:
            typer.echo(f"    ... and {len(report.signals) - 50} more")
    typer.echo("─" * 60)
    typer.echo("NOTE: paper/backtest results overstate real performance "
               "(no market impact, latency, or adverse selection).")


def _make_strategy(name: str, config):
    if name not in REGISTRY:
        raise typer.BadParameter(
            f"unknown strategy '{name}'. Choices: {', '.join(REGISTRY)}"
        )
    cls = REGISTRY[name]
    params = getattr(config.strategy, name, None)
    return cls(params)


@app.command()
def collect(
    minutes: float = typer.Option(3.0, help="How long to poll, in minutes."),
    config_path: str = typer.Option(None, "--config", help="Path to YAML config."),
):
    """Collect live public market data into SQLite."""
    from .collector.collector import Collector

    config = load_config(config_path)
    _setup_logging(config.log_level)
    collector = Collector(config)
    try:
        total = collector.run(minutes)
    finally:
        collector.close()
    typer.echo(f"Collected {total} order-book snapshots into {config.db_path}")


@app.command()
def daemon(
    config_path: str = typer.Option(None, "--config", help="Path to YAML config."),
):
    """Collect data continuously (for always-on VPS use). Ctrl-C / SIGTERM to stop."""
    import signal
    import threading

    from .collector.collector import Collector

    config = load_config(config_path)
    _setup_logging(config.log_level)

    stop = threading.Event()

    def _handle(signum, _frame):
        logging.getLogger("polybot.cli").info("received signal %s, shutting down", signum)
        stop.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    collector = Collector(config)
    try:
        total = collector.run_forever(stop)
    finally:
        collector.close()
    typer.echo(f"Daemon stopped. Collected {total} snapshots into {config.db_path}")


@app.command()
def backtest(
    strategy: str = typer.Option("arb_scanner", help="Strategy name."),
    config_path: str = typer.Option(None, "--config", help="Path to YAML config."),
):
    """Replay stored snapshots through a strategy."""
    from .backtest.engine import BacktestEngine

    config = load_config(config_path)
    _setup_logging(config.log_level)
    strat = _make_strategy(strategy, config)
    report = BacktestEngine(config, strat).run()
    _print_report(report)


@app.command(name="mm-backtest")
def mm_backtest(
    config_path: str = typer.Option(None, "--config", help="Path to YAML config."),
):
    """Backtest the professional market maker on collected order-book data."""
    from .backtest.mm_engine import MMBacktest

    config = load_config(config_path)
    _setup_logging(config.log_level)
    report = MMBacktest(config).run()

    typer.echo("─" * 60)
    typer.echo("  Professional MM backtest (rewards NOT credited)")
    typer.echo("─" * 60)
    typer.echo(f"  Starting cash : ${report.starting_cash:,.2f}")
    typer.echo(f"  Final equity  : ${report.final_equity:,.2f}")
    typer.echo(f"  Net PnL       : ${report.net_pnl():,.2f}")
    typer.echo(f"  Tokens / steps: {report.tokens} / {report.steps}")
    typer.echo(f"  Fills         : {report.total_fills} "
               f"(buys {report.total_buys}, sells {report.total_sells})")
    typer.echo(f"  Stand-aside   : {report.total_kills} ticks (vol guard / inventory cap)")
    typer.echo(f"  Max |inventory|: {report.max_abs_inventory:.0f} shares")
    typer.echo(f"  PnL/step risk : {report.risk_ratio():.3f} (mean/std, rough)")
    if report.top_tokens:
        typer.echo("  Top tokens by equity:")
        for t in report.top_tokens:
            typer.echo(f"    {t.token_id[:14]}… eq ${t.equity():+.2f} "
                       f"fills {t.fills} maxInv {t.max_abs_inventory:.0f}")
    typer.echo("─" * 60)
    typer.echo("NOTE: snapshot-based maker fills (10s) — approximate; no queue "
               "position. Profit here would be a floor: rewards are upside.")


@app.command(name="paper-run")
def paper_run(
    strategy: str = typer.Option("naive_mm", help="Strategy name."),
    minutes: float = typer.Option(2.0, help="How long to run, in minutes."),
    config_path: str = typer.Option(None, "--config", help="Path to YAML config."),
):
    """Run a strategy live against real books, in simulation only."""
    from .paper.runner import PaperRunner

    config = load_config(config_path)
    _setup_logging(config.log_level)
    strat = _make_strategy(strategy, config)
    runner = PaperRunner(config, strat)
    try:
        report = runner.run(minutes)
    finally:
        runner.close()
    _print_report(report)


if __name__ == "__main__":
    app()
