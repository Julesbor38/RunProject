# Le jeu : familiers, points, (bientôt) duels et boutique

Tout est décidé par le serveur (`app/game/`) ; le front (`frontend/src/pet.ts`) ne fait qu'afficher.

- **Points** : gagnés en courant, en explorant, en visitant des lieux, avec les paliers et badges, en évaluant
  ses sorties (`app/explore/credits.py`, barème et plafond de 2 000 / mois). Jamais achetables.
- **Gemmes** : monnaie achetable (étape boutique, pas encore branchée). Les deux monnaies ne se mélangent jamais.
- **Portefeuille** (`wallet.py`) : soldes et journal (`transactions`) dans `data/game/game.sqlite`, mis à jour
  dans la même transaction SQLite ; une dépense ne passe que si le solde la couvre ; chaque ligne a une clé
  unique (un gain ou un achat rejoué ne compte jamais deux fois). **À sauvegarder.**
- **Familiers** (`pets.py`) : un starter choisi une fois ; on achète des niveaux avec des points (appui sur
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
# starter = true             # seulement pour les trois de départ (jamais vendus)

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

## Ajouter un bot ou un article de boutique

Étapes suivantes (duels, boutique) : `config/bots.toml` et `config/shop.toml`, décrits ici quand elles seront
faites. Règle déjà fixée : tout achat en gemmes ou en argent réel est déterministe ; un tirage aléatoire ne se
paie qu'en points, probabilités affichées.
