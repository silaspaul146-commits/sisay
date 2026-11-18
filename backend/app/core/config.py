"""Runtime configuration (DB spec 12.3). Values come from the environment or a .env file."""
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Accept the URL forms hosts hand out (Neon, Render: postgres:// or postgresql://) and use psycopg 3."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def libpq_url(url: str) -> str:
    """The same URL for direct psycopg/libpq use (LISTEN connection)."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/crisis"
    # Public map routes connect as a role that can read only the two public views (DB spec 7.2).
    # Defaults to database_url for local development.
    public_database_url: str | None = None

    # Staff (dashboard) routes connect as app_dashboard: no reporter identity, no credentials.
    # Defaults to database_url for local development.
    dashboard_database_url: str | None = None

    # Staff sign-in: any OpenID Connect provider (U-1). The API only validates the provider's
    # access tokens; users and their permissions live in identity.* (python -m app.manage grant).
    oidc_issuer: str | None = None          # e.g. https://your-tenant.eu.auth0.com/
    oidc_audience: str | None = None        # the API identifier configured at the provider
    oidc_jwks_url: str | None = None        # optional; discovered from the issuer when unset
    oidc_algorithms: list[str] = Field(default_factory=lambda: ["RS256", "ES256"])

    # Run the outbox worker as a background thread inside the API process, connected as the
    # worker role. For hosts without background workers (e.g. Render free plan) and testing only:
    # an idle free instance sleeps, and the worker sleeps with it.
    run_worker_in_api: bool = False
    worker_database_url: str | None = None

    # Anonymous report credentials (DB spec 7.3). Peppers are secrets: supply them via the
    # secret store in any shared environment. Format: {"1": "<random secret>"}.
    token_peppers: dict[int, str] = Field(default_factory=lambda: {1: "dev-only-pepper-change-me"})
    token_pepper_active_version: int = 1
    report_token_ttl_days: int = 180

    # Matching (DB spec 6)
    report_matching_policy_version: str = "match-2026.11.1"
    report_matching_max_location_uncertainty_m: int = 5000

    # Abuse control: reports per installation per hour before new reports are quarantined.
    intake_max_reports_per_installation_per_hour: int = 20

    # Outbox and jobs (DB spec 8.2)
    outbox_max_attempts: int = 10
    outbox_lease_seconds: int = 60
    outbox_poll_interval_s: float = 2.0
    outbox_batch_size: int = 50
    projection_freshness_interval_s: int = 300

    journey_check_retention_hours: int = 24

    # Retention (U-2, docs/DECISIONS.md): raw reports are short-lived; incidents remain as history.
    report_retention_days: int = 30
    report_submitter_retention_days: int = 7
    credential_retention_days_after_expiry: int = 30
    retention_hour_utc: int = 2  # nightly run time

    # Single-secret convenience for hosts that generate one random value (e.g. Render).
    # If set, it becomes pepper version 1 and overrides TOKEN_PEPPERS.
    token_pepper: str | None = None

    @field_validator("database_url", "public_database_url", "worker_database_url", "dashboard_database_url", mode="before")
    @classmethod
    def _normalize_url(cls, v):
        return normalize_database_url(v) if isinstance(v, str) else v

    def model_post_init(self, __context) -> None:
        if self.token_pepper:
            self.token_peppers = {1: self.token_pepper}
            self.token_pepper_active_version = 1

    @field_validator("app_env")
    @classmethod
    def _known_env(cls, v: str) -> str:
        if v not in {"development", "test", "staging", "production"}:
            raise ValueError("APP_ENV must be development, test, staging or production")
        return v

    @property
    def effective_public_database_url(self) -> str:
        return self.public_database_url or self.database_url

    @property
    def effective_dashboard_database_url(self) -> str:
        return self.dashboard_database_url or self.database_url

    def check_production_safety(self) -> None:
        if self.run_worker_in_api and not self.worker_database_url:
            raise RuntimeError("RUN_WORKER_IN_API needs WORKER_DATABASE_URL (the app_worker role)")
        if self.app_env in ("staging", "production") and any("dev-only" in p for p in self.token_peppers.values()):
            raise RuntimeError("Set TOKEN_PEPPER (or TOKEN_PEPPERS) to a real secret outside development")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.check_production_safety()
    return settings
