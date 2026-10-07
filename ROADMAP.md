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

### 2026-10-04 — Nouveau PC, calcul plus rapide, aller simple avec distance, envoi vers la montre
- Installation sur un nouveau PC : `data/` restauré depuis Run-Project-Data, `.venv` recréé.
  Node 12 du système trop ancien pour Vite 8 → Node 24 LTS installé dans `~/.local/node`
  (`export PATH=~/.local/node/bin:$PATH` avant `npm`).
- Lenteur signalée à Tassin avec « déjà couru » au max : ce curseur n'en était pas la cause.
  L'attente venait des tuiles OSM pas encore téléchargées et du calcul A* en Python.
  - Coût des tronçons précalculé une fois par génération (`Weights` : adjacence pondérée,
    heuristique A* = plus petit coût au mètre du graphe).
  - Grille de 200 m pour `nearest_node` (avant : parcours de tous les nœuds).
  - Résultats identiques, 2 à 3× plus rapide : 20 km + tranche de D+ passe de 15 s à 7 s,
    10 km de 3,3 s à 1,2 s.
  - Petit changement : la pénalité de réutilisation s'applique après le bonus de montée.
- Aller simple : choix « Le plus court » ou « Distance visée » (+ tranche de D+).
  Détour par un point placé sur une ellipse dont A et B sont les foyers (8 angles, taille corrigée
  une fois), même score que les boucles, jusqu'à 3 propositions. Si la distance visée est plus
  courte que le trajet direct, on renvoie le direct avec un message.
  Exemple Tassin → Fourvière (direct 4,2 km) : 12 km visés → 11,9 / 12,9 / 11,9 km, tous dans la tranche.
- Bouton « ⌚ Envoyer vers la montre » : menu de partage du système avec le GPX (Web Share API),
  pour l'ouvrir dans l'app COROS. Affiché seulement si le navigateur sait partager un .gpx
  et en contexte sécurisé (HTTPS ou localhost). Pas encore testé sur téléphone.
  L'API COROS est réservée aux partenaires, pas d'app COROS pour ordinateur.
- 31 tests OK, 1 ignoré.

### 2026-10-04 — Carte « Mes sorties » : rendu par fréquentation
- Les traces superposées devenaient illisibles là où je cours souvent. Nouveau mode « Fréquentation »
  (par défaut) : chaque chemin est plus foncé et plus épais selon le nombre de sorties distinctes
  passées dessus (7 niveaux : 1, 2, 3–4, 5–9, 10–19, 20–49, 50+), avec une légende sur la carte.
  Sélecteur « Fréquentation / Par type » pour revenir à l'affichage par sport.
