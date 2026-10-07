# Auto-hébergement — Trail Map sur le PC de la maison

Objectif : l'app tourne en continu sur le PC Windows (WSL2 Ubuntu), sans rien relancer à la main,
et n'est joignable **que** depuis le tailnet Tailscale (téléphone, autres appareils à soi).

```
téléphone ──(tailnet, HTTPS)──> tailscale serve (Windows) ──> http://localhost:8000 (Windows)
    ──(relais localhost de WSL)──> uvicorn 127.0.0.1:8000 (WSL, service systemd « trailmap »)
                                     ├─ /api/...   l'API
                                     └─ le reste   le front construit (frontend/dist)
```

## Dev et production

| | Dev (inchangé) | Production |
|---|---|---|
| Front | `npm run dev` (Vite, port 5173, rechargement à chaud) | `npm run build` → `frontend/dist`, servi par FastAPI |
| API | `uvicorn app.api:app --reload` (port 8000) | service systemd, `uvicorn` sans `--reload`, `127.0.0.1:8000` |
| Ports | 5173 (+ 8000 derrière le proxy Vite) | 8000 uniquement |

Les deux utilisent le port 8000 : **arrêter le service avant de travailler en dev**
(`sudo systemctl stop trailmap`), puis `./deploy-local.sh` (ou `sudo systemctl start trailmap`) ensuite.
Si `frontend/dist` n'existe pas, l'API ne sert que `/api` (comme avant).

Pourquoi `127.0.0.1` : en mode réseau `nat` de WSL (le nôtre, `wslinfo --networking-mode`),
Windows relaie son propre `localhost:8000` vers un port écouté sur `127.0.0.1` dans WSL. Le service
n'est donc joignable que depuis le PC lui-même : ni le réseau local ni Internet ne le voient.
Constaté sur ce PC : `curl.exe http://localhost:8000` répond depuis Windows. Vite, lui, écoute en IPv6
et ne répond que sur `localhost:5173` (pas sur `127.0.0.1:5173`). D'où la règle : Tailscale vise
toujours **`http://localhost:<port>`**.

## 1. Installation (une fois, dans WSL)

Prérequis : systemd activé dans WSL. C'est déjà le cas ici (`/etc/wsl.conf`) :

```ini
[boot]
systemd=true
```

(sinon : l'ajouter, puis `wsl --shutdown` dans PowerShell et rouvrir Ubuntu ; `systemctl is-system-running`
doit répondre `running` ou `degraded`).

Puis, depuis le dépôt :

```bash
./deploy-local.sh            # dépendances, build du front, tests, installe et démarre le service
```

Au premier lancement, le script appelle `deploy/install-service.sh`, qui écrit
`/etc/systemd/system/trailmap.service` à partir de `deploy/trailmap.service.in` (utilisateur et chemins
réels), puis `systemctl enable --now trailmap`. `sudo` demande le mot de passe.
Le service démarre avec WSL et redémarre tout seul s'il plante (`Restart=always`, après 5 s).

## 2. Démarrage automatique de WSL à l'ouverture de session Windows

WSL s'arrête quand plus aucun processus Windows ne l'utilise (terminal fermé). Une tâche planifiée lance
à l'ouverture de session un `sleep infinity` dans Ubuntu, dans une console invisible : WSL reste
allumé, et systemd démarre le service. Dans **PowerShell (utilisateur normal, pas besoin d'admin)** :

```powershell
$action = New-ScheduledTaskAction -Execute "C:\Windows\System32\conhost.exe" `
  -Argument "--headless C:\Windows\System32\wsl.exe -d Ubuntu --exec /bin/sleep infinity"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "WSL keep-alive (Trail Map)" -Action $action -Trigger $trigger `
  -Settings $settings -Description "Keeps WSL (and the trailmap systemd service) running"
Start-ScheduledTask -TaskName "WSL keep-alive (Trail Map)"   # tout de suite, sans attendre la prochaine session
```

- `conhost.exe --headless` : pas de fenêtre noire à l'ouverture de session (Windows 11).
- `ExecutionTimeLimit 0` : la tâche n'est jamais arrêtée au bout de 72 h (défaut de Windows).
- `RestartCount` / `RestartInterval` : relancée chaque minute si elle s'arrête (ex. après `wsl --shutdown`).

Vérifier / gérer :

```powershell
Get-ScheduledTask -TaskName "WSL keep-alive (Trail Map)" | Get-ScheduledTaskInfo   # LastRunTime, LastTaskResult
wsl -l -v                                                    # Ubuntu doit être « Running »
Stop-ScheduledTask -TaskName "WSL keep-alive (Trail Map)"    # laisse WSL s'éteindre ~1 min plus tard
Unregister-ScheduledTask -TaskName "WSL keep-alive (Trail Map)" -Confirm:$false   # supprimer
```

Limite : la tâche démarre à l'**ouverture de session** Windows. Après un redémarrage (ex. mise à jour
Windows), l'app ne revient qu'une fois la session ouverte. Activer la connexion automatique de Windows
n'est pas conseillé sur un portable.

