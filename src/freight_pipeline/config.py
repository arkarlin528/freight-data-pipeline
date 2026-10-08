from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (or a local .env file), prefixed FREIGHT_."""

    model_config = SettingsConfigDict(env_prefix="FREIGHT_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://localhost/freight_pipeline"

    # Where the carrier sites live (the mock site in development).
    source_base_url: str = "http://127.0.0.1:8900"
    sources: list[str] = Field(default_factory=lambda: ["asl", "mcl", "ssc"])

    # Politeness: identify ourselves, respect robots.txt, never hammer a site.
    user_agent: str = "FreightRateBot/0.1 (+https://github.com/arkarlin528/freight-data-pipeline)"
    min_request_interval: float = 1.0
    honour_crawl_delay: bool = True  # only ever turned off in tests
    request_timeout: float = 15.0
    max_attempts: int = 4

    # Mekong Container Lines: "api" calls the JSON endpoint behind the page; "browser" renders it.
    mcl_mode: str = "api"
    # Playwright browser channel: None = bundled Chromium (Docker/CI), "msedge"/"chrome" = installed browser.
    browser_channel: str | None = None

    # Raw zone: every response is kept, so any run can be re-parsed later without re-crawling.
    raw_dir: Path = Path("data/raw")
    report_dir: Path = Path("data/reports")

    # Publishing to the logistics platform (project #1).
    logistics_api_url: HttpUrl | None = None
    logistics_api_key: SecretStr | None = None
    publish_batch_size: int = 500

    # Optional failure alert.
    slack_webhook_url: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