- Backend `app/frequency.py`, sans map-matching : grille de cellules de 12 m. Chaque sortie compte
  une fois par cellule (aller-retour = 1 passage), et ses cellules sont élargies aux 8 voisines
  pour absorber le GPS (deux passages décalés de ~10 m s'additionnent). Les traces masquées de
  `/api/activities` sont redécoupées en tronçons de niveau constant (médiane glissante de ~60–125 m
  pour qu'un croisement ne fasse pas de tache sombre).
- `GET /api/frequency`, cache `data/cache/frequency.geojson` (1,3 Mo, 1,3 s de calcul),
  recalculé quand le cache des activités change ou quand les réglages de l'algorithme changent.
  Maximum actuel : 54 sorties au même endroit.
- Le calque par sport reste au-dessus (transparent) : survol, clic et fiche de sortie inchangés.
- 40 tests OK, 1 ignoré (9 nouveaux pour le comptage et le cache).

### 2026-10-04 — Fréquentation : un seul trait par chemin
- Les légers décalages GPS laissaient plusieurs traits côte à côte sur un même passage (effet gribouillage).
- Le réseau dessiné est construit une seule fois : les traces sont posées des plus représentatives
  (le long des chemins les plus fréquentés) aux autres, et on ne garde d'une trace que ce qui est
  à plus de ~30 m de ce qui est déjà dessiné. Ce réseau est ensuite découpé par niveau de passages.
  Un aller-retour n'est dessiné qu'une fois ; un croisement ne coupe pas le trait ; un petit écart
  GPS (< ~60 m de long) n'est pas dessiné ; les bifurcations sont raccordées au trait existant.
- Filtres par sport : chaque tronçon indique les sports passés par là (affiché si l'un est coché).
- Résultat sur les vraies données : 817 tronçons, 0,3 Mo (contre 3 950 et 1,3 Mo), 2,7 s de calcul.
- 42 tests OK, 1 ignoré.

### 2026-10-04 — Fréquentation dessinée sur les rues et chemins OSM
- Le tracé « une trace par chemin » laissait de grandes coupures et ne suivait pas les rues.
  Le trait est maintenant la rue / le chemin OpenStreetMap lui-même (tuiles déjà en cache pour le routage) :
  - les voies OSM sont découpées en portions de ~25–50 m ; une sortie compte un passage sur une
    portion si sa trace (tolérance 12–24 m) en suit au moins 60 % (la croiser ne compte pas) ;
  - trottoirs et passages piétons cartographiés à part (`footway=sidewalk/crossing`) ignorés :
    la route porte le trait ;
  - dédoublonnage seulement entre voies **parallèles** à moins de ~20 m (on garde celle où tombent
    les points GPS) ; les rues qui se croisent ne se masquent jamais ; les deux chaussées d'une
    même avenue sont toutes deux dessinées ;
  - petite portion sans passage au milieu d'une rue fréquentée comblée ; débuts de rues
    adjacentes (« moustaches ») retirés ;
  - là où aucune voie OSM n'explique la trace (zone pas encore téléchargée, chemin absent d'OSM),
    la trace elle-même est dessinée, une fois par chemin.
- Recalcul automatique quand de nouvelles tuiles OSM arrivent (fin du pré-téléchargement, et au
  démarrage si la liste des tuiles a changé). 5–6 s de calcul, ~1,2 Mo.
- Traits plus larges aux zooms rapprochés pour couvrir la largeur de la rue.
- 47 tests OK, 1 ignoré (5 nouveaux sur le dessin OSM).

### 2026-10-04 — Fréquentation : traits continus et lissés
- Il restait des pointillés et des coupures sur la plupart des parcours fréquentés, et l'épaisseur
  changeait tous les 50 m. Diagnostic chiffré (extrémités de traits qui s'arrêtent près d'un autre) :
  2 388 coupures au départ, surtout des portions de rue masquées à tort comme « doublon parallèle »
  par la portion voisine de la même rue.
- L'étape OSM raisonne maintenant sur le réseau :
  - voies coupées à chaque carrefour ; portions de 25–50 m dessinées entières ou pas du tout ;
  - choix entre voies parallèles fait sur toute la rue (pas portion par portion), jamais contre les
    portions reliées à moins de 40 m, ni pour les bouts de moins de 24 m ;
  - trous comblés le long d'une rue (jusqu'à 150 m, en suivant la rue d'une voie OSM à l'autre) ;
  - branches de moins de 60 m jusqu'au premier carrefour retirées (ergots aux carrefours) ;
  - niveau affiché = médiane sur 150 m de part et d'autre, puis une section de moins de 200 m à un
    autre niveau que ses voisines prend le leur : couleur et épaisseur stables le long d'une rue ;
  - passages piétons (`footway=crossing`) de nouveau pris en compte : ils relient un chemin de part et
    d'autre d'une route (seuls les trottoirs sont ignorés).
- Résultat : 253 coupures (contre 2 388), 560 km dessinés sur les rues (contre 397), 88 km d'après les
  traces (surtout des zones dont les tuiles OSM ne sont pas encore téléchargées). ~9 s de calcul.
- 50 tests OK, 1 ignoré.

### 2026-10-04 — Fréquentation : lignes complètes, plus de gribouillage
- Il restait des coupures, des rues jamais courues dessinées (barreaux entre deux rues parallèles
  courues, ex. Vaise) et des traits GPS hors des rues. Mesuré puis corrigé jusqu'à disparition :
  - **direction** : une sortie ne compte sur une portion de voie que si sa trace y va dans le même
    sens (±34°) ; une rue perpendiculaire près d'un carrefour ne compte plus (cause des barreaux) ;
  - **traces hors OSM** : là où OSM est connu, un morceau de trace sans voie correspondante n'est
    dessiné que s'il fait ≥ 300 m, ne revient pas près de son départ (< 800 m) et passe surtout à
    plus de ~30 m de toute voie (vrai sentier non cartographié) ; sinon c'est une erreur GPS ;
  - **culs-de-sac peu utilisés** (< 200 m, 4 fois moins fréquentés que la rue qu'ils quittent) retirés ;
  - **raccords** : une extrémité de trait qui s'arrête à moins de 25 m d'un autre trait y est reliée ;
    comblement des trous aussi à travers le réseau (virages), pas seulement en ligne droite ;
  - **toutes les zones traversées** par une trace sont maintenant pré-téléchargées (avant : seulement
    celles courues 2 fois ou plus ; 15 zones manquaient pour toujours).
- Résultat : 33 coupures (2 388 au départ), 541 km dessinés sur les rues, 74 km d'après les traces
  (presque tous dans des zones OSM pas encore téléchargées, qui basculeront sur les rues).
- Essayé puis retiré : suppression des petites boucles redondantes (ouvrait des coupures sur de vraies rues).
- 53 tests OK, 1 ignoré.

### 2026-10-07 — Itinéraires : annulation, Overpass en panne, tuiles OSM hors-ligne
- Installation sur ce PC : sans le paquet `python3-venv` (sudo), venv créé avec `uv` (`~/.local/bin`) ;
  Node 24 LTS dans `~/.local/node` ; `data/` restauré depuis Run-Project-Data.
- Aller simple à distance visée qui « mouline » (ex. Tassin → Fourvière 30 km) : le calcul ne prend
  que quelques secondes, l'attente venait d'Overpass (> 100 s par zone, 504, jusqu'à ~12 min de
  tentatives par zone, et une zone en échec faisait tout échouer).
  - Bouton « ✕ Annuler le calcul » (et Échap) : le serveur s'arrête en moins d'une seconde
    (`Job`, `POST /api/routes/{id}/cancel`).
  - Avancement affiché (`GET /api/routes/{id}/progress`) : zones du départ/arrivée, autres zones x/y,
    préparation du réseau, essais x/16.
  - Zones du départ et de l'arrivée téléchargées d'abord (jusqu'à 3 min, indispensables), puis les
    autres, les plus proches d'abord, 45 s au plus ; on calcule sans celles qui manquent (message),
    elles finissent en arrière-plan. Une zone en échec n'est pas redemandée avant 5 min.
  - Seules les zones à portée sont chargées (bande autour du segment A–B, disque pour une boucle) :
    30 km depuis Tassin, 9 zones à télécharger au lieu de 15.
  - Tassin → Fourvière 30 km : 1 min 08 la première fois avec Overpass saturé (> 4 min et souvent
    un échec avant), 36 s graphe à reconstruire, 6 s ensuite.
- Overpass entièrement en panne (tous les serveurs en 504 / sans réponse) : impossible de partir loin
  de chez soi. → **Tuiles OSM hors-ligne pour Rhône-Alpes** : extrait Geofabrik (530 Mo) découpé par
  `python -m app.routing.extract` (pyosmium) au même format que les tuiles Overpass, seulement les
  zones entièrement dans la région (les bords restent à Overpass). 1 859 zones en 1 min 42,
  1,3 Go de mémoire ; > 99,8 % de chemins en commun avec Overpass. Annecy boucle 15 km : 6,5 s ;
  Grenoble aller simple 25 km : 17 s, sans Overpass.
- `backend/Run-Project-Data/` (clone du dépôt privé) ajouté au `.gitignore`.
- 62 tests OK, 1 ignoré.

### 2026-10-07 — Accès depuis le téléphone via Tailscale
- Vite accepte les hôtes `.ts.net` (`allowedHosts`, pas `true`) ; `tailscale serve --bg 5173` côté
  Windows sert l'app en HTTPS sur https://jules-laptop.tailf52fab.ts.net, sur le tailnet seulement.
- Vérifié en simulant l'hôte .ts.net : page, `/api` et génération d'itinéraire OK, autre hôte refusé (403).
  Le front n'appelle que des chemins relatifs `/api` (pas de cookies, pas d'URL localhost).
- HTTPS : géolocalisation et « Envoyer vers la montre » deviennent testables sur le téléphone.
- Ne jamais utiliser `tailscale funnel` (rendrait l'app publique).

### 2026-10-07 — Auto-hébergement sur le PC de la maison
- Mode production sur un seul port : `npm run build` puis FastAPI sert `frontend/dist` (fichiers +
  `index.html` pour toute autre page hors `/api` ; une route `/api` inconnue reste un 404 JSON).
  Assets Vite en cache longue durée, `index.html` en `no-cache`. Mode dev inchangé (Vite 5173 + `--reload`).
- Correctif build : MapLibre cherchait son worker à côté du bundle, absent de `dist/` (la carte serait restée
  vide) → worker empaqueté par Vite (`?worker&url`) et `setWorkerUrl` en production.
- `GET|HEAD /api/health` : activités chargées, erreurs d'import, fréquentation, état du routage, front présent.
- Service systemd `trailmap` (`deploy/trailmap.service.in`, installé par `deploy/install-service.sh`) :
  uvicorn sans `--reload` sur `127.0.0.1:8000`, `Restart=always`, logs dans journald.
  Vérifié : depuis Windows, `localhost:8000` et `127.0.0.1:8000` atteignent un uvicorn lié à 127.0.0.1
  dans WSL (mode `nat`) ; Vite (IPv6) seulement `localhost`.
- `deploy-local.sh` : pull, dépendances, build du front, tests, redémarrage, attente de `/api/health`.
- `SELF-HOST.md` : tâche planifiée Windows qui garde WSL allumé (`conhost --headless wsl ... sleep infinity`),
  Tailscale vers `http://localhost:8000`, jamais `funnel`, alimentation (capot fermé = rien), vérifications,
  transposition sur un VPS.
- 65 tests OK, 1 ignoré.

---

## État au 2026-10-07
- Tuiles OSM : toute la région Rhône-Alpes en local (extrait Geofabrik du 2026-10-07, à rafraîchir
  avec `--force`) ; Overpass seulement en bordure et hors région, souvent saturé.
- Auto-hébergement prêt côté code (service systemd, `deploy-local.sh`, `SELF-HOST.md`). Côté Windows à faire
  à la main : tâche planifiée « WSL keep-alive », `tailscale serve --bg http://localhost:8000`, alimentation.
- Rien n'utilise encore PostGIS ni GraphHopper.

## Prochaines tâches
1. **Corriger les 3 .fit.gz illisibles** (`10708302692`, `10690331142`, `10690331477`) :
   erreur `developer_data_index 0 not defined`, assouplir le parseur FIT.
2. **Performances** : ~6 s pour 30 km graphe en mémoire, mais ~20–30 s pour construire un grand
   graphe (beaucoup de zones). Pistes : un seul Dijkstra depuis le départ partagé entre candidats,
   graphe plus compact, ou GraphHopper (qui peut lire le même extrait .osm.pbf).
3. **Fréquentation** : quelques petits détails dans les carrefours complexes (géométrie OSM réelle) ;
   à vérifier quand toutes les zones OSM seront téléchargées. Le comptage par portion de voie OSM
   (avec direction) est une base pour le map-matching de l'étape 2.
4. **Profil altimétrique des sorties passées** dans « Mes sorties » (seul le D+ montre est affiché).
5. **Étape 2 — map-matching** des traces sur les tronçons OSM (GraphHopper en Docker ou moteur Python).
6. **Étape 3 — notation des tronçons** : modèle de données (PostGIS), API, interface de notation.
7. **Étape 4 — itinéraires pondérés par les notes.**
8. **Étape 5 — communautaire** : comptes, agrégation, modération.
9. **Tester sur le téléphone via Tailscale** : bouton « Envoyer vers la montre » (Android accepte-t-il
   le partage d'un .gpx ?), géolocalisation. Puis PWA (installation, hors ligne).
