"""Extraction des informations et téléchargement via yt-dlp."""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from .config import Settings
from .errors import ApiError, explain

log = logging.getLogger("vidgrab")

TMP_PREFIX = "vidgrab_"
TMP_MAX_AGE = 600  # secondes avant suppression d'un dossier temporaire oublié
# Seuls ces extracteurs sont chargés : l'extracteur « générique » (qui suit
# n'importe quelle URL) est donc désactivé.
ALLOWED_EXTRACTORS = [r"(?i)^(twitter|instagram|facebook|tiktok)"]


@dataclass
class MediaFile:
    path: Path
    tmpdir: Path
    title: str
    media_type: str
    ext: str


def _options(cfg: Settings) -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "playlist_items": "1",  # carrousels : première vidéo seulement
        "ignoreconfig": True,
        "cachedir": False,
        "retries": 3,
        "extractor_retries": 2,
        "socket_timeout": 15,
        "max_filesize": cfg.max_filesize_mb * 1024 * 1024,
        "allowed_extractors": ALLOWED_EXTRACTORS,
    }


def _first_entry(data: dict | None) -> dict | None:
    if data and data.get("_type") == "playlist":
        return next((e for e in data.get("entries") or [] if e), None)
    return data


def safe_name(title: str) -> str:
    """Nom de fichier sûr : lettres, chiffres, espaces et tirets uniquement."""
    cleaned = re.sub(r"[^\w\- ]", "", title or "").strip()[:60]
    return cleaned or "video"


def purge_stale_tmp() -> None:
    """Supprime les dossiers temporaires abandonnés (téléchargement interrompu)."""
    limit = time.time() - TMP_MAX_AGE
    for d in Path(tempfile.gettempdir()).glob(TMP_PREFIX + "*"):
        try:
            if d.is_dir() and d.stat().st_mtime < limit:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def fetch_info(cfg: Settings, url: str) -> dict:
    """Métadonnées de la vidéo, sans la télécharger."""
    try:
        with yt_dlp.YoutubeDL(_options(cfg) | {"skip_download": True}) as ydl:
            data = _first_entry(ydl.extract_info(url, download=False))
    except yt_dlp.utils.YoutubeDLError as e:
        raise explain(e) from e
    if not data:
        raise ApiError(404, "Vidéo introuvable ou supprimée.")
    if data.get("is_live"):
        raise ApiError(422, "Les directs ne sont pas pris en charge.")
    duration = int(data.get("duration") or 0)
    thumbnail = data.get("thumbnail") or ""
    return {
        "title": (data.get("title") or "Vidéo")[:200],
        "uploader": (data.get("uploader") or "")[:100] or None,
        "duration": duration,
        "thumbnail": thumbnail if thumbnail.startswith("https://") else None,
        "heights": sorted({f["height"] for f in data.get("formats") or [] if f.get("height")}, reverse=True),
        "too_long": duration > cfg.max_duration,
    }


def download_media(cfg: Settings, url: str, fmt: str, quality: int) -> MediaFile:
    """Télécharge la vidéo (mp4) ou son audio (mp3) dans un dossier temporaire."""
    purge_stale_tmp()
    tmpdir = Path(tempfile.mkdtemp(prefix=TMP_PREFIX))
    rejected: dict[str, str] = {}

    def match_filter(info, *, incomplete=False):
        if info.get("is_live"):
            rejected["why"] = "live"
            return "live"
        if (info.get("duration") or 0) > cfg.max_duration:
            rejected["why"] = "long"
            return "trop longue"
        return None

    opts = _options(cfg) | {"outtmpl": str(tmpdir / "%(id)s.%(ext)s"), "match_filter": match_filter}
    if fmt == "mp4":
        opts["format"] = f"bv*[height<={quality}]+ba/b[height<={quality}]/b"
        opts["merge_output_format"] = "mp4"
    else:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": str(quality)}
        ]

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = _first_entry(ydl.extract_info(url, download=True))
        files = [p for p in tmpdir.iterdir() if p.is_file() and p.suffix != ".part"]
        if not files:
            if rejected.get("why") == "long":
                raise ApiError(413, f"Vidéo trop longue (max {cfg.max_duration // 60} min).")
            if rejected.get("why") == "live":
                raise ApiError(422, "Les directs ne sont pas pris en charge.")
            raise ApiError(502, "Aucun fichier produit. Réessaie ou mets yt-dlp à jour.")
        path = max(files, key=lambda p: p.stat().st_size)
        if path.stat().st_size > cfg.max_filesize_mb * 1024 * 1024:
            raise ApiError(413, f"Fichier trop volumineux (max {cfg.max_filesize_mb} Mo).")
    except yt_dlp.utils.YoutubeDLError as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise explain(e) from e
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise

    return MediaFile(
        path=path,
        tmpdir=tmpdir,
        title=(info or {}).get("title") or "video",
        media_type="video/mp4" if fmt == "mp4" else "audio/mpeg",
        ext=fmt,
    )
