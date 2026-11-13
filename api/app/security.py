"""Validation des entrées, limitation de débit et identification des clients."""
from __future__ import annotations

import ipaddress
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

from .errors import ApiError

# --- Plateformes autorisées (liste blanche) --------------------------------
PLATFORMS = {
    "twitter.com": "X (Twitter)",
    "x.com": "X (Twitter)",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "fb.watch": "Facebook",
    "tiktok.com": "TikTok",
}
# Liens raccourcis, résolus par nos soins (redirections validées une à une).
SHORT_HOSTS = {"fb.watch", "vm.tiktok.com", "vt.tiktok.com"}

MAX_URL_LENGTH = 500
AUDIO_BITRATES = {128, 192, 320}
_FORBIDDEN = re.compile(r"[\s\\<>\"`]")  # espaces, contrôles, antislash, guillemets


def _platform_for(host: str) -> str | None:
    for domain, name in PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def validate_media_url(raw: str) -> tuple[str, str]:
    """Vérifie le lien et renvoie (url_normalisée_en_https, plateforme).

    Refuse : domaines hors liste blanche, adresses IP, identifiants dans l'URL,
    ports inhabituels, caractères suspects. Protège contre les requêtes vers
    des services internes (SSRF).
    """
    bad = ApiError(400, "Lien invalide ou plateforme non prise en charge.")
    url = raw.strip()
    if not url or len(url) > MAX_URL_LENGTH or _FORBIDDEN.search(url):
        raise bad
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise bad
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in {"http", "https"} or parts.username or parts.password:
        raise bad
    if port not in (None, 80, 443) or not host.isascii() or _is_ip(host):
        raise bad
    platform = _platform_for(host)
    if not platform:
        raise bad
    return urlunsplit(("https", host, parts.path or "/", parts.query, "")), platform


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # on lit l'en-tête Location sans suivre
        return None


def _head_location(url: str) -> str | None:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    try:
        urllib.request.build_opener(_NoRedirect).open(request, timeout=5)
    except urllib.error.HTTPError as e:
        return e.headers.get("Location")
    except OSError:
        return None
    return None


def resolve_short_link(
    url: str, platform: str, locate: Callable[[str], str | None] = _head_location, max_hops: int = 3
) -> tuple[str, str]:
    """Suit les liens raccourcis (fb.watch, vm.tiktok.com) en revalidant chaque étape."""
    for _ in range(max_hops):
        if urlsplit(url).hostname not in SHORT_HOSTS:
            return url, platform
        location = locate(url)
        if not location:
            break
        url, platform = validate_media_url(urljoin(url, location))
    if urlsplit(url).hostname in SHORT_HOSTS:
        raise ApiError(422, "Lien raccourci impossible à résoudre : colle le lien complet.")
    return url, platform


def prepare_url(raw: str) -> tuple[str, str]:
    """Validation complète d'un lien reçu : (url_propre, plateforme)."""
    return resolve_short_link(*validate_media_url(raw))


def parse_quality(fmt: str, quality: str) -> int:
    """Valide la qualité : hauteur 144-1080 p pour le MP4, 128/192/320 kbps pour le MP3."""
    bad = ApiError(422, "Qualité demandée invalide.")
    m = re.fullmatch(r"(\d{2,4})\s?(p|kbps)", quality.strip().lower())
    if not m:
        raise bad
    value, unit = int(m[1]), m[2]
    if fmt == "mp4" and unit == "p" and 144 <= value <= 1080:
        return value
    if fmt == "mp3" and unit == "kbps" and value in AUDIO_BITRATES:
        return value
    raise bad


# --- Clients et limitation de débit ----------------------------------------
def client_ip(request, hops: int) -> str:
    """IP du client. Derrière `hops` proxys, on lit l'entrée ajoutée par le dernier :
    les valeurs plus à gauche dans X-Forwarded-For peuvent être falsifiées par le client."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if hops > 0 and forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Fenêtre glissante en mémoire : `limit` requêtes par `window` secondes et par clé."""

    def __init__(self, limit: int, window: int, max_keys: int = 10_000):
        self.limit, self.window, self.max_keys = limit, window, max_keys
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            if len(self._hits) > self.max_keys:
                self._purge(now)
            return True

    def _purge(self, now: float) -> None:
        for key in list(self._hits):
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if not hits:
                del self._hits[key]
