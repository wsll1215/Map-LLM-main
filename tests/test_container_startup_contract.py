from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_web_is_health_checked_before_nginx_starts():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "healthcheck:" in compose.split("\n  map-worker:", 1)[0]
    assert "condition: service_healthy" in compose.split("\n  nginx:", 1)[1]


def test_nginx_resolves_web_at_request_time():
    nginx = (ROOT / "nginx.conf").read_text(encoding="utf-8")

    assert "resolver 127.0.0.11" in nginx
    assert "set $django_upstream http://web:8000" in nginx
    assert "proxy_pass http://django_upstream" not in nginx
