from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

import httpx
from sqlalchemy.orm import Session
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from backend.models import Search, TelegramAccount, User
from backend.utils.auth import check_subscription_access, get_active_subscription
from backend.utils.plan_limits import get_search_limit
from bot.config import Settings
from bot.keyboards import back_to_menu, cancel_search, main_menu, subscription_menu

logger = logging.getLogger(__name__)

QUERY, LOCATION, RADIUS, PRICE_FROM, PRICE_TO = range(5)


@dataclass
class BotContext:
    settings: Settings
    db_factory: Callable[[], Session]


def app_context(application: Application) -> BotContext:
    return application.bot_data["context"]


def get_or_create_user(db: Session, telegram_user_id: int, username: str | None) -> User:
    telegram_id = str(telegram_user_id)
    user = db.query(User).filter(User.telegram_user_id == telegram_id).first()
    if user is None:
        user = User(telegram_user_id=telegram_id)
        db.add(user)
        db.flush()

    account = db.query(TelegramAccount).filter(TelegramAccount.user_id == user.id).first()
    if account is None:
        db.add(
            TelegramAccount(
                user_id=user.id,
                telegram_user_id=telegram_id,
                telegram_username=username,
            )
        )
    else:
        account.telegram_username = username
    db.commit()
    return user


def get_current_user(db: Session, update: Update) -> User:
    telegram_user = update.effective_user
    if telegram_user is None:
        raise RuntimeError("Telegram user is missing")
    return get_or_create_user(db, telegram_user.id, telegram_user.username)


def get_search_capacity(db: Session, user_id: int) -> tuple[bool, str, int, int]:
    subscription = get_active_subscription(db, user_id)
    if subscription is None:
        return False, "Für Suchen brauchst du ein aktives Abo.", 0, 0

    limit = get_search_limit(subscription.plan_tier)
    used = db.query(Search).filter(Search.user_id == user_id).count()
    if used >= limit:
        plan = subscription.plan_tier.value.capitalize()
        return (
            False,
            f"Du nutzt bereits alle {limit} Suchplätze deines {plan}-Plans. "
            "Lösche eine Suche oder upgrade dein Abo.",
            used,
            limit,
        )
    return True, "", used, limit


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = app_context(context.application).db_factory()
    try:
        user = get_current_user(db, update)
        access = check_subscription_access(db, user.id)
        status = "✅ aktiv" if access["has_access"] else "❌ kein aktives Abo"
        await update.message.reply_text(
            f"Willkommen beim Kleinanzeigen Alert Bot!\n\nAbo: {status}\n\nWähle eine Funktion:",
            reply_markup=main_menu(),
        )
    finally:
        db.close()


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hauptmenü:", reply_markup=main_menu())


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    action = query.data

    if action == "menu:main":
        await query.edit_message_text("Hauptmenü:", reply_markup=main_menu())
    elif action == "subscription:status":
        await show_subscription(update, context)
    elif action.startswith("subscription:buy:"):
        await buy_subscription(update, context)
    elif action == "search:list":
        await list_searches(update, context)
    elif action == "settings:show":
        await query.edit_message_text(
            "⚙️ Einstellungen\n\nSuchfilter werden beim Erstellen einer Suche gesetzt. "
            "Erweiterte Einstellungen folgen nach dem MVP.",
            reply_markup=back_to_menu(),
        )
    elif action == "help:show":
        await query.edit_message_text(
            "ℹ️ Hilfe\n\nMit 'Suche erstellen' legst du Suchbegriff, Ort, Radius und "
            "Preisbereich fest. Bei neuen Treffern erhältst du eine Telegram-Nachricht.",
            reply_markup=back_to_menu(),
        )


async def show_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    db = app_context(context.application).db_factory()
    try:
        user = get_current_user(db, update)
        access = check_subscription_access(db, user.id)
        if access["has_access"]:
            subscription = get_active_subscription(db, user.id)
            assert subscription is not None
            limit = get_search_limit(subscription.plan_tier)
            used = db.query(Search).filter(Search.user_id == user.id).count()
            text = (
                "💳 Dein Abo\n\n"
                f"Plan: {access['plan_tier'].capitalize()}\n"
                f"Suchintervall: alle {access['interval_minutes']} Minuten\n"
                f"Suchen: {used}/{limit}\n"
                f"Gültig bis: {access['current_period_end']}"
            )
        else:
            text = "💳 Kein aktives Abo\n\nWähle deinen Plan:"
        await query.edit_message_text(text, reply_markup=subscription_menu())
    finally:
        db.close()


