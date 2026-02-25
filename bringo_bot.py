"""
╔══════════════════════════════════════════════════════════════╗
║         BRINGO — BOT TELEGRAM LOG INCIDENTS TDC             ║
║         Tour de Contrôle · Real-Time Opérations             ║
╚══════════════════════════════════════════════════════════════╝

FONCTIONS :
  /incident   → Saisir un incident (formulaire guidé)
  /stats      → Taux de proactivité + résumé
  /today      → Résumé du jour
  /help       → Aide

INSTALLATION : voir GUIDE_INSTALLATION.md
"""

import logging
import os
from datetime import datetime, date
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)
import gspread
from google.oauth2.service_account import Credentials

# ─── CONFIGURATION ───────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = "8447041739:AAGRFcrTQ6ZVKBJ_xF6tyTQHYbGg8y1zrUo"
GOOGLE_SHEET_ID  = "1wshADdZVfo_istMjrpk4iZiuQoDtLoTsLzEwsqmu1k0"
CREDENTIALS_FILE = "credentials.json" if os.path.exists("credentials.json") else "credentials.json.json"
ALERT_CHAT_ID    = None                        # ID du groupe/canal pour alertes (optionnel)

# Utilisateurs autorisés (Telegram user_id) — laisser vide pour tout autoriser
AUTHORIZED_USERS = []  # ex: [123456789, 987654321]

# Seuil alerte MTTR (en minutes)
MTTR_ALERT_THRESHOLD = 30

# ─── ÉTATS DU FORMULAIRE ─────────────────────────────────────────────────────
(TYPE, DESCRIPTION, ZONE, ACTION, CLIENT_CONTACTE, STATUT) = range(6)

# ─── CHOIX PRÉDÉFINIS ────────────────────────────────────────────────────────
TYPES_INCIDENT = [
    ["🚚 Retard livreur",    "📦 Rupture stock"],
    ["🕐 Slot indisponible", "🔒 Commande bloquée"],
    ["💻 Système lent",      "💳 Problème paiement"],
    ["🚗 Accident livreur",  "❓ Autre"]
]

ZONES = [
    ["🏙 Casablanca Centre",  "🌆 Ain Sebaâ"],
    ["🏘 Hay Hassani",        "🏖 Ain Diab"],
    ["🕌 Sidi Maarouf",       "🌍 Tous secteurs"],
    ["📍 Autre zone"]
]

DESCRIPTIONS = [
    ["Retard livraison suite accident",  "Livreur bloqué en route"],
    ["Rupture stock produit principal",  "Commande bloquée >2h"],
    ["Slot surchargé / indisponible",    "Système lent / planté"],
    ["✏️ Autre (écrire ci-dessous)"]
]

ACTIONS = [
    ["📞 Contact coordinateur",     "🔄 Réaffectation livreur"],
    ["🔁 Substitution produit",     "⬆️ Escalade équipe IT"],
    ["📅 Rééquilibrage créneaux",   "👤 Contact client direct"],
    ["✏️ Autre (écrire ci-dessous)"]
]

CLIENT_CHOICES  = [["✅ Non — géré avant", "⚠️ Oui — client a appelé d'abord"]]
STATUT_CHOICES  = [["✅ Résolu", "🔄 En cours", "⬆️ Escaladé"]]

# ─── CONNEXION GOOGLE SHEETS ─────────────────────────────────────────────────
def get_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds  = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scope)
    client = gspread.authorize(creds)
    sh     = client.open_by_key(GOOGLE_SHEET_ID)

    # Créer les onglets si besoin
    try:
        ws = sh.worksheet("Log Incidents")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Log Incidents", rows=1000, cols=12)
        ws.append_row([
            "Date", "Heure Détection", "Type", "Description",
            "Zone", "Détecté par", "Action menée",
            "Client contacté ?", "Statut", "Heure résolution", "Durée (min)"
        ], value_input_option="USER_ENTERED")
        # Mise en forme header
        ws.format("A1:K1", {
            "backgroundColor": {"red": 0.02, "green": 0.36, "blue": 0.64},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            "horizontalAlignment": "CENTER"
        })
    return sh, ws

# ─── UTILITAIRES ─────────────────────────────────────────────────────────────
def is_authorized(user_id: int) -> bool:
    return not AUTHORIZED_USERS or user_id in AUTHORIZED_USERS

