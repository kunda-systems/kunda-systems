#!/bin/bash
# ============================================================
# backup.sh - Sauvegarde hebdomadaire de la configuration
# ============================================================

BOT_DIR="/home/cryptobot/cryptobot"
BACKUP_DIR="/home/cryptobot/backups"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
BACKUP_FILE="$BACKUP_DIR/cryptobot_backup_$TIMESTAMP.tar.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Démarrage de la sauvegarde..."

# Sauvegarder configs, stratégies et bases de données (exclure .env pour sécurité)
tar -czf "$BACKUP_FILE" \
    --exclude="$BOT_DIR/.env" \
    --exclude="$BOT_DIR/logs" \
    "$BOT_DIR/freqtrade" \
    "$BOT_DIR/n8n" \
    "$BOT_DIR/reporting" \
    "$BOT_DIR/scripts" \
    "$BOT_DIR/docker-compose.yml" \
    2>/dev/null

# Sauvegarder aussi les bases SQLite Freqtrade
docker cp freqtrade_compartiment_b:/freqtrade/user_data/tradesv3_compartiment_b.sqlite \
    "$BACKUP_DIR/trades_b_$TIMESTAMP.sqlite" 2>/dev/null || true

docker cp freqtrade_compartiment_a:/freqtrade/user_data/tradesv3_compartiment_a.sqlite \
    "$BACKUP_DIR/trades_a_$TIMESTAMP.sqlite" 2>/dev/null || true

echo "[$(date)] Sauvegarde terminée : $BACKUP_FILE"

# Garder seulement les 8 dernières sauvegardes
ls -t "$BACKUP_DIR"/cryptobot_backup_*.tar.gz 2>/dev/null | tail -n +9 | xargs rm -f

echo "[$(date)] Sauvegardes anciennes supprimées. Sauvegardes actives :"
ls -lh "$BACKUP_DIR"/*.tar.gz 2>/dev/null || echo "Aucune sauvegarde"
