"""
Halal Crypto AI Trading Agent (Process Over Profit).
CLI Entrypoint and Interactive Dashboard.
"""

import sys
import time
from datetime import datetime
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from config.settings import settings
from config.halal_whitelist import (
    HALAL_WHITELIST,
    HARAM_BLACKLIST,
    is_pair_halal,
    get_screening_info,
)
from core.binance_client import BinanceSpotClient
from execution.bot_engine import BotEngine
from storage.database import Database

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

console = Console(highlight=False)

def print_banner():
    banner = """
=============================================================================
                 HALAL CRYPTO AI SPOT TRADING AGENT
               "Process Over Profit" - Shariah Compliant
   [100% Spot Only | Zero Riba | No Shorting | Screened Halal Assets]
=============================================================================
    """
    console.print(f"[bold cyan]{banner}[/bold cyan]")

@click.group()
def cli():
    """Halal Crypto AI Spot Trading Agent CLI."""
    pass

@cli.command()
def test_connection():
    """Test Binance Spot API connectivity."""
    print_banner()
    client = BinanceSpotClient()
    console.print("[yellow]Pinging Binance Spot API...[/yellow]")
    if client.ping():
        server_time = client.get_server_time()
        time_str = datetime.utcfromtimestamp(server_time / 1000).strftime('%Y-%m-%d %H:%M:%S UTC')
        console.print(f"[bold green][OK] Binance Spot API is connected successfully![/bold green] (Server Time: {time_str})")
        
        # Test BTC price fetch
        btc_price = client.get_ticker_price("BTCUSDT")
        console.print(f"[bold green][OK] Live BTC/USDT Spot Price:[/bold green] [bold white]${btc_price:,.2f}[/bold white]")
    else:
        console.print("[bold red][ERROR] Failed to reach Binance API. Check network or proxy.[/bold red]")

@cli.command()
@click.argument("symbol", default="BTC")
def screen(symbol: str):
    """Check Shariah compliance status and rationale for any crypto asset."""
    print_banner()
    sym = symbol.upper().strip()
    console.print(f"[bold yellow]Performing Shariah screening for:[/bold yellow] [bold white]{sym}[/bold white]\n")

    if sym in HARAM_BLACKLIST:
        console.print(Panel(
            f"[bold red]STATUS: IMPERMISSIBLE (HARAM)[/bold red]\n\n"
            f"[bold]Reason:[/bold] {HARAM_BLACKLIST[sym]}\n"
            f"[italic red]Trading this asset is blocked at the code level by ShariahComplianceGuard.[/italic red]",
            title=f"Screening Report: {sym}",
            border_style="red"
        ))
        return

    info = get_screening_info(sym)
    if info:
        console.print(Panel(
            f"[bold green]STATUS: {info.status} (PERMISSIBLE SPOT ASSET)[/bold green]\n\n"
            f"[bold]Full Name:[/bold] {info.name}\n"
            f"[bold]Primary Utility:[/bold] {info.primary_utility}\n"
            f"[bold]Shariah Notes:[/bold] {info.shariah_notes}\n\n"
            f"[italic cyan]Compliant under Bay' al-Sarf / Bay' al-Sila' spot exchange rules.[/italic cyan]",
            title=f"Screening Report: {sym}",
            border_style="green"
        ))
    else:
        console.print(Panel(
            f"[bold yellow]STATUS: UNVERIFIED / NOT IN WHITELIST[/bold yellow]\n\n"
            f"The asset '{sym}' has not yet been audited for technological utility, revenue model, or debt exposure.\n"
            f"By default, the bot refuses to trade unverified assets to prevent Gharar (uncertainty).",
            title=f"Screening Report: {sym}",
            border_style="yellow"
        ))

