# Trail Map — contexte projet

App qui recense les chemins courus (trail / course à pied / randonnée), permet de les noter
(plaisir, sécurité, éclairage, entretien, abri, fréquentation, circulation)
et génère des itinéraires selon ces critères. D'abord perso, puis communautaire.

**Journal chronologique et prochaines tâches : voir `ROADMAP.md`.**
À chaque fin de session de travail : mettre à jour `ROADMAP.md` (ce qui a été fait, état,
prochaines étapes) et la section « État actuel » ci-dessous, puis committer et pousser.

## État actuel (2026-10-07)
- Étape 1 (import) : fonctionnelle. 254 activités (course, trail, randonnée), doublons Strava/Coros fusionnés.
  Reste : 3 .fit.gz Strava illisibles (`developer_data_index 0 not defined`).
- Carte web : traces distinctes, une par sortie, colorées par type, cliquables dans les deux onglets
  (couche invisible large ; fiche avec « Évaluer cette sortie ») (le rendu « Fréquentation » unifié
  sur les voies OSM a été retiré le 2026-10-07 : trop complexe, voir l'historique git), filtres, fiches, générateur d'itinéraires (boucle / aller simple le plus
  court ou à distance visée), dénivelé (tranche de D+, profil, relief 3D), export GPX,
  téléphone, `src/share.ts` : « Ouvrir avec COROS » (lien signé /dl/<id>.gpx hors scope PWA, ouvert par-dessus l'app :
  aperçu iOS → Partager → COROS → OK) et « Enregistrer dans Fichiers » (feuille de partage, GPX préparé à l'avance,
  appel synchrone dans le tap, 1er type MIME accepté). Jamais de navigation de la page de l'app vers un fichier ;
  COROS n'est jamais proposé dans la feuille de partage web. Panneau de debug : ?debug=1 ou appui long sur le titre.
- Front servi sous **/app/** (scope de la PWA ; / redirige vers /app/) : /api et /dl restent hors scope.
- Interface : identité « trail » (logo `frontend/public/logo.svg`, palette forêt / braise, Barlow Condensed),
  icônes SVG, réglages fins repliables, bouton Générer collant, panneau du bas compact sur téléphone,
  icônes d'écran d'accueil + manifest.
- Génération d'itinéraires annulable, avec avancement ; tuiles OSM de **toute la France** en local
  (extrait Geofabrik France, 36 349 tuiles, 7,5 Go) : plus de dépendance à Overpass en France
  (~4 s pour une première génération dans une zone jamais utilisée). Accès téléphone via Tailscale (HTTPS, tailnet).
- Auto-hébergement (`SELF-HOST.md`) : en production FastAPI sert aussi le front construit sur un seul port
  (8000, 127.0.0.1), service systemd `trailmap` dans WSL, WSL gardé allumé par une tâche planifiée Windows,
  `tailscale serve --bg http://localhost:8000`. Mise à jour : `./deploy-local.sh`. État : `GET /api/health`.
- Prochaine grosse étape : map-matching (étape 2), puis notation des tronçons (étape 3).
- Dénivelé : « Le plus plat » minimise le D+ (grande boucle, pétales de 2–5 km ou aller-retour, `flat: true`) ;
  Vallonné / Montagne / Personnalisé gardent une tranche de D+.
- Comptes : connexion obligatoire (identifiant + mot de passe) pour toute l'API sauf /api/health ;
  création de compte sur l'écran de connexion (désactivable : TRAILMAP_SIGNUP=0) ou en ligne de commande.
  **Chaque compte n'a accès qu'à ses propres données** (data/users/<nom>/) ; mise en commun plus tard.
- « Mes sorties » : « Mettre à jour mes données » (nouvelle archive Strava .zip ou fichiers .fit/.gpx/.tcx,
  import en arrière-plan, bandeau des nouvelles sorties) ; évaluation de chaque sortie de 1 à 5 sur
  8 critères (sécurité, éclairage, beauté du paysage, plaisir, entretien, abri, tranquillité,
  peu de circulation) + commentaire, en attendant de les reporter sur les tronçons (étape 3).
- Tests : 69 OK, 1 ignoré.

## Architecture
- backend/ : Python 3.12, FastAPI (`app/api.py`), PostgreSQL + PostGIS prévu (docker-compose, pas encore utilisé)
  - `app/ingest/` : parsers (FIT/GPX/TCX, archive Strava), clean, dedup, privacy, simplify, pipeline
  - `app/routing/` : moteur d'itinéraires Python (en attendant GraphHopper)
  - `app/auth.py` : comptes (scrypt), sessions (cookie HttpOnly/Secure/SameSite=Strict, seul le SHA-256
    du jeton est stocké), blocage après 5 échecs ; middleware dans `api.py` : toute route /api exige une
    session sauf PUBLIC_API (health, login, logout) ; tests : marqueur `auth`, sinon session simulée (conftest)
  - `app/workspace.py` : données propres à chaque compte (`Workspace` : sorties, moteur d'itinéraires avec
    ses traces pour « déjà couru », générations, import en cours), chargées à la première requête du compte
    (dépendance FastAPI `workspace` dans api.py) ; `adopt` : rattacher les données d'avant les comptes
  - `app/imports.py` : archive Strava (.zip, extraction limitée à activities.csv + activities/, anti zip-slip
    et zip-bomb) ou fichiers isolés ; `app/ratings.py` : évaluations par sortie et par utilisateur
- frontend/ : TypeScript + Vite + MapLibre GL 6 (PWA à venir), fond OpenFreeMap
  - `index.html` (structure + sprite d'icônes SVG `#i-…`), `src/style.css` (variables de couleurs en tête),
    `public/` (logo, icônes PNG, manifest ; copiés tels quels dans dist/)
  - `main.ts`, `share.ts` (GPX sur téléphone : partage, repli /dl), `debug.ts` (panneau de debug),
    `auth.ts` (écran de connexion), `importer.ts` (mise à jour des données), `ratings.ts`
    (fiche d'évaluation), `activities.ts` (onglet Mes sorties), `planner.ts` (onglet Itinéraire),
    `profile.ts` (profil altimétrique), `terrain.ts` (relief 3D), `api.ts`, `format.ts`
  - Vite ne pré-empaquette pas MapLibre (sinon le worker est perdu et la carte ne charge pas) ;
    en build de production, le worker est empaqueté à part et donné à `setWorkerUrl`
- Routage actuel : graphe OSM par tuiles 0,05° en cache dans data/osm/. En France, tuiles
  découpées localement depuis l'extrait Geofabrik (`app/routing/extract.py`, seulement les tuiles
  entièrement dans le polygone ; index des nœuds sur disque pour un extrait > 1,5 Go) ; hors de France
  et sur la frontière, Overpass (plusieurs instances en secours,
  souvent saturées). Une génération attend jusqu'à 3 min les tuiles du départ et de l'arrivée
  (indispensables), puis 45 s les autres (les plus proches d'abord) et calcule sans celles qui
  manquent ; une tuile en échec n'est pas redemandée avant 5 min. Seules les tuiles à portée
  (bande autour du segment départ-arrivée, disque autour du départ pour une boucle) sont chargées.
  Génération annulable et suivie (`Job` dans `app/routing/job.py`). A* pondéré par les préférences (coûts précalculés par
  génération, `Weights`), boucles en triangle, aller simple à distance visée via un détour sur ellipse ;
  « le plus plat » (`flattest`) : triangles, triangles étroits, allers-retours et combinaisons de petites boucles
  (pétales), classés au D+ par km.
  Critères dérivés des tags OSM (nature, circulation, éclairage estimé, escaliers)
  + "déjà couru" calculé depuis les traces de l'utilisateur.
  Pré-téléchargement en arrière-plan des tuiles autour des zones courues et de toutes celles qu'une
  trace traverse (176 zones,
  GET /api/routing/status), mis en pause quand une génération a besoin de tuiles.
- Altitude : tuiles DEM Terrarium (AWS, ~±3 m vs IGN RGE ALTI autour de Lyon), z13, cache data/dem/.
  Sert au D+/D- par tronçon et sens, à la tranche de D+ visée (boucles, aller simple à distance) et au relief 3D du front.
- Cible : routage + map-matching via GraphHopper auto-hébergé (Docker).
- Les notes seront attachées à des tronçons OSM (après map-matching), pas aux traces brutes.

## API
Toutes les routes exigent une session (cookie), sauf /api/health et /api/auth/login|logout|signup|options.
Chaque route ne lit et n'écrit que les données du compte connecté (data/users/<nom>/).
- POST /api/auth/login {username, password}, POST /api/auth/signup (même corps : crée le compte et connecte),
  GET /api/auth/options ({signup}), POST /api/auth/logout, GET /api/auth/me
- POST /api/import (multipart `files`) : archive Strava .zip et/ou .fit/.gpx/.tcx, puis réimport en arrière-plan ;
  GET /api/import/status : running / done (`new` : clés des sorties ajoutées) / error
- GET /api/ratings : critères + évaluations de l'utilisateur ; PUT|DELETE /api/ratings/{key}
  ({scores: {critère: 1..5}, comment}) ; `key` = clé stable de la sortie (`strava:<id>` ou `file:<nom>`)
- GET  /api/health : état (comptes chargés, générations en cours, front construit), rien sur les données d'un compte
- GET  /api/activities : traces masquées + simplifiées (~700 Ko), cache data/cache/
- POST /api/reload : relit data/raw
- GET  /api/routing/status : avancement du pré-téléchargement OSM
- POST /api/routes : génère des itinéraires (boucle / aller simple, préférences, tranche de D+ ou `flat: true`) ;
  `request_id` optionnel pour suivre / annuler ; `warning` si des tuiles OSM manquent
  Chaque itinéraire reçoit `route_id`, `name`, `gpx_filename` et est gardé dans data/routes/ (300 derniers)
- GET  /api/routes/{route_id}/gpx : GPX 1.1 (application/gpx+xml, attachment, nom ASCII .gpx)
- POST /api/routes/{route_id}/link : lien signé (1 h, lié au compte et à l'itinéraire) -> GET /dl/<id>.gpx?user=…&expires=…&sig=…
  (sans session, hors /api et hors scope PWA : repli du partage sur iPhone)
- POST /api/routes/gpx : GPX d'un itinéraire envoyé par le client ({name, coordinates})
- GET  /api/routes/{request_id}/progress : étape (download_ends, download, graph, routes) et avancement
- POST /api/routes/{request_id}/cancel : annule la génération

## Étapes
1. [fait, reste 3 FIT illisibles] Import des activités (export Strava + .fit Coros) -> traces normalisées
2. [à faire] Map-matching des traces sur OSM -> tronçons parcourus
3. [à faire] Interface de notation des tronçons
4. [prototype] Itinéraires pondérés par les notes (custom model GraphHopper)
   Prototype en place : boucles / aller simple selon critères OSM + D+, sans les notes
5. [à faire] Communautaire : comptes, agrégation, modération, zones de confidentialité

## Règles
- Données de l'utilisateur dans data/ (ignoré par git). Ne jamais committer de traces
  dans ce dépôt (il est public).
- Les données sont sauvegardées à part dans le dépôt GitHub **privé**
  https://github.com/Julesbor38/Run-Project-Data (`trail-map-data/` = contenu de data/,
  `strava-export/` = export Strava complet). Le mettre à jour quand data/ change, **sans data/osm/**
  (cache régénérable de 7,5 Go + extraits .pbf de plusieurs Go, trop gros pour GitHub) ni
  data/auth/sessions.json ; data/users/ (sorties, évaluations de chaque compte), lui, doit y être.
- Ne PAS utiliser l'API Strava comme source pour la version communautaire
  (CGU depuis nov. 2024 : affichage limité au seul utilisateur, pas d'usage IA).
  Source = export d'archive Strava / fichiers importés par l'utilisateur.
- Masquage début/fin de trace (200 m) + zones de confidentialité appliqués dès l'import.
- Code et commentaires en anglais, échanges en français.
- Tests : pytest dans backend/tests.
- Environnement : WSL2. Le navigateur est côté Windows ; la géolocalisation ne marche que
  sur http://localhost:5173 (pas via l'IP du WSL).

## Commandes
- Installation sur une nouvelle machine :
  - git clone https://github.com/Julesbor38/RunProject.git trail-map
  - git clone https://github.com/Julesbor38/Run-Project-Data.git
  - cp -a Run-Project-Data/trail-map-data/. trail-map/data/
- cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
  (sans le paquet python3-venv : `uv venv .venv && uv pip install -e ".[dev]"`, uv dans ~/.local/bin)
  (recréer le .venv si le dossier du projet a été déplacé : ses chemins sont absolus)
- Comptes : sur l'écran de connexion (« Créer un compte »), ou
  cd backend && .venv/bin/python -m app.auth add-user <nom> | passwd <nom> | list | remove <nom>
  (mot de passe demandé au clavier, 10 caractères minimum ; un nouveau mot de passe ferme les sessions ;
  remove ne supprime pas data/users/<nom>/). Identifiant : 3–32 caractères [a-z0-9._-], en minuscules.
- Données d'avant les comptes (data/raw…) -> un compte : python -m app.workspace adopt <nom> (fait pour jules)
- python -m app.ingest <fichier|dossier|archive_strava_dézippée>
- pytest
- API : cd backend && uvicorn app.api:app --reload  (port 8000, lit data/raw, cache data/cache/)
- Front : cd frontend && npm install && npm run dev  (http://localhost:5173/app/, proxy /api et /dl -> 8000)
  Vite 8 demande Node >= 20 ; si le Node système est trop vieux : Node LTS dans ~/.local/node
  et `export PATH=~/.local/node/bin:$PATH`
- Production (voir SELF-HOST.md) : `./deploy-local.sh` (pull, dépendances, build, tests, redémarrage du
  service systemd `trailmap`) ; `journalctl -u trailmap -f` ; `sudo systemctl stop trailmap` avant le mode dev
  (même port 8000). Tailscale vise alors `http://localhost:8000` (pas 127.0.0.1 pour Vite : IPv6 seulement).
- Accès depuis le téléphone (Tailscale) : https://jules-laptop.tailf52fab.ts.net
  - En dev, côté Windows, dans PowerShell : `tailscale serve --bg 5173` (relaie le tailnet en HTTPS vers Vite ;
    `tailscale serve status` pour vérifier, `tailscale serve --https=443 off` pour arrêter)
  - Vite n'accepte que les hôtes `.ts.net` en plus de localhost (`allowedHosts` dans vite.config.ts,
    jamais `allowedHosts: true`) ; le front n'appelle que des chemins relatifs /api, relayés au backend.
  - En HTTPS, la géolocalisation fonctionne aussi sur le téléphone.
  - ⚠️ Ne JAMAIS utiliser `tailscale funnel` : il rendrait l'app (et les traces) publique sur Internet.
- Tuiles OSM hors-ligne (France, extrait 5,1 Go -> 7,5 Go de tuiles, ~30 min, 940 Go libres ;
  à rafraîchir de temps en temps avec --force) :
  curl -L -o data/osm/france-latest.osm.pbf https://download.geofabrik.de/europe/france-latest.osm.pbf
  curl -L -o data/osm/france.poly https://download.geofabrik.de/europe/france.poly
  cd backend && python -m app.routing.extract ../data/osm/france-latest.osm.pbf ../data/osm/france.poly [--force]
  puis redémarrer l'API (graphes en mémoire). Une seule région : même commande avec son extrait et son .poly.
- docker compose up -d db  (PostGIS, pas encore utilisé par l'API)

## Données
- data/users/<nom>/ : tout ce qui appartient à un compte (personne d'autre n'y accède) :
  - raw/strava/ : export Strava dézippé (activities.csv + activities/) ; raw/strava-export.zip : dernière
    archive envoyée ; raw/uploads/ : fichiers ajoutés depuis la page ; raw/*.fit : exports Coros
    (jules : archive d'origine raw/export_124148223.zip + 18 .fit)
  - cache/ : sorties prétraitées ; routes/ : itinéraires générés (GPX) ; ratings.json : évaluations
    (à sauvegarder !) ; privacy.json : zones de confidentialité (optionnel)
- data/auth/ : comptes (users.json, mots de passe hachés) et sessions (sessions.json), droits 600
- data/osm/ : tuiles OSM (cache, communes), data/dem/ : tuiles d'altitude (communes)
- Types importés : course, trail, randonnée (sport normalisé run / trail_run / hike)
