# 🤖 CryptoBot - Guide de Déploiement

**Architecture double compartiment | Freqtrade + n8n + Claude API**

---

## Vue d'ensemble

```
Compartiment A (Le Coffre)         Compartiment B (Le Moteur)
━━━━━━━━━━━━━━━━━━━━━━━━━━         ━━━━━━━━━━━━━━━━━━━━━━━━━━
BTC 60% / ETH 40%                  BTC/USDT 40%
DCA mensuel automatique            ETH/USDT 35%
Horizon : 24 mois min              SOL/USDT 25%
Capital : ~1 000 €                 Stratégie : ADX Hybride
                                   Capital : ~500 €
         ←── Gains B (mensuel) ───┘
```

---

## Étape 1 — Créer le VPS Hetzner (5 min, manuel)

1. Aller sur **hetzner.com** → Cloud → Créer un projet
2. Ajouter un serveur :
   - **Type** : CX21 (~5€/mois, 2 vCPU / 4 Go RAM)
   - **Image** : Ubuntu 22.04
   - **SSH Key** : Ajouter ta clé publique (obligatoire — PAS de mot de passe)
   - **Région** : Nuremberg ou Helsinki
3. Cliquer sur **Create & Buy now**
4. Noter l'IP du VPS

> **Générer une clé SSH si tu n'en as pas :**
> ```bash
> ssh-keygen -t ed25519 -C "cryptobot"
> cat ~/.ssh/id_ed25519.pub   # Copier cette clé dans Hetzner
> ```

---

## Étape 2 — Créer les clés API Binance (5 min, manuel)

1. Binance → **Mon Compte** → **Gestion API** → Créer une API
2. Nom : `cryptobot`
3. **Droits à activer : Spot Trading UNIQUEMENT**
4. **Droits à NE JAMAIS activer : Activer les retraits**
5. Whitelist IP : ajouter l'IP de ton VPS (obligatoire)
6. Sauvegarder la clé et le secret (ils n'apparaissent qu'une fois)

> ⚠️ **RÈGLE ABSOLUE** : Sans droits de retrait, personne ne peut vider ton compte même si les clés sont compromises.

---

## Étape 3 — Déployer le bot (automatique)

### Connexion au VPS
```bash
ssh root@VOTRE_IP_VPS
```

### Copier les fichiers du projet
```bash
# Depuis ton Mac/PC local :
scp -r cryptobot/ root@VOTRE_IP_VPS:/root/
```

### Lancer le script de setup
```bash
ssh root@VOTRE_IP_VPS
chmod +x /root/cryptobot/setup_vps.sh
bash /root/cryptobot/setup_vps.sh
```

Le script installe automatiquement Docker, sécurise le VPS, configure le pare-feu et prépare l'environnement.

### Configurer les variables d'environnement
```bash
nano /home/cryptobot/cryptobot/.env
```

