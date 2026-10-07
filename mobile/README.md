# Trail Map — app iPhone (prototype)

Enveloppe native (Capacitor) autour de l'app web : elle affiche Trail Map depuis le serveur
(`server.url` dans `capacitor.config.json`, via Tailscale) et ajoute une seule chose qu'une page web
ne peut pas faire : **« Envoyer à ma montre » ouvre le menu « Ouvrir dans… » d'iOS** sur le GPX,
celui de l'app Fichiers, où apparaissent les apps de montre (COROS, Garmin Connect, Suunto…).
Le module natif est `ios/App/App/SceneDelegate.swift` (`OpenInPlugin`) ; côté web, `frontend/src/share.ts`.

## Compilation (sans Mac)

GitHub Actions (`.github/workflows/ios-app.yml`, macOS gratuit pour un dépôt public) compile l'app
**non signée** à chaque changement de `mobile/`, ou à la main : onglet *Actions* → *iOS app (AltStore)* →
*Run workflow*. Le fichier `TrailMap.ipa` est dans les *Artifacts* du run (archive .zip à décompresser).

## Installation avec AltStore (gratuit, depuis le PC Windows)

Une fois :
1. Sur le PC : installer **iTunes** et **iCloud** depuis le site d'Apple (pas la version Microsoft Store),
   puis **AltServer** (https://altstore.io), qui se loge dans la barre des tâches.
2. Brancher l'iPhone en USB, accepter « Faire confiance à cet ordinateur ».
3. Icône AltServer → *Install AltStore* → l'iPhone → identifiant Apple (envoyé seulement à Apple).
4. Sur l'iPhone : Réglages → Général → VPN et gestion de l'appareil → faire confiance à son identifiant ;
   puis Réglages → Confidentialité et sécurité → **Mode développeur** → activer (redémarrage).

À chaque nouvelle version :
1. Télécharger `TrailMap.ipa` (Artifacts du run GitHub), le mettre sur l'iPhone (iCloud Drive, ou AirDrop).
2. Dans **AltStore** → *My Apps* → **+** → choisir `TrailMap.ipa`.
   (Ou sur le PC : icône AltServer, Maj + clic → *Sideload .ipa…*.)

Limites d'un identifiant Apple gratuit : la signature dure **7 jours** ; AltStore la renouvelle tout seul
si l'iPhone et le PC (AltServer lancé) sont sur le même Wi-Fi. 3 apps installées ainsi au maximum.
**Tailscale** doit être connecté sur l'iPhone (l'app charge Trail Map depuis le PC).

## Développement

```bash
cd mobile && npm install
npx cap sync ios        # après un changement de capacitor.config.json
```
