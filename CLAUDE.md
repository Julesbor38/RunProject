# Trail Map — contexte projet

App qui recense les chemins courus (trail / course à pied), permet de les noter
(plaisir, sécurité, éclairage, entretien, abri, fréquentation, circulation)
et génère des itinéraires selon ces critères. D'abord perso, puis communautaire.

## Architecture cible
- backend/ : Python 3.12, FastAPI, PostgreSQL + PostGIS (docker-compose)
- frontend/ : TypeScript + MapLibre GL (PWA) — pas encore créé
- routage + map-matching : GraphHopper auto-hébergé (Docker) — étape 2
- Les notes sont attachées à des tronçons OSM (après map-matching), pas aux traces brutes.

## Étapes
1. [en cours] Import des activités (export Strava + .fit Coros) -> traces normalisées
2. Map-matching des traces sur OSM -> tronçons parcourus
3. Interface de notation des tronçons
4. Itinéraires pondérés par les notes (custom model GraphHopper)
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
- docker compose up -d db
