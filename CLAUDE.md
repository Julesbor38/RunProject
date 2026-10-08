# Trail Map — contexte projet

App qui recense les chemins courus (trail / course à pied / randonnée), permet de les noter
(plaisir, sécurité, éclairage, entretien, abri, fréquentation, circulation)
et génère des itinéraires selon ces critères. D'abord perso, puis communautaire.

**Journal chronologique et prochaines tâches : voir `ROADMAP.md`.**
À chaque fin de session de travail : mettre à jour `ROADMAP.md` (ce qui a été fait, état,
prochaines étapes) et la section « État actuel » ci-dessous, puis committer et pousser.

## État actuel (2026-10-08)
- Étape 1 (import) : fonctionnelle. 254 activités (course, trail, randonnée), doublons Strava/Coros fusionnés.
  Reste : 3 .fit.gz Strava illisibles (`developer_data_index 0 not defined`).
- Téléphone : le panneau du bas se replie d'un glissé vers le bas.
- Carte web : traces distinctes, une par sortie, colorées par type, cliquables dans les deux onglets
  (couche invisible large ; fiche avec « Évaluer cette sortie ») (le rendu « Fréquentation » unifié
  sur les voies OSM a été retiré le 2026-10-07 : trop complexe, voir l'historique git), filtres, fiches, générateur d'itinéraires (boucle / aller simple le plus
  court ou à distance visée), dénivelé (tranche de D+, profil, relief 3D), export GPX,
  téléphone, `src/share.ts` : un bouton générique « Envoyer à ma montre » (pas de marque dans l'interface) → feuille
  de partage (GPX préparé à l'avance, appel synchrone dans le tap, 1er type MIME accepté) → « Enregistrer dans
  Fichiers » → l'app de la montre depuis Fichiers ; secours automatique : lien signé /dl/<id>.gpx hors scope PWA.
  Jamais de navigation de la page de l'app vers un fichier ; aucune app de montre n'est proposée dans la feuille de
  partage web (essayé : « Ouvrir avec COROS » via /dl ne marche pas sur l'iPhone). Debug : ?debug=1 ou appui long sur le titre.
- Front servi sous **/app/** (scope de la PWA ; / redirige vers /app/) : /api et /dl restent hors scope.
- **App iOS native** (Capacitor 8, `frontend/ios/`, « RunProject », com.julesbor38.runproject) compilée sans Mac ni
  signature par GitHub Actions (`.github/workflows/ios.yml`, à la main ou tag v*), installée avec AltStore
  (IOS-ALTSTORE.md). Adresse du serveur tapée au 1er lancement ; session par jeton Bearer ; GPX écrit en vrai
  fichier (Filesystem) puis menu « Ouvrir avec… » d'iOS (plugin maison OpenWith, celui de l'app Fichiers où les
  apps de montre apparaissent), feuille de partage (Share) en secours.
- Interface : identité « trail » (logo `frontend/public/logo.svg`, palette forêt / braise, Barlow Condensed),
  icônes SVG, réglages fins repliables, bouton Générer collant, panneau du bas compact sur téléphone,
  icônes d'écran d'accueil + manifest.
- Génération d'itinéraires annulable, avec avancement ; tuiles OSM de **toute la France** en local
  (extrait Geofabrik France, 36 349 tuiles, 7,5 Go) : plus de dépendance à Overpass en France
  (~4 s pour une première génération dans une zone jamais utilisée). Accès téléphone via Tailscale (HTTPS, tailnet).
- Auto-hébergement (`SELF-HOST.md`) **en place** : service systemd `trailmap` (uvicorn 127.0.0.1:8000, front construit
  servi sous /app/), WSL gardé allumé par la tâche Windows « WSL keep-alive (Trail Map) », alimentation sur secteur
  réglée, `tailscale serve --bg http://localhost:8000`. Mise à jour : `./deploy-local.sh` ; logs :
  `journalctl -u trailmap -f` ; dev : `sudo systemctl stop trailmap` d'abord (même port 8000).
- **Exploration** (`app/explore/`, `src/explore.ts`, onglet « Exploration ») : map-matching des sorties horodatées
  sur les tronçons OSM praticables (arêtes du graphe, ≤ 20 m, direction, 80 % couverts, trottoirs ignorés,
  portions à plus de 25 km/h et zones de confidentialité exclus), stocké par compte dans data/explore/explore.sqlite, calcul
  incrémental en arrière-plan (démarrage + après import ; `TRAILMAP_EXPLORE=0` pour le couper) ; par commune
  (OSM admin_level=8, 34 770 extraites) : % de la **superficie** découverte (bande de 50 m de chaque côté des
  passages, cellules de ~10 m, `area.py`) et % des chemins ; lieux découverts (≤ 30 m), paliers 10–90 % des chemins
  et badges (annoncés seulement après un import, les rattrapages sont silencieux), mode « Brouillard » (voile
  percé sur la superficie découverte, contours arrondis, chemins courus en jaune au zoom ≥ 13), suggestions de zones jamais courues -> générateur en
  mode Découverte. Tables prêtes pour un classement (opt-in désactivé par défaut), rien d'exposé aux autres.
- **Familiers** (`app/game/`, `src/pet.ts`, `src/pet-art.ts`, onglet « Familier », README dans `app/game/README.md`) :
  les 3 starters adoptables (Montagne / Vitesse / Endurance, triangle d'efficacité ; chacun une fois, gratuit, ils
  évoluent chacun de leur côté ; sélecteur en haut de l'onglet), niveaux **achetés avec
  des points** (appui sur l'image ; coût `ceil(0,5 × n^1,5)`) jusqu'au niveau max du stade (œuf 5, bébé 15,
  jeune 35, adulte 60, finale 100), puis évolution payante (50 / 250 / 1 000 / 3 000) ; forme finale à 2 branches
  selon le profil de course (D+, nuit, sorties longues, rapides, chemins nouveaux ; `app/explore/profile.py`).
  Config en TOML (`app/game/config/`), base `data/game/game.sqlite` (migrations numérotées, `PRAGMA user_version`).
  **Portefeuille** (`app/game/wallet.py`) : points et gemmes, soldes mis à jour dans la même transaction que le
  journal (`BEGIN IMMEDIATE`, dépense refusée si le solde ne couvre pas : pas de double dépense), clé unique par
  ligne. Les crédits d'explore.sqlite y ont été déplacés (une fois, `credits.adopt_legacy`).
  **Boutique** (`app/game/shop.py`, `config/shop.toml`, sous-onglet « Boutique » du Familier) : 5 familiers rares
  (Colossaure rare 360, Tempestor / Sylvarion épiques 390, Brasaltor / Aurorelle légendaires 420 de stats de base,
  3–4 capacités chacun ; 3 000 / 6 000 / 10 000 points ou 300 / 600 / 1 000 gemmes), achat déterministe, une fois
  par compte ; capacités (`[[species.ability]]`) pour tous, débloquées par stade, affichées (serviront aux duels) ;
  gemmes : `payments.py` (`PaymentProvider`, factice avec `TRAILMAP_PAYMENTS=mock`, sinon 503).
  **Combats contre des bots** (`app/game/combat.py`, `battles.py`, `config/moves.toml`, `config/battles.toml`,
  `src/battle.ts`, sous-onglet « Combats ») : tour par tour, je choisis l'attaque (et la cible), le serveur résout
  (graine enregistrée, rejouable) ; kit par type (2 attaques + 1 défense, une animation chacune : Éboulement,
  Racines…) + capacités spéciales ; sentier de niveaux (mobs seuls ou en groupe, boss tous les 5, grand boss tous
  les 10 avec rage et renforts) ; victoire : points (première fois 20 + 4 × niveau, × 3 / × 5 boss, rejouer 25 %,
  10 par jour).
  **Amis et combats amicaux en direct** (`app/game/friends.py`, `pvp.py`, `src/friends.ts`, sous-onglet « Amis ») :
  demande par identifiant, acceptée ou refusée, retrait, blocage (sans dire qui a bloqué) ; un ami ne voit que
  l'identifiant, les familiers et le bilan, **jamais** les sorties, traces, communes ni le solde. Défi (5 min) en
  mode normal ou équilibré (adulte niveau 50 pour les deux) ; chacun choisit son coup, le tour se résout quand les
  deux ont joué ou au bout de 30 s (l'IA joue pour l'absent, 2 tours manqués = défaite) ; pas de points, un bilan ;
  le front interroge toutes les 6 s (toast « X te défie ») et 1,2 s pendant le combat.
  Prochaine étape : brancher un vrai paiement (App Store / Stripe).
- **Points** (anciennement « crédits » ; `app/explore/credits.py`, `src/credits.ts`) : **gains** en place — 1/km couru, +2/km de chemin
  nouveau, 10/km², lieux 1–10, paliers de commune 10–100, 25/badge ; journal par compte (table `credits`, clé unique,
  jamais payé deux fois) ; l'historique d'avant les crédits ne compte que dans un bonus de bienvenue plafonné à 500 ;
  **2 000 / mois** au plus gagnés en courant (mois de la sortie) ; générer un itinéraire est **gratuit** (le coût de
  1 point / km a été retiré le 2026-10-08 : `ROUTE_CREDITS = False`) ; solde « ✦ N » dans l'en-tête, section
  « Crédits » dans Exploration, annonce « +N crédits ». **Suite : la collection** (tâche 1 de ROADMAP.md, plan à
  valider d'abord). Ensuite : notation des tronçons (étape 3).
- **Lieux notables** (`app/pois/`, `src/pois.ts`) : extraits de l'extrait OSM France dans data/pois/pois.sqlite
  (commun à tous), Overpass hors de France, Wikidata (photo créditée) ; fiche + « Passer par ici » (points de
  passage du générateur, 3 max) ; lieux à ~50 m listés sous chaque itinéraire.
- Dénivelé : « Le plus plat » minimise le D+ (grande boucle, pétales de 2–5 km ou aller-retour, `flat: true`) ;
  Vallonné / Montagne / Personnalisé gardent une tranche de D+.
- Comptes : connexion obligatoire (identifiant + mot de passe) pour toute l'API sauf /api/health ;
  création de compte sur l'écran de connexion (désactivable : TRAILMAP_SIGNUP=0) ou en ligne de commande.
  **Chaque compte n'a accès qu'à ses propres données** (data/users/<nom>/) ; mise en commun plus tard.
- « Mes sorties » : « Mettre à jour mes données » (nouvelle archive Strava .zip ou fichiers .fit/.gpx/.tcx,
  import en arrière-plan, bandeau des nouvelles sorties) ; évaluation de chaque sortie de 1 à 5 sur
  8 critères (sécurité, éclairage, beauté du paysage, plaisir, entretien, abri, tranquillité,
  peu de circulation) + commentaire, en attendant de les reporter sur les tronçons (étape 3).
- Tests : 152 OK, 1 ignoré.

## Architecture
- backend/ : Python 3.12, FastAPI (`app/api.py`), PostgreSQL + PostGIS prévu (docker-compose, pas encore utilisé)
  - `app/ingest/` : parsers (FIT/GPX/TCX, archive Strava), clean, dedup, privacy, simplify, pipeline
  - `app/routing/` : moteur d'itinéraires Python (en attendant GraphHopper)
  - `app/explore/` : matching (map-matching, `explorable`, `segment_key`), area (bande de 50 m sur grille
    de ~10 m, point dans polygone vectorisé), store (SQLite), communes
    (extraction + total praticable), explorer (traitement incrémental, résumé, paliers, suggestions)
  - `app/game/` : config (TOML), db (migrations), wallet, pets, service (vues JSON), balance (courbes)
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
  - `main.ts`, `share.ts` (GPX sur téléphone : partage, repli /dl ; app native : Filesystem + Share),
    `native.ts` (app native : adresse du serveur, jeton de session, `apiUrl()`), `debug.ts` (panneau de debug),
    `auth.ts` (écran de connexion), `importer.ts` (mise à jour des données), `ratings.ts`
    (fiche d'évaluation), `activities.ts` (onglet Mes sorties), `explore.ts` (onglet Exploration, brouillard), `planner.ts` (onglet Itinéraire),
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
Toutes les routes exigent une session (cookie, ou `Authorization: Bearer <jeton>` pour l'app native), sauf
/api/health et /api/auth/login|logout|signup|options. CORS : seulement capacitor://localhost (app native) et Vite.
Connexion / création de compte avec `token: true` : le jeton est renvoyé (app native).
Chaque route ne lit et n'écrit que les données du compte connecté (data/users/<nom>/).
- POST /api/auth/login {username, password}, POST /api/auth/signup (même corps : crée le compte et connecte),
  GET /api/auth/options ({signup}), POST /api/auth/logout, GET /api/auth/me
- POST /api/import (multipart `files`) : archive Strava .zip et/ou .fit/.gpx/.tcx, puis réimport en arrière-plan ;
  GET /api/import/status : running / done (`new` : clés des sorties ajoutées) / error
- GET /api/ratings : critères + évaluations de l'utilisateur ; PUT|DELETE /api/ratings/{key}
  ({scores: {critère: 1..5}, comment}) ; `key` = clé stable de la sortie (`strava:<id>` ou `file:<nom>`)
- GET  /api/health : état (comptes chargés, générations en cours, front construit), rien sur les données d'un compte
- GET  /api/pois?bbox=&zoom=&categories= : lieux notables de la zone ; GET /api/pois/<id> : fiche (Wikidata)
- GET  /api/explore : résumé (totaux dont km², communes avec % des chemins et `area_pct` de la superficie, paliers / badges, `new` = franchis non vus, suggestions) ;
  POST /api/explore/seen {ids} ; GET /api/explore/fog?bbox= (tronçons faits / à faire, petite zone sinon 422) ;
  GET /api/explore/communes/{id} : contour (GeoJSON + bbox) ; GET /api/explore/veil?bbox=&zoom= : voile du
  brouillard (monde moins la superficie découverte, ≤ 2 deg²)
- Jeu (`/api/game…`) : GET /api/game (soldes, starter choisi, familiers) ; GET /api/game/starters ;
  POST /api/game/starter {species, name} (chaque starter une fois ; `adopted` dans /starters) ; GET /api/game/pets[/{id}] ; POST …/{id}/activate ;
  PATCH …/{id} {name} ; POST …/{id}/levels {count | "max", request_id} ; POST …/{id}/evolve {request_id}
  (402 points insuffisants, 409 refus, 404 familier d'un autre) ; GET /api/game/wallet ; GET /api/game/transactions ;
  GET /api/game/shop ; POST /api/game/shop/buy {item, currency: points|gems, request_id} ;
  POST /api/game/gems/buy {pack, request_id, receipt?} (503 tant que le paiement n'est pas branché) ;
  GET /api/game/battles (sentier, combat en cours, gains du jour) ; POST /api/game/battles {level} ;
  GET /api/game/battles/{id} ; POST …/{id}/turn {move, target?} (événements à animer + état) ; POST …/{id}/flee ;
  GET /api/game/friends ; POST /api/game/friends {username} ; POST …/friends/{nom}/accept|decline|block ;
  DELETE …/friends/{nom}[/block] ; GET|POST /api/game/pvp ({friend, mode}) ; POST …/pvp/{id}/accept|decline|move|forfeit ;
  GET …/pvp/{id}?since=N (tours à animer, qui a joué, secondes restantes)
- PUT /api/ratings/{key} renvoie aussi `points` (gagnés à la première évaluation de la sortie)
- GET  /api/credits : solde, bonus de bienvenue (`welcome`, `history`, `welcome_cap`), `by_kind`, `new` (gagnés depuis
  la dernière annonce ; POST /api/explore/seen {ids: ["credits"]}), `month` {earned, cap}, derniers mouvements
  (`entries`, dépenses négatives), barème, `running`
- POST /api/routes accepte `via` : [[lon, lat], …] (3 max), points de passage
- GET  /api/activities : traces masquées + simplifiées (~700 Ko), cache data/cache/
- POST /api/reload : relit data/raw
- GET  /api/routing/status : avancement du pré-téléchargement OSM
- POST /api/routes : génère des itinéraires (boucle / aller simple, préférences, tranche de D+ ou `flat: true`) ;
  gratuit (le coût en points, `ROUTE_CREDITS`, est coupé) ;
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
2. [première version : Exploration] Map-matching des traces sur OSM -> tronçons parcourus
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
- App iOS : cd frontend && npm run build:native && npx cap sync ios ; compilation : GitHub Actions « iOS (AltStore) »
  (Run workflow, ou tag v*) ; .ipa dans les Artifacts / la Release ; installation : IOS-ALTSTORE.md
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
- data/pois/pois.sqlite : lieux notables (extraits de l'OSM France, + Overpass hors France, + cache Wikidata)
- data/game/game.sqlite : jeu (portefeuille points / gemmes et journal, familiers) : **à sauvegarder**
- data/explore/explore.sqlite : Exploration (tronçons parcourus et lieux découverts par compte : **à sauvegarder**,
  + contours des communes, recalculables avec `python -m app.explore.communes ../data/osm/france-latest.osm.pbf`)
- data/osm/ : tuiles OSM (cache, communes), data/dem/ : tuiles d'altitude (communes)
- Types importés : course, trail, randonnée (sport normalisé run / trail_run / hike)
