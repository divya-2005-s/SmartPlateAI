"""Static checks of the deployment files (Dockerfile, docker-compose, Caddyfile, env template). Docker and Caddy are not
needed: the files are read as text / YAML, so these checks run anywhere. They do not prove that an image builds."""
import re
from pathlib import Path

import pytest

from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
CADDY = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / "deploy" / "smartplate.env.example").read_text(encoding="utf-8")


def test_uvicorn_trusts_forwarded_headers_only_from_the_proxy():
    cmd = next(line for line in DOCKERFILE.splitlines() if line.startswith("CMD "))
    assert "--proxy-headers" in cmd and "--limit-concurrency" in cmd
    assert "forwarded-allow-ips" not in cmd  # taken from FORWARDED_ALLOW_IPS (uvicorn default 127.0.0.1), never '*'
    assert "ENVIRONMENT=production" in DOCKERFILE  # turns the abuse limits on ("auto")


def test_compose_gives_caddy_the_only_trusted_address():
    yaml = pytest.importorskip("yaml")
    c = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    app, caddy = c["services"]["app"], c["services"]["caddy"]
    trusted = dict(e.split("=", 1) for e in app["environment"])["FORWARDED_ALLOW_IPS"]
    assert trusted == caddy["networks"]["web"]["ipv4_address"] != app["networks"]["web"]["ipv4_address"]
    assert "ports" not in app and caddy["ports"] == ["80:80", "443:443"]  # the app port is never published
    assert app["env_file"] == "./smartplate.env"


def test_caddy_caps_bodies_and_times_out_slow_clients():
    assert re.search(r"max_size\s+30MB", CADDY)
    for directive in ("read_header", "read_body", "idle", "response_header_timeout"):
        assert directive in CADDY
    directives = [line for line in CADDY.splitlines() if not line.strip().startswith("#")]
    directives = " ".join(directives)
    assert "trusted_proxies" not in directives  # Caddy must overwrite, not trust, a client's X-Forwarded-For


def test_every_setting_in_the_env_template_exists_and_has_a_valid_value():
    fields = {name.upper() for name in Settings.model_fields}
    unmanaged = {"AUTH_COOKIE_SECURE", "AUTH_COOKIE_SAMESITE"}  # read by the auth route directly
    values = dict(line.split("=", 1) for line in ENV_EXAMPLE.splitlines() if line and not line.startswith("#"))
    assert set(values) - fields - unmanaged == set()
    assert values["PAID_PROVIDERS_REQUIRE_LOGIN"] == "true" and values["RATE_LIMITS_ENABLED"] == "true"
    assert not any(values[k] for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "GOOGLE_VISION_API_KEY", "USDA_FDC_API_KEY"))
    Settings(_env_file=None, **{k.lower(): v for k, v in values.items() if k.lower() in Settings.model_fields})  # parses


def _compose(env: dict | None = None) -> dict:
    """docker-compose.yml with ${VAR:-default} / ${VAR:?msg} substituted the way Compose does."""
    yaml = pytest.importorskip("yaml")
    env = {"SITE_DOMAIN": "smartplate.test", **(env or {})}
    text = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    text = re.sub(r"\$\{(\w+)(?::-([^}]*)|:\?[^}]*)?\}", lambda m: env.get(m.group(1)) or m.group(2) or "", text)
    return yaml.safe_load(text)


@pytest.mark.parametrize("net", [None, "10.213.47"])
def test_network_addresses_stay_consistent_when_the_range_is_changed(net):
    import ipaddress
    c = _compose({"SMARTPLATE_NET": net} if net else None)
    subnet = ipaddress.ip_network(c["networks"]["web"]["ipam"]["config"][0]["subnet"])
    caddy = ipaddress.ip_address(c["services"]["caddy"]["networks"]["web"]["ipv4_address"])
    app = ipaddress.ip_address(c["services"]["app"]["networks"]["web"]["ipv4_address"])
    trusted = dict(e.split("=", 1) for e in c["services"]["app"]["environment"])["FORWARDED_ALLOW_IPS"]
    assert caddy in subnet and app in subnet and caddy != app and str(caddy) == trusted
    assert subnet.prefixlen == 24 and str(subnet).startswith(net or "172.31.240")


def test_compose_persists_data_and_rotates_logs():
    c = _compose()
    assert c["name"] == "smartplate"
    assert "smartplate-data:/data" in c["services"]["app"]["volumes"] and "caddy-data:/data" in c["services"]["caddy"]["volumes"]
    for svc in c["services"].values():
        assert svc["logging"]["options"]["max-size"] and svc["restart"] == "unless-stopped"


