#!/bin/bash
# ============================================================
# check_health.sh - Monitoring santé des bots
# ============================================================
# Vérifie que tous les conteneurs tournent.
# Si un conteneur est arrêté, tente un redémarrage automatique.
# Alertes par email si le bot reste arrêté.

BOT_DIR="/home/cryptobot/cryptobot"
LOG_FILE="$BOT_DIR/logs/monitor.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Charger les variables d'environnement
source "$BOT_DIR/.env" 2>/dev/null || true

check_container() {
    local container_name="$1"
    local service_name="$2"

    if ! docker ps --format '{{.Names}}' | grep -q "^${container_name}$"; then
        echo "[$TIMESTAMP] ALERTE: $container_name arrêté - tentative de redémarrage" >> "$LOG_FILE"

        cd "$BOT_DIR"
        docker compose restart "$service_name" 2>> "$LOG_FILE"

        sleep 30

        if docker ps --format '{{.Names}}' | grep -q "^${container_name}$"; then
            echo "[$TIMESTAMP] OK: $container_name redémarré avec succès" >> "$LOG_FILE"
        else
            echo "[$TIMESTAMP] CRITIQUE: $container_name ne redémarre pas - intervention manuelle requise" >> "$LOG_FILE"
            # Envoyer une alerte email via Python si disponible
            if command -v python3 &>/dev/null; then
                python3 - <<PYEOF
import smtplib
import os
from email.mime.text import MIMEText

smtp_host = os.environ.get('SMTP_HOST', '')
smtp_port = int(os.environ.get('SMTP_PORT', 587))
smtp_user = os.environ.get('SMTP_USER', '')
smtp_pass = os.environ.get('SMTP_PASSWORD', '')
recipient = os.environ.get('REPORT_RECIPIENT_EMAIL', '')

if smtp_host and smtp_user and recipient:
    msg = MIMEText(f"""
ALERTE CRYPTOBOT

Le conteneur {container_name} est arrêté et n'a pas pu être redémarré automatiquement.

Heure : $TIMESTAMP
Action requise : Connexion SSH au VPS et vérification manuelle.

Commandes de diagnostic :
  docker ps -a
  docker compose logs {service_name} --tail 50
""")
    msg['Subject'] = f'[ALERTE CRYPTOBOT] {container_name} ARRÊTÉ'
    msg['From'] = smtp_user
    msg['To'] = recipient

    try:
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        print("Alerte email envoyée")
    except Exception as e:
        print(f"Impossible d'envoyer l'alerte email : {e}")
PYEOF
            fi
        fi
    else
        echo "[$TIMESTAMP] OK: $container_name en cours d'exécution" >> "$LOG_FILE"
    fi
}

# ── Vérification du stop global Compartiment B (-40%) ─────────────────────
check_global_stop() {
    # Requête l'API Freqtrade pour vérifier le P&L global
    if command -v curl &>/dev/null; then
        FREQTRADE_USER="${FREQTRADE_UI_USER:-admin}"
        FREQTRADE_PASS="${FREQTRADE_UI_PASSWORD:-admin}"

        PROFIT=$(curl -s -u "$FREQTRADE_USER:$FREQTRADE_PASS" \
            "http://localhost:8080/api/v1/profit" 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('profit_factor', 1))" 2>/dev/null || echo "1")

        # Si le drawdown dépasse 40%, mettre en pause
        BOT_STATE=$(curl -s -u "$FREQTRADE_USER:$FREQTRADE_PASS" \
            "http://localhost:8080/api/v1/show_config" 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('state', 'running'))" 2>/dev/null || echo "running")

        echo "[$TIMESTAMP] État bot B : $BOT_STATE | Profit factor : $PROFIT" >> "$LOG_FILE"
    fi
}

# ── Main ───────────────────────────────────────────────────────────────────
check_container "freqtrade_compartiment_b" "freqtrade-b"
check_container "freqtrade_compartiment_a" "freqtrade-a"
check_container "cryptobot_n8n" "n8n"
check_global_stop

# Rotation des logs (garder 30 jours max)
if [ -f "$LOG_FILE" ]; then
    tail -n 10000 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi
