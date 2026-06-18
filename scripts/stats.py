#!/usr/bin/env python3
"""
Show an overview of all scam-baiting engagements.

Read-only: it never opens a browser or sends anything, so it is safe to run at
any time, including while the main loop is live.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import Database
from src.core.stats import gather_overview, human_duration

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


# Colour per scammer status, with a sensible default for anything unmapped.
STATUS_STYLE = {
    "active": "green",
    "paused": "yellow",
    "flagged": "red",
    "archived": "dim",
}


def render(overview) -> None:
    """Print the overview as a summary panel plus a per-conversation table."""
    status_bits = " · ".join(
        f"[{STATUS_STYLE.get(status, 'white')}]{count} {status}[/]"
        for status, count in overview.by_status.items()
        if count
    ) or "[dim]none[/dim]"

    summary = (
        f"[bold]{overview.total_scammers}[/bold] scammers engaged   "
        f"({status_bits})\n"
        f"[bold]{overview.total_messages}[/bold] messages "
        f"([cyan]{overview.inbound_messages} in[/cyan] / "
        f"[green]{overview.outbound_messages} out[/green])   "
        f"time wasted: [bold]{human_duration(overview.total_engagement)}[/bold]\n"
        f"pending reviews: [bold]{overview.pending_reviews}[/bold]"
    )
    console.print(Panel(summary, title="ClaudeInLove — Stats", border_style="magenta"))

    if not overview.conversations:
        console.print("[dim]No conversations yet.[/dim]")
        return

    table = Table(show_lines=False)
    table.add_column("Scammer", overflow="fold")
    table.add_column("Status")
    table.add_column("Msgs", justify="right")
    table.add_column("Flags", justify="right")
    table.add_column("Engaged", justify="right")

    for c in overview.conversations:
        label = c.display_name or c.scammer_id[:12]
        style = STATUS_STYLE.get(c.status, "white")
        table.add_row(
            label,
            f"[{style}]{c.status}[/{style}]",
            str(c.message_count),
            str(c.suspicion_flags),
            human_duration(c.engagement),
        )

    console.print(table)


async def main():
    async with Database() as db:
        overview = await gather_overview(db)
    render(overview)


if __name__ == "__main__":
    asyncio.run(main())