## 3. Tailscale (côté Windows, PowerShell)

Remplacer l'ancien relais vers Vite (5173) par le port de production :

```powershell
tailscale serve --https=443 off
tailscale serve --bg http://localhost:8000
tailscale serve status        # doit afficher https://jules-laptop.tailf52fab.ts.net -> http://localhost:8000
```

`serve --bg` est persistant : il survit aux redémarrages de Tailscale et de Windows.
Pour revenir au mode dev depuis le téléphone : `tailscale serve --https=443 off` puis
`tailscale serve --bg http://localhost:5173`.

> ⚠️ **Ne JAMAIS utiliser `tailscale funnel`.** Funnel publie le service sur Internet pour n'importe qui :
> l'app n'a pas d'authentification, les traces (et donc les lieux fréquentés) seraient publiques.
> `tailscale serve` ne sert que les appareils du tailnet. En cas de doute : `tailscale funnel status`
> ne doit rien lister.

## 4. Alimentation Windows (portable)

Le PC doit rester allumé et ne pas se mettre en veille, même capot fermé. Dans **PowerShell** :

```powershell
# Capot fermé : ne rien faire (sur secteur ; ajouter la ligne DC pour la batterie aussi)
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
powercfg /setdcvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
# Jamais de veille ni de veille prolongée sur secteur (l'écran peut, lui, s'éteindre)
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /setactive SCHEME_CURRENT
```

Équivalent graphique : Panneau de configuration → Options d'alimentation → « Choisir l'action qui suit
la fermeture du capot » → « Ne rien faire » ; Paramètres → Système → Alimentation → Veille : « Jamais »
sur secteur. Laisser le portable sur secteur, ventilation dégagée.

## 5. Vérifier, redémarrer, mettre à jour

Dans WSL :

```bash
systemctl status trailmap                 # actif ? depuis quand ? derniers logs
journalctl -u trailmap -f                 # logs en direct (Ctrl+C pour quitter)
journalctl -u trailmap --since "1 hour ago"
curl -s http://127.0.0.1:8000/api/health  # état de l'app
sudo systemctl restart trailmap           # redémarrer (ex. après un import ou des tuiles OSM)
sudo systemctl stop trailmap              # arrêter (ex. pour travailler en dev)
./deploy-local.sh                         # mettre à jour : pull, dépendances, build, tests, redémarrage
./deploy-local.sh --no-pull               # idem avec le code local (sans git pull)
```

Depuis Windows (PowerShell) :

```powershell
curl.exe -I http://localhost:8000                  # HTTP/1.1 200 OK (le front)
curl.exe http://localhost:8000/api/health
curl.exe -I https://jules-laptop.tailf52fab.ts.net  # via Tailscale
```

`/api/health` (sans authentification, aucune donnée de trace) :

```json
{"status": "ok", "uptime_s": 3600, "activities": 254, "ingest_errors": 3, "frequency_ways": 3640,
 "routing": {"tiles_total": 176, "tiles_cached": 176, "running": false, "error": null, "jobs_running": 0},
 "frontend": true}
```

`deploy-local.sh` s'arrête à la première erreur : si les tests échouent, le service en place n'est pas
redémarré. Il attend ensuite jusqu'à 2 min que `/api/health` réponde (le premier démarrage reconstruit
le cache des activités, ~20 s).

## 6. Plus tard : un VPS (OVH)

La même structure s'applique telle quelle :

- `git clone` du dépôt et restauration de `data/` (dépôt privé Run-Project-Data), puis `./deploy-local.sh`
  (installe le service systemd avec l'utilisateur et les chemins du VPS ; `deploy/install-service.sh /chemin/data`
  pour des données ailleurs).
- Le service reste sur `127.0.0.1:8000`. On met devant soit Tailscale (`tailscale serve --bg http://localhost:8000`
  sur le VPS, même logique qu'ici), soit un reverse proxy HTTPS (Caddy / nginx) **avec une authentification**
  avant toute ouverture publique.
- Pas de WSL ni de tâche planifiée : systemd démarre le service au boot (`WantedBy=multi-user.target`).
- Pare-feu : n'ouvrir que 22 (et 443 si reverse proxy public).
