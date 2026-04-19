"""
monthly_report.py - Rapport mensuel CryptoBot
===============================================
Déclenché le 1er de chaque mois par n8n.
Analyse plus profonde + projection 24 mois mise à jour.

Usage : python3 monthly_report.py
"""

import json
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests

# ── Configuration (identique à weekly_report.py) ──────────────────────────
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

# ── Paramètres du projet ───────────────────────────────────────────────────
CAPITAL_INITIAL = 1500     # EUR
APPORT_MENSUEL = 300       # EUR
HORIZON_MOIS = 24
DATE_DEBUT = "2026-05-01"  # Date de démarrage du bot (à ajuster)


def get_freqtrade_data(base_url: str) -> dict:
    """Récupère les données complètes depuis Freqtrade."""
    auth = (FREQTRADE_USER, FREQTRADE_PASS)
    data = {}
    endpoints = {
        "profit": "/profit",
        "trades": "/trades?limit=500",
        "performance": "/performance",
        "balance": "/balance",
        "daily": "/daily?timescale=30",
    }
    for key, endpoint in endpoints.items():
        try:
            r = requests.get(f"{base_url}{endpoint}", auth=auth, timeout=15)
            data[key] = r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"}
        except Exception as e:
            data[key] = {"error": str(e)}
    return data


def calculate_projection(
    current_capital_a: float,
    current_capital_b: float,
    monthly_return_b: float,
    months_elapsed: int,
) -> list:
    """
    Calcule la projection sur les mois restants.
    Hypothèse : rendement mensuel moyen du bot B = monthly_return_b
    """
    projections = []
    cap_a = current_capital_a
    cap_b = current_capital_b

    remaining_months = HORIZON_MOIS - months_elapsed

    for month in range(1, remaining_months + 1):
        # Gains Compartiment B
        gains_b = cap_b * monthly_return_b

        # Transfert 100% des gains B → A
        cap_a += gains_b + APPORT_MENSUEL  # apport mensuel vers A

        # Compartiment B reste stable (les gains sont transférés)
        total = cap_a + cap_b

        projections.append({
            "mois": months_elapsed + month,
            "compartiment_a": round(cap_a, 2),
            "compartiment_b": round(cap_b, 2),
            "total": round(total, 2),
        })

    return projections