async def buy_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    plan = query.data.rsplit(":", 1)[-1]
    bot_context = app_context(context.application)
    db = bot_context.db_factory()
    try:
        user = get_current_user(db, update)
        if not getattr(bot_context.settings, f"stripe_price_{plan}"):
            await query.edit_message_text("Dieser Plan ist noch nicht konfiguriert.", reply_markup=back_to_menu())
            return

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{bot_context.settings.backend_url}/checkout/create",
                json={"user_id": user.id, "plan": plan},
            )
            response.raise_for_status()
            checkout_url = response.json()["checkout_url"]

        await query.edit_message_text(
            f"💳 {plan.capitalize()} auswählen\n\nDie Zahlung erfolgt sicher über Stripe.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("Jetzt abonnieren", url=checkout_url)],
                    [InlineKeyboardButton("⬅️ Zurück", callback_data="subscription:status")],
                ]
            ),
        )
    except httpx.HTTPError:
        logger.exception("Could not create checkout session")
        await query.edit_message_text(
            "Checkout konnte nicht erstellt werden. Bitte versuche es später erneut.",
            reply_markup=back_to_menu(),
        )
    finally:
        db.close()


async def list_searches(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    db = app_context(context.application).db_factory()
    try:
        user = get_current_user(db, update)
        searches = (
            db.query(Search)
            .filter(Search.user_id == user.id)
            .order_by(Search.created_at.desc())
            .all()
        )
        if not searches:
            text = "📋 Meine Suchen\n\nDu hast noch keine Suchen gespeichert."
        else:
            entries = [
                f"{'✅' if item.is_enabled else '⏸️'} {item.name}\n"
                f"{item.query} · {item.location or 'bundesweit'} · {item.radius or 0} km"
                for item in searches
            ]
            text = "📋 Meine Suchen\n\n" + "\n\n".join(entries)
        await query.edit_message_text(text, reply_markup=back_to_menu())
    finally:
        db.close()


async def start_search_from_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END

    db = app_context(context.application).db_factory()
    try:
        user = get_current_user(db, update)
        allowed, reason, _, _ = get_search_capacity(db, user.id)
        if not allowed:
            await query.edit_message_text(reason, reply_markup=subscription_menu())
            return ConversationHandler.END
    finally:
        db.close()

    await query.edit_message_text("🔎 Was möchtest du suchen?", reply_markup=cancel_search())
    return QUERY


async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db = app_context(context.application).db_factory()
    try:
        user = get_current_user(db, update)
        allowed, reason, _, _ = get_search_capacity(db, user.id)
        if not allowed:
            await update.message.reply_text(reason, reply_markup=subscription_menu())
            return ConversationHandler.END
    finally:
        db.close()

    await update.message.reply_text("🔎 Was möchtest du suchen?", reply_markup=cancel_search())
    return QUERY


async def search_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["search_query"] = update.message.text.strip()
    await update.message.reply_text("📍 Welche Stadt oder Region?", reply_markup=cancel_search())
    return LOCATION


async def search_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["search_location"] = update.message.text.strip()
    await update.message.reply_text("📏 Radius in km?", reply_markup=cancel_search())
    return RADIUS


async def search_radius(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        value = int(update.message.text.strip())
        if value < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Bitte eine ganze Zahl ab 0 eingeben.")
        return RADIUS
    context.user_data["search_radius"] = value
    await update.message.reply_text("💶 Mindestpreis? (0 = kein Mindestpreis)", reply_markup=cancel_search())
    return PRICE_FROM


async def search_price_from(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        value = float(update.message.text.replace(",", "."))
        if value < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Bitte eine gültige Zahl eingeben.")
        return PRICE_FROM
    context.user_data["price_from"] = value
    await update.message.reply_text("💶 Maximalpreis? (0 = kein Maximalpreis)", reply_markup=cancel_search())
    return PRICE_TO


async def search_price_to(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        price_to = float(update.message.text.replace(",", "."))
        if price_to < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Bitte eine gültige Zahl eingeben.")
        return PRICE_TO

    db = app_context(context.application).db_factory()
    try:
        user = get_current_user(db, update)
        allowed, reason, _, _ = get_search_capacity(db, user.id)
        if not allowed:
            context.user_data.clear()
            await update.message.reply_text(reason, reply_markup=subscription_menu())
            return ConversationHandler.END

        data = context.user_data
        search = Search(
            user_id=user.id,
            name=f"{data['search_query']} · {data['search_location']}"[:255],
            query=data["search_query"],
            location=data["search_location"],
            radius=data["search_radius"],
            price_from=data["price_from"] or None,
            price_to=price_to or None,
        )
        db.add(search)
        db.commit()
    finally:
        db.close()

    context.user_data.clear()
    await update.message.reply_text(
        "✅ Suche gespeichert. Sobald der Polling-Worker aktiv ist, bekommst du neue Treffer per Telegram.",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Abgebrochen.", reply_markup=main_menu())
    return ConversationHandler.END


def register_handlers(application: Application) -> None:
    conversation = ConversationHandler(
        entry_points=[
            CommandHandler("neue_suche", search_start),
            CallbackQueryHandler(start_search_from_button, pattern="^search:new$"),
        ],
        states={
            QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_query)],
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_location)],
            RADIUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_radius)],
            PRICE_FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_price_from)],
            PRICE_TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_price_to)],
        },
        fallbacks=[
            CommandHandler("abbrechen", cancel),
            CallbackQueryHandler(cancel, pattern="^search:cancel$"),
        ],
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(conversation)
    application.add_handler(CallbackQueryHandler(menu_callback))
