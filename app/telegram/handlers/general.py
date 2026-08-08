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
/latest [count] - Show latest transactions as a table (default: 10, max: 50)
/today - Show today's spending total
/week - Show this week's spending total
/thismonth - Show this month's spending total
/range <start> <end> - Show transactions in range (YYYY-MM-DD)
/search <merchant> - Search transactions by merchant name

Managing transactions:
/add <amount> <merchant> [description] [date] - Add manual transaction
/edit <index> <field> <value> - Edit a transaction (amount, merchant, description, transaction_time, tag)
/delete <index> - Start delete confirmation
/confirm - Confirm a pending delete (omit the index)
/confirm <index> - Confirm a specific pending delete
/cancel - Cancel all pending deletes
/cancel <index> - Cancel a specific pending delete
/tag <index> [<tag>] - Set or clear the tag on a transaction. Tags are free-form (e.g. coffee, transport, vacation).
/categorize <index> - Re-run the LLM categorizer on a transaction.

Every transaction is auto-categorized (food, transport, groceries, shopping, bills, subscriptions, health, entertainment, travel, transfers, fees, refunds, cash, other) on insert. If the LLM is misconfigured or fails, the category is left NULL — use /categorize to retry, or /edit <index> category <value> to set one manually.

Typical flow:

  /latest 2
    -> "About to delete: You spent S$3.98 at STARBUCKS ... Send /confirm to delete, or /cancel to abort."
  /confirm
    -> "Transaction deleted."

  /latest
    -> [rich table]
  /tag 1 coffee
    -> "Tag set: coffee"
  /week coffee
    -> "This week's spending (tag: coffee): S$15.30"

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
