# Workflows n8n - CryptoBot

## Comment importer ces workflows

1. Ouvrir n8n : http://localhost:5678 (via tunnel SSH)
2. Aller dans **Workflows** → **Import from file**
3. Importer chaque fichier JSON

## Workflows disponibles

### 1. `monthly_transfer.json`
**Déclencheur** : 1er du mois à 6h00
**Action** :
- Récupère le profit total du Compartiment B via API Freqtrade
- Note le montant dans Google Sheets
- Envoie une notification de confirmation

**Note** : Le transfert réel B→A se fait manuellement sur Binance (ou via un script Python séparé). n8n gère le déclenchement et le logging.

### 2. `weekly_report.json`
**Déclencheur** : Chaque lundi à 7h00
**Action** :
- Exécute `weekly_report.py` sur le VPS
- Le script génère et envoie le rapport email via Claude API

### 3. `monthly_report.json`
**Déclencheur** : 1er du mois à 8h00
**Action** :
- Exécute `monthly_report.py` sur le VPS
- Rapport mensuel complet avec projection mise à jour

### 4. `stop_global_monitor.json`
**Déclencheur** : Toutes les heures
**Action** :
- Vérifie le P&L global du Compartiment B
- Si drawdown > 40% : met le bot en pause via API Freqtrade
- Envoie une alerte email immédiate
