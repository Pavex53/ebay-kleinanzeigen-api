from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Suche erstellen", callback_data="search:new")],
        [InlineKeyboardButton("📋 Meine Suchen", callback_data="search:list")],
        [InlineKeyboardButton("💳 Abo & Status", callback_data="subscription:status")],
        [InlineKeyboardButton("⚙️ Einstellungen", callback_data="settings:show")],
        [InlineKeyboardButton("ℹ️ Hilfe", callback_data="help:show")],
    ])


def subscription_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Basic · 14,99 €", callback_data="subscription:buy:basic")],
        [InlineKeyboardButton("Pro · 24,99 €", callback_data="subscription:buy:pro")],
        [InlineKeyboardButton("Expert · 49,99 €", callback_data="subscription:buy:expert")],
        [InlineKeyboardButton("⬅️ Menü", callback_data="menu:main")],
    ])


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menü", callback_data="menu:main")]])


def cancel_search() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Abbrechen", callback_data="search:cancel")]])
