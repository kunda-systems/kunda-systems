#!/bin/bash
# ============================================================
# CRYPTOBOT - Script de setup VPS complet
# ============================================================
# Compatible : Ubuntu 22.04 LTS (Hetzner CX21 ou DigitalOcean)
# Lancer en root ou avec sudo : bash setup_vps.sh
#
# Ce script installe et configure :
#   1. Sécurité SSH (firewall UFW, fail2ban)
#   2. Docker & Docker Compose
#   3. Le projet CryptoBot
#   4. Les variables d'environnement
#   5. Le monitoring uptime
# ============================================================

set -euo pipefail

# ── Couleurs pour les logs ─────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ── Vérifications préliminaires ────────────────────────────────────────────
check_prerequisites() {
    log_info "Vérification des prérequis..."

    if [[ $EUID -ne 0 ]]; then
        log_error "Ce script doit être exécuté en root. Relancer avec : sudo bash setup_vps.sh"
    fi

    if ! grep -q "Ubuntu 22" /etc/os-release 2>/dev/null; then
        log_warn "Ce script est testé sur Ubuntu 22.04. Continuer ? (y/N)"
        read -r confirm
        [[ "$confirm" == "y" ]] || exit 0
    fi

    log_success "Prérequis OK"
}

# ── Mise à jour système ────────────────────────────────────────────────────
update_system() {
    log_info "Mise à jour du système..."
    apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get upgrade -yq
    apt-get install -yq \
        curl wget git unzip htop vim \
        ufw fail2ban \
        python3 python3-pip \
        build-essential
    log_success "Système à jour"
}

# ── Sécurisation SSH ───────────────────────────────────────────────────────
secure_ssh() {
    log_info "Configuration de la sécurité SSH..."

    # Désactiver l'authentification par mot de passe (clé SSH uniquement)
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
    sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
    sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config

    # Désactiver le login root direct (connexion via utilisateur dédié)
    sed -i 's/PermitRootLogin yes/PermitRootLogin without-password/' /etc/ssh/sshd_config

    systemctl reload sshd
    log_success "SSH sécurisé (clé uniquement, root sans mot de passe)"
}

# ── Configuration du pare-feu UFW ─────────────────────────────────────────
setup_firewall() {
    log_info "Configuration du pare-feu UFW..."

    # Règles par défaut
    ufw default deny incoming
    ufw default allow outgoing

    # SSH (IMPORTANT : à faire avant d'activer UFW !)
    ufw allow 22/tcp comment "SSH"

    # Ports internes uniquement (accès via tunnel SSH)
    # NE PAS ouvrir 8080, 8081, 5678 au public - accès via SSH tunnel

    ufw --force enable
    ufw status verbose

    # Fail2ban (protection brute-force)
    systemctl enable fail2ban
    systemctl start fail2ban

    log_success "Pare-feu actif : seul le port 22 (SSH) est ouvert"
    log_warn "Pour accéder aux interfaces web, utiliser un tunnel SSH :"
    log_warn "  ssh -L 8080:localhost:8080 -L 5678:localhost:5678 root@VOTRE_IP"
}

# ── Création d'un utilisateur dédié ───────────────────────────────────────
create_bot_user() {
    log_info "Création de l'utilisateur 'cryptobot'..."

    if id "cryptobot" &>/dev/null; then
        log_warn "Utilisateur 'cryptobot' existe déjà, skip"
    else
        useradd -m -s /bin/bash cryptobot
        usermod -aG sudo cryptobot
        usermod -aG docker cryptobot
        log_success "Utilisateur 'cryptobot' créé"
    fi
}

# ── Installation Docker ────────────────────────────────────────────────────
install_docker() {
    log_info "Installation de Docker..."

    if command -v docker &>/dev/null; then
        log_warn "Docker déjà installé : $(docker --version)"
    else
        curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
        sh /tmp/get-docker.sh
        rm /tmp/get-docker.sh
        systemctl enable docker
        systemctl start docker
        log_success "Docker installé : $(docker --version)"
    fi

    if command -v docker compose &>/dev/null; then
        log_warn "Docker Compose déjà installé"
    else
        # Docker Compose v2 (plugin intégré dans Docker moderne)
        apt-get install -yq docker-compose-plugin
        log_success "Docker Compose installé : $(docker compose version)"
    fi
}

