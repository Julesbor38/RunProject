# Le jeu : familiers, points, (bientôt) duels et boutique

Tout est décidé par le serveur (`app/game/`) ; le front (`frontend/src/pet.ts`) ne fait qu'afficher.

- **Points** : gagnés en courant, en explorant, en visitant des lieux, avec les paliers et badges, en évaluant
  ses sorties (`app/explore/credits.py`, barème et plafond de 2 000 / mois). Jamais achetables.
- **Gemmes** : monnaie achetable (étape boutique, pas encore branchée). Les deux monnaies ne se mélangent jamais.
- **Portefeuille** (`wallet.py`) : soldes et journal (`transactions`) dans `data/game/game.sqlite`, mis à jour
  dans la même transaction SQLite ; une dépense ne passe que si le solde la couvre ; chaque ligne a une clé
  unique (un gain ou un achat rejoué ne compte jamais deux fois). **À sauvegarder.**
- **Familiers** (`pets.py`) : les trois starters, adoptables chacun une fois (ils évoluent chacun de leur côté) ; on achète des niveaux avec des points (appui sur
  l'image), jusqu'au niveau max du stade, puis l'évolution ; la forme finale dépend du profil de course.
- Base de données : migrations numérotées dans `migrations/` (`NNN_nom.sql`, appliquées au démarrage dans
  l'ordre, suivies par `PRAGMA user_version`). Pour changer le schéma : ajouter un fichier, ne jamais modifier
  un fichier déjà appliqué.

Après toute modification de la config : `pytest` (la config est vérifiée au chargement et par les tests),
`python -m app.game.balance` pour voir les courbes, puis redémarrer l'API.

## Ajouter une espèce

Dans `config/species.toml`, un bloc `[[species]]` :

```toml
[[species]]
id = "lucine"                 # identifiant stable (stocké dans la base : ne plus le changer)
type = "nocturne"             # un des types de types.toml
names = ["Œuf de Lucine", "Lucine", "Luciole", "Lucifère"]   # œuf, bébé, jeune, adulte
color = "#4b3f8f"
description = "…"
base = { hp = 70, attack = 80, defense = 65, speed = 85 }    # stats du stade jeune au niveau 1
# starter = true             # adoptable gratuitement, une fois (jamais vendu)

  [[species.branch]]          # au moins une ; la forme finale prend celle au meilleur score
  id = "eclipse"
  name = "Éclipse"
  type = "nocturne"
  metric = "night_share"      # ascent_per_km, night_share, long_share, fast_share, new_share
  reference = 0.15            # score = métrique / référence ; égalité : la première branche
  hint = "des sorties de nuit"
```

Le total des stats de base fixe la puissance de l'espèce (les starters ont tous 300). L'illustration
provisoire vient de `frontend/src/pet-art.ts` (couleur + type + stade) ; une vraie image pourra la remplacer.

## Régler la progression

- `config/stages.toml` : niveaux max par stade, coût de chaque évolution, multiplicateur de stats ;
  `[levels]` : coût d'un niveau `ceil(cost_base × n^cost_exponent)` et bonus de stats par niveau.
- `config/types.toml` : `[strong]` liste, pour chaque type, ceux contre qui il inflige ×1,5 (ils lui rendent
  ×0,75). Chaque type doit avoir au moins une force et une faiblesse (vérifié au chargement).

## Capacités

Dans le bloc d'une espèce, des `[[species.ability]]` : `kind` = strike (dégâts, `power` 100 = un coup normal),
guard (défense +`value` % pendant 2 tours), heal (`value` % des PV max), haste (vitesse +`value` % pendant 2 tours),
drain (dégâts `power`, soigne `value` % des dégâts) ; `stage` = stade où elle se débloque (baby, young, adult,
final) ; `branch` (facultatif) = seulement pour cette forme finale. Elles serviront aux duels (étape suivante).

## Ajouter un article de boutique

1. L'espèce dans `config/species.toml`, avec `rarity = "rare" | "epique" | "legendaire"` (pas `starter`), des stats
   de base au-dessus de celles des starters (300) et 3 à 4 capacités.
2. L'article dans `config/shop.toml` :

```toml
[[item]]
id = "oeuf_lucine"            # identifiant stable (gardé dans les achats)
kind = "pet"
species = "lucine"
price_points = 6000           # l'un ou l'autre, ou les deux
price_gems = 600
# random = true               # un tirage : seulement en points (refusé au chargement avec des gemmes)
```

3. Son illustration dans `frontend/src/pet-art.ts` (une fonction par espèce, enregistrée dans `SPECIES`) ; sans
   elle, une créature générique aux couleurs de son type.

Un familier de boutique s'achète une fois par compte, arrive en œuf, devient le familier actif ; son profil de
course (pour sa forme finale) compte à partir de l'achat.

## Gemmes et paiement

`payments.py` : `PaymentProvider.confirm(user, pack, request_id, receipt)` vérifie le paiement et renvoie une
preuve, gardée avec l'achat (un même reçu n'est jamais crédité deux fois). Seul un fournisseur factice existe :
`TRAILMAP_PAYMENTS=mock` (tout achat accepté, rien n'est facturé ; à réserver au développement), sinon l'achat de
gemmes répond 503. À brancher plus tard : achats intégrés App Store (obligatoires dans l'app iOS pour une
monnaie virtuelle), Stripe sur le web. Packs de gemmes : `[[gem_pack]]` dans `shop.toml`.

## Combats contre des bots

Tour par tour, résolus par le serveur (`combat.py`, `battles.py`) ; le front (`frontend/src/battle.ts`) ne fait
que choisir l'attaque et rejouer les événements renvoyés (animations).

- **Kit par type** (`config/moves.toml`, `[kits]`) : 2 attaques + 1 défense par type, chacune avec son animation
  (`anim`, dessinée par les classes `.fx-<anim>` de `style.css`). Un familier combat avec le kit de son type (celui
  de sa forme finale une fois évolué), plus ses capacités spéciales débloquées (`species.toml`, recharge de
  `special_cooldown` tours) ; une défense attend `defense_cooldown` tour avant d'être rejouée.
- **Sentier de niveaux** (`config/battles.toml`) : 1 à 3 mobs sauvages (plus souvent en groupe en avançant), un
  boss intermédiaire tous les 5 niveaux, un grand boss tous les 10 (rage à mi-PV, + 2 renforts pour le grand). Les
  ennemis sont ramenés à la puissance d'un starter (`mob_total`) puis × `base_scale + per_level × niveau` (× le bonus
  de boss). Les ennemis d'un niveau sont toujours les mêmes.
- **Dégâts** : puissance / 100 × Att × Att / (Att + Déf) × efficacité du type × ±10 % (× 1,5 sur un critique,
  6 % + le bonus de l'attaque) ; ordre : attaques prioritaires, puis Vitesse.
- **Déterministe** : l'aléatoire d'un tour vient de `Random(f"{graine}:{tour}")` ; un combat garde son état initial
  et les coups joués : `Battles.check_replay` rejoue et compare.
- **Gains** : première victoire d'un niveau `reward_base + reward_per_level × niveau` points (× 3 boss, × 5 grand
  boss), rejouer : 25 % ; `daily_rewarded` victoires récompensées par jour (la progression continue au-delà).

Équilibrage : modifier `battles.toml` et vérifier avec une simulation (pour chaque familier type, le taux de victoire
par niveau, en choisissant à chaque tour l'attaque la plus forte) : bébé ~niveaux 1–5, jeune ~8–15, adulte ~20,
forme finale niveau 100 ~40–55.

## Ajouter un bot

- Un **mob** : ajouter son espèce à `mob_species` dans `battles.toml` (il prend l'apparence du stade du niveau).
- Un **boss** : un bloc `[[mid_boss]]` (niveaux 5, 15, 25…) ou `[[boss]]` (10, 20, 30…), dans l'ordre d'apparition :

```toml
[[boss]]
name = "Lucifère, Ombre des cols"
species = "lucine"
stage = "final"
branch = "eclipse"
summon = "galet"             # grand boss : les 2 renforts de sa seconde phase
```

Après la liste, les boss reviennent, plus forts (`+` dans leur nom).
