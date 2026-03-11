"""
╔══════════════════════════════════════════════════════════════╗
║         BRINGO — BOT TELEGRAM LOG INCIDENTS TDC             ║
║         Tour de Contrôle · Real-Time Opérations             ║
║         Version SQLite - Simple et Fiable                   ║
╚══════════════════════════════════════════════════════════════╝
"""

import logging
import sqlite3
import os
from datetime import datetime, date
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

# ─── CONFIGURATION ───────────────────────────────────────────────────────────
TELEGRAM_TOKEN = "8797415348:AAG6nYtEW-b4EsZu6QwRr3xWQk5bmjk4XE4"
DB_FILE = "incidents.db"

# ─── ÉTATS DU FORMULAIRE ─────────────────────────────────────────────────────
(TYPE, DESCRIPTION, ZONE, ACTION, CLIENT_CONTACTE, STATUT) = range(6)

# ─── CHOIX PRÉDÉFINIS ────────────────────────────────────────────────────────
TYPES_INCIDENT = [
    ["🚚 Retard livreur", "📦 Rupture stock"],
    ["🕐 Slot indisponible", "🔒 Commande bloquée"],
    ["💻 Système lent", "💳 Problème paiement"],
    ["🚗 Accident livreur", "❓ Autre"]
]

ZONES = [
    ["🏙 Casablanca Centre", "🌆 Ain Sebaâ"],
    ["🏘 Hay Hassani", "🏖 Ain Diab"],
    ["🕌 Sidi Maarouf", "🌍 Tous secteurs"],
    ["📍 Autre zone"]
]

DESCRIPTIONS = [
    ["Retard livraison suite accident", "Livreur bloqué en route"],
    ["Rupture stock produit principal", "Commande bloquée >2h"],
    ["Slot surchargé / indisponible", "Système lent / planté"],
    ["✏️ Autre (écrire ci-dessous)"]
]

ACTIONS = [
    ["📞 Contact coordinateur", "🔄 Réaffectation livreur"],
    ["🔁 Substitution produit", "⬆️ Escalade équipe IT"],
    ["📅 Rééquilibrage créneaux", "👤 Contact client direct"],
    ["✏️ Autre (écrire ci-dessous)"]
]

CLIENT_CHOICES = [["✅ Non — géré avant", "⚠️ Oui — client a appelé d'abord"]]
STATUT_CHOICES = [["✅ Résolu", "🔄 En cours", "⬆️ Escaladé"]]

# ─── GESTION BASE DE DONNÉES ──────────────────────────────────────────────────

def init_db():
    """Crée la base de données si elle n'existe pas"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        heure_detection TEXT,
        type TEXT,
        description TEXT,
        zone TEXT,
        detecte_par TEXT,
        action TEXT,
        client_contacte TEXT,
        statut TEXT,
        heure_resolution TEXT,
        duree INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    conn.commit()
    conn.close()
    logging.info("✅ Base de données SQLite initialisée")

def add_incident(date_inc, heure_det, type_inc, desc, zone, detecte_par, action, client, statut, heure_res, duree):
    """Ajoute un incident à la BD"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''INSERT INTO incidents 
                    (date, heure_detection, type, description, zone, detecte_par, action, client_contacte, statut, heure_resolution, duree)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (date_inc, heure_det, type_inc, desc, zone, detecte_par, action, client, statut, heure_res, duree))
        conn.commit()
        conn.close()
        logging.info(f"✅ Incident enregistré: {type_inc}")
        return True
    except Exception as e:
        logging.error(f"❌ Erreur BD: {e}")
        return False

def get_stats():
    """Récupère les statistiques"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Total
        c.execute("SELECT COUNT(*) FROM incidents")
        total = c.fetchone()[0]
        
        # Proactifs
        c.execute("SELECT COUNT(*) FROM incidents WHERE client_contacte = 'Non'")
        proactifs = c.fetchone()[0]
        
        # Réactifs
        c.execute("SELECT COUNT(*) FROM incidents WHERE client_contacte = 'Oui'")
        reactifs = c.fetchone()[0]
        
        # Résolus
        c.execute("SELECT COUNT(*) FROM incidents WHERE statut LIKE '%Résolu%'")
        resolus = c.fetchone()[0]
        
        # MTTR moyen
        c.execute("SELECT AVG(duree) FROM incidents WHERE duree IS NOT NULL AND duree > 0")
        mttr_result = c.fetchone()[0]
        mttr = round(mttr_result, 1) if mttr_result else 0
        
        # Taux
        taux = round((proactifs / total * 100), 1) if total > 0 else 0
        
        conn.close()
        
        return {
            "total": total,
            "proactifs": proactifs,
            "reactifs": reactifs,
            "resolus": resolus,
            "taux": taux,
            "mttr": mttr
        }
    except Exception as e:
        logging.error(f"❌ Erreur stats: {e}")
        return {"total": 0, "proactifs": 0, "reactifs": 0, "resolus": 0, "taux": 0, "mttr": 0}

def get_today_incidents():
    """Récupère les incidents du jour"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        today_str = date.today().strftime("%d/%m/%Y")
        c.execute("SELECT * FROM incidents WHERE date = ? ORDER BY heure_detection", (today_str,))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"❌ Erreur: {e}")
        return []