# ── Déploiement du projet ──────────────────────────────────────────────────
deploy_project() {
    log_info "Déploiement du projet CryptoBot..."

    BOT_DIR="/home/cryptobot/cryptobot"

    # Copier les fichiers du projet (si lancé depuis le dossier du projet)
    if [ -f "$(dirname "$0")/docker-compose.yml" ]; then
        cp -r "$(dirname "$0")" "$BOT_DIR"
        chown -R cryptobot:cryptobot "$BOT_DIR"
        log_success "Fichiers copiés vers $BOT_DIR"
    else
        # Créer la structure si les fichiers ne sont pas là
        mkdir -p "$BOT_DIR"/{freqtrade/strategies,n8n/workflows,reporting,scripts}
        chown -R cryptobot:cryptobot "$BOT_DIR"
        log_warn "Structure créée dans $BOT_DIR - copier manuellement les fichiers du projet"
    fi
}

# ── Configuration des variables d'environnement ────────────────────────────
setup_env() {
    BOT_DIR="/home/cryptobot/cryptobot"
    ENV_FILE="$BOT_DIR/.env"

    log_info "Configuration des variables d'environnement..."

    if [ -f "$ENV_FILE" ]; then
        log_warn "Fichier .env existe déjà - skip"
        return
    fi

    if [ -f "$BOT_DIR/.env.example" ]; then
        cp "$BOT_DIR/.env.example" "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        chown cryptobot:cryptobot "$ENV_FILE"
        log_warn ""
        log_warn "========================================================"
        log_warn "ÉTAPE MANUELLE REQUISE"
        log_warn "========================================================"
        log_warn "Éditer le fichier : $ENV_FILE"
        log_warn "Commande : nano $ENV_FILE"
        log_warn ""
        log_warn "Remplir au minimum :"
        log_warn "  - BINANCE_API_KEY"
        log_warn "  - BINANCE_API_SECRET"
        log_warn "  - FREQTRADE_UI_PASSWORD (changer l'exemple !)"
        log_warn "  - ANTHROPIC_API_KEY (pour les rapports)"
        log_warn "========================================================"
    fi
}

# ── Génération des tokens aléatoires ──────────────────────────────────────
generate_secrets() {
    log_info "Génération des secrets aléatoires..."
    BOT_DIR="/home/cryptobot/cryptobot"
    ENV_FILE="$BOT_DIR/.env"

    if [ -f "$ENV_FILE" ]; then
        JWT_SECRET=$(openssl rand -hex 32)
        WS_TOKEN=$(openssl rand -hex 16)
        JWT_SECRET_A=$(openssl rand -hex 32)
        WS_TOKEN_A=$(openssl rand -hex 16)

        sed -i "s/generez_une_chaine_aleatoire_de_32_chars_ici/$JWT_SECRET/" "$ENV_FILE"
        sed -i "s/generez_un_autre_token_aleatoire_ici/$WS_TOKEN/" "$ENV_FILE"
        sed -i "s/generez_encore_une_autre_chaine_32_chars/$JWT_SECRET_A/" "$ENV_FILE"
        sed -i "s/generez_un_autre_token_pour_compartiment_a/$WS_TOKEN_A/" "$ENV_FILE"

        log_success "Tokens JWT et WS générés automatiquement"
    fi
}

# ── Installation des dépendances Python (reporting) ───────────────────────
install_python_deps() {
    log_info "Installation des dépendances Python..."

    pip3 install --break-system-packages \
        anthropic \
        python-binance \
        pandas \
        requests \
        schedule \
        smtplib 2>/dev/null || pip3 install \
        anthropic \
        python-binance \
        pandas \
        requests \
        schedule

    log_success "Dépendances Python installées"
}