def test_secret_files_never_reach_the_build_context():
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for pattern in ("**/.env", "**/.env.*", "**/*.env", "backups", "backend/data", "**/.venv-*", "**/*.bak"):
        assert pattern in ignore
    assert "!deploy/smartplate.env.example" in ignore


# ------------------------------------------------------------------ preflight and bundle
PRODUCTION_ENV = {"ENVIRONMENT": "production", "AUTH_COOKIE_SECURE": "true", "CORS_ORIGINS": "https://smartplate.test",
                  "PAID_PROVIDERS_REQUIRE_LOGIN": "true", "RATE_LIMITS_ENABLED": "true", "FORWARDED_ALLOW_IPS": "172.31.240.2"}


@pytest.fixture
def prod_env(tmp_path, monkeypatch):
    from app.core.config import get_settings
    s = get_settings()
    for k, v in PRODUCTION_ENV.items():
        monkeypatch.setenv(k, v)
        if k.lower() in Settings.model_fields:
            monkeypatch.setattr(s, k.lower(), v)
    monkeypatch.setattr(s, "database_path", str(tmp_path / "smartplate.db"))
    monkeypatch.setattr(s, "usage_database_path", "")
    monkeypatch.setenv("AUTH_DATABASE_PATH", str(tmp_path / "smartplate_users.db"))
    ref = ROOT / "deploy" / "reference_data"
    for name, f in {"FOOD_NUTRITION_CSV": "final_food_nutrient_dataset.csv", "PACKAGED_FOODS_CSV": "packaged_foods_india_clean.csv",
                    "PACKAGED_ADDITIVES_CSV": "packaged_food_additives.csv", "ADDITIVE_REFERENCE_CSV": "additive_reference_populated.csv"}.items():
        monkeypatch.setenv(name, str(ref / f))
    return s, monkeypatch


def test_preflight_passes_a_correct_production_configuration(prod_env):
    if not (ROOT / "deploy" / "reference_data" / "final_food_nutrient_dataset.csv").is_file():
        pytest.skip("run scripts/prepare_deploy_data.py first")
    from app.core import preflight
    assert [t for level, t in preflight.run() if level == "FAIL"] == []


@pytest.mark.parametrize("setting, value, expect", [
    ("paid_providers_require_login", "false", "anonymous users can trigger paid calls"),
    ("rate_limits_enabled", "false", "RATE_LIMITS_ENABLED is off"),
    ("environment", "development", "not production"),
    ("rate_limit_anon_analyses_per_hour", 0, "rate limit is 0"),
])
def test_preflight_fails_an_insecure_configuration(prod_env, setting, value, expect):
    s, mp = prod_env
    mp.setattr(s, setting, value)
    from app.core import preflight
    assert any(level == "FAIL" and expect in t for level, t in preflight.run())


def test_preflight_rejects_trusting_every_proxy_and_never_prints_keys(prod_env, capsys):
    s, mp = prod_env
    mp.setenv("FORWARDED_ALLOW_IPS", "*")
    mp.setattr(s, "openai_api_key", "sk-test-NOT-A-REAL-KEY-0123456789")
    from app.core import preflight
    assert preflight.main() == 1
    out = capsys.readouterr().out
    assert "trusts too much" in out and "OPENAI_API_KEY=yes" in out and "sk-test" not in out


def test_bundle_excludes_env_files_and_refuses_files_with_keys(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("bundle", ROOT / "backend" / "scripts" / "make_deploy_bundle.py")
    bundle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundle)
    src = tmp_path / "proj"
    (src / "app").mkdir(parents=True)
    (src / "app" / "main.py").write_text("print('ok')")
    (src / "app" / ".env").write_text("OPENAI_API_KEY=x")
    (src / "app" / ".env.bak").write_text("OPENAI_API_KEY=x")
    (src / "deploy").mkdir()
    (src / "deploy" / "smartplate.env.example").write_text("OPENAI_API_KEY=\n")
    monkeypatch.setattr(bundle, "ROOT", src)
    monkeypatch.setattr(bundle, "INCLUDE", ["app", "deploy/smartplate.env.example"])
    assert sorted(f.relative_to(src).as_posix() for f in bundle.files()) == ["app/main.py", "deploy/smartplate.env.example"]
    monkeypatch.setattr("sys.argv", ["x", "--out", str(tmp_path / "b.tgz")])
    assert bundle.main() == 0
    (src / "app" / "leak.py").write_text("KEY = 'sk-" + "a" * 30 + "'")
    assert bundle.main() == 1
