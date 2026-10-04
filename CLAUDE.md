# Trail Map — contexte projet

App qui recense les chemins courus (trail / course à pied), permet de les noter
(plaisir, sécurité, éclairage, entretien, abri, fréquentation, circulation)
et génère des itinéraires selon ces critères. D'abord perso, puis communautaire.

## Architecture cible
- backend/ : Python 3.12, FastAPI, PostgreSQL + PostGIS (docker-compose)
- frontend/ : TypeScript + Vite + MapLibre GL (PWA à venir), fond OpenFreeMap
- routage + map-matching : GraphHopper auto-hébergé (Docker) — étape 2
- En attendant Docker : moteur Python dans backend/app/routing/ (graphe OSM via Overpass,
  tuiles 0,05° en cache dans data/osm/, A* pondéré par les préférences, boucles en triangle).
  Critères dérivés des tags OSM (nature, circulation, éclairage estimé, escaliers)
  + "déjà couru" calculé depuis les traces de l'utilisateur.
  Tuiles OSM pré-téléchargées en arrière-plan autour des zones courues (GET /api/routing/status),
  plusieurs instances Overpass en secours.
- Altitude : tuiles DEM Terrarium (AWS, ~±3 m vs IGN RGE ALTI autour de Lyon), z13, cache data/dem/.
  Sert au D+/D- par tronçon et sens, à la tranche de D+ visée (boucles) et au relief 3D du front.
- Les notes sont attachées à des tronçons OSM (après map-matching), pas aux traces brutes.

## Étapes
1. [en cours] Import des activités (export Strava + .fit Coros) -> traces normalisées
2. Map-matching des traces sur OSM -> tronçons parcourus
3. Interface de notation des tronçons
4. Itinéraires pondérés par les notes (custom model GraphHopper)
   [prototype en place : boucles / aller simple selon critères OSM, sans les notes]
5. Communautaire : comptes, agrégation, modération, zones de confidentialité

## Règles
- Données de l'utilisateur dans data/ (ignoré par git). Ne jamais committer de traces.
- Ne PAS utiliser l'API Strava comme source pour la version communautaire
  (CGU depuis nov. 2024 : affichage limité au seul utilisateur, pas d'usage IA).
  Source = export d'archive Strava / fichiers importés par l'utilisateur.
- Prévoir dès le départ le masquage début/fin de trace (zones de confidentialité).
- Code et commentaires en anglais, échanges en français.
- Tests : pytest dans backend/tests.

## Commandes
- cd backend && pip install -e ".[dev]"
- python -m app.ingest <fichier|dossier|archive_strava_dézippée>
- pytest
- API : cd backend && uvicorn app.api:app --reload  (port 8000, lit data/raw, cache data/cache/)
- Front : cd frontend && npm install && npm run dev  (http://localhost:5173, proxy /api -> 8000)
- docker compose up -d db  (PostGIS, pas encore utilisé par l'API)

## Données
- data/raw/strava/ : export Strava dézippé (activities.csv + activities/)
- data/raw/*.fit : exports Coros
- data/privacy.json : zones de confidentialité (optionnel)
- data/osm/ : tuiles OSM téléchargées (cache), data/dem/ : tuiles d'altitude, data/cache/ : activités prétraitées
- Types importés : course, trail, randonnée (sport normalisé run / trail_run / hike)