def format_monthly_data(comp_b: dict, comp_a: dict, month_label: str) -> str:
    """Formate les données pour Claude."""

    profit_b = comp_b.get("profit", {})
    balance_b = comp_b.get("balance", {})
    trades_b = comp_b.get("trades", {}).get("trades", [])
    daily_b = comp_b.get("daily", {}).get("data", [])

    profit_a = comp_a.get("profit", {})
    balance_a = comp_a.get("balance", {})

    # Calcul du rendement mensuel réel du Compartiment B
    monthly_profit_b = 0.0
    if daily_b:
        monthly_profit_b = sum(d.get("profit_all_coin", 0) for d in daily_b[-30:])

    # Calcul de la durée écoulée depuis le début
    try:
        debut = datetime.strptime(DATE_DEBUT, "%Y-%m-%d")
        months_elapsed = max(1, (datetime.now() - debut).days // 30)
    except Exception:
        months_elapsed = 1

    # Rendement mensuel moyen estimé
    cap_b_current = float(balance_b.get("total", 500))
    monthly_return_pct = monthly_profit_b / cap_b_current if cap_b_current > 0 else 0.0

    # Projection mise à jour
    cap_a_current = float(balance_a.get("total", 1000))
    projections = calculate_projection(
        cap_a_current, cap_b_current, monthly_return_pct, months_elapsed
    )

    # Paires les plus performantes
    performance = comp_b.get("performance", [])
    top_pairs = sorted(performance, key=lambda x: x.get("profit", 0), reverse=True)[:5]

    summary = f"""
RAPPORT MENSUEL - {month_label}
Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}

=== COMPARTIMENT B (TRADING ACTIF) ===
Capital actuel : {cap_b_current:.2f} USDT
Profit du mois : {monthly_profit_b:.2f} USDT ({monthly_return_pct*100:.2f}%)
Profit total cumulé : {profit_b.get('profit_all_coin', 'N/A')} USDT
Nombre de trades ce mois : {len([t for t in trades_b if t.get('close_date', '') >= month_label[:7]])}
Taux de réussite global : {profit_b.get('winrate', 'N/A')}%
Max drawdown : {profit_b.get('max_drawdown', 'N/A')}%

Top 5 paires les plus performantes :
{chr(10).join([f"  {i+1}. {p.get('pair','?')} : {p.get('profit',0):.2f} USDT ({p.get('count',0)} trades)" for i, p in enumerate(top_pairs)]) or "  Données non disponibles"}

=== COMPARTIMENT A (DCA LONG TERME) ===
Capital actuel : {cap_a_current:.2f} USDT
Montant transféré depuis B ce mois : {monthly_profit_b:.2f} USDT
Évolution depuis début : {profit_a.get('profit_all_percent_mean', 'N/A')}%

=== PROJECTION MISE À JOUR (mois restants) ===
Hypothèse de rendement mensuel B : {monthly_return_pct*100:.2f}% (basé sur performance réelle du mois)
Apport mensuel supposé : {APPORT_MENSUEL} EUR/mois

Prochains jalons :
{chr(10).join([f"  Mois {p['mois']} : Total {p['total']:.0f} USDT (A: {p['compartiment_a']:.0f} | B: {p['compartiment_b']:.0f})" for p in projections[::3][:8]]) or "  Calcul non disponible"}

Capital projeté à 24 mois : {projections[-1]['total']:.0f} USDT (si rendement maintenu)
"""
    return summary, monthly_return_pct


def generate_monthly_report_with_claude(data_summary: str, month_label: str) -> str:
    """Génère le rapport mensuel via Claude API."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Tu es l'assistant analytique d'un bot de trading crypto personnel.
Voici les données de performance du mois de {month_label}.

{data_summary}

Génère un rapport mensuel complet et actionnable en français :

## 📊 Performance du mois de {month_label}

[Résumé exécutif en 3-4 phrases : chiffres clés, comparaison avec les objectifs, tendance générale]

## 🔍 Analyse détaillée

### Compartiment B (Le Moteur)
[Analyse de la stratégie : quelles conditions de marché ont prévalu ? La stratégie ADX a-t-elle bien switché entre Grid et Momentum ? Anomalies ?]

### Compartiment A (Le Coffre)
[Évolution de l'accumulation BTC/ETH, montant DCA effectué, comparaison avec le plan initial]

## 📈 Projection actualisée

[Commentaire sur la projection mise à jour. Si le rendement réel est supérieur/inférieur aux hypothèses initiales, le noter et en expliquer les implications sur l'objectif 24 mois]

## ⚙️ Recommandations d'ajustement

[0 à 3 recommandations concrètes basées sur les données réelles. Ex : ajuster le grid_spacing si la volatilité a changé, modifier les seuils ADX si trop de faux signaux, etc.
Si aucun ajustement n'est nécessaire : "Les paramètres actuels semblent adaptés, pas d'ajustement recommandé."]

## 🗓️ Objectifs du mois prochain

[2-3 points de surveillance prioritaires pour le mois suivant]

---
Ton : professionnel mais accessible. Chiffres précis. Ne pas inventer de données absentes.
Longueur : 500-700 mots.
"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text


def send_email(subject: str, html_body: str, text_body: str):
    """Envoie le rapport mensuel par email."""
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


def markdown_to_html(md_text: str, month_label: str) -> str:
    """Conversion Markdown → HTML pour l'email mensuel."""
    lines = md_text.split("\n")
    html_lines = []
    for line in lines:
        if line.startswith("## "):
            html_lines.append(f"<h2 style='color:#1a3c6e; border-bottom:2px solid #f0c040; padding-bottom:5px'>{line[3:]}</h2>")
        elif line.startswith("### "):
            html_lines.append(f"<h3 style='color:#2c5282'>{line[4:]}</h3>")
        elif line.startswith("- "):
            html_lines.append(f"<li>{line[2:]}</li>")
        elif line.strip() == "---":
            html_lines.append("<hr style='border:1px solid #eee'>")
        elif line.strip() == "":
            html_lines.append("<br>")
        else:
            html_lines.append(f"<p>{line}</p>")

    return f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 750px; margin: 0 auto; padding: 20px; color: #333;">
    <div style="background: linear-gradient(135deg, #1a1a2e, #16213e); color: #eee; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
        <h1 style="color: #f0c040; margin: 0 0 5px 0;">🤖 CryptoBot - Rapport Mensuel</h1>
        <p style="color: #aaa; margin: 0; font-size: 14px;">{month_label} • Généré par Claude AI</p>
    </div>
    {"".join(html_lines)}
    <div style="background: #fff8e1; border-left: 4px solid #f0c040; padding: 15px; margin-top: 25px; border-radius: 0 5px 5px 0; font-size: 13px; color: #666;">
        <strong>⚠️ Avertissement</strong> : Ce rapport est généré automatiquement à titre informatif uniquement.
        Les projections sont indicatives. Les cryptomonnaies sont des actifs hautement volatils.
        Les performances passées ne garantissent pas les performances futures.
    </div>
    </body></html>
    """


def main():
    now = datetime.now()
    month_label = now.strftime("%B %Y")

    print(f"[{now}] Génération du rapport mensuel {month_label}...")

    comp_b_data = get_freqtrade_data(FREQTRADE_B_URL)
    comp_a_data = get_freqtrade_data(FREQTRADE_A_URL)

    data_summary, monthly_return = format_monthly_data(comp_b_data, comp_a_data, month_label)

    print(f"Rendement mensuel Compartiment B : {monthly_return*100:.2f}%")
    print("Génération du rapport via Claude API...")

    report_text = generate_monthly_report_with_claude(data_summary, month_label)

    subject = f"🤖 CryptoBot | Rapport mensuel - {month_label}"
    html_body = markdown_to_html(report_text, month_label)

    if SMTP_USER and SMTP_PASSWORD:
        send_email(subject, html_body, report_text)
        print(f"Rapport mensuel envoyé à {RECIPIENT}")
    else:
        print("Email non configuré - rapport :")
        print("=" * 70)
        print(report_text)

    # Archive
    report_dir = os.path.join(os.path.dirname(__file__), "archives")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, f"monthly_{now.strftime('%Y-%m')}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Rapport mensuel {month_label}\n\n")
        f.write(report_text)
    print(f"Rapport archivé : {report_path}")


if __name__ == "__main__":
    main()
