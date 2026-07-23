import pytest

from app.config import ConfigError, resolve_cors_origins


def test_defaults_to_local_dev_origins_when_unset():
    origins = resolve_cors_origins({})
    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5173" in origins
    assert "*" not in origins


def test_explicit_development_uses_default_dev_origins():
    origins = resolve_cors_origins({"ATLAS_ENV": "development"})
    assert origins == resolve_cors_origins({})


def test_development_honors_an_explicit_override():
    origins = resolve_cors_origins(
        {"ATLAS_ENV": "development", "ATLAS_ALLOWED_ORIGINS": "http://localhost:3000"}
    )
    assert origins == ["http://localhost:3000"]


def test_production_uses_configured_origins():
    origins = resolve_cors_origins(
        {
            "ATLAS_ENV": "production",
            "ATLAS_ALLOWED_ORIGINS": "https://atlas.example.com, https://app.atlas.example.com",
        }
    )
    assert origins == ["https://atlas.example.com", "https://app.atlas.example.com"]


def test_production_without_allowed_origins_raises():
    with pytest.raises(ConfigError):
        resolve_cors_origins({"ATLAS_ENV": "production"})


def test_production_with_blank_allowed_origins_raises():
    with pytest.raises(ConfigError):
        resolve_cors_origins({"ATLAS_ENV": "production", "ATLAS_ALLOWED_ORIGINS": " , ,"})


def test_production_rejects_wildcard():
    with pytest.raises(ConfigError):
        resolve_cors_origins({"ATLAS_ENV": "production", "ATLAS_ALLOWED_ORIGINS": "*"})


def test_rejects_unknown_atlas_env():
    with pytest.raises(ConfigError):
        resolve_cors_origins({"ATLAS_ENV": "staging"})


def test_atlas_env_is_case_insensitive():
    origins = resolve_cors_origins(
        {"ATLAS_ENV": "PRODUCTION", "ATLAS_ALLOWED_ORIGINS": "https://atlas.example.com"}
    )
    assert origins == ["https://atlas.example.com"]


def test_rejects_origin_with_a_path():
    with pytest.raises(ConfigError):
        resolve_cors_origins(
            {"ATLAS_ENV": "production", "ATLAS_ALLOWED_ORIGINS": "https://atlas.example.com/app"}
        )


def test_rejects_origin_with_a_trailing_slash():
    with pytest.raises(ConfigError):
        resolve_cors_origins(
            {"ATLAS_ENV": "production", "ATLAS_ALLOWED_ORIGINS": "https://atlas.example.com/"}
        )


def test_rejects_malformed_origin_missing_scheme():
    with pytest.raises(ConfigError):
        resolve_cors_origins(
            {"ATLAS_ENV": "development", "ATLAS_ALLOWED_ORIGINS": "atlas.example.com"}
        )


def test_rejects_wildcard_subdomain_pattern_not_just_bare_star():
    # Wildcard subdomain matching isn't supported (see design doc) -- a
    # value like this must fail loudly at startup, not silently produce an
    # origin that can never match a real browser Origin header.
    with pytest.raises(ConfigError):
        resolve_cors_origins(
            {"ATLAS_ENV": "development", "ATLAS_ALLOWED_ORIGINS": "https://*.example.com"}
        )


def test_rejects_wildcard_embedded_anywhere_in_an_origin():
    with pytest.raises(ConfigError):
        resolve_cors_origins(
            {"ATLAS_ENV": "production", "ATLAS_ALLOWED_ORIGINS": "https://evil*.example.com"}
        )
