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

### 2026-10-07 — Envoi du GPX vers l'app COROS depuis le téléphone
- Sur iPhone, l'app COROS n'apparaissait pas pour ouvrir le GPX ; il fallait enregistrer le fichier puis
  passer par Fichiers. Causes probables : partage du fichier **avec un titre** (iOS partage alors aussi du
  texte et masque les apps qui n'acceptent qu'un fichier), nom avec accents et espaces, GPX fabriqué
  dans le navigateur.
- GPX produit par le backend (`app/gpx.py`) : GPX 1.1 valide (vérifié contre le schéma officiel),
  en-tête XML UTF-8, namespace topografix, `creator`, `metadata`, un `<trk>`/`<trkseg>`/`<trkpt>` avec `<ele>`,
  `<wpt>` nommés possibles. Nom de fichier ASCII sans espaces (`trail-map-boucle-10-0-km.gpx`).
  En-têtes `Content-Type: application/gpx+xml`, `Content-Disposition: attachment; filename="….gpx"`.
- Chaque itinéraire généré reçoit un `route_id` et est gardé dans `data/routes/` (300 derniers) :
  `GET /api/routes/{route_id}/gpx`. `POST /api/routes/gpx` renvoie le GPX d'un itinéraire envoyé par le client.
- Front : « Exporter en GPX » = lien direct vers l'endpoint.
- Testé sur iPhone (page de test, 6 variantes : avec/sans titre, types `application/gpx+xml`, aucun,
  `octet-stream`, `text/xml`, `application/xml`) : **COROS n'apparaît jamais** dans la feuille de partage
  d'une page web (`navigator.share`). Confirmé par le support COROS : l'import passe par l'app Fichiers
  (Partager → COROS). Pas d'API ni de lien profond public pour ouvrir COROS avec un parcours.
  → « ⌚ Envoyer vers la montre » (téléphone) télécharge directement le .gpx depuis l'endpoint et rappelle
  la suite : Fichiers → Téléchargements → Partager → COROS. Web Share API abandonnée.
  Piste pour un vrai « un clic » : passer par un service que COROS synchronise (Komoot, Ride with GPS…),
  à étudier (API, CGU).
- 69 tests OK, 1 ignoré (4 nouveaux sur le GPX : structure, nom de fichier, en-têtes, itinéraires gardés).

### 2026-10-07 — Interface : identité « trail » et logo
- Logo (`frontend/public/logo.svg`) : sentier en lacets jusqu'au sommet, soleil couchant, fond vert forêt ;
  favicon, icône d'écran d'accueil iOS (`apple-touch-icon.png`), icônes 192/512 et `manifest.webmanifest`
  (nom, couleurs) pour « Ajouter à l'écran d'accueil ».
- Palette forêt / sable avec un orange « braise » pour l'action principale ; titres en Barlow Condensed
  (paquet `@fontsource`, servi par l'app, pas de Google Fonts). En-tête vert foncé avec courbes de niveau.
- Icônes SVG à la place des emojis (affichage identique partout), boutons et onglets uniformisés,
  interrupteur « Afficher mes traces », réglages fins (curseurs) repliés sous « Réglages fins ».
- Bouton « Générer » toujours accessible en bas de l'onglet (collant) pendant qu'on fait défiler les réglages.
- Cartes d'itinéraire : pastille de couleur avec la lettre, distance en grand, D+ / D- / altitudes en étiquettes,
  boutons « GPX » et « Envoyer vers la montre ».
- Téléphone : panneau du bas plus haut (64 %), poignée, en-tête et pied compacts (avancement OSM sur une ligne),
  légende « Passages » en haut à gauche (plus coupée par le panneau), crédits de la carte repliables (ⓘ),
  bouton « Trail Map » pour rouvrir le panneau au-dessus des crédits.
- Vérifié par captures (Chromium headless, vue ordinateur 1280×800 et iPhone 390×844) : itinéraire,
  résultats, mes sorties, réglages fins, panneau replié ; aucune erreur dans la console.

### 2026-10-07 — « Le plus plat » : boucles en pétales
- Problème : « Plat » donnait toujours « hors tranche » (10 km depuis la maison : 112–129 m de D+ pour une
  tranche 0–120 m ; Méribel : 330–420 m). Diagnostic :
  - le modèle d'altitude ne gonfle pas le D+ (sur 139 sorties réelles, il mesure ~0,7× le D+ enregistré) ;
  - les vraies sorties plates depuis la maison étaient des tours de piste (8 km sur 0,7 km de chemins distincts) ;
  - le générateur cherchait une seule grande boucle en triangle, qui doit sortir du plateau, et sa variante
    « pour élargir le choix » relâchait la préférence plat (plus vallonnée).
- « Plat » devient **« Le plus plat »** : plus de tranche, le serveur minimise le D+ (`router.flattest`,
  `POST /api/routes` avec `flat: true`) :
  - une grande boucle, ou 2 à 8 **pétales** de 2 à 5 km (les deux nombres de pétales les plus proches de 3,5 km),
    choisis parmi les petites boucles les plus plates (une même boucle au plus deux fois) ;
  - formes : triangle, triangle étroit et **aller-retour** (retour par un autre chemin s'il existe), utile en
    montagne où le seul terrain plat est un balcon ou un fond de vallée ;
  - montées 40× plus coûteuses que le plat pendant la recherche, classement au D+ par km (puis écart de distance,
    répétitions, préférences) ; aussi pour l'aller simple.
- Résultats depuis la maison : 5 km D+ 13, 8 km D+ 26, 10 km D+ 42, 15 km D+ 60–79 (avant : 30 / 74–107 /
  112–129 / 173–211). Limite théorique calculée (aller-retour au moindre D+) : ~5 m/km ; atteinte.
  Méribel centre : 25–31 m/km, au niveau de la limite théorique (~33 m/km pour 4 km) : le terrain ne permet
  pas mieux depuis ce point.
- Cartes : « N boucles » quand l'itinéraire est fait de pétales, D+ par km en mode « Le plus plat ».
  Tranche impossible (Vallonné / Montagne / Personnalisé) : message « le terrain ne permet pas… » et
  suggestion de « Le plus plat » si les résultats sont trop vallonnés.
- 71 tests OK, 1 ignoré (vallée synthétique : pétales plats là où un triangle doit grimper ; aller simple plat).

### 2026-10-07 — Toute la France hors-ligne
- Premières générations très lentes à Clermont-Ferrand et dans les zones jamais utilisées : hors de
  Rhône-Alpes, les chemins venaient d'Overpass (minutes, ou échec quand il est saturé).
- Extrait Geofabrik **France** (5,1 Go) découpé en tuiles : 34 370 nouvelles tuiles (36 349 en tout),
  10,6 millions de chemins, **7,5 Go** sur le disque, 30 min 36 de calcul.
  `extract.py` garde l'index des nœuds **sur disque** (`sparse_file_array`) au-delà de 1,5 Go d'extrait :
  en mémoire il aurait fallu plus de 10 Go (WSL : 7,6 Go). Test : mêmes tuiles qu'avec l'index en mémoire.
- Résultat (première génération, zone jamais utilisée) : Clermont-Ferrand 10 km en 4,0 s, frontière
  Loire / Puy-de-Dôme 12 km en 3,9 s (plus de trou entre anciennes régions), Bordeaux 8 km en 4,6 s.
- Reste sur Overpass : hors de France (21 zones courues à l'étranger : Croatie, Riviera italienne, Val d'Aoste).
  Overpass refuse actuellement les connexions (aussi depuis Windows) : panne ou blocage de leur côté.
- `data/osm/` ne doit pas aller dans la sauvegarde privée (cache régénérable, trop gros pour GitHub).
- 72 tests OK, 1 ignoré.

### 2026-10-07 — Connexion, mise à jour des données, évaluation des sorties
- **Connexion** : identifiant + mot de passe pour tout le site. Toute route `/api` exige une session (middleware :
  les routes futures sont protégées par défaut), sauf `/api/health` et la connexion. Mots de passe hachés
  (scrypt, sel), jeton de session aléatoire dans un cookie HttpOnly / Secure / SameSite=Strict, seul son
  SHA-256 est stocké, sessions de 30 jours, blocage 15 min après 5 échecs, fichiers en 600.
  Pas d'inscription en ligne : comptes créés en ligne de commande (`python -m app.auth add-user`).
- **Mettre à jour mes données** (onglet Mes sorties) : nouvelle archive Strava (.zip, remplace l'ancienne :
  seuls activities.csv et activities/ sont extraits, chemins vérifiés, taille limitée) ou fichiers
  .fit / .gpx / .tcx (montre). Envoi avec avancement, réimport en arrière-plan, puis rechargement : les
  nouvelles sorties sont marquées « Nouveau » avec un bandeau « N à évaluer ».
- **Évaluation des sorties** : de 1 à 5 étoiles sur sécurité, éclairage, beauté du paysage, plaisir,
  entretien des chemins, abri, tranquillité, peu de circulation, + commentaire. Depuis la liste
  (« Évaluer » / « ★ 4,2 ») ou la fiche sur la carte. Stockées par sortie (clé stable `strava:<id>`) et par
  utilisateur dans `data/ratings.json` : prêtes pour plusieurs comptes et pour l'étape 3 (report sur les tronçons).
- Vérifié de bout en bout sur une copie des données (Chromium, vue iPhone) : mauvais mot de passe refusé,
  connexion, évaluation enregistrée, ajout d'un .gpx (255 sorties, bandeau), déconnexion.
- 83 tests OK, 1 ignoré (11 nouveaux : sessions, cookies, blocage, secrets non stockés en clair ; import
  Strava, fichier isolé, archives piégées ; évaluations).

### 2026-10-07 — Retour aux traces distinctes
- Le rendu « Fréquentation » (passages comptés par portion de voie OSM et dessinés sur les rues, avec
  ses nombreuses règles de nettoyage) est retiré : trop complexe, risque de bugs. Retour aux traces
  distinctes, une par sortie, colorées par type (course / trail / randonnée), comme au début.
- Supprimés : `app/frequency.py`, `GET /api/frequency`, `data/cache/frequency.geojson`, le recalcul après
  le pré-téléchargement OSM, la légende « Passages » et le sélecteur Fréquentation / Par type (22 tests).
  Le pré-téléchargement des zones courues reste (routage). Le code reste dans l'historique git
  (dernier état : commit `6807c2b`).
- En-tête : résumé sur une ligne malgré le bouton de déconnexion (panneau un peu plus large).
- 61 tests OK, 1 ignoré.

### 2026-10-07 — Traces cliquables partout, évaluation depuis la carte
- Les traces distinctes (2,5 px) étaient presque impossibles à toucher au doigt, et ne réagissaient que
  dans l'onglet « Mes sorties ». Ajout d'une couche invisible large (10–20 px selon le zoom) qui reçoit
  survol et clic.
- Cliquables aussi dans l'onglet « Itinéraire », sauf quand le clic sert au planificateur (placer ou
  déplacer un point, choisir un itinéraire proposé) : `Planner.claimsClick`.
- La fiche d'une sortie garde son bouton « Évaluer cette sortie » / « ★ x · Modifier ».
- Vérifié (ordinateur et vue iPhone) en cliquant sur de vraies traces : départ placé d'abord quand il
  manque, puis fiche de la sortie et fiche d'évaluation, dans les deux onglets.

### 2026-10-07 — Création de compte et données séparées par compte
- « Créer un compte » sur l'écran de connexion (identifiant 3–32 caractères [a-z0-9._-], mot de passe
  ≥ 10 caractères confirmé), connexion automatique ; 5 créations par heure et par adresse au plus ;
  fermable avec `TRAILMAP_SIGNUP=0` (serveur public).
