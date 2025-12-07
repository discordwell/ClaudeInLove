"""
Configuration management for ClaudeInLove.
"""

import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass
class Config:
    """Application configuration."""

    # Paths
    data_dir: Path
    log_dir: Path
    browser_profile_dir: Path

    # Signal
    signal_debug_port: int

    # Browser
    browser_headless: bool

    # Safety
    suspicion_threshold: float
    auto_pause_on_flag: bool

    # Logging
    log_level: str

    # Rate limiting
    min_response_delay: float  # Minimum seconds before responding
    max_response_delay: float  # Maximum seconds before responding

    # LLM Provider
    llm_provider: str  # "openrouter" or "chatgpt"
    openrouter_api_key: str | None
    openrouter_model: str

    @classmethod
    def load(cls, env_file: str = ".env") -> "Config":
        """Load configuration from environment variables."""
        load_dotenv(env_file)

        # Get project root
        project_root = Path(__file__).parent.parent.parent

        return cls(
            # Paths
            data_dir=Path(os.getenv("DATA_DIR", project_root / "data")),
            log_dir=Path(os.getenv("LOG_DIR", project_root / "logs")),
            browser_profile_dir=Path(os.getenv(
                "BROWSER_USER_DATA_DIR",
                project_root / "data" / "browser_profile"
            )),

            # Signal
            signal_debug_port=int(os.getenv("SIGNAL_DEBUG_PORT", "9222")),

            # Browser
            browser_headless=os.getenv("BROWSER_HEADLESS", "false").lower() == "true",

            # Safety
            suspicion_threshold=float(os.getenv("SUSPICION_THRESHOLD", "0.7")),
            auto_pause_on_flag=os.getenv("AUTO_PAUSE_ON_FLAG", "true").lower() == "true",

            # Logging
            log_level=os.getenv("LOG_LEVEL", "INFO"),

            # Rate limiting (appear more human)
            min_response_delay=float(os.getenv("MIN_RESPONSE_DELAY", "30")),
            max_response_delay=float(os.getenv("MAX_RESPONSE_DELAY", "180")),

            # LLM Provider (openrouter = free, chatgpt = browser automation)
            llm_provider=os.getenv("LLM_PROVIDER", "openrouter"),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
            openrouter_model=os.getenv("OPENROUTER_MODEL", "deepseek-r1"),
        )

    def ensure_dirs(self):
        """Create required directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Path:
        """Path to SQLite database."""
        return self.data_dir / "conversations.db"

    @property
    def persona_path(self) -> Path:
        """Path to persona JSON file."""
        return self.data_dir / "persona.json"

    @property
    def screenshots_dir(self) -> Path:
        """Path to screenshots directory."""
        path = self.data_dir / "screenshots"
        path.mkdir(parents=True, exist_ok=True)
        return path


# Global config instance
_config: Config | None = None


def get_config() -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = Config.load()
        _config.ensure_dirs()
    return _config