Remplir **obligatoirement** :
- `BINANCE_API_KEY` et `BINANCE_API_SECRET`
- `FREQTRADE_UI_PASSWORD` (changer l'exemple !)
- `ANTHROPIC_API_KEY` (pour les rapports)
- `SMTP_USER` / `SMTP_PASSWORD` (pour les emails)

---

## Étape 4 — Phase 1 : Backtesting (obligatoire)

### Démarrer les conteneurs en mode dry-run
```bash
cd /home/cryptobot/cryptobot
docker compose up -d
```

### Accéder aux interfaces (via tunnel SSH)
```bash
# Sur ton PC local :
ssh -L 8080:localhost:8080 -L 8081:localhost:8081 -L 5678:localhost:5678 root@VOTRE_IP_VPS
```
Puis ouvrir :
- FreqUI Compartiment B : http://localhost:8080
- FreqUI Compartiment A : http://localhost:8081
- n8n : http://localhost:5678

### Lancer le backtesting Compartiment B
```bash
docker exec freqtrade_compartiment_b \
  freqtrade backtesting \
  --strategy HybridADXStrategy \
  --config /freqtrade/user_data/config.json \
  --timerange 20230101-20240101 \
  --export trades
```

### Analyser les résultats
```bash
docker exec freqtrade_compartiment_b \
  freqtrade backtesting-analysis \
  --export-filename /freqtrade/user_data/backtest_results/
```

**Critères de validation :**
- Sharpe ratio > 1.0
- Max drawdown < 40%
- Profit factor > 1.5
- Taux de réussite > 50%

---

## Étape 5 — Phase 1 : Dry-run (2 semaines minimum)

Le bot démarre automatiquement en mode `dry_run: true` (argent fictif).

**Surveiller pendant 2 semaines :**
- Fréquence des trades (trop ou pas assez ?)
- Drawdown maximum atteint
- Cohérence entre backtesting et dry-run

```bash
# Voir les logs en temps réel :
docker compose logs -f freqtrade-b

# Stats en cours :
docker exec freqtrade_compartiment_b \
  freqtrade show-trades --db-url sqlite:////freqtrade/user_data/tradesv3_compartiment_b.sqlite
```

---

## Étape 6 — Passer en mode réel

**Uniquement si le dry-run est satisfaisant sur 2 semaines.**

### Désactiver le dry-run
Éditer les deux fichiers de config :
```bash
nano /home/cryptobot/cryptobot/freqtrade/config_compartiment_b.json
# Changer : "dry_run": true  →  "dry_run": false

nano /home/cryptobot/cryptobot/freqtrade/config_dca_compartiment_a.json
# Changer : "dry_run": true  →  "dry_run": false
```

### Redémarrer les bots
```bash
cd /home/cryptobot/cryptobot
docker compose restart
```

### Vérifier les premiers ordres
Dans FreqUI → onglet **Trades** : les premiers ordres réels devraient apparaître dans les minutes qui suivent.

---

## Étape 7 — Importer les workflows n8n

1. Ouvrir n8n : http://localhost:5678
2. **Workflows** → **Import** → Importer chaque fichier dans `n8n/workflows/`
3. Configurer les credentials dans n8n :
   - `FreqtradeAuth` : nom d'utilisateur et mot de passe FreqUI
   - `SMTP` : paramètres email
4. **Activer** les workflows (bouton toggle)

---

## Commandes utiles

```bash
# État des conteneurs
docker compose ps

# Logs en temps réel
docker compose logs -f freqtrade-b
docker compose logs -f freqtrade-a
docker compose logs -f n8n

# Redémarrer un service
docker compose restart freqtrade-b

# Arrêt d'urgence complet
docker compose down

# Arrêter uniquement les nouveaux achats (garder les trades ouverts)
curl -X POST -u admin:MOT_DE_PASSE http://localhost:8080/api/v1/stopbuy

# Reprendre après arrêt
curl -X POST -u admin:MOT_DE_PASSE http://localhost:8080/api/v1/start

# Voir les profits actuels
curl -u admin:MOT_DE_PASSE http://localhost:8080/api/v1/profit
```

---

## Structure des fichiers

```
cryptobot/
├── setup_vps.sh                          Script de setup VPS complet
├── docker-compose.yml                    Orchestration Docker
├── .env.example                          Template variables d'environnement
├── .env                                  Variables réelles (NE PAS PARTAGER)
│
├── freqtrade/
│   ├── config_compartiment_b.json        Config bot de trading actif
│   ├── config_dca_compartiment_a.json    Config DCA long terme
│   └── strategies/
│       ├── HybridADXStrategy.py          Stratégie hybride ADX/Grid/Momentum
│       └── DCAStrategy.py                Stratégie DCA Compartiment A
│
├── n8n/workflows/
│   ├── stop_global_monitor.json          Surveillance stop -40%
│   ├── weekly_report.json                Rapport lundi 7h
│   ├── monthly_transfer.json             Transfert B→A + rapport mensuel
│   └── README_n8n.md                     Guide d'import n8n
│
├── reporting/
│   ├── weekly_report.py                  Générateur rapport hebdomadaire
│   ├── monthly_report.py                 Générateur rapport mensuel
│   └── archives/                         Rapports archivés
│
└── scripts/
    ├── check_health.sh                   Monitoring santé des bots
    └── backup.sh                         Sauvegarde hebdomadaire
```

---

## Sécurité — Rappels essentiels

- **Clés API Binance** : droits Spot Trading uniquement, jamais de retrait
- **Fichier .env** : ne jamais committer dans git, ne jamais partager
- **Accès VPS** : uniquement via clé SSH, pas de mot de passe
- **Interfaces web** : jamais exposées sur internet, toujours via tunnel SSH
- **Stop global** : configuré à -40% sur Compartiment B, surveillance automatique toutes les heures

---

## Checklist de lancement

- [ ] VPS Hetzner créé et IP notée
- [ ] Clé SSH configurée sur le VPS
- [ ] Clés API Binance créées (droits limités, IP whitelist)
- [ ] Script `setup_vps.sh` exécuté avec succès
- [ ] Fichier `.env` configuré avec toutes les clés
- [ ] Conteneurs Docker démarrés (`docker compose up -d`)
- [ ] Backtesting lancé et résultats validés (Sharpe > 1, drawdown < 40%)
- [ ] Dry-run observé pendant 2 semaines minimum
- [ ] Workflows n8n importés et activés
- [ ] Mode réel activé (`dry_run: false`)
- [ ] Premier rapport hebdomadaire reçu

---

*Document technique privé. Ne constitue pas un conseil en investissement.*
*Les cryptomonnaies comportent un risque de perte totale du capital.*
