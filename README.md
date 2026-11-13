# VidGrab

Télécharge une vidéo X, Instagram, Facebook ou TikTok à partir de son lien.
Interface web statique + API Python (FastAPI, yt-dlp, ffmpeg).

```
vidgrab/
├── api/                  API (hébergée sur Render)
│   ├── app/
│   │   ├── main.py       routes, middlewares, gestion des erreurs
│   │   ├── security.py   validation des liens, limitation de débit
│   │   ├── downloader.py extraction et téléchargement (yt-dlp)
│   │   ├── errors.py     messages d'erreur clairs
│   │   └── config.py     réglages (variables d'environnement)
│   ├── tests/            tests automatiques (pytest)
│   ├── Dockerfile
│   └── lancer.bat        lancement local (Windows)
└── docs/                 interface (hébergée sur GitHub Pages)
    ├── index.html
    ├── css/style.css
    ├── js/config.js      adresse de l'API (à modifier)
    ├── js/app.js
    └── assets/           logo et icônes
```

## En local (Windows)
Python et ffmpeg doivent être installés. Double-clique sur `api/lancer.bat` :
l'interface s'ouvre sur http://localhost:8000.

## Tests
```
cd api
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Mise en ligne
1. **API sur Render** (Web Service, Docker, Root Directory `api`, plan Free).
2. Variables d'environnement Render : `ALLOWED_ORIGINS` = `https://TONPSEUDO.github.io`.
3. Dans `docs/js/config.js`, remplace `REMPLACE-MOI` par le nom du service Render.
4. **Interface sur GitHub Pages** : Settings > Pages > branche `main`, dossier `/docs`.

## Réglages de l'API (variables d'environnement)
| Variable | Défaut | Rôle |
|---|---|---|
| `ALLOWED_ORIGINS` | localhost | Origines autorisées (séparées par des virgules, `*` refusé) |
| `TRUSTED_PROXY_HOPS` | 0 (1 dans le Dockerfile) | Nombre de proxys devant l'API |
| `MAX_DURATION` | 900 | Durée maximale d'une vidéo (secondes) |
| `MAX_FILESIZE_MB` | 200 | Taille maximale d'un fichier |
| `MAX_CONCURRENT` | 2 | Téléchargements simultanés |
| `RATE_INFO_PER_MIN` / `RATE_DOWNLOAD_PER_MIN` | 20 / 5 | Limites par IP et par minute |
| `GLOBAL_DOWNLOADS_PER_HOUR` | 150 | Plafond global par heure |

## Sécurité
- Liste blanche de domaines, refus des IP, ports, identifiants et caractères suspects dans les liens.
- Liens raccourcis résolus côté serveur, chaque redirection étant revalidée.
- Extracteur « générique » de yt-dlp désactivé.
- Origines (CORS) restreintes, requêtes d'origine inconnue refusées.
- Limites par IP, plafond global, nombre de téléchargements simultanés, durée et taille maximales.
- Aucun détail interne dans les erreurs, `/docs` désactivé, conteneur sans droits root.
- Interface : CSP stricte, aucun script ni style en ligne, données affichées via `textContent`.

Ne jamais publier de cookies, de clés ou de mots de passe dans ce dépôt.
Télécharge uniquement des contenus dont tu as le droit de conserver une copie.
