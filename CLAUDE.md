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
- Carte web : traces (rendu « Fréquentation » plus foncé selon le nombre de sorties distinctes,
  ou « Par type »), filtres, fiches, générateur d'itinéraires (boucle / aller simple le plus
  court ou à distance visée), dénivelé (tranche de D+, profil, relief 3D), export GPX,
  bouton « Envoyer vers la montre » (partage du GPX vers l'app COROS, non testé sur téléphone).
- Génération d'itinéraires annulable, avec avancement ; tuiles OSM de Rhône-Alpes en local
  (plus de dépendance à Overpass dans la région).
- Prochaine grosse étape : map-matching (étape 2), puis notation des tronçons (étape 3).
- Tests : 62 OK, 1 ignoré.

## Architecture
- backend/ : Python 3.12, FastAPI (`app/api.py`), PostgreSQL + PostGIS prévu (docker-compose, pas encore utilisé)
  - `app/ingest/` : parsers (FIT/GPX/TCX, archive Strava), clean, dedup, privacy, simplify, pipeline
  - `app/routing/` : moteur d'itinéraires Python (en attendant GraphHopper)
  - `app/frequency.py` : nombre de sorties distinctes par portion de voie OSM (~25–50 m, une sortie
    compte si sa trace suit 75 % de la portion dans le même sens, tolérance 12–24 m), dessiné sur la voie ;
    voies coupées aux carrefours, trottoirs ignorés, choix entre voies parallèles par rue entière,
    trous comblés le long d'une rue, ergots < 60 m retirés, niveau lissé le long de la rue ; repli
    sur la trace là où aucune voie OSM ne l'explique (sauf écarts GPS : courts, en boucle, ou en
    ville) ; extrémités raccordées à < 25 m. Recalculé quand de nouvelles tuiles OSM arrivent
- frontend/ : TypeScript + Vite + MapLibre GL 6 (PWA à venir), fond OpenFreeMap
  - `main.ts`, `activities.ts` (onglet Mes sorties), `planner.ts` (onglet Itinéraire),
    `profile.ts` (profil altimétrique), `terrain.ts` (relief 3D), `api.ts`, `format.ts`
  - Vite ne pré-empaquette pas MapLibre (sinon le worker est perdu et la carte ne charge pas)
- Routage actuel : graphe OSM par tuiles 0,05° en cache dans data/osm/. En Rhône-Alpes, tuiles
  découpées localement depuis l'extrait Geofabrik (`app/routing/extract.py`, seulement les tuiles
  entièrement dans la région) ; ailleurs et en bordure, Overpass (plusieurs instances en secours,
  souvent saturées). Une génération attend jusqu'à 3 min les tuiles du départ et de l'arrivée
  (indispensables), puis 45 s les autres (les plus proches d'abord) et calcule sans celles qui
  manquent ; une tuile en échec n'est pas redemandée avant 5 min. Seules les tuiles à portée
  (bande autour du segment départ-arrivée, disque autour du départ pour une boucle) sont chargées.
  Génération annulable et suivie (`Job` dans `app/routing/job.py`). A* pondéré par les préférences (coûts précalculés par
  génération, `Weights`), boucles en triangle, aller simple à distance visée via un détour sur ellipse.
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
- GET  /api/activities : traces masquées + simplifiées (~700 Ko), cache data/cache/
- GET  /api/frequency : voies OSM (ou traces) parcourues avec leur nombre de passages, cache data/cache/
- POST /api/reload : relit data/raw
- GET  /api/routing/status : avancement du pré-téléchargement OSM
- POST /api/routes : génère des itinéraires (boucle / aller simple, préférences, tranche de D+) ;
  `request_id` optionnel pour suivre / annuler ; `warning` si des tuiles OSM manquent
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
  `strava-export/` = export Strava complet). Le mettre à jour quand data/ change.
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
- python -m app.ingest <fichier|dossier|archive_strava_dézippée>
- pytest
- API : cd backend && uvicorn app.api:app --reload  (port 8000, lit data/raw, cache data/cache/)
- Front : cd frontend && npm install && npm run dev  (http://localhost:5173, proxy /api -> 8000)
  Vite 8 demande Node >= 20 ; si le Node système est trop vieux : Node LTS dans ~/.local/node
  et `export PATH=~/.local/node/bin:$PATH`
- Tuiles OSM hors-ligne (Rhône-Alpes, ~530 Mo, à rafraîchir de temps en temps avec --force) :
  curl -L -o data/osm/rhone-alpes-latest.osm.pbf https://download.geofabrik.de/europe/france/rhone-alpes-latest.osm.pbf
  curl -L -o data/osm/rhone-alpes.poly https://download.geofabrik.de/europe/france/rhone-alpes.poly
  cd backend && python -m app.routing.extract ../data/osm/rhone-alpes-latest.osm.pbf ../data/osm/rhone-alpes.poly [--force]
  puis redémarrer l'API (graphes en mémoire)
- docker compose up -d db  (PostGIS, pas encore utilisé par l'API)

## Données
- data/raw/strava/ : export Strava dézippé (activities.csv + activities/), archive d'origine data/raw/export_124148223.zip
- data/raw/*.fit : exports Coros (18 fichiers)
- data/privacy.json : zones de confidentialité (optionnel)
- data/osm/ : tuiles OSM (cache), data/dem/ : tuiles d'altitude, data/cache/ : activités prétraitées
- Types importés : course, trail, randonnée (sport normalisé run / trail_run / hike)