def clean_choice(text: str) -> str:
    """Supprime les emojis"""
    import re
    return re.sub(r'[^\w\s\-\/àâäéèêëïîôöùûüçÀÂÄÉÈÊËÏÎÔÖÙÛÜÇ]', '', text).strip()

def taux_emoji(taux: float) -> str:
    if taux >= 60: return "🟢"
    if taux >= 40: return "🟡"
    return "🔴"

# ─── HANDLERS ────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🟡 *Bienvenue sur le Bot TDC Bringo !*\n\n"
        "📋 *Commandes :*\n"
        "• /incident — Saisir un nouvel incident\n"
        "• /stats — Statistiques\n"
        "• /today — Résumé du jour\n"
        "• /help — Aide",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *AIDE — BOT TDC BRINGO*\n\n"
        "*Saisir un incident :*\nTape /incident\n\n"
        "*Champ clé — 'Client contacté ?'*\n"
        "• ✅ Non = proactif\n"
        "• ⚠️ Oui = réactif",
        parse_mode="Markdown"
    )

async def incident_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["incident"] = {
        "date": date.today().strftime("%d/%m/%Y"),
        "heure_detection": datetime.now().strftime("%H:%M"),
        "detecte_par": update.effective_user.first_name or "Opérateur TDC"
    }
    await update.message.reply_text(
        "📡 *Nouvel incident — Étape 1/6*\n\nQuel est le *type* ?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(TYPES_INCIDENT, one_time_keyboard=True, resize_keyboard=True)
    )
    return TYPE

async def get_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["incident"]["type"] = clean_choice(update.message.text)
    await update.message.reply_text(
        "📝 *Étape 2/6 — Description*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(DESCRIPTIONS, one_time_keyboard=True, resize_keyboard=True)
    )
    return DESCRIPTION

async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["incident"]["description"] = update.message.text
    await update.message.reply_text(
        "📍 *Étape 3/6 — Zone*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(ZONES, one_time_keyboard=True, resize_keyboard=True)
    )
    return ZONE

async def get_zone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["incident"]["zone"] = clean_choice(update.message.text)
    await update.message.reply_text(
        "🔧 *Étape 4/6 — Action*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(ACTIONS, one_time_keyboard=True, resize_keyboard=True)
    )
    return ACTION

async def get_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["incident"]["action"] = update.message.text
    await update.message.reply_text(
        "❓ *Étape 5/6 — Client contacté ?*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(CLIENT_CHOICES, one_time_keyboard=True, resize_keyboard=True)
    )
    return CLIENT_CONTACTE

async def get_client_contacte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["incident"]["client_contacte"] = "Oui" if "Oui" in update.message.text else "Non"
    await update.message.reply_text(
        "📊 *Étape 6/6 — Statut*",
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

    duree = None
    if heure_res:
        try:
            t1 = datetime.strptime(inc["heure_detection"], "%H:%M")
            t2 = datetime.strptime(heure_res, "%H:%M")
            duree = (t2 - t1).seconds // 60
        except:
            pass

    # Enregistrer en BD
    saved = add_incident(
        inc["date"], inc["heure_detection"], inc.get("type", ""),
        inc.get("description", ""), inc.get("zone", ""),
        inc.get("detecte_par", ""), inc.get("action", ""),
        inc.get("client_contacte", ""), statut, heure_res, duree
    )

    proactif = inc.get("client_contacte") == "Non"
    badge = "✅ *PROACTIF*" if proactif else "⚠️ *RÉACTIF*"

    recap = (
        f"{'✅' if saved else '❌'} *Incident enregistré{'!' if saved else ' (erreur)'}*\n\n"
        f"• 📅 {inc['date']} {inc['heure_detection']}\n"
        f"• Type: {inc.get('type', '')}\n"
        f"• Zone: {inc.get('zone', '')}\n"
        f"• Action: {inc.get('action', '')}\n"
        f"• Client: {badge}\n"
        f"• Statut: {statut}\n"
    )
    if duree:
        recap += f"• Durée: {duree} min\n"

    await update.message.reply_text(recap, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Annulé.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_stats()
    emoji = taux_emoji(s["taux"])

    await update.message.reply_text(
        f"📊 *STATS — TDC Bringo*\n"
        f"📋 Total: {s['total']}\n"
        f"✅ Proactifs: {s['proactifs']}\n"
        f"⚠️ Réactifs: {s['reactifs']}\n"
        f"🔧 Résolus: {s['resolus']}\n\n"
        f"{emoji} *Taux Proactivité: {s['taux']}%*\n"
        f"⏱ MTTR moyen: {s['mttr']} min",
        parse_mode="Markdown"
    )

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_today_incidents()

    if not rows:
        await update.message.reply_text(f"📅 Aucun incident aujourd'hui.", parse_mode="Markdown")
        return

    msg = f"📅 *Incidents du jour*\n\n"
    for i, row in enumerate(rows, 1):
        msg += f"{i}. {row[3]} — {row[2]} → {row[9]}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

def main():
    logging.basicConfig(level=logging.INFO)
    print("=" * 60)
    print("🤖 BOT BRINGO TDC (SQLite Edition)")
    print("=" * 60)
    
    # Initialiser la BD
    init_db()
    print(f"✅ Base de données: {DB_FILE}\n")
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("incident", incident_start)],
        states={
            TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_type)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
            ZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_zone)],
            ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_action)],
            CLIENT_CONTACTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_client_contacte)],
            STATUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_statut)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(conv)

    print("🚀 Bot démarré!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