- **Chaque compte n'a accès qu'à ses données** : data/users/<nom>/ (sorties, cache, évaluations, itinéraires
  générés et leurs GPX, zones de confidentialité). Côté serveur, un `Workspace` par compte, chargé à sa
  première requête : sorties, moteur d'itinéraires (« déjà couru » d'après ses propres traces),
  générations et import en cours. Tuiles OSM et altitudes restent communes (aucune donnée personnelle).
  `/api/health` ne dit plus rien des données d'un compte.
- Un nouveau compte arrive directement sur « Mes sorties » avec l'import ouvert et un message d'accueil.
- Point de départ mémorisé par compte dans le navigateur (deux comptes sur le même téléphone ne voient
  pas le départ de l'autre).
- Données existantes rattachées au compte « jules » (`python -m app.workspace adopt jules` : déplacement,
  rien d'écrasé). Un cache vide recréé à la racine pendant la bascule a été supprimé.
- Vérifié de bout en bout (vue iPhone) : création de « marie », mots de passe différents refusés, compte vide
  accueilli, import d'une sortie ; « demo » garde ses 254 sorties sans celle de marie.
- 66 tests OK, 1 ignoré (nouveaux : création de compte et ses règles, cloisonnement des sorties, évaluations,
  imports et GPX entre deux comptes, rattachement des anciennes données).
- Prochaine étape côté comptes : mise en commun (évaluations partagées des tronçons, étape 5).

### 2026-10-07 — Plus d'app bloquée après « Envoyer vers la montre » (iPhone, écran d'accueil)
- Dans l'app ajoutée à l'écran d'accueil iOS, « Envoyer vers la montre » (et le lien GPX) naviguait vers le
  fichier : iOS l'affichait à la place de l'app, sans retour possible (il fallait fermer l'app).
  Ouvrir le GPX dans Safari n'est pas une solution : depuis iOS 16.4 l'app d'écran d'accueil ne partage pas
  ses cookies avec Safari (on y serait déconnecté).
- Sur téléphone, les deux boutons ouvrent maintenant la feuille de partage du système **par-dessus l'app**
  avec le fichier .gpx (préchargé avec la session, partagé dans le geste) : « Enregistrer dans Fichiers »,
  puis Fichiers → Partager → COROS. Fermer la feuille ramène à l'app. Là où le partage de fichiers est
  refusé (Chrome sur Android), téléchargement classique (sans blocage là-bas). Ordinateur : inchangé.
- Vérifié en navigateur mobile simulé : avec partage, la page ne change pas et le fichier partagé est le bon
  (.gpx, application/gpx+xml, sans titre) ; sans partage, téléchargement et page inchangée.
  À confirmer sur un vrai iPhone en mode écran d'accueil.

### 2026-10-07 — « Envoyer vers la montre » : téléchargement dans Safari, à côté de l'app
- La feuille de partage (entrée précédente) ne permettait pas d'arriver à COROS. Le seul chemin qui
  fonctionne : télécharger le GPX dans Safari, puis Fichiers → Téléchargements → Partager → COROS.
- Le GPX s'ouvre maintenant dans un nouvel onglet Safari (`window.open`, dans le geste) : l'app d'écran
  d'accueil reste en place, on y revient après. Safari n'ayant pas la session de l'app, le lien est
  **signé** (HMAC-SHA256, secret dans data/auth/link-secret, 600) et expire au bout d'une heure :
  `POST /api/routes/{id}/link` (connecté) -> `GET /api/share/gpx/{compte}/{id}?expires=…&sig=…` (sans session,
  seulement ce GPX). Lien préchargé à l'affichage de la carte, renouvelé s'il va expirer.
- Testé : lien valable sans session pour cet itinéraire, refusé s'il est modifié, pour un autre compte,
  un autre itinéraire ou expiré ; le reste de l'API reste fermé. En navigateur mobile simulé : un nouvel
  onglet s'ouvre sur le lien, l'app ne bouge pas. À confirmer sur l'iPhone.
- 67 tests OK, 1 ignoré.

### 2026-10-07 — Page de téléchargement pour le navigateur intégré d'iOS
- Retour du téléphone : le lien s'ouvre dans le navigateur intégré d'iOS (croix en haut à gauche pour revenir
  à l'app : ça, c'est bien), mais la page reste vide : ce navigateur ne lance pas seul le téléchargement d'un
  fichier ouvert directement.
- Le lien signé ouvre maintenant une petite page (nom de l'itinéraire, gros bouton « Télécharger le GPX »,
  marche à suivre jusqu'à COROS, et en secours : ouvrir la page dans Safari avec la boussole). Le bouton
  pointe vers le même lien avec `dl=1` (le GPX en pièce jointe) : un téléchargement lancé par un tap.
  Page sans script ni ressource externe (CSP `default-src 'none'`), pas de cache, pas de referrer.
- À confirmer sur l'iPhone.

### 2026-10-07 — Le GPX part dans le vrai Safari, l'app d'écran d'accueil n'est plus touchée
- Retour du téléphone : la page intermédiaire marche mais n'apporte rien ; surtout, après Fichiers → COROS,
  le navigateur intégré reste affiché dans Trail Map **sans sa croix** : app à fermer entièrement.
- Dans l'app d'écran d'accueil iOS (`navigator.standalone`), le bouton confie le lien direct du GPX
  (`…&dl=1`, signé) au **vrai Safari** via `x-safari-https://…` (iOS 17+) : Safari le télécharge comme avant,
  et Trail Map n'ouvre rien (ni navigation, ni navigateur intégré) ; on y revient par son icône.
  Si l'app est encore au premier plan 2,5 s après (iOS trop ancien), un bouton propose la page de
  téléchargement en secours. Dans un onglet de navigateur : le GPX directement dans un nouvel onglet.
- Vérifié en simulation : app inchangée, bon lien confié au système, secours affiché quand Safari ne prend
  pas la main ; onglet de navigateur : lien direct. À confirmer sur l'iPhone.

### 2026-10-07 — Rester dans l'app : page de téléchargement avec « Revenir à Trail Map »
- Retour : être envoyé dans Safari ne plaît pas (on veut rester dans l'app) et le téléchargement y est peu
  visible. Abandon de `x-safari-https://`, retour à la page ouverte **par-dessus l'app** (navigateur intégré
  d'iOS), celle avec laquelle le téléchargement marchait.
- Le problème de retour venait de ce que la vue restait sur le fichier, sans croix. Désormais :
  - le téléchargement est un `<a download>` : la page reste affichée pendant et après, avec « Téléchargement
    lancé ✓ » ; en revenant de Fichiers / COROS, c'est elle qu'on retrouve ;
  - grand bouton **« ← Revenir à Trail Map »** en haut, qui ferme la vue (`window.close()` : elle a été ouverte
    par l'app) ; s'il ne la ferme pas, la page explique de toucher le haut de l'écran pour faire réapparaître
    la croix (la barre de cette vue se replie) ;
  - un seul petit script autorisé (CSP avec nonce), toujours sans ressource externe.
- Vérifié en simulation : l'app ne bouge pas, la page reste pendant le téléchargement (bon fichier .gpx),
  « Revenir à Trail Map » ferme la vue et l'app est intacte. À confirmer sur l'iPhone.

### 2026-10-07 — Feuille de partage avec guide : l'app ne peut plus se bloquer
- Constat sur l'iPhone : après « Télécharger le GPX », iOS affiche son propre aperçu du fichier (avec le partage
  vers COROS) dans la vue ouverte par-dessus l'app, **sans aucun retour possible**. Cet écran appartient à iOS :
  une page web ne peut ni y ajouter de bouton, ni le fermer, ni l'éviter. Gênant pour de futurs utilisateurs.
- Choix de l'utilisateur : la **feuille de partage** du système, qui s'ouvre et se referme par-dessus l'app,
  la seule voie qui ne peut jamais bloquer. COROS n'y figure pas (il ne prend un GPX que depuis Fichiers) :
  la première fois, un guide en 2 étapes (« Enregistrer dans Fichiers », puis Fichiers → le fichier → Partager
  → COROS), ensuite la feuille directement ; rappel des étapes dans l'app après le partage.
  Le GPX est préchargé (avec la session) et partagé dans le geste ; sans partage de fichiers (Chrome sur Android),
  il est téléchargé sans quitter la page.
- Supprimés : lien signé, `/api/share/gpx`, page de téléchargement, `data/auth/link-secret` (plus rien
  d'accessible sans session à part la connexion et /api/health).
- Vérifié en simulation (avec la règle de Safari : partage seulement dans un geste) : guide la 1re fois, plus
  ensuite, bon fichier partagé, app inchangée ; sans partage : téléchargement, app inchangée.
- 66 tests OK, 1 ignoré.

### 2026-10-07 — Retour au téléchargement simple du GPX (choix de l'utilisateur)
- La feuille de partage ne propose pas COROS (limite de COROS : il ne prend un GPX que depuis Fichiers) ;
  l'étape « Enregistrer dans Fichiers » ne convainc pas. Choix pour l'instant : la solution de base.
- « Envoyer vers la montre » télécharge le GPX (`location.href` vers `/api/routes/{id}/gpx`), puis Fichiers →
  Partager → COROS. Dans l'app d'écran d'accueil iOS, l'aperçu du fichier remplace l'app sans retour :
  il faut la relancer (accepté pour l'instant).
- Guide et feuille de partage retirés (pas de code mort). Bilan des essais, pour ne pas les refaire :
  feuille de partage (COROS absent, quel que soit le type du fichier), page par-dessus l'app (aperçu iOS sans
  retour après le téléchargement), envoi vers Safari via `x-safari-https://` (refusé : on veut rester dans l'app).
- Pistes pour un vrai envoi en un geste : service synchronisé par COROS (Komoot, Ride with GPS…), ou petite
  app iOS native qui enveloppe Trail Map (« Ouvrir dans COROS » natif).

### 2026-10-07 — iOS PWA : partager le GPX sans quitter l'app
- Objectif : récupérer le GPX sans jamais quitter ni remplacer la page de l'app (dans l'app d'écran d'accueil iOS,
  un téléchargement la remplace par un aperçu plein écran sans retour).
- **Panneau de debug** (sans Mac ni inspecteur) : `?debug=1` ou appui long sur le titre « Trail Map ». Mode écran
  d'accueil (`navigator.standalone`, `display-mode`), version d'iOS et user agent, présence de `navigator.share` /
  `canShare`, résultat de `canShare({files})` pour chaque type MIME (fichier test et dernier GPX préparé), type
  retenu, journal des derniers partages (erreurs : name + message), gardé dans le stockage local pour être lu
  même après avoir relancé l'app ; bouton « Tester le partage ».
- **Feuille de partage d'abord** (`src/share.ts`) : le GPX et son objet File sont prêts dès l'affichage d'un
  itinéraire ; le tap appelle `navigator.share` de façon synchrone (aucun await ni fetch avant). Types essayés
  dans l'ordre : application/gpx+xml, application/xml, text/xml, application/octet-stream ; le premier accepté
  par `canShare` est utilisé. AbortError = silence ; autre erreur = journal + bouton « Ouvrir le fichier » (repli).
- **Repli** : lien signé, expirant (1 h), lié au compte et à l'itinéraire, **hors du scope de la PWA** :
  `GET /dl/<id>.gpx?user=…&expires=…&sig=…` (application/gpx+xml, attachment), ouvert en nouvelle fenêtre ; iOS
  l'affiche par-dessus l'app avec son « OK », jamais à la place. `POST /api/routes/{id}/link` le fournit (tous les
  itinéraires générés sont gardés côté serveur, donc accessibles). Pour que /dl soit hors scope, **l'app passe
  sous `/app/`** : manifest `scope`/`start_url`/`id` = /app/, Vite `base: "/app/"`, FastAPI sert le front sous /app/
  et redirige / vers /app/ (Vite fait de même en dev et relaie /dl).
- Ordinateur : téléchargement classique inchangé.
- Vérifié en simulation iPhone (avec la règle de Safari : partage seulement dans le geste) : 1er type accepté
  utilisé (application/xml quand seul lui passe), annulation silencieuse, refus -> bouton de repli -> /dl (GPX en
  pièce jointe sans session), aucun partage de fichiers -> /dl directement, page de l'app jamais quittée ;
  ordinateur : lien GPX classique. Tests /dl : en-têtes, expiration, refus pour un autre compte / itinéraire /
  signature modifiée. 69 tests OK, 1 ignoré.
- ⚠️ L'app d'écran d'accueil déjà installée garde l'ancien scope (/) : la supprimer et la rajouter depuis Safari
  (https://jules-laptop.tailf52fab.ts.net/app/) pour que /dl soit bien hors scope.

### 2026-10-07 — « Ouvrir avec COROS » : l'aperçu iOS par-dessus l'app
- Retour : COROS n'apparaît toujours pas dans la feuille de partage — attendu, et définitif pour une app web :
  COROS ne s'y inscrit pas, il ne s'ouvre que depuis un fichier affiché par iOS (Fichiers, aperçu de fichier).
- L'aperçu iOS du fichier, lui, propose COROS (c'est celui qui bloquait l'app quand il la remplaçait). Le lien
  /dl/ étant désormais hors du scope de la PWA (/app/), iOS doit l'ouvrir **par-dessus l'app** avec « OK ».
- Sur téléphone, deux boutons : **« Ouvrir avec COROS »** (lien signé /dl/, nouvelle fenêtre : aperçu → Partager
  → COROS → OK) et **« Enregistrer dans Fichiers »** (feuille de partage). Le lien GPX simple est masqué sur
  téléphone (il remplacerait l'app). Ordinateur : inchangé.
- Vérifié en simulation : les deux boutons, page de l'app jamais quittée. À confirmer sur l'iPhone, avec l'app
  réinstallée depuis https://jules-laptop.tailf52fab.ts.net/app/ (sinon /dl reste dans l'ancien scope « / »).

### 2026-10-07 — Un seul bouton générique « Envoyer à ma montre »
- Retour : « Ouvrir avec COROS » ne marche pas sur l'iPhone, et l'interface ne doit pas viser une seule marque.
- Sur téléphone : un seul bouton pleine largeur **« Envoyer à ma montre »** → feuille de partage par-dessus l'app
  (la seule voie qui ne bloque jamais) → « Enregistrer dans Fichiers », puis l'app de la montre (COROS, Garmin
  Connect, Suunto…) ouvre le fichier depuis Fichiers. Message d'étape juste sous le bouton (le message en haut de
  l'onglet était invisible une fois la carte d'itinéraire à l'écran). Lien /dl/ seulement en secours automatique
  (partage de fichiers impossible, ex. Android). Ordinateur : « Exporter le GPX ».
- Vérifié en simulation (partage dans le geste, app jamais quittée, message sous le bouton).

### 2026-10-07 — App iOS native (Capacitor) compilée sur GitHub Actions pour AltStore
- Étude de la piste app native (pas de Mac) : compilation macOS gratuite sur GitHub Actions (dépôt public),
  installation par AltStore avec un identifiant Apple gratuit (signature 7 jours, renouvelée par AltServer sur
  le PC). Un premier prototype (dossier mobile/, menu « Ouvrir dans… » natif) a validé la compilation sans
  signature (run réussi, .ipa de 554 Ko) ; remplacé par l'intégration ci-dessous.
- **Capacitor 8 dans `frontend/`** (Swift Package Manager, pas de CocoaPods) : projet `frontend/ios/` versionné,
  app « RunProject », `com.julesbor38.runproject`, icône et écran de lancement d'après le logo. Build web de
  l'app à part (`npm run build:native` : base « / », dist-native/) : le web et la PWA (/app/) ne changent pas.
- **Serveur** : adresse tapée au premier lancement, gardée sur le téléphone (rien de personnel dans le .ipa
  public) ; serveur injoignable : « Active Tailscale sur ton iPhone » + Réessayer (`src/native.ts`).
- **Session** : la page de l'app (capacitor://localhost) n'a pas les cookies du serveur (bloqués par iOS) :
  connexion avec `token: true` -> jeton renvoyé, puis `Authorization: Bearer` ; même stockage de sessions
  (SHA-256 seulement). **CORS** limité à `capacitor://localhost` (et Vite en dev) ; le middleware de connexion
  laisse passer les pré-requêtes OPTIONS et ses 401 portent les en-têtes CORS.
- **GPX natif** : écrit dans le cache de l'app (plugin Filesystem), puis feuille de partage native sur ce fichier
  (plugin Share) ; jamais d'aperçu à la place de l'app.
- **Workflow** `.github/workflows/ios.yml` (macos-latest, à la main ou sur tag v*) : npm ci, build native,
  cap sync, xcodebuild Release iphoneos sans signature, numéro de build = numéro du run, version = tag ou
  package.json, `Payload/RunProject.app` -> `RunProject.ipa` (artifact ; Release GitHub pour les tags) ;
  échoue si l'app contient un nom de machine, de tailnet ou un jeton.
- Vérifié : build native simulée dans un navigateur (autre origine, pont iOS simulé) : écran d'adresse,
  « Active Tailscale », connexion par jeton sans aucun cookie, relance directe ; web et PWA inchangés ;
  71 tests OK (jeton, CORS). Les plugins natifs et la compilation se vérifient sur GitHub puis sur l'iPhone.
- Documentation : IOS-ALTSTORE.md (compiler, récupérer le .ipa, AltStore, limites).
- Premier run GitHub « iOS (AltStore) » réussi (run 1 : `RunProject-ipa-0.1.0-1`, 1,3 Mo, vérification « aucune
  donnée personnelle » passée). Correctif : en dev, Vite répondait lui-même aux pré-requêtes CORS de /api (sans
  l'origine autorisée) : `server.cors: false`, c'est l'API qui répond (capacitor://localhost seulement).

### 2026-10-07 — Service permanent installé sur le PC
- Service systemd `trailmap` installé (`./deploy-local.sh --no-pull`) : uvicorn sans --reload sur 127.0.0.1:8000, actif
  et lancé au démarrage de WSL ; test de plantage (kill -9) : relancé tout seul en quelques secondes.
- Tâche planifiée Windows « WSL keep-alive (Trail Map) » créée et lancée (WSL gardé allumé dès l'ouverture de
  session, sans terminal). Alimentation sur secteur : capot fermé = ne rien faire, jamais de veille / veille
  prolongée (batterie inchangée).
- Tailscale : `tailscale serve --bg http://localhost:8000` (tailnet only, pas de funnel). Vérifié depuis Windows via
  https://jules-laptop.tailf52fab.ts.net : / -> /app/ (307), /app/ 200, /api/health 200, /api/activities 401 sans
  session, pré-requête CORS de l'app native acceptée.
- Le mode dev (Vite + --reload) n'est plus lancé : pour développer, `sudo systemctl stop trailmap` puis le relancer,
  et `./deploy-local.sh --no-pull` pour mettre le service à jour.

### 2026-10-07 — App native : menu « Ouvrir avec… » d'abord
- Test du soir (app web, raccourci iOS « Obtenir le contenu de l'URL » + « Partager ») : COROS absent là aussi,
  alors qu'il apparaît depuis l'app Fichiers. Le menu de Fichiers est le « Ouvrir avec… » d'iOS
  (UIDocumentInteractionController), pas la feuille de partage : la feuille du plugin Share de l'app native
  risquait donc le même échec.
- App native : plugin maison `OpenWith` (`frontend/ios/App/App/SceneDelegate.swift`, `RunProjectViewController`) :
  le GPX écrit par Filesystem est ouvert dans le menu « Ouvrir avec… » ; feuille de partage seulement si aucune
  app ne l'ouvre. À recompiler (Actions -> iOS (AltStore) -> Run workflow) avant l'installation.

### 2026-10-07 — Lieux notables sur la carte (nature, eau, patrimoine, parcs, points utiles)
- Données : le cache de tuiles du routage ne contient que les chemins ; les lieux sont extraits **une fois de
  l'extrait OSM France** déjà téléchargé (`python -m app.pois.extract ../data/osm/france-latest.osm.pbf [--force]`,
  pyosmium, surfaces reconstituées -> centre + superficie ; rivières nommées : un point par ~5 km ; doublons
  nœud / surface fusionnés à 150 m) dans `data/pois/pois.sqlite` (SQLite + R-tree, commun à tous les comptes).
  Hors de France : Overpass par zone de 0,25°, en arrière-plan, une zone à la fois, mise en cache (30 min avant
  de réessayer un échec), seulement pour les zones regardées.
- Catégories / types d'après les tags demandés (cascade rangée dans « Eau »), éléments sans nom ignorés sauf
  points de vue, sommets, sources, croix, eau potable, toilettes, abris, pique-nique. Score (Wikidata, Wikipédia,
  ref:mhs, altitude des sommets, point de vue nommé, superficie) -> zoom minimal d'affichage (9 à 15).
- Wikidata : description FR, lien Wikipédia FR, vignette Commons **avec auteur et licence** ; appels groupés
  (50), User-Agent explicite, cache 30 jours (1 jour après un échec), préchargement des lieux visibles.
- API (derrière la connexion) : `GET /api/pois?bbox=&zoom=&categories=` (≤ 400, meilleurs scores),
  `GET /api/pois/<id>` (fiche). Chaque itinéraire proposé liste ses lieux à moins de ~50 m (`properties.pois`).
- **Points de passage** (« Passer par ici ») dans le générateur, 3 au plus : boucle par les points (ordre de leur
  direction depuis le départ) + un point libre pour la distance ; aller simple départ -> points -> arrivée, détour
  pour la distance sur la dernière portion ; message si les points imposent une boucle plus longue.
- Front : icônes par type sur pastille de couleur de catégorie, regroupement en vue large (≤ zoom 12), chargement
  de la zone visible après 300 ms d'arrêt, cache par zone, requête précédente annulée ; puces de catégories
  (mémorisées) dans « Itinéraire » ; fiche : photo + crédit + licence, description, « Monument historique »,
  liens Wikipédia / OSM, « © OpenStreetMap contributors », « Passer par ici » (feuille par-dessus l'app sur
  téléphone : une bulle passait sous le panneau du bas) ; sous chaque itinéraire « 2 points de vue, 1 cascade… »
  et les lieux nommés, cliquables.
- Vérifié (copie de test, vue iPhone + ordinateur) : 32 lieux à Fourvière (zoom 15), fiche « Colline de Fourvière »
  avec photo Commons créditée (CC BY-SA 4.0), boucle de 6,8 km passant par elle, lieux listés sous l'itinéraire.
- 84 tests OK (extraction sur un petit extrait, catégories, score, lieux le long d'un tracé, cache Wikidata,
  lecture Overpass, API, points de passage).
- Extraction France lancée le 2026-10-07 au soir (lente sur les chemins et surfaces : index des nœuds sur disque).

### 2026-10-07 — Exploration : chemins découverts, progression par commune, badges
- **Map-matching** (première version, `app/explore/matching.py`) : un tronçon = une arête du graphe de routage
  (voie OSM praticable entre deux carrefours), clé stable tirée de ses nœuds OSM (servira aux notes de l'étape 3).
  Trace rééchantillonnée tous les 5 m, chaque point accroché au tronçon à moins de 20 m dont la direction
  concorde (45°), continuité préférée (pas de saut vers la rue parallèle) ; un tronçon est parcouru quand
  80 % de sa longueur est couverte (traverser une rue ou toucher son bout ne compte pas, un aller-retour compte
  une fois). Trottoirs, passages piétons, allées privées et de parking ignorés (une rue ne compte qu'une fois).
- Ne comptent que : les sorties horodatées course / trail / rando, les parties visibles (200 m masqués aux
  extrémités, zones de confidentialité) et les portions à moins de 25 km/h (vélo, voiture, sauts GPS exclus).
- Stockage `data/explore/explore.sqlite` (SQLite + R-tree) : tronçons parcourus par compte (1re date et sortie),
  sorties traitées (version du calcul : retraitement si l'algorithme change), lieux découverts (lieux notables à
  moins de 30 m), réglages par compte prêts pour un futur classement (**participation désactivée par défaut**,
  pseudonyme ; rien n'est montré aux autres), communes.
- **Communes** (OSM `boundary=administrative`, `admin_level=8`, extraites une fois de l'extrait France :
  `python -m app.explore.communes ../data/osm/france-latest.osm.pbf`) : longueur totale des chemins praticables
  (calculée à la première visite, puis gardée) vs parcourue -> pourcentage.
- Calcul **incrémental** en arrière-plan : au démarrage pour chaque compte, puis après chaque import (seules les
  nouvelles sorties sont traitées). Historique réel : 254 sorties en ~3 min, 545 km de chemins, 397 lieux.
- API : `GET /api/explore` (résumé, paliers, suggestions), `POST /api/explore/seen`, `GET /api/explore/fog?bbox=`
  (zone visible, zoom ≥ 13), `GET /api/explore/communes/{id}` (contour).
- Onglet **« Exploration »** : km découverts, communes triées par % (anneau, km faits / total, lieux, dernière
  date ; clic -> contour sur la carte), mode **« Brouillard »** (voile sur la carte, chemins courus en jaune, les
  autres en gris), **paliers** 10/25/50/75/90 % par commune et **badges** (communes, sommets, cascades, points de
  vue, monuments, lacs ; icônes SVG) avec une courte animation discrète (respecte « réduire les animations ») pour
  ce qui est franchi depuis la dernière visite ; le premier passage sur l'historique est enregistré sans fête.
- **Suggestions** « X km de chemins jamais courus à Y km d'ici » (carrés de 1 km à moins de 8 km du départ
  habituel, pondérés par la distance, espacés de 2 km) ; « Explorer » ouvre le générateur en mode Découverte avec
  le départ placé dans la zone.
- 96 tests OK (rue parcourue vs rues voisines, toucher sans parcourir, aller-retour, vélo ignoré, zone de
  confidentialité, sorties sans heure, % de commune, lieu à 30 m mais pas à 60 m, paliers et badges, trottoirs,
  premier passage silencieux, API par compte).

### 2026-10-08 — Exploration : superficie découverte de chaque commune
- Extractions France terminées : 479 026 lieux notables (1 h, 6,3 Go de mémoire au plus) puis 34 770 communes
  (11 min) dans data/explore/explore.sqlite ; service redémarré.
- À la demande : chaque passage découvre une **bande de 20 m de chaque côté** du chemin emprunté (la trace
  masquée et à moins de 25 km/h, échantillonnée tous les 5 m) sur une grille fixe de cellules de ~10 m
  (`app/explore/area.py`, calcul vectorisé numpy) ; une cellule appartient à la commune de son centre. Superficie
  des communes calculée depuis leur contour. Une nouvelle sortie n'ajoute que ses cellules nouvelles.
- Onglet : l'anneau de chaque commune montre maintenant le **% de la superficie découverte** (km² découverts /
  km² de la commune), avec en dessous le % des chemins parcourus ; communes triées par superficie ; total
  « km² découverts ». Les paliers 10–90 % restent sur les chemins (« Tassin : 25 % des chemins »).
- Version du calcul passée à 2 : tout l'historique est retraité une fois (~4 min pour 254 sorties).
  Historique réel : 24,1 km² découverts, 81 communes ; Tassin-la-Demi-Lune 23 % de sa superficie (1,85 / 7,97 km²)
  et 40 % de ses chemins, Lyon 7,1 % (3,4 / 48 km²).
- Correction : les rattrapages (démarrage, nouvelle version du calcul, communes ajoutées après coup) enregistrent
  les paliers sans les fêter ; seul le calcul qui suit un import de nouvelles sorties les annonce (21 paliers
  annoncés d'un coup sinon). Le calcul de l'Exploration a son propre réglage `TRAILMAP_EXPLORE` (indépendant du
  pré-téléchargement des tuiles).
- 101 tests OK (bande de 20 m, aller-retour, cellules comptées une fois, superficie et trous, rattrapage silencieux).

### 2026-10-08 — Brouillard éclairci sur la superficie découverte
- Le voile du mode « Brouillard » n'est plus uniforme : il est percé sur la superficie découverte (la bande de
  20 m de chaque côté des passages). `GET /api/explore/veil?bbox=&zoom=` renvoie le monde moins les zones
  découvertes de la vue (+ 25 % de marge) : contours des cellules suivis en anneaux (zones / poches non
  découvertes, enroulement adapté à MapLibre), escaliers lissés (Douglas-Peucker), poches d'un ou deux blocs
  ignorées ; cellules regroupées en vue éloignée (10 m dès le zoom 13, 20 m au 12, 40 m au 11, 80 m en dessous),
  voile complet sous le zoom 9. Couche `fill` à la place du fond uniforme ; les chemins (jaune / gris) restent
  au zoom 13 et plus.
- Historique réel : 0,2 à 0,3 s et 50 à 200 Ko par vue, du quartier à l'agglomération lyonnaise.
- 104 tests OK (voile percé sur la trace et à 12 m, voilé à 300 m, après un virage, à plusieurs échelles ; API).

### 2026-10-08 — Brouillard arrondi, bande de 50 m
- À la demande : la superficie découverte est maintenant la bande de **50 m** de chaque côté des passages (au lieu
  de 20 m) ; version du calcul 3, tout l'historique retraité une fois (~7 min pour 254 sorties). Historique réel :
  52,9 km² découverts, 83 communes ; Tassin-la-Demi-Lune 42 % de sa superficie, Charbonnières 33 %.
- Contours du voile **arrondis** (lissage de Chaikin, 3 passes, après simplification) : formes naturelles au lieu
  des marches de la grille ; cellules regroupées un cran plus tôt en vue éloignée (le lissage masque les blocs).
- Échantillonnage de la trace : aussi ses propres points (le demi-tour d'un aller-retour est toujours couvert).
- Réponses compressées (gzip) : voile 452 -> 99 Ko au zoom 13, traces 700 -> 190 Ko.
- 104 tests OK.

### 2026-10-08 — Glisser le panneau vers le bas (téléphone)
- Sur téléphone, le panneau du bas se replie d'un glissé vers le bas (depuis l'en-tête, ou depuis le contenu une
  fois remonté en haut ; seuil ~120 px ou geste rapide) ; curseurs et champs gardent leurs gestes.

### 2026-10-08 — Crédits gagnés en courant (première partie : les gains)
- Plan validé : barème « équilibré », historique en **bonus de bienvenue plafonné** (500).
- Barème (`app/explore/credits.py`) : 1 par km couru (parties visibles des sorties horodatées, ≤ 25 km/h), +2 par
  km de chemin nouveau, 10 par km² découvert ; lieux 10 (sommet, cascade), 5 (point de vue, lac), 3 (monument),
  2 (nature, eau), 1 (parcs, points utiles) ; paliers de commune 10/25/50/75/90 % -> 10/20/40/60/100 ; 25 par badge.
- **Journal** par compte (table `credits` d'explore.sqlite, clé unique `act:` / `poi:` / `ach:` : jamais payé deux
  fois) ; `credits_meta` : début des crédits du compte et dernier gain annoncé. Historique (`history`) = tout ce qui
  existait au premier calcul, puis les sorties importées plus tard mais datées de plus de 14 jours avant ce début ;
  il ne compte que dans le bonus de bienvenue (plafond 500).
- `processed` garde maintenant les km courus, la superficie nouvelle et la date de chaque sortie ; les km des
  sorties déjà traitées sont recalculés une fois sans nouveau map-matching (~35 s pour 254 sorties) ; leur
  superficie est créditée d'un bloc (`history:area`).
- Calcul à la fin de chaque passage de l'Exploration (démarrage, après import) ; rattrapages silencieux.
- API : GET /api/credits ; POST /api/explore/seen avec `credits` ; front `src/credits.ts` : solde « ✦ N » dans
  l'en-tête (ouvre le détail), section « Crédits » en tête de l'onglet Exploration (solde, par type, barème,
  derniers gains), annonce « +N crédits » quand les nouvelles sorties sont analysées.
- Historique réel (jules) : 2 150 km courus, 545 km nouveaux, 52,9 km² -> historique de 5 715, solde de départ 500.
- 108 tests OK, 1 ignoré.

### 2026-10-08 — Crédits : plafond mensuel et coût des itinéraires
- À la demande : **5 000 crédits par mois** (abaissé à **2 000** le même jour, pour limiter les abus) au plus gagnés en courant (mois de la date de la sortie, ou du jour
  pour un palier / badge : les exports Strava hebdomadaires se lissent sur le mois) ; au-delà, le gain est
  inscrit au journal mais réduit (jusqu'à 0, `capped_from` garde le montant d'origine) : jamais payé plus tard.
- **Dépense** : générer un itinéraire coûte **1 crédit par km** (`credits.ROUTE_PER_KM`) du premier itinéraire
  proposé, au moins 1 ; vérifié avant le calcul sur la distance demandée (sinon 1,2 × la distance à vol d'oiseau),
  402 « crédits insuffisants » sinon ; jamais en dessous de 0. Lignes `spend` (négatives) dans le journal.
- Front : « −N crédits (solde : M) » après la génération, solde de l'en-tête mis à jour ; section Crédits : barre
  du mois, « Dépensés », derniers mouvements.
- Plus tard : la collection (autre dépense).
- 110 tests OK, 1 ignoré.

### 2026-10-08 — Jeu, étape 1 : familiers et portefeuille
- Plan validé (familiers -> duels -> boutique, chaque étape validée) ; **tout se fait en dépensant des points** :
  niveaux achetés (appui sur l'image du familier), évolution payante au niveau max du stade ; le bonus de
  bienvenue compte (il est sur le solde).
- `app/game/` : config TOML (stades, coûts, types, espèces) vérifiée au chargement ; `data/game/game.sqlite` avec
  migrations numérotées ; **portefeuille** points / gemmes (solde matérialisé, `CHECK >= 0`, dépense conditionnelle
  sous `BEGIN IMMEDIATE`, clé unique par ligne, `request_id` pour rejouer sans effet) ; le journal des crédits
  d'explore.sqlite y est déplacé une fois (486 points pour jules, rien de perdu).
- 3 starters (total 300) : Galet (Montagne : Déf / PV), Fusette (Vitesse : Vit / Att), Foulon (Endurance : PV,
  équilibré) ; triangle Montagne > Vitesse > Endurance > Montagne ; Nocturne et Exploration ont chacun deux forces
  et deux faiblesses. Formes finales : Cimeval / Ombrecrête, Éclairon / Nuitfilante, Ultravent / Sentinomade.
- Coût d'un niveau `ceil(0,5 × n^1,5)`, évolutions 50 / 250 / 1 000 / 3 000 ; du niveau 1 au 100 : 24 601 points
  (`python -m app.game.balance`). Stats = base × stade (0,5 à 2) × (1 + 0,01 × (niveau − 1)).
- **Profil de course** par sortie (`app/explore/profile.py`) : D+ (hystérésis 3 m), km de nuit (soleil sous −6°),
  km à moins de 5:00/km ; recalculé une fois pour l'historique (~35 s). Jules : 20 m/km, 6 % de nuit, 26 % en
  sorties longues, 40 % rapides, 25 % de chemins nouveaux (-> Cimeval, Éclairon, Ultravent).
- Points pour les évaluations : 5 par sortie évaluée la première fois, 10 par jour.
- Front : onglet « Familier » (choix du starter, image cliquable -> +1 / +5 / max niveaux, évolution, aperçu des
  formes finales dès l'adulte, stats), illustrations SVG provisoires (`src/pet-art.ts`) ; « crédits » -> « points ».
- 130 tests OK, 1 ignoré.

### 2026-10-08 — Les trois starters adoptables
- À la demande : plus de choix unique ; chaque starter s'adopte une fois (gratuit), le dernier adopté devient
  actif, chacun évolue de son côté (niveaux et points dépensés par familier). Migration 003 (index unique par
  espèce de starter). Onglet : sélecteur des familiers en haut, « Adopter un autre familier » en bas.
- Illustrations refaites (`src/pet-art.ts`) : une ligne par espèce, six formes finales distinctes (kawaii -> badass).
- 130 tests OK, 1 ignoré.

### 2026-10-08 — Jeu, étape 3 avant la 2 : la boutique
- À la demande, la boutique avant les duels : 5 nouveaux familiers plus grands, plus forts, avec plus de capacités :
  Colossaure (mammouth de givre, rare, 360), Tempestor (dragon d'orage, épique, 390), Sylvarion (cerf aux bois de
  cristal, épique, 390), Brasaltor (dragon de basalte et de lave, légendaire, 420), Aurorelle (renarde céleste à neuf
  queues d'aurore, légendaire, 420) ; une ligne d'évolution chacun et une forme finale unique ; halo de rayons
  tournants pour les légendaires.
- Capacités (`[[species.ability]]` : strike, guard, heal, haste, drain), débloquées par stade, pour les starters
  aussi (une par forme finale) ; affichées sur la fiche et dans la boutique ; elles serviront aux duels.
- `shop.toml` : prix en points ou en gemmes (3 000 / 6 000 / 10 000 points, 300 / 600 / 1 000 gemmes), packs de
  gemmes (0,99 / 4,99 / 9,99 €) ; règle vérifiée au chargement : un article aléatoire ne se paie qu'en points.
- `shop.py` : achat atomique (prix pris, familier créé en œuf et actif, achat enregistré), une fois par compte,
  `request_id` rejouable ; `payments.py` : `PaymentProvider`, factice (`TRAILMAP_PAYMENTS=mock`), sinon 503.
  Migration 004 (`purchases`, un familier de boutique par espèce et par compte).
- Front : sous-onglets « Mes familiers » / « Boutique » ; cartes par rareté (forme finale en grand, ligne
  d'évolution, stats, capacités, « +30 % vs les starters »), confirmation qui dit exactement ce qu'on obtient.
- 137 tests OK, 1 ignoré.

### 2026-10-08 — Jeu : combats contre des bots
- Choix validés : je choisis l'attaque à chaque tour ; mon familier actif seul ; victoires en points, plafonnées
  par jour.
- **Kits par type** (`config/moves.toml`) : Montagne Éboulement (zone) / Poing de granit / Rempart rocheux ;
  Vitesse Éclair (prioritaire) / Rafale de coups (×3) / Esquive ; Endurance Charge / Coup de fond (vol de vie) /
  Second souffle ; Nocturne Griffe d'ombre (critiques) / Nuée nocturne (zone, ronge) / Voile de nuit ; Exploration
  Ronces (ronge) / Pluie de feuilles (zone) / Racines (défense + régénération). Capacités spéciales des espèces
  utilisables en combat (recharge 3 tours) ; une défense attend 1 tour (sinon esquives et soins à l'infini).
- **Moteur** (`combat.py`) : ordre priorité puis Vitesse, dégâts Att² / (Att + Déf) × type × ±10 %, critiques
  rares, effets (garde, esquive, régénération, poison, vitesse), IA des mobs, boss en rage à mi-PV (le grand boss
  appelle 2 renforts), 50 tours au plus ; aléatoire `Random(graine:tour)` : un combat se rejoue à l'identique.
- **Sentier** (`config/battles.toml`, `battles.py`) : niveaux sans fin, mobs seuls ou en groupe, boss intermédiaire
  tous les 5 (Granitor, Zéphyr, Tenace, Ombrecrête, Nuitfilante), grand boss tous les 10 (Colossaure, Tempestor,
  Sylvarion, Brasaltor, Aurorelle), puis ils reviennent plus forts. Équilibré par simulation : bébé ~1–5,
  jeune ~8–15, adulte ~20, forme finale niveau 100 ~40–55 ; les types comptent (on change de familier contre un
  boss qui nous contre). Combat en cours repris à la réouverture. Migration 005.
- Front : sous-onglet « Combats » (sentier en zigzag, ennemis et gains de chaque niveau), arène plein écran (fond
  selon le type, barres de PV, cible à toucher, 2 attaques + défense + spéciales), une animation CSS par attaque
  (rochers qui tombent, éclair, griffes d'ombre, ronces, racines…), dégâts flottants, critiques, efficacité,
  K.O., rage, renforts, écran de victoire / défaite ; le kit de combat affiché sur la fiche du familier.
- 146 tests OK, 1 ignoré.

---

## Bilan des 7 et 8 octobre 2026
Deux journées chargées, détaillées dans le journal ci-dessus :
- **Auto-hébergement** sur le PC (service systemd `trailmap`, Tailscale, `/api/health`, `deploy-local.sh`).
- **Interface** refaite (identité « trail », logo) ; **« Le plus plat »** (pétales, aller-retour) ;
  **tuiles OSM de toute la France** en local.
- **Comptes** (connexion, création, données par compte), **imports** depuis la page (archive Strava, .fit/.gpx/.tcx),
  **évaluation des sorties** ; retour aux traces distinctes et cliquables.
- **Envoi vers la montre** sur iPhone : bouton générique « Envoyer à ma montre » (feuille de partage) ; front
  déplacé sous /app/ ; panneau de debug ; **app iOS native** (Capacitor, GitHub Actions, AltStore, menu
  « Ouvrir avec… ») — reste à l'installer sur le téléphone (câble USB).
- **Lieux notables** : 479 026 lieux de France (nature, eau, patrimoine, parcs, points utiles), fiches Wikidata,
  « Passer par ici » dans le générateur.
- **Exploration** (première version de l'étape 2, map-matching) : 545 km de chemins découverts, 34 770 communes
  extraites, % des chemins et **% de la superficie** de chaque commune (bande de 50 m de chaque côté des
  passages : 52,9 km² découverts, 83 communes), lieux découverts, paliers et badges, suggestions de zones jamais
  courues, **brouillard** arrondi éclairci sur la superficie découverte ; réponses compressées (gzip).
- Tests : 104 OK, 1 ignoré.

## État au 2026-10-08
- Tuiles OSM : toute la France en local (extrait Geofabrik du 2026-10-07, à rafraîchir avec `--force`) ;
  Overpass seulement hors de France. Lieux notables et communes extraits du même extrait.
- Auto-hébergement en service : systemd `trailmap` (port 8000), tâche Windows « WSL keep-alive », Tailscale vers
  le port 8000, alimentation réglée. Mise à jour : `./deploy-local.sh` (ou redémarrage du service).
- ⚠️ Sauvegarde : `data/explore/explore.sqlite` (~500 Mo, surtout les contours des communes, recalculables) n'est
  pas sur Run-Project-Data (limite GitHub de 100 Mo par fichier) ; la progression de chaque compte est
  recalculable depuis ses sorties, mais un export des seules données des comptes serait plus sûr.
- Rien n'utilise encore PostGIS ni GraphHopper.

## Prochaines tâches

> **Jeu : familiers, portefeuille, boutique et combats contre des bots faits le 2026-10-08.** Suite : tester les
> combats sur le téléphone (rendu, rythme des animations, équilibrage réel), puis brancher un vrai paiement
> (App Store / Stripe) ; idées : équipes de 3 familiers, duels entre comptes.

1. **Crédits : gagner en courant, dépenser dans l'app.** **Gains faits**, plafond de 2 000 / mois, itinéraires à
   1 crédit / km (journal du 2026-10-08) ; reste : la collection (rareté), bâtiments, autres dépenses. Notes d'origine :
   - **Gagner des crédits** :
     - selon les **kilomètres parcourus** (sorties horodatées seulement, mêmes règles que l'Exploration : parties
       visibles, ≤ 25 km/h ; peut-être un bonus pour les km nouveaux par rapport aux km déjà connus) ;
     - en complétant des **succès** (les paliers et badges existants, et de nouveaux) ;
     - en atteignant un **% de la superficie ou des chemins d'une commune** (10 / 25 / 50 / 75 / 90 %) ;
     - en **visitant des lieux** : tel nombre de monuments, sommets, cascades, points de vue… ; et pourquoi pas des
       **bâtiments** (attention : les bâtiments OSM ne sont pas dans nos tuiles de routage ni dans les lieux
       notables ; il faudrait les compter depuis l'extrait France, des dizaines de millions d'éléments, peut-être
       seulement leur nombre par cellule de la grille de l'Exploration).
   - **Dépenser des crédits** (à réfléchir) : générer un itinéraire coûte tant de crédits (la boucle simple
     gratuite ? les options avancées payantes : points de passage, « Le plus plat », Découverte…) ; **collection**
     (cartes des lieux ou des communes découverts, avec une **rareté** : commune peu courue, sommet élevé,
     monument classé, cascade…) ; **trophées** ; personnalisation (couleurs du brouillard, thèmes de carte, icônes).
   - **Questions à trancher** : barème (crédits par km, par succès, par %), plafonds anti-abus (une même sortie
     importée deux fois, une trace de vélo, des allers-retours devant chez soi), rétroactivité sur l'historique
     (crédits de bienvenue d'après les sorties passées ?), ce qu'on obtient en dépensant, s'il y a des échanges
     plus tard entre comptes (classement, opt-in déjà prévu dans la table `settings`, désactivé par défaut).
   - **Pistes techniques** : un **journal des crédits** par compte (table SQLite à côté de data/explore :
     une ligne par gain / dépense, avec sa source — sortie, succès, palier, lieu — et une clé unique pour qu'un
     retraitement ou un réimport ne crédite jamais deux fois) ; solde = somme du journal ; s'appuyer sur ce qui
     existe : `processed` (sorties traitées), `traversed` / `area_cells` (km et superficie nouveaux),
     `discovered_pois` (lieux), `Explorer.achievements()` (succès) et les annonces « Nouveau palier » (à étendre
     avec « +N crédits ») ; coût d'un itinéraire vérifié côté serveur dans POST /api/routes.
2. **Corriger les 3 .fit.gz illisibles** (`10708302692`, `10690331142`, `10690331477`) :
   erreur `developer_data_index 0 not defined`, assouplir le parseur FIT.
3. **Performances** : ~6 s pour 30 km graphe en mémoire, mais ~20–30 s pour construire un grand
   graphe (beaucoup de zones). Pistes : un seul Dijkstra depuis le départ partagé entre candidats,
   graphe plus compact, ou GraphHopper (qui peut lire le même extrait .osm.pbf).
4. (Rendu « Fréquentation » abandonné le 2026-10-07 ; son comptage par portion de voie OSM, dans
   l'historique git, peut resservir d'idée pour le map-matching de l'étape 2.)
5. **Profil altimétrique des sorties passées** dans « Mes sorties » (seul le D+ montre est affiché).
6. **Étape 2 — map-matching** : première version en place (Exploration, moteur Python) ; à affiner (GPS en
   ville dense, chemins absents d'OSM) ou à remplacer par GraphHopper.
7. **Étape 3 — notation des tronçons** : reporter les évaluations des sorties sur les tronçons OSM parcourus
   (après map-matching), puis noter directement un tronçon.
8. **Étape 4 — itinéraires pondérés par les notes.**
9. **Étape 5 — communautaire** : comptes, agrégation, modération.
10. **Téléphone** : installer l'app iOS native (AltStore, câble USB : IOS-ALTSTORE.md) et vérifier « Envoyer à ma
   montre » avec le menu « Ouvrir avec… » ; puis hors ligne.
11. **Sauvegarde de l'Exploration** : exporter les données des comptes de data/explore/explore.sqlite (sans les
   communes) vers Run-Project-Data.