@cli.command()
def scan():
    """Execute a single market scan across whitelisted Halal pairs."""
    print_banner()
    mode_text = "[yellow]PAPER TRADING (SIMULATION)[/yellow]" if settings.PAPER_TRADING else "[red]LIVE BINANCE SPOT[/red]"
    console.print(f"Mode: {mode_text} | AI Provider: [cyan]{settings.AI_PROVIDER}[/cyan]\n")

    engine = BotEngine()
    with console.status("[bold cyan]Scanning whitelisted spot markets & evaluating AI models...[/bold cyan]"):
        res = engine.scan_and_execute_cycle()

    # Table of scanned pairs
    table = Table(title="Whitelisted Spot Market Scan Results", header_style="bold magenta")
    table.add_column("Symbol", style="cyan", justify="left")
    table.add_column("Spot Price", justify="right")
    table.add_column("Regime", justify="center")
    table.add_column("RSI(14)", justify="right")
    table.add_column("AI Action", justify="center")
    table.add_column("Conviction", justify="right")
    table.add_column("Rationale", justify="left")

    for pair in res["pairs_scanned"]:
        action_style = "bold green" if pair["action"] == "BUY" else ("bold red" if pair["action"] == "SELL" else "yellow")
        table.add_row(
            pair["symbol"],
            f"${pair['price']:,.2f}",
            pair["regime"],
            f"{pair['rsi']:.1f}",
            Text(pair["action"], style=action_style),
            f"{pair['confidence']:.2f}",
            pair["rationale"][:60] + ("..." if len(pair["rationale"]) > 60 else "")
        )

    console.print(table)

    # Actions taken
    if res["actions_taken"]:
        console.print("\n[bold green]Orders Executed This Cycle:[/bold green]")
        for action in res["actions_taken"]:
            console.print(f" * [bold]{action['type']}[/bold] {action['symbol']} - Amount: {action['quantity']} @ ${action['price' if 'price' in action else 'exit_price']:,.2f}")
    else:
        console.print("\n[dim]No new orders executed. Waiting for high-confluence AI setup.[/dim]")

    console.print(f"\n[bold]Current Available USDT Balance:[/bold] [bold green]${res['ending_balance_usdt']:,.2f}[/bold green]\n")

@cli.command()
def status():
    """Show current portfolio, open spot positions, and risk metrics."""
    print_banner()
    db = Database()
    client = BinanceSpotClient()
    is_paper = settings.PAPER_TRADING
    
    balance = db.get_paper_balance() if is_paper else client.get_spot_account_balance("USDT")
    mode_text = "[bold yellow]PAPER SIMULATION[/bold yellow]" if is_paper else "[bold red]LIVE SPOT[/bold red]"

    console.print(f"Trading Mode: {mode_text}")
    console.print(f"Available Cash (USDT): [bold green]${balance:,.2f}[/bold green]\n")

    positions = db.get_all_active_positions()
    if not positions:
        console.print("[dim]No open spot positions currently active.[/dim]")
        return

    table = Table(title="Active Spot Positions", header_style="bold cyan")
    table.add_column("Symbol", style="white")
    table.add_column("Quantity", justify="right")
    table.add_column("Entry Price", justify="right")
    table.add_column("Current Price", justify="right")
    table.add_column("Stop-Loss", justify="right", style="red")
    table.add_column("Take-Profit", justify="right", style="green")
    table.add_column("Highest Seen", justify="right")
    table.add_column("Unrealized PnL", justify="right")

    total_unrealized_usdt = 0.0

    for pos in positions:
        sym = pos["symbol"]
        curr_price = client.get_ticker_price(sym)
        entry = pos["entry_price"]
        qty = pos["quantity"]
        pnl_pct = ((curr_price - entry) / entry) * 100.0
        pnl_usdt = (curr_price - entry) * qty
        total_unrealized_usdt += pnl_usdt

        pnl_style = "bold green" if pnl_pct >= 0 else "bold red"
        table.add_row(
            sym,
            f"{qty:.4f}",
            f"${entry:,.2f}",
            f"${curr_price:,.2f}",
            f"${pos['stop_loss']:,.2f}",
            f"${pos['take_profit']:,.2f}",
            f"${pos['highest_price']:,.2f}",
            Text(f"{pnl_pct:+.2f}% (${pnl_usdt:+.2f})", style=pnl_style)
        )

    console.print(table)
    summary_style = "bold green" if total_unrealized_usdt >= 0 else "bold red"
    console.print(f"\nTotal Unrealized PnL: [{summary_style}]${total_unrealized_usdt:+,.2f}[/{summary_style}]\n")

