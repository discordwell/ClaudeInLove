#!/usr/bin/env python3
"""
One-time script to scrape Facebook profile and build persona.

Run this before starting ClaudeInLove to set up your alter ego.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.persona.facebook_scraper import scrape_facebook_profile
from src.persona.persona_builder import create_persona_from_file
from src.core.database import Database
from src.core.config import get_config

from rich.console import Console
from rich.panel import Panel

console = Console()


async def main():
    console.print(Panel.fit(
        "[bold cyan]ClaudeInLove - Persona Setup[/bold cyan]\n"
        "[dim]Scrape Facebook profile to build alter ego[/dim]",
        border_style="cyan"
    ))

    console.print("\n[yellow]This will:[/yellow]")
    console.print("1. Open a browser to Facebook")
    console.print("2. You'll need to log in (if not already)")
    console.print("3. Scrape your profile info")
    console.print("4. Build a persona document for scam-baiting")
    console.print()

    confirm = input("Continue? [y/N]: ")
    if confirm.lower() != 'y':
        console.print("[dim]Cancelled[/dim]")
        return

    try:
        # Scrape Facebook
        console.print("\n[bold]Starting Facebook scraper...[/bold]")
        data = await scrape_facebook_profile()

        console.print("\n[green]Scraping complete![/green]")
        console.print(f"  Name: {data.get('name', 'N/A')}")
        console.print(f"  Location: {data.get('location', 'N/A')}")
        console.print(f"  Posts found: {len(data.get('recent_posts', []))}")

        # Build persona and save to database
        console.print("\n[bold]Building persona...[/bold]")

        async with Database() as db:
            persona = await create_persona_from_file(db=db)

        console.print("\n[green]Persona created successfully![/green]")
        console.print(f"  Name: {persona.name}")
        console.print("\n[bold]Persona document:[/bold]")
        console.print(persona.persona_document[:500] + "...")

    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        raise


if __name__ == "__main__":
    asyncio.run(main())
