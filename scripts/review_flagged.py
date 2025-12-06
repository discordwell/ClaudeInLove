#!/usr/bin/env python3
"""
Interactive script to review flagged conversations.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import Database
from src.safety.human_review import interactive_review_session

from rich.console import Console
from rich.panel import Panel

console = Console()


async def main():
    console.print(Panel.fit(
        "[bold yellow]ClaudeInLove - Review Flagged[/bold yellow]\n"
        "[dim]Review conversations flagged for suspicion[/dim]",
        border_style="yellow"
    ))

    async with Database() as db:
        await interactive_review_session(db)


if __name__ == "__main__":
    asyncio.run(main())
