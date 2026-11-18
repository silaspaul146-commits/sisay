import pytest

from app.core.config import Settings, libpq_url, normalize_database_url


@pytest.mark.parametrize("raw", ["postgres://u:p@h/db?sslmode=require", "postgresql://u:p@h/db?sslmode=require",
                                 "postgresql+psycopg://u:p@h/db?sslmode=require"])
def test_host_urls_are_normalized_to_psycopg(raw):
    assert normalize_database_url(raw) == "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert libpq_url(normalize_database_url(raw)) == "postgresql://u:p@h/db?sslmode=require"


def test_single_pepper_overrides_pepper_map(monkeypatch):
    monkeypatch.setenv("TOKEN_PEPPER", "render-generated-secret")
    s = Settings()
    assert s.token_peppers == {1: "render-generated-secret"} and s.token_pepper_active_version == 1


def test_development_pepper_refused_outside_development(monkeypatch):
    monkeypatch.delenv("TOKEN_PEPPER", raising=False)
    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(RuntimeError):
        Settings().check_production_safety()


def test_in_api_worker_requires_worker_role_url():
    import pytest

    from app.core.config import Settings
    with pytest.raises(RuntimeError, match="WORKER_DATABASE_URL"):
        Settings(run_worker_in_api=True).check_production_safety()
    s = Settings(run_worker_in_api=True, worker_database_url="postgres://app_worker:x@h/db")
    s.check_production_safety()
    assert s.worker_database_url.startswith("postgresql+psycopg://")
