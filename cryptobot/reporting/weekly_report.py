"""
weekly_report.py - Rapport hebdomadaire CryptoBot
===================================================
Déclenché chaque lundi matin par n8n.
Récupère les données Freqtrade, les analyse via Claude API,
et envoie un rapport par email.

Usage : python3 weekly_report.py
"""

import json
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests

# ── Configuration ──────────────────────────────────────────────────────────
FREQTRADE_B_URL = "http://localhost:8080/api/v1"
FREQTRADE_A_URL = "http://localhost:8081/api/v1"
FREQTRADE_USER = os.environ.get("FREQTRADE_UI_USER", "admin")
FREQTRADE_PASS = os.environ.get("FREQTRADE_UI_PASSWORD", "")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
RECIPIENT = os.environ.get("REPORT_RECIPIENT_EMAIL", "yd@kunda.io")


def get_freqtrade_data(base_url: str) -> dict:
    """Récupère les données de performance depuis l'API Freqtrade."""
    auth = (FREQTRADE_USER, FREQTRADE_PASS)
    data = {}

    endpoints = {
        "profit": "/profit",
        "trades": "/trades?limit=50",
        "performance": "/performance",
        "balance": "/balance",
        "status": "/status",
        "config": "/show_config",
    }

    for key, endpoint in endpoints.items():
        try:
            response = requests.get(f"{base_url}{endpoint}", auth=auth, timeout=10)
            if response.status_code == 200:
                data[key] = response.json()
            else:
                data[key] = {"error": f"HTTP {response.status_code}"}
        except Exception as e:
            data[key] = {"error": str(e)}

    return data


def format_data_for_claude(comp_b: dict, comp_a: dict, week_start: str, week_end: str) -> str:
    """Prépare les données brutes pour Claude."""

    def safe_get(d: dict, *keys, default="N/A"):
        for key in keys:
            if isinstance(d, dict):
                d = d.get(key, {})
            else:
                return default
        return d if d != {} else default

    profit_b = comp_b.get("profit", {})
    balance_b = comp_b.get("balance", {})
    trades_b = comp_b.get("trades", {}).get("trades", [])

    # Filtrer les trades de la semaine
    week_trades = [
        t for t in trades_b
        if t.get("close_date", "") >= week_start
    ]

    winning_trades = [t for t in week_trades if t.get("profit_ratio", 0) > 0]
    losing_trades = [t for t in week_trades if t.get("profit_ratio", 0) <= 0]

    profit_a = comp_a.get("profit", {})
    balance_a = comp_a.get("balance", {})

    data_summary = f"""
DONNÉES PERFORMANCE - SEMAINE DU {week_start} AU {week_end}

=== COMPARTIMENT B (LE MOTEUR - TRADING ACTIF) ===
Capital actuel : {safe_get(balance_b, 'total')} USDT
Profit total cumulé : {safe_get(profit_b, 'profit_all_coin')} USDT
Profit total (%) : {safe_get(profit_b, 'profit_all_percent_mean')}%
Profit cette semaine (estimé) : calculé sur {len(week_trades)} trades fermés

Trades cette semaine :
  - Total : {len(week_trades)}
  - Gagnants : {len(winning_trades)} ({len(winning_trades)/max(len(week_trades),1)*100:.1f}%)
  - Perdants : {len(losing_trades)} ({len(losing_trades)/max(len(week_trades),1)*100:.1f}%)

Top trades gagnants cette semaine :
{chr(10).join([f"  + {t.get('pair','?')} : +{t.get('profit_ratio',0)*100:.2f}% ({t.get('open_date','?')[:10]})" for t in sorted(winning_trades, key=lambda x: x.get('profit_ratio',0), reverse=True)[:5]]) or "  Aucun"}

Trades perdants cette semaine :
{chr(10).join([f"  - {t.get('pair','?')} : {t.get('profit_ratio',0)*100:.2f}% ({t.get('open_date','?')[:10]})" for t in sorted(losing_trades, key=lambda x: x.get('profit_ratio',0))[:5]]) or "  Aucun"}

Nombre total de trades (historique) : {safe_get(profit_b, 'trade_count')}
Meilleur trade : {safe_get(profit_b, 'best_pair')} à {safe_get(profit_b, 'best_rate')}%
Max drawdown : {safe_get(profit_b, 'max_drawdown')}%

=== COMPARTIMENT A (LE COFFRE - DCA LONG TERME) ===
Capital actuel : {safe_get(balance_a, 'total')} USDT
Valeur totale (BTC+ETH) : {safe_get(profit_a, 'profit_all_coin')} USDT
Évolution depuis début : {safe_get(profit_a, 'profit_all_percent_mean')}%

=== CONTEXTE MARCHÉ ===
(Les données de marché BTC/ETH/SOL seront à insérer ici via n8n)
"""
    return data_summary


