"""Tests de sécurité et de comportement de l'API (sans accès réseau)."""
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.config import Settings
from app.downloader import MediaFile
from app.errors import ApiError, explain
from app.main import create_app
from app.security import RateLimiter, client_ip, resolve_short_link, validate_media_url

OK_URL = "https://x.com/user/status/123"
ORIGIN = "http://localhost:8000"


def make_client(**overrides) -> TestClient:
    return TestClient(create_app(Settings(**overrides)))


@pytest.fixture
def fake_info(monkeypatch):
    seen = {}

    def fetch(cfg, url):
        seen["url"] = url
        return {"title": "t", "uploader": None, "duration": 10, "thumbnail": None, "heights": [720], "too_long": False}

    monkeypatch.setattr(main_module, "fetch_info", fetch)
    return seen


def test_health():
    assert make_client().get("/health").json() == {"ok": True}


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com/video",
        "https://x.com@evil.com/a",
        "https://x.com.evil.com/a",
        "http://127.0.0.1/a",
        "https://x.com:8080/a",
        "https://evil.com\\@x.com/a",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://x.com/a b",
        "https://xn--x-9ja.com/a",
        "https://" + "a" * 600 + ".x.com",
    ],
)
def test_rejects_dangerous_urls(url):
    with pytest.raises(ApiError):
        validate_media_url(url)


def test_info_normalizes_url(fake_info):
    r = make_client().get("/info", params={"url": "http://www.x.com/u/status/1#frag"})
    assert r.status_code == 200 and r.json()["platform"] == "X (Twitter)"
    assert fake_info["url"] == "https://www.x.com/u/status/1"


def test_info_rejects_foreign_domain():
    r = make_client().get("/info", params={"url": "https://evil.com/x"})
    assert r.status_code == 400 and "detail" in r.json()


@pytest.mark.parametrize("params", [{"format": "avi"}, {"format": "mp3", "quality": "999kbps"}, {"quality": "4000p"}])
def test_download_rejects_bad_params(params):
    r = make_client().get("/download", params={"url": OK_URL, **params})
    assert r.status_code == 422


def test_blocks_unknown_origin_and_allows_known(fake_info):
    c = make_client()
    assert c.get("/info", params={"url": OK_URL}, headers={"Origin": "https://evil.com"}).status_code == 403
    r = c.get("/info", params={"url": OK_URL}, headers={"Origin": ORIGIN})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == ORIGIN


def test_wildcard_origin_is_ignored(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "*, https://moi.github.io/")
    assert Settings.from_env().allowed_origins == ("https://moi.github.io",)


def test_rate_limit(fake_info):
    c = make_client(rate_info_per_min=2)
    codes = [c.get("/info", params={"url": OK_URL}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_security_headers_and_no_docs():
    c = make_client()
    r = c.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


def test_download_serves_file_then_cleans_tmp(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="vidgrab_test_"))
    (tmp / "v.mp4").write_bytes(b"data")
    monkeypatch.setattr(
        main_module, "download_media", lambda *a: MediaFile(tmp / "v.mp4", tmp, "Ma vidéo!", "video/mp4", "mp4")
    )
    r = make_client().get("/download", params={"url": OK_URL, "format": "mp4", "quality": "720p"})
    assert r.status_code == 200 and r.content == b"data"
    assert 'filename="Ma vidéo.mp4"' in r.headers["content-disposition"] or "Ma%20vid" in r.headers["content-disposition"]
    assert not tmp.exists()
    shutil.rmtree(tmp, ignore_errors=True)


def test_download_refused_when_server_busy():
    r = make_client(max_concurrent=0).get("/download", params={"url": OK_URL})
    assert r.status_code == 503


def test_short_links_are_resolved_and_revalidated():
    locate = lambda u: "https://www.facebook.com/watch/?v=1"
    url, platform = resolve_short_link("https://fb.watch/abc/", "Facebook", locate)
    assert url.startswith("https://www.facebook.com/") and platform == "Facebook"
    with pytest.raises(ApiError):  # redirection vers un domaine non autorisé
        resolve_short_link("https://fb.watch/abc/", "Facebook", lambda u: "https://evil.com/")
    with pytest.raises(ApiError):  # lien impossible à résoudre
        resolve_short_link("https://vm.tiktok.com/abc/", "TikTok", lambda u: None)


class _Req:
    def __init__(self, xff, host="9.9.9.9"):
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = type("C", (), {"host": host})()


def test_client_ip_ignores_spoofed_values():
    assert client_ip(_Req("6.6.6.6, 1.2.3.4"), 1) == "1.2.3.4"
    assert client_ip(_Req("6.6.6.6, 1.2.3.4"), 0) == "9.9.9.9"
    assert client_ip(_Req(None), 1) == "9.9.9.9"


def test_rate_limiter_window():
    rl = RateLimiter(2, 60)
    assert [rl.allow("a"), rl.allow("a"), rl.allow("a"), rl.allow("b")] == [True, True, False, True]


@pytest.mark.parametrize(
    "message,status",
    [("This video is private", 403), ("HTTP Error 429: Too Many Requests", 429), ("Video unavailable", 404), ("boom", 502)],
)
def test_explain(message, status):
    assert explain(Exception(message)).status == status
