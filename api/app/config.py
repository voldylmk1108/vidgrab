"""Configuration de l'API, lue depuis les variables d'environnement."""
from __future__ import annotations

import os
from dataclasses import dataclass

DEV_ORIGINS = "http://localhost:8000,http://127.0.0.1:8000"


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Origines autorisées à appeler l'API (adresse de ta page GitHub Pages en production).
    allowed_origins: tuple[str, ...] = tuple(DEV_ORIGINS.split(","))
    max_duration: int = 900              # durée maximale d'une vidéo (secondes)
    max_filesize_mb: int = 200           # taille maximale d'un fichier (Mo)
    max_concurrent: int = 2              # téléchargements simultanés
    rate_info_per_min: int = 20          # requêtes /info par minute et par IP
    rate_download_per_min: int = 5       # requêtes /download par minute et par IP
    global_downloads_per_hour: int = 150  # plafond global, toutes IP confondues
    trusted_proxy_hops: int = 0          # nombre de proxys devant l'API (1 sur Render)
    enable_docs: bool = False            # active /docs (développement uniquement)
    serve_front: bool = False            # sert le dossier docs/ (usage local)

    @classmethod
    def from_env(cls) -> "Settings":
        raw = os.getenv("ALLOWED_ORIGINS", DEV_ORIGINS)
        # Le joker "*" est volontairement ignoré : il faut lister les origines.
        origins = tuple(o.strip().rstrip("/") for o in raw.split(",") if o.strip() and o.strip() != "*")
        return cls(
            allowed_origins=origins,
            max_duration=_int("MAX_DURATION", cls.max_duration),
            max_filesize_mb=_int("MAX_FILESIZE_MB", cls.max_filesize_mb),
            max_concurrent=_int("MAX_CONCURRENT", cls.max_concurrent),
            rate_info_per_min=_int("RATE_INFO_PER_MIN", cls.rate_info_per_min),
            rate_download_per_min=_int("RATE_DOWNLOAD_PER_MIN", cls.rate_download_per_min),
            global_downloads_per_hour=_int("GLOBAL_DOWNLOADS_PER_HOUR", cls.global_downloads_per_hour),
            trusted_proxy_hops=_int("TRUSTED_PROXY_HOPS", cls.trusted_proxy_hops),
            enable_docs=_flag("ENABLE_DOCS"),
            serve_front=_flag("SERVE_FRONT"),
        )