@cli.command()
def history():
    """View closed trade history and PnL metrics."""
    print_banner()
    db = Database()
    trades = db.get_trade_history(limit=25)

    if not trades:
        console.print("[dim]No closed trades recorded yet.[/dim]")
        return

    table = Table(title="Completed Trades History", header_style="bold green")
    table.add_column("ID", justify="right")
    table.add_column("Symbol", style="cyan")
    table.add_column("Quantity", justify="right")
    table.add_column("Buy Price", justify="right")
    table.add_column("Sell Price", justify="right")
    table.add_column("Net PnL ($)", justify="right")
    table.add_column("Return (%)", justify="right")
    table.add_column("Exit Reason", justify="left")

    total_pnl = 0.0
    wins = 0

    for t in trades:
        pnl = t["pnl_usdt"]
        total_pnl += pnl
        if pnl > 0:
            wins += 1
        pnl_style = "bold green" if pnl >= 0 else "bold red"
        table.add_row(
            str(t["id"]),
            t["symbol"],
            f"{t['quantity']:.4f}",
            f"${t['buy_price']:,.2f}",
            f"${t['sell_price']:,.2f}",
            Text(f"${pnl:+,.2f}", style=pnl_style),
            Text(f"{t['pnl_pct']:+.2f}%", style=pnl_style),
            t["exit_reason"]
        )

    console.print(table)
    win_rate = (wins / len(trades)) * 100.0 if trades else 0.0
    console.print(f"\n[bold]Total Realized PnL:[/bold] [{'green' if total_pnl >= 0 else 'red'}]${total_pnl:+,.2f}[/{'green' if total_pnl >= 0 else 'red'}] | [bold]Win Rate:[/bold] {win_rate:.1f}% ({wins}/{len(trades)} trades)\n")

@cli.command()
def report():
    """Generate Executive Portfolio Performance Report for the Lead Manager."""
    print_banner()
    db = Database()
    client = BinanceSpotClient()
    is_paper = settings.PAPER_TRADING

    cash = db.get_paper_balance() if is_paper else client.get_spot_account_balance("USDT")
    positions = db.get_all_active_positions()
    trades = db.get_trade_history(limit=100)
    ai_logs = db.get_recent_ai_logs(limit=5)

    # Calculate portfolio valuation
    unrealized_pnl = 0.0
    invested_capital = 0.0
    for p in positions:
        try:
            curr_p = client.get_ticker_price(p["symbol"])
            unrealized_pnl += (curr_p - p["entry_price"]) * p["quantity"]
            invested_capital += curr_p * p["quantity"]
        except Exception:
            invested_capital += p["entry_price"] * p["quantity"]

    total_portfolio_value = cash + invested_capital
    realized_pnl = sum(t["pnl_usdt"] for t in trades)
    wins = sum(1 for t in trades if t["pnl_usdt"] > 0)
    win_rate = (wins / len(trades) * 100.0) if trades else 0.0

    mode_label = "SIMULATED PAPER TRADING" if is_paper else "LIVE BINANCE SPOT"
    console.print(Panel(
        f"[bold white]EXECUTIVE PORTFOLIO STATUS ({mode_label})[/bold white]\n\n"
        f" • [bold]Available Cash:[/bold] ${cash:,.2f} USDT\n"
        f" • [bold]Invested in Positions:[/bold] ${invested_capital:,.2f} USDT ({len(positions)} active)\n"
        f" • [bold]Total Portfolio Net Worth:[/bold] [bold green]${total_portfolio_value:,.2f} USDT[/bold green]\n"
        f" • [bold]Realized PnL (Closed Trades):[/bold] [{'green' if realized_pnl >= 0 else 'red'}]${realized_pnl:+,.2f} USDT[/{'green' if realized_pnl >= 0 else 'red'}]\n"
        f" • [bold]Unrealized PnL (Open Positions):[/bold] [{'green' if unrealized_pnl >= 0 else 'red'}]${unrealized_pnl:+,.2f} USDT[/{'green' if unrealized_pnl >= 0 else 'red'}]\n"
        f" • [bold]Total Trades Completed:[/bold] {len(trades)} | [bold]Win Rate:[/bold] {win_rate:.1f}%\n"
        f" • [bold]Risk Rule:[/bold] Max {settings.RISK_PER_TRADE_PERCENT}% capital at risk per trade | Shariah 100% Spot",
        title="Portfolio Overview",
        border_style="cyan"
    ))

    # Show recent AI rationales
    if ai_logs:
        table = Table(title="Recent AI Market Convictions & Decisions", header_style="bold magenta")
        table.add_column("Time (UTC)", justify="left", style="dim")
        table.add_column("Symbol", style="cyan")
        table.add_column("Price", justify="right")
        table.add_column("Action", justify="center")
        table.add_column("Score", justify="right")
        table.add_column("AI Rationale", justify="left")

        for log in ai_logs:
            time_part = log["created_at"].split("T")[1][:8] if "T" in log["created_at"] else log["created_at"]
            act_style = "bold green" if log["action"] == "BUY" else ("bold red" if log["action"] == "SELL" else "yellow")
            table.add_row(
                time_part,
                log["symbol"],
                f"${log['current_price']:,.2f}",
                Text(log["action"], style=act_style),
                f"{log['confidence']:.2f}",
                log["rationale"][:65] + ("..." if len(log["rationale"]) > 65 else "")
            )
        console.print(table)

