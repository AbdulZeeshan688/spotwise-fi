import pytest

from spotwise.config import Settings


def test_defaults_match_finland(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAT_RATE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.vat_rate == 0.255
    assert settings.timezone == "Europe/Helsinki"
    assert settings.price_area == "FI"


def test_empty_env_value_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAT_RATE", "")
    monkeypatch.setenv("ENTSOE_TOKEN", "")
    settings = Settings(_env_file=None)
    assert settings.vat_rate == 0.255
    assert settings.entsoe_token is None


def test_cors_origins_split_on_commas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, https://spotwise.netlify.app")
    settings = Settings(_env_file=None)
    assert settings.cors_origin_list == [
        "http://localhost:5173",
        "https://spotwise.netlify.app",
    ]


def test_secrets_are_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-very-secret")
    settings = Settings(_env_file=None)
    assert "sk-very-secret" not in repr(settings)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require",
        "postgres://u:p@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require",
        "postgresql+psycopg://u:p@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require",
    ],
)
def test_database_url_from_neon_gets_psycopg_driver(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    settings = Settings(_env_file=None)
    assert settings.database_url == (
        "postgresql+psycopg://u:p@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require"
    )
