"""Erreurs de l'API et traduction des erreurs yt-dlp en messages clairs."""
from __future__ import annotations


class ApiError(Exception):
    """Erreur renvoyée au client sous la forme {"detail": message}."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def explain(err: Exception) -> ApiError:
    """Traduit une erreur yt-dlp en ApiError lisible (sans détails internes)."""
    m = str(err).lower()
    if any(k in m for k in ("private", "log in", "login", "sign in", "cookies", "authentication")):
        return ApiError(403, "Cette vidéo est privée ou demande une connexion.")
    if any(k in m for k in ("429", "too many requests", "rate-limit", "rate limit")):
        return ApiError(429, "La plateforme limite les requêtes. Réessaie dans quelques minutes.")
    if any(k in m for k in ("no video", "there is no video", "no media")):
        return ApiError(422, "Ce lien ne contient pas de vidéo (photo ou texte seulement).")
    if any(k in m for k in ("unavailable", "not exist", "removed", "deleted", "404", "not found")):
        return ApiError(404, "Vidéo introuvable ou supprimée.")
    if "unsupported url" in m:
        return ApiError(422, "Lien non pris en charge.")
    return ApiError(502, "Extraction impossible. La plateforme a peut-être changé : mets yt-dlp à jour.")