@cli.command()
@click.option("--interval", default=60, help="Seconds between scan loops")
@click.option("--quiet", is_flag=True, default=False, help="Minimal output mode")
def run(interval: int, quiet: bool):
    """Run continuous autonomous trading loop."""
    print_banner()
    console.print(f"[bold green]Starting autonomous bot loop (Poll interval: {interval}s)...[/bold green]")
    console.print("[dim]Press Ctrl+C at any time to pause or stop safely.[/dim]\n")

    engine = BotEngine()
    try:
        while True:
            time_now = datetime.now().strftime("%H:%M:%S")
            console.print(f"[bold cyan][{time_now}] Market Scan Cycle:[/bold cyan]")
            res = engine.scan_and_execute_cycle()

            if not quiet:
                for pair in res["pairs_scanned"]:
                    action_style = "bold green" if pair["action"] == "BUY" else ("bold red" if pair["action"] == "SELL" else "yellow")
                    short_rat = pair["rationale"][:45] + ("..." if len(pair["rationale"]) > 45 else "")
                    console.print(
                        f"  [white]{pair['symbol']:<9}[/white] : "
                        f"[bold white]${pair['price']:>9,.2f}[/bold white] | "
                        f"[magenta]{pair['regime']:<14}[/magenta] | "
                        f"RSI: [cyan]{pair['rsi']:>4.1f}[/cyan] | "
                        f"Score: [yellow]{pair['confidence']:.2f}[/yellow] -> "
                        f"[{action_style}]{pair['action']}[/{action_style}] [dim]({short_rat})[/dim]"
                    )

            if res["actions_taken"]:
                console.print("\n[bold green]Orders Executed This Cycle:[/bold green]")
                for action in res["actions_taken"]:
                    console.print(f"  * [bold green][OK] EXECUTED:[/bold green] {action['type']} {action['symbol']} - Qty: {action['quantity']} @ ${action.get('price', action.get('exit_price'))}")

            active_cnt = len(res["positions_reviewed"])
            console.print(f"[dim]Summary: Monitored {len(res['pairs_scanned'])} pairs | {active_cnt} active position(s) | Cash: ${res['ending_balance_usdt']:,.2f} USDT | Next scan in {interval}s[/dim]\n")

            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Trading loop stopped by user. All active positions and logs remain safely stored.[/yellow]")

@cli.command()
@click.option("--port", default=8000, help="Port to run web dashboard")
@click.option("--host", default="127.0.0.1", help="Host address")
def dashboard(port: int, host: str):
    """Launch the interactive visual web dashboard with live charts & controls."""
    print_banner()
    import uvicorn
    console.print(f"[bold green]Starting Live Visual Dashboard on http://{host}:{port}[/bold green]")
    console.print(f"[cyan]Open your browser and navigate to: [bold white]http://{host}:{port}[/bold white][/cyan]\n")
    uvicorn.run("web.app:app", host=host, port=port, reload=False)

if __name__ == "__main__":
    cli()