def generate_report_with_claude(data_summary: str, week_start: str) -> str:
    """Génère le rapport narratif via Claude API."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Tu es l'assistant analytique d'un bot de trading crypto personnel.
Voici les données de performance de la semaine du {week_start}.

{data_summary}

Génère un rapport hebdomadaire clair et utile en français, structuré ainsi :

## 📊 Résumé de la semaine

[2-3 phrases résumant les points clés de la semaine]

## ✅ Ce qui a bien fonctionné

[Analyse des points positifs : trades gagnants, paires performantes, comportement de la stratégie]

## ⚠️ Points d'attention

[Trades perdants, anomalies, comportements inhabituels à surveiller]

## 📈 État des compartiments

[Statut Compartiment A (coffre) et Compartiment B (moteur), évolution vs semaine précédente]

## 🎯 Recommandations

[0 à 3 recommandations concrètes si pertinent. Sinon : "Aucun ajustement recommandé cette semaine."]

---
Règles de rédaction :
- Ton direct, factuel, pas de jargon excessif
- Chiffres précis quand disponibles
- Si les données sont manquantes ou en erreur, le mentionner clairement
- Ne pas inventer de données non fournies
- Longueur : 300-500 mots maximum
"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text


def send_email(subject: str, html_body: str, text_body: str):
    """Envoie le rapport par email."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = RECIPIENT

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)

    print(f"Rapport envoyé à {RECIPIENT}")


def markdown_to_html(md_text: str) -> str:
    """Conversion simple Markdown → HTML pour l'email."""
    lines = md_text.split("\n")
    html_lines = []
    for line in lines:
        if line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("- "):
            html_lines.append(f"<li>{line[2:]}</li>")
        elif line.strip() == "---":
            html_lines.append("<hr>")
        elif line.strip() == "":
            html_lines.append("<br>")
        else:
            html_lines.append(f"<p>{line}</p>")

    html = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; padding: 20px;">
    <div style="background: #1a1a2e; color: #eee; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
        <h1 style="color: #f0c040; margin: 0;">🤖 CryptoBot - Rapport Hebdomadaire</h1>
        <p style="color: #aaa; margin: 5px 0 0 0;">Généré automatiquement par Claude AI</p>
    </div>
    {"".join(html_lines)}
    <div style="background: #f5f5f5; padding: 10px; border-radius: 5px; margin-top: 20px; font-size: 12px; color: #888;">
        Ce rapport est généré automatiquement. Les performances passées ne garantissent pas les performances futures.
        Les cryptomonnaies sont des actifs hautement volatils.
    </div>
    </body></html>
    """
    return html


def main():
    now = datetime.now()
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    week_end = now.strftime("%Y-%m-%d")

    print(f"[{now}] Génération du rapport hebdomadaire ({week_start} → {week_end})...")

    # Récupération des données
    print("Récupération des données Freqtrade...")
    comp_b_data = get_freqtrade_data(FREQTRADE_B_URL)
    comp_a_data = get_freqtrade_data(FREQTRADE_A_URL)

    # Préparation du résumé
    data_summary = format_data_for_claude(comp_b_data, comp_a_data, week_start, week_end)

    # Génération du rapport via Claude
    print("Génération du rapport via Claude API...")
    report_text = generate_report_with_claude(data_summary, week_start)

    # Envoi email
    subject = f"🤖 CryptoBot | Rapport semaine du {week_start}"
    html_body = markdown_to_html(report_text)

    if SMTP_USER and SMTP_PASSWORD:
        print("Envoi de l'email...")
        send_email(subject, html_body, report_text)
    else:
        print("Email non configuré - rapport affiché dans la console :")
        print("=" * 60)
        print(report_text)
        print("=" * 60)

    # Sauvegarder le rapport localement
    report_dir = os.path.join(os.path.dirname(__file__), "archives")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, f"weekly_{week_start}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Rapport hebdomadaire {week_start}\n\n")
        f.write(report_text)
    print(f"Rapport archivé : {report_path}")


if __name__ == "__main__":
    main()
