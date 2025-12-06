"""
Logging utilities for ClaudeInLove.
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.logging import RichHandler

from ..core.config import get_config


# Rich console for pretty output
console = Console()


def setup_logging(name: str = "claudeinlove") -> logging.Logger:
    """Set up logging with both file and console handlers."""
    config = get_config()

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, config.log_level.upper()))

    # Remove existing handlers
    logger.handlers = []

    # Console handler with Rich
    console_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
    )
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    # File handler
    log_file = config.log_dir / f"{name}_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(file_handler)

    return logger


# Default logger
logger = setup_logging()


def log_suspicion(scammer_id: str, message: str, score: float, reason: str):
    """Log a suspicion flag prominently."""
    config = get_config()

    # Log to file
    suspicion_log = config.log_dir / "suspicion.log"
    with open(suspicion_log, "a") as f:
        f.write(f"{datetime.now().isoformat()} | {scammer_id} | {score:.2f} | {reason}\n")
        f.write(f"  Message: {message[:200]}...\n\n")

    # Console warning
    console.print(f"[bold yellow]SUSPICION FLAG[/bold yellow] (score: {score:.2f})")
    console.print(f"  Scammer: {scammer_id}")
    console.print(f"  Reason: {reason}")
    console.print(f"  Message: {message[:100]}...")

    logger.warning(f"Suspicion flag: {scammer_id} - {reason} (score: {score:.2f})")


def log_message(direction: str, scammer_id: str, content: str):
    """Log a message exchange."""
    arrow = "←" if direction == "inbound" else "→"
    color = "cyan" if direction == "inbound" else "green"

    console.print(f"[{color}]{arrow} [{scammer_id[:8]}][/{color}] {content[:100]}...")
    logger.info(f"{direction.upper()}: {scammer_id[:8]} - {content[:50]}...")


def log_error(message: str, exc: Exception = None):
    """Log an error."""
    console.print(f"[bold red]ERROR:[/bold red] {message}")
    if exc:
        logger.exception(message)
    else:
        logger.error(message)


def log_status(message: str):
    """Log a status message."""
    console.print(f"[dim]{message}[/dim]")
    logger.info(message)