def clean_choice(text: str) -> str:
    """Supprime les emojis et espaces inutiles"""
    import re
    return re.sub(r'[^\w\s\-\/àâäéèêëïîôöùûüçÀÂÄÉÈÊËÏÎÔÖÙÛÜÇ]', '', text).strip()

def get_stats(ws) -> dict:
    """Calcule les stats depuis le Google Sheet"""
    rows = ws.get_all_values()[1:]  # skip header
    if not rows:
        return {"total": 0, "proactifs": 0, "reactifs": 0, "resolus": 0, "taux": 0, "mttr": 0}

    today_str = date.today().strftime("%d/%m/%Y")
    total = len(rows)
    proactifs = sum(1 for r in rows if len(r) > 7 and "Non" in r[7])
    reactifs  = sum(1 for r in rows if len(r) > 7 and "Oui" in r[7])
    resolus   = sum(1 for r in rows if len(r) > 8 and "Résolu" in r[8])
    today_rows = [r for r in rows if len(r) > 0 and r[0] == today_str]

    # MTTR
    durations = []
    for r in rows:
        if len(r) > 10 and r[10]:
            try:
                durations.append(float(r[10]))
            except:
                pass
    mttr = round(sum(durations) / len(durations), 1) if durations else 0
    taux = round((proactifs / total * 100), 1) if total > 0 else 0

    return {
        "total": total, "proactifs": proactifs, "reactifs": reactifs,
        "resolus": resolus, "today": len(today_rows),
        "taux": taux, "mttr": mttr
    }

def taux_emoji(taux: float) -> str:
    if taux >= 60: return "🟢"
    if taux >= 40: return "🟡"
    return "🔴"

# ─── HANDLERS COMMANDES ──────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Accès non autorisé.")
        return

    await update.message.reply_text(
        "🟡 *Bienvenue sur le Bot TDC Bringo !*\n\n"
        "Je suis ton assistant pour logger les incidents de la Tour de Contrôle.\n\n"
        "📋 *Commandes disponibles :*\n"
        "• /incident — Saisir un nouvel incident\n"
        "• /stats — Taux de proactivité & statistiques\n"
        "• /today — Résumé des incidents du jour\n"
        "• /help — Aide\n\n"
        "💡 _Chaque incident loggé améliore ton taux de proactivité !_",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *AIDE — BOT TDC BRINGO*\n\n"
        "*Saisir un incident :*\n"
        "Tape /incident et suis le formulaire étape par étape.\n\n"
        "*Champ clé — 'Client contacté ?'*\n"
        "• ✅ Non = tu as géré AVANT que le client appelle → proactif\n"
        "• ⚠️ Oui = le client a appelé en premier → réactif\n\n"
        "*Taux de proactivité cible :* > 60%\n"
        "*MTTR cible :* < 30 min\n\n"
        "📞 _Problème ? Contacte le Responsable des Services._",
        parse_mode="Markdown"
    )

# ─── FORMULAIRE INCIDENT ─────────────────────────────────────────────────────

async def incident_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Accès non autorisé.")
        return ConversationHandler.END

    context.user_data["incident"] = {
        "date": date.today().strftime("%d/%m/%Y"),
        "heure_detection": datetime.now().strftime("%H:%M"),
        "detecte_par": update.effective_user.first_name or "Opérateur TDC"
    }

    await update.message.reply_text(
        "📡 *Nouvel incident — Étape 1/6*\n\n"
        "Quel est le *type d'incident* ?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(TYPES_INCIDENT, one_time_keyboard=True, resize_keyboard=True)
    )
    return TYPE

async def get_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["incident"]["type"] = clean_choice(update.message.text)

    await update.message.reply_text(
        "📝 *Étape 2/6 — Description*\n\n"
        "Choisis une description ou écris la tienne :",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(DESCRIPTIONS, one_time_keyboard=True, resize_keyboard=True)
    )
    return DESCRIPTION

async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["incident"]["description"] = update.message.text

    await update.message.reply_text(
        "📍 *Étape 3/6 — Zone / Secteur*\n\n"
        "Quel secteur est concerné ?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(ZONES, one_time_keyboard=True, resize_keyboard=True)
    )
    return ZONE

async def get_zone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["incident"]["zone"] = clean_choice(update.message.text)

    await update.message.reply_text(
        "🔧 *Étape 4/6 — Action menée*\n\n"
        "Qu'as-tu fait pour gérer cet incident ?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(ACTIONS, one_time_keyboard=True, resize_keyboard=True)
    )
    return ACTION

