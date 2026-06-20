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


def _print_mm_report(report, *, title: str, elapsed_secs: float | None = None) -> None:
    typer.echo("─" * 60)
    typer.echo(f"  {title}")
    typer.echo("─" * 60)
    typer.echo(f"  Starting cash : ${report.starting_cash:,.2f}")
    typer.echo(f"  Spread PnL    : ${report.net_pnl():,.2f}  ({report.return_pct():+.2f}% of capital)")
    typer.echo(f"  Rewards (est) : ${report.total_rewards:,.2f}  (liquidity-reward model)")
    typer.echo(f"  TOTAL (PnL+rw): ${report.net_with_rewards():,.2f}")
    if elapsed_secs:
        typer.echo(f"  Over          : {elapsed_secs / 3600.0:.2f} hours (NOT annualized)")
    typer.echo(f"  Tokens / steps: {report.tokens} / {report.steps}")
    typer.echo(f"  Fills         : {report.total_fills} "
               f"(buys {report.total_buys}, sells {report.total_sells})")
    typer.echo(f"  Stand-aside   : {report.total_kills} ticks (vol guard / inventory cap)")
    typer.echo(f"  Max |inventory|: {report.max_abs_inventory:.0f} shares")
    typer.echo(f"  Open positions: {report.open_inventory_tokens} tokens still holding inventory")
    typer.echo(f"  PnL/step risk : {report.risk_ratio():.3f} (mean/std, rough)")
    if report.worst_tokens:
        typer.echo("  Worst tokens by equity (where the bleed is):")
        for t in report.worst_tokens:
            typer.echo(f"    {t.token_id[:14]}… eq ${t.equity():+.2f} "
                       f"inv {t.inventory:+.0f} fills {t.fills}")
    typer.echo("─" * 60)
    typer.echo("NOTE: ~snapshot-resolution maker fills, no queue position. Rewards"
               " are a conservative estimate (competition = full visible book).")


@app.command(name="data-report")
def data_report(
    config_path: str = typer.Option(None, "--config", help="Path to YAML config."),
):
    """Show what the collected data actually contains (spreads, movement, markets)."""
    from .analysis.data_report import build_data_report
    from .storage.db import make_engine

    config = load_config(config_path)
    _setup_logging(config.log_level)
    typer.echo(build_data_report(make_engine(config.db_path)))


@app.command(name="mm-backtest")
def mm_backtest(
    config_path: str = typer.Option(None, "--config", help="Path to YAML config."),
):
    """Backtest the professional market maker on collected order-book data."""
    from .backtest.mm_engine import MMBacktest

    config = load_config(config_path)
    _setup_logging(config.log_level)
    report = MMBacktest(config).run()
    _print_mm_report(report, title="Professional MM backtest")


@app.command(name="mm-dryrun")
def mm_dryrun(
    minutes: float = typer.Option(10.0, help="How long to run, in minutes."),
    interval: float = typer.Option(None, help="Seconds between polls (default: config)."),
    log: str = typer.Option(None, "--log", help="Append the equity curve to this CSV file."),
    config_path: str = typer.Option(None, "--config", help="Path to YAML config."),
):
    """Run the market maker live against the real book, fully simulated (no orders)."""
    import csv
    import signal
    import threading
    from pathlib import Path

    from .paper.mm_dryrun import MMDryRun

    config = load_config(config_path)
    _setup_logging(config.log_level)

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    log_fh = log_writer = None
    if log:
        Path(log).expanduser().parent.mkdir(parents=True, exist_ok=True)
        new = not Path(log).exists()
        log_fh = open(log, "a", newline="")
        log_writer = csv.writer(log_fh)
        if new:
            log_writer.writerow(
                ["elapsed_secs", "equity", "net_pnl", "return_pct", "fills", "kills", "max_inv"]
            )

    def status(report, elapsed):
        typer.echo(
            f"[{elapsed/60:5.1f}m] equity ${report.final_equity:,.2f} "
            f"PnL ${report.net_pnl():+.2f} ({report.return_pct():+.2f}%) "
            f"fills {report.total_fills} kills {report.total_kills} "
            f"maxInv {report.max_abs_inventory:.0f}"
        )
        if log_writer:
            log_writer.writerow([
                round(elapsed, 1), round(report.final_equity, 4), round(report.net_pnl(), 4),
                round(report.return_pct(), 4), report.total_fills, report.total_kills,
                round(report.max_abs_inventory, 1),
            ])
            log_fh.flush()

    runner = MMDryRun(config)
    try:
        report = runner.run(minutes, interval=interval, stop=stop, on_status=status)
    finally:
        runner.close()
        if log_fh:
            log_fh.close()
    _print_mm_report(report, title="Professional MM dry-run", elapsed_secs=minutes * 60.0)


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
