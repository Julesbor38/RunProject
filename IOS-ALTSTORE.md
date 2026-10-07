# RunProject sur iPhone — app native installée avec AltStore

L'app iOS est l'app web de RunProject dans une enveloppe native (Capacitor, `frontend/ios/`). Elle ajoute ce
qu'une page web ne peut pas faire : **« Envoyer à ma montre » partage un vrai fichier .gpx** depuis la feuille
de partage native, sans jamais remplacer l'app par un aperçu de fichier.

- **Pas de Mac** : l'app est compilée par GitHub Actions (`.github/workflows/ios.yml`, macOS gratuit pour un
  dépôt public), **sans signature** ; AltStore la signe avec un identifiant Apple gratuit à l'installation.
- **Rien de personnel dans l'app** (le dépôt et les .ipa sont publics) : l'adresse du serveur se tape au premier
  lancement et reste sur le téléphone ; la compilation échoue si un nom de machine ou un jeton s'y trouvait.
- **Tailscale** doit être actif sur l'iPhone : l'app parle au serveur RunProject du PC
  (`https://<pc>.<tailnet>.ts.net`). Sinon : écran « Active Tailscale sur ton iPhone » et bouton Réessayer.

## 1. Lancer la compilation

- **À la main** : GitHub → dépôt RunProject → onglet **Actions** → **iOS (AltStore)** → **Run workflow** (branche
  `main`) → ~10 min.
- **Avec un tag** : `git tag v0.2.0 && git push origin v0.2.0` → même compilation, plus une **Release GitHub**
  avec `RunProject.ipa` attaché (version 0.2.0).

Numéro de build : le numéro du run GitHub (augmente à chaque compilation). Version : celle du tag, sinon
`frontend/package.json`.

## 2. Récupérer le .ipa

- Run manuel : page du run → section **Artifacts** → `RunProject-ipa-<version>-<build>` (un .zip contenant
  `RunProject.ipa`, gardé 30 jours ; il faut être connecté à GitHub).
- Tag : page **Releases** du dépôt → `RunProject.ipa`.

## 3. Installer AltStore (une fois)

Sur le PC Windows :
1. Installer **iTunes** et **iCloud** depuis le site d'Apple (pas les versions du Microsoft Store).
2. Installer **AltServer** (https://altstore.io) ; il s'ouvre dans la barre des tâches, près de l'horloge.
3. Brancher l'iPhone en USB, le déverrouiller, accepter « Faire confiance à cet ordinateur ».
4. Icône AltServer → **Install AltStore** → choisir l'iPhone → identifiant Apple et mot de passe
   (envoyés uniquement à Apple).

Sur l'iPhone :
5. Réglages → Général → **VPN et gestion de l'appareil** → son identifiant Apple → **Faire confiance**.
6. Réglages → Confidentialité et sécurité → **Mode développeur** → activer, redémarrer, confirmer.
7. Dans AltStore → Réglages : se connecter avec le même identifiant Apple.

## 4. Installer ou mettre à jour RunProject

1. Mettre `RunProject.ipa` sur l'iPhone : par exemple, le déposer dans iCloud Drive depuis le PC, ou
   l'ouvrir directement depuis la page Releases dans Safari (« Télécharger »).
2. **AltStore** → onglet **My Apps** → **+** → choisir `RunProject.ipa` (dans Fichiers).
   Autre possibilité, depuis le PC : iPhone branché, icône AltServer, **Maj + clic** → **Sideload .ipa…**.
3. Premier lancement : taper l'adresse du serveur (`<pc>.<tailnet>.ts.net`, sans `https://` ni `/app/`), puis
   se connecter avec son compte RunProject.

Une mise à jour s'installe de la même façon par-dessus : les données de l'app (adresse, session) sont gardées.

## 5. Limites d'un identifiant Apple gratuit

- La signature dure **7 jours**. AltStore la renouvelle tout seul quand l'iPhone et le PC (AltServer lancé)
  sont sur le **même Wi-Fi** ; sinon : AltStore → My Apps → **Refresh All**. Une app expirée ne s'ouvre plus
  (rien n'est perdu : la renouveler suffit).
- **3 apps** signées ainsi au maximum sur l'iPhone (AltStore compte pour une).
- Le compte développeur Apple (99 $/an) supprimerait ces limites et permettrait TestFlight (voir ROADMAP.md).

## Développement

```bash
cd frontend
npm run build:native     # build web pour l'app : base « / », dans dist-native/ (dist/ = le web, servi sous /app/)
npx cap sync ios         # copie dist-native et les plugins dans ios/
```

En natif, les appels vont à `<serveur>/api/…` avec `Authorization: Bearer <jeton>` (`src/native.ts`) ; le
serveur n'accepte que l'origine `capacitor://localhost` en plus de Vite (CORS, `backend/app/api.py`).