async def get_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["incident"]["action"] = update.message.text

    await update.message.reply_text(
        "❓ *Étape 5/6 — Client contacté ?*\n\n"
        "⚠️ *Question clé pour le taux de proactivité :*\n"
        "Le client a-t-il contacté le service réclamations *avant* que tu gères cet incident ?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(CLIENT_CHOICES, one_time_keyboard=True, resize_keyboard=True)
    )
    return CLIENT_CONTACTE

async def get_client_contacte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rep = update.message.text
    context.user_data["incident"]["client_contacte"] = "Oui" if "Oui" in rep else "Non"

    await update.message.reply_text(
        "📊 *Étape 6/6 — Statut*\n\n"
        "Quel est le statut actuel de l'incident ?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(STATUT_CHOICES, one_time_keyboard=True, resize_keyboard=True)
    )
    return STATUT

async def get_statut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rep = update.message.text
    if "Résolu" in rep:
        statut = "Résolu ✅"
        heure_res = datetime.now().strftime("%H:%M")
    elif "cours" in rep:
        statut = "En cours 🔄"
        heure_res = ""
    else:
        statut = "Escaladé ⬆️"
        heure_res = ""

    inc = context.user_data["incident"]
    inc["statut"] = statut
    inc["heure_resolution"] = heure_res

    # Calcul durée si résolu
    duree = ""
    if heure_res:
        try:
            fmt = "%H:%M"
            t1 = datetime.strptime(inc["heure_detection"], fmt)
            t2 = datetime.strptime(heure_res, fmt)
            diff = (t2 - t1).seconds // 60
            duree = str(diff)
        except:
            duree = ""

    # Enregistrement Google Sheets
    try:
        _, ws = get_sheet()
        ws.append_row([
            inc["date"],
            inc["heure_detection"],
            inc.get("type", ""),
            inc.get("description", ""),
            inc.get("zone", ""),
            inc.get("detecte_par", ""),
            inc.get("action", ""),
            inc.get("client_contacte", ""),
            statut,
            heure_res,
            duree
        ], value_input_option="USER_ENTERED")
        saved = True
    except Exception as e:
        saved = False
        logging.error(f"Erreur Google Sheets: {e}")

    # Résumé
    proactif = inc.get("client_contacte") == "Non"
    badge = "✅ *PROACTIF*" if proactif else "⚠️ *RÉACTIF*"

    recap = (
        f"{'✅' if saved else '❌'} *Incident enregistré{'!' if saved else ' (erreur Sheets)'}*\n\n"
        f"📋 *Récapitulatif :*\n"
        f"• 📅 Date : {inc['date']} à {inc['heure_detection']}\n"
        f"• 🔴 Type : {inc.get('type', '')}\n"
        f"• 📍 Zone : {inc.get('zone', '')}\n"
        f"• 📝 Description : {inc.get('description', '')}\n"
        f"• 🔧 Action : {inc.get('action', '')}\n"
        f"• 👤 Client : {inc.get('client_contacte', '')} → {badge}\n"
        f"• 📊 Statut : {statut}\n"
    )
    if duree:
        recap += f"• ⏱ Durée : {duree} min\n"

    await update.message.reply_text(
        recap, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )

    # Alerte MTTR si dépassement
    if duree and int(duree) > MTTR_ALERT_THRESHOLD:
        await update.message.reply_text(
            f"🚨 *Alerte MTTR* — Incident résolu en *{duree} min*\n"
            f"Cible : < {MTTR_ALERT_THRESHOLD} min\n"
            f"_Pense à documenter la cause du retard._",
            parse_mode="Markdown"
        )

    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Saisie annulée. Tape /incident pour recommencer.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# ─── STATS & RÉSUMÉS ─────────────────────────────────────────────────────────

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    try:
        _, ws = get_sheet()
        s = get_stats(ws)
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur de connexion au Sheet : {e}")
        return

    emoji = taux_emoji(s["taux"])

    await update.message.reply_text(
        f"📊 *STATISTIQUES — Tour de Contrôle Bringo*\n"
        f"_{datetime.now().strftime('%d/%m/%Y à %H:%M')}_\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Total incidents loggés : *{s['total']}*\n"
        f"✅ Proactifs (avant client) : *{s['proactifs']}*\n"
        f"⚠️ Réactifs (après client) : *{s['reactifs']}*\n"
        f"🔧 Résolus : *{s['resolus']}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} *Taux de Proactivité : {s['taux']}%*\n"
        f"🎯 Cible : > 60%\n\n"
        f"⏱ *MTTR moyen : {s['mttr']} min*\n"
        f"🎯 Cible : < 30 min\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 _Plus tu logges tôt, plus le taux monte !_",
        parse_mode="Markdown"
    )

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    try:
        _, ws = get_sheet()
        rows = ws.get_all_values()[1:]
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")
        return

    today_str = date.today().strftime("%d/%m/%Y")
    today_rows = [r for r in rows if len(r) > 0 and r[0] == today_str]

    if not today_rows:
        await update.message.reply_text(
            f"📅 *Résumé du {today_str}*\n\n"
            "Aucun incident loggé aujourd'hui.\n"
            "Tape /incident pour saisir le premier ! 👍",
            parse_mode="Markdown"
        )
        return

    proactifs = sum(1 for r in today_rows if len(r) > 7 and "Non" in r[7])
    reactifs  = sum(1 for r in today_rows if len(r) > 7 and "Oui" in r[7])
    resolus   = sum(1 for r in today_rows if len(r) > 8 and "Résolu" in r[8])
    taux = round(proactifs / len(today_rows) * 100, 1) if today_rows else 0

    msg = (
        f"📅 *Résumé du {today_str}*\n\n"
        f"📋 Incidents loggés : *{len(today_rows)}*\n"
        f"✅ Proactifs : *{proactifs}*\n"
        f"⚠️ Réactifs : *{reactifs}*\n"
        f"🔧 Résolus : *{resolus}*\n"
        f"{taux_emoji(taux)} Taux proactivité : *{taux}%*\n\n"
        f"*Détail des incidents :*\n"
    )

    for i, r in enumerate(today_rows, 1):
        type_inc = r[2] if len(r) > 2 else "?"
        heure    = r[1] if len(r) > 1 else "?"
        statut   = r[8] if len(r) > 8 else "?"
        msg += f"{i}. `{heure}` — {type_inc} → {statut}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

