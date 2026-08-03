from telegram import Update
from telegram.ext import ContextTypes

from app.telegram.auth import auth_handler


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not await auth_handler(update, context):
        return

    await update.message.reply_text(
        "Welcome to Spending Tracker Bot!\n\n"
        "Track your expenses by forwarding bank emails to this bot.\n"
        "Use /help to see available commands."
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if not await auth_handler(update, context):
        return

    help_text = """
Available commands:

Viewing transactions:
/latest [count] - Show latest transactions (default: 10, max: 50)
/today - Show today's spending total
/week - Show this week's spending total
/thismonth - Show this month's spending total
/range <start> <end> - Show transactions in range (YYYY-MM-DD)
/search <merchant> - Search transactions by merchant name

Managing transactions:
/add <amount> <merchant> [description] [date] - Add manual transaction
/edit <index> <field> <value> - Edit a transaction (amount, merchant, description, transaction_time)
/delete <index> - Start delete confirmation
/confirm <index> - Confirm deletion
/cancel <index> - Cancel a pending delete

For /edit, /delete, /confirm, and /cancel, pass the 1-based row number from
the most recent /latest, /search, or /range output. Example flow:

  /latest            → 1. STARBUCKS
                       2. GRAB
  /delete 2          → confirms intent for the 2nd transaction shown
  /confirm 2         → deletes that transaction

Other:
/ping - Check bot is alive

Signed amount convention:
- Positive = purchase/debit/payment
- Negative = refund/credit
"""
    await update.message.reply_text(help_text)


async def ping_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ping command."""
    if not await auth_handler(update, context):
        return
    await update.message.reply_text("pong")