# ── Script de monitoring & redémarrage automatique ────────────────────────
setup_monitoring() {
    log_info "Configuration du monitoring..."

    cat > /etc/cron.d/cryptobot-monitor << 'CRON'
# Vérification toutes les 5 minutes que les bots tournent
*/5 * * * * cryptobot /home/cryptobot/cryptobot/scripts/check_health.sh >> /home/cryptobot/cryptobot/logs/monitor.log 2>&1

# Backup hebdomadaire (dimanche à 3h)
0 3 * * 0 cryptobot /home/cryptobot/cryptobot/scripts/backup.sh >> /home/cryptobot/cryptobot/logs/backup.log 2>&1
CRON

    mkdir -p /home/cryptobot/cryptobot/logs
    chown -R cryptobot:cryptobot /home/cryptobot/cryptobot/logs

    log_success "Monitoring cron configuré"
}

# ── Démarrage des services ─────────────────────────────────────────────────
start_services() {
    BOT_DIR="/home/cryptobot/cryptobot"

    log_warn ""
    log_warn "========================================================"
    log_warn "AVANT DE DÉMARRER : Vérifier que .env est configuré !"
    log_warn "Commande : cat $BOT_DIR/.env"
    log_warn "========================================================"
    echo ""
    read -p "Les variables d'environnement sont-elles configurées ? (y/N) : " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "Démarrage en mode DRY-RUN (simulation - aucun argent réel)..."
        cd "$BOT_DIR"
        sudo -u cryptobot docker compose up -d

        log_success ""
        log_success "========================================================"
        log_success "Bot démarré en mode DRY-RUN !"
        log_success "========================================================"
        log_success ""
        log_success "Accéder aux interfaces (via tunnel SSH) :"
        log_success "  FreqUI Comp B : http://localhost:8080"
        log_success "  FreqUI Comp A : http://localhost:8081"
        log_success "  n8n           : http://localhost:5678"
        log_success ""
        log_success "Tunnel SSH : ssh -L 8080:localhost:8080 -L 8081:localhost:8081 -L 5678:localhost:5678 root@VOTRE_IP_VPS"
        log_success ""
        log_success "Logs : docker compose logs -f freqtrade-b"
        log_success "========================================================"
    else
        log_warn "Services non démarrés. Démarrer manuellement avec :"
        log_warn "  cd $BOT_DIR && docker compose up -d"
    fi
}

# ── Résumé final ───────────────────────────────────────────────────────────
print_summary() {
    echo ""
    echo -e "${GREEN}============================================================${NC}"
    echo -e "${GREEN}  SETUP TERMINÉ - Récapitulatif${NC}"
    echo -e "${GREEN}============================================================${NC}"
    echo ""
    echo "Prochaines étapes manuelles :"
    echo "  1. Éditer .env : nano /home/cryptobot/cryptobot/.env"
    echo "  2. Ajouter vos clés API Binance (droits Spot Trading uniquement !)"
    echo "  3. Démarrer : cd /home/cryptobot/cryptobot && docker compose up -d"
    echo "  4. Lancer le backtesting (voir README.md)"
    echo "  5. Observer le dry-run pendant 2 semaines"
    echo "  6. Passer en mode réel uniquement si résultats satisfaisants"
    echo ""
    echo -e "${RED}RAPPEL SÉCURITÉ :${NC}"
    echo "  - Les clés API Binance ne doivent JAMAIS avoir les droits de retrait"
    echo "  - Le .env ne doit JAMAIS être partagé ou committé dans git"
    echo "  - Accéder aux interfaces uniquement via tunnel SSH"
    echo ""
}

# ── Main ───────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo -e "${BLUE}============================================================${NC}"
    echo -e "${BLUE}  CRYPTOBOT - Setup VPS Ubuntu 22.04${NC}"
    echo -e "${BLUE}============================================================${NC}"
    echo ""

    check_prerequisites
    update_system
    secure_ssh
    setup_firewall
    create_bot_user
    install_docker
    deploy_project
    setup_env
    generate_secrets
    install_python_deps
    setup_monitoring
    start_services
    print_summary
}

main "$@"
