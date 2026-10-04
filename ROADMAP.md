# Feuille de route — Trail Map

Journal chronologique de l'avancement (le plus ancien en haut), puis les prochaines tâches.
À compléter à la fin de chaque session de travail.

---

## Journal

### Avant le 2026-10-04 — Démarrage
- Définition du projet : recenser les chemins courus, les noter (plaisir, sécurité, éclairage,
  entretien, abri, fréquentation, circulation), générer des itinéraires selon ces notes.
- Choix d'architecture : FastAPI + PostGIS, front MapLibre, GraphHopper pour le routage.
- Règle sur les données : pas d'API Strava (CGU nov. 2024), source = export d'archive.

### 2026-10-04 — Étape 1 : import des activités
- Commit `346d9ab` « Step 1: activity ingest » : parsers FIT / GPX / TCX, lecture de l'archive Strava,
  modèle d'activité normalisé, commande `python -m app.ingest`.
- Ajout du nettoyage des traces (`clean.py`) : tri chronologique, points (0,0), pics GPS > 12 m/s,
  points à moins de 1 m.
- Fusion des doublons Strava / Coros (`dedup.py`) : départ à moins de 3 min et distance à moins de 10 %
  d'écart ; on garde la trace la plus dense, avec le nom et le type « trail » de Strava.
- Confidentialité (`privacy.py`) : 200 premiers et derniers mètres masqués + zones de `data/privacy.json`.
- Import de l'export Strava réel dans `data/raw/strava/` + 18 .fit Coros :
  246 activités GPS (2 232 km), 14 doublons fusionnés, 3 fichiers en erreur.
- Ajout de la randonnée (`hike`) aux types importés, en plus de course et trail → 254 activités.

### 2026-10-04 — Première carte
- API FastAPI (`app/api.py`) : `/api/activities`, traces masquées et simplifiées (~700 Ko),
  cache `data/cache/` (22 s au premier chargement, instantané ensuite).
- Front Vite + MapLibre : traces colorées par type, totaux, filtre, liste des sorties, fiche au clic.
- Correction : la carte ne chargeait pas (Vite perdait le worker de MapLibre) → MapLibre exclu
  du pré-empaquetage, serveur ouvert sur l'IP du WSL.

### 2026-10-04 — Générateur d'itinéraires
- Moteur Python `app/routing/` : graphe OSM via Overpass, A* pondéré, boucles en triangle.
- Interface refaite : panneau à onglets « Itinéraire » / « Mes sorties », repliable, version mobile.
- Boucle ou aller simple, distance 2–42 km, curseurs d'exigences (nature, circulation, éclairage,
  escaliers, découverte ↔ déjà couru), préréglages, jusqu'à 3 propositions, export GPX.
- Choix du départ : « Placer sur la carte », « Ma position », ou centre de la carte par défaut ;
  carte centrée sur la zone habituelle.

### 2026-10-04 — Lenteur hors ville + dénivelé
- Lenteur à Pollionnay venant du premier téléchargement OSM (Overpass saturé) :
  pré-téléchargement en arrière-plan des 161 zones courues, priorité aux demandes,
  serveurs Overpass de secours, message clair si tous indisponibles.
- Altitude via tuiles DEM Terrarium (~3 m d'écart avec l'IGN).
- Tranche de D+ souhaitée (Plat / Vallonné / Montagne / Personnalisé), badge « hors tranche »,
  D+ / D- / altitudes min-max par itinéraire, profil altimétrique interactif, GPX avec altitude.
- Bouton 3D (relief incliné) + ombrage du relief.
- 28 tests OK.

### 2026-10-04 — Sauvegarde et passage sur un autre PC
- Code poussé sur https://github.com/Julesbor38/RunProject (public), commit `6e3c87b`.
- Données (export Strava complet + `data/`) poussées sur le dépôt privé
  https://github.com/Julesbor38/Run-Project-Data.
- `CLAUDE.md` mis à jour, création de cette feuille de route.

---

## État au 2026-10-04
- Pré-téléchargement OSM : ~54 / 161 zones en cache (il reprend au lancement de l'API).
- Rien n'utilise encore PostGIS ni GraphHopper.

## Prochaines tâches
1. **Corriger les 3 .fit.gz illisibles** (`10708302692`, `10690331142`, `10690331477`) :
   erreur `developer_data_index 0 not defined`, assouplir le parseur FIT.
2. **Performances en ville** : génération avec tranche de D+ en 4–7 s à Tassin (vs ~1 s à Pollionnay).
3. **Profil altimétrique des sorties passées** dans « Mes sorties » (seul le D+ montre est affiché).
4. **Étape 2 — map-matching** des traces sur les tronçons OSM (GraphHopper en Docker ou moteur Python).
5. **Étape 3 — notation des tronçons** : modèle de données (PostGIS), API, interface de notation.
6. **Étape 4 — itinéraires pondérés par les notes.**
7. **Étape 5 — communautaire** : comptes, agrégation, modération.
8. PWA (installation sur téléphone, hors ligne).