# ─── ALERTE AUTOMATIQUE (à appeler via scheduler) ───────────────────────────

async def send_daily_summary(app):
    """Envoie le résumé quotidien automatique à 18h"""
    if not ALERT_CHAT_ID:
        return
    try:
        _, ws = get_sheet()
        s = get_stats(ws)
        today_str = date.today().strftime("%d/%m/%Y")
        rows = ws.get_all_values()[1:]
        today_count = sum(1 for r in rows if len(r) > 0 and r[0] == today_str)

        await app.bot.send_message(
            chat_id=ALERT_CHAT_ID,
            text=(
                f"🌆 *Rapport quotidien TDC — {today_str}*\n\n"
                f"📋 Incidents aujourd'hui : *{today_count}*\n"
                f"{taux_emoji(s['taux'])} Taux proactivité global : *{s['taux']}%*\n"
                f"⏱ MTTR moyen : *{s['mttr']} min*\n\n"
                f"{'✅ Objectifs atteints !' if s['taux'] >= 60 and s['mttr'] <= 30 else '⚠️ Objectifs à améliorer.'}"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Erreur rapport quotidien: {e}")

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
        level=logging.INFO
    )

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Formulaire incident (ConversationHandler)
    conv = ConversationHandler(
        entry_points=[CommandHandler("incident", incident_start)],
        states={
            TYPE:             [MessageHandler(filters.TEXT & ~filters.COMMAND, get_type)],
            DESCRIPTION:      [MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
            ZONE:             [MessageHandler(filters.TEXT & ~filters.COMMAND, get_zone)],
            ACTION:           [MessageHandler(filters.TEXT & ~filters.COMMAND, get_action)],
            CLIENT_CONTACTE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_client_contacte)],
            STATUT:           [MessageHandler(filters.TEXT & ~filters.COMMAND, get_statut)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(conv)

    # Rapport quotidien automatique à 18h00
    import asyncio
    from datetime import time as dt_time
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(
            lambda ctx: asyncio.create_task(send_daily_summary(app)),
            time=dt_time(hour=18, minute=0)
        )

    print("🤖 Bot Bringo TDC démarré ! Ctrl+C pour arrêter.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
