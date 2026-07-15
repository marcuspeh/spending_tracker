# Expense Tracker

Self-hosted personal expense tracker that automatically imports bank transactions from forwarded Gmail emails and exposes query/management through a Telegram bot.

## Prerequisites

- Python 3.12+
- MySQL 8 (or Docker to run MySQL in a container)
- Gmail account with App Password
- Telegram bot token (from [@BotFather](https://t.me/BotFather))

## Installation

### 1. Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Clone and setup environment

```bash
git clone <repository-url>
cd expense-tracker
cp .env.example .env
```

### 3. Configure environment

Edit `.env` with your settings:

```env
TIMEZONE=Asia/Singapore
DATABASE_URL=mysql://expense_user:expense_password@mysql:3306/expense_tracker
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USERNAME=your-email@gmail.com
IMAP_PASSWORD=your-app-password
POLL_INTERVAL_SECONDS=60
LOG_LEVEL=INFO
```

### 4. Database Setup (with Docker Compose)

```bash
docker compose up -d mysql
```

Wait for MySQL to be healthy, then:

```bash
docker compose up -d expense-tracker
```

### 5. Manual DB Onboarding

Connect to MySQL and add users:

```sql
-- Connect to MySQL
docker exec -it expense-tracker-mysql mysql -u root -p

-- Insert a user (chat_id from Telegram)
INSERT INTO users (telegram_chat_id, name, active) VALUES (123456789, 'Your Name', true);

-- Add forwarding email address
INSERT INTO user_emails (user_id, email) VALUES (1, 'your-email@gmail.com');
```

### 6. Telegram Setup

1. Start a conversation with your bot by sending `/start`
2. Configure Gmail forwarding to send PayNow/PayLah/UOB emails to your configured inbox

## Email Forwarding Setup

Configure your Gmail to forward bank emails to the shared inbox:

1. PayNow emails from your bank
2. PayLah notifications
3. UOB card transaction alerts

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot |
| `/help` | Show help text |
| `/ping` | Check bot is alive |
| `/latest [count]` | Show latest transactions (default: 10, max: 50) |
| `/today` | Show today's spending total |
| `/week` | Show this week's spending total |
| `/thismonth` | Show this month's spending total |
| `/range <start> <end>` | Show transactions in range (YYYY-MM-DD) |
| `/search <merchant>` | Search transactions by merchant name |
| `/add <amount> <merchant> [description] [date]` | Add manual transaction |
| `/edit <id> <field> <value>` | Edit a transaction |
| `/delete <id>` | Start delete confirmation |
| `/confirm <id>` | Confirm deletion |

### Signed Amount Convention

- **Positive** = purchase/debit/payment
- **Negative** = refund/credit

This ensures `/today`, `/week`, `/thismonth`, and `/range` aggregates reflect net spend (a $5 refund reduces a $20 day's total to $15).

## Healthcheck

The application exposes an in-process HTTP endpoint at `http://localhost:$HEALTH_PORT/health` (default port `8080`). It returns `200 OK` when both the Telegram bot and email poller are running, and `503` otherwise. It does not call the Telegram API or touch the database.

The Docker healthcheck runs:

```bash
python -m app.cli healthcheck
```

This CLI simply does an HTTP GET against the local endpoint and exits `0` on `200`. Because the check is purely a liveness signal for the application process, it succeeds immediately on startup without requiring any user to have messaged the bot first, and it is unaffected by Telegram or MySQL outages.

## Database Migrations

When models change, create a new migration:

```bash
uv run aerich migrate --name "description"
```

Apply migrations:

```bash
uv run aerich upgrade
```

## Running Tests

```bash
uv sync --extra dev
uv run pytest tests/
```

## Development

Install dependencies:

```bash
uv sync --extra dev
```

Run linters:

```bash
uv run ruff check .
uv run ruff format .
```

## Architecture

- **5 Parsers** (one per bank/channel): `UOBCCParser`, `UOBPayNowParser`, `DBSCCParser`, `DBSPayNowParser`, `PayLahParser` — each extends a shared `BankParser` base
- **Telegram Bot**: Command-based interface with whitelist authorization
- **Email Poller**: IMAP-based polling with deduplication
- **Database**: Tortoise-ORM async ORM with Aerich migrations
- **Timezone**: All user-facing times in SGT (Asia/Singapore), UTC at DB boundary

## Local Development (without Docker)

The full application (Telegram bot + poller + health server) runs locally with `uv run python -m app.main`. MySQL must be available — either installed directly or in a Docker container.

**1. Install dependencies**

```bash
uv sync
```

**2. MySQL**

Option A: Docker container only (no Docker Compose for the app):

```bash
docker run -d \
  --name expense-mysql \
  -e MYSQL_ROOT_PASSWORD=rootpassword \
  -e MYSQL_DATABASE=expense_tracker \
  -e MYSQL_USER=expense_user \
  -e MYSQL_PASSWORD=expense_password \
  -p 3306:3306 \
  mysql:8
```

Option B: Local MySQL installation — ensure it's running and create the database:

```sql
CREATE DATABASE expense_tracker;
CREATE USER 'expense_user'@'%' IDENTIFIED BY 'expense_password';
GRANT ALL ON expense_tracker.* TO 'expense_user'@'%';
```

**3. Configure `.env`**

```env
TIMEZONE=Asia/Singapore
DATABASE_URL=mysql://expense_user:expense_password@127.0.0.1:3306/expense_tracker
TELEGRAM_BOT_TOKEN=your-bot-token
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USERNAME=your-email@gmail.com
IMAP_PASSWORD=your-app-password
POLL_INTERVAL_SECONDS=60
LOG_LEVEL=INFO
```

**4. Bootstrap users**

Tortoise creates the schema automatically on first startup. You still need to insert user rows:

```sql
-- Find your Telegram chat_id by sending /start to @userinfobot
INSERT INTO users (telegram_chat_id, name, active) VALUES (123456789, 'Your Name', true);
INSERT INTO user_emails (user_id, email) VALUES (1, 'your-forwarding-email@gmail.com');
```

**5. Run**

```bash
# Full application (bot + poller + health server)
uv run python -m app.main

# Poller only (no Telegram, no DB required)
uv run python scripts/test_poller.py

# Parser smoke test
uv run python scripts/test_fixtures.py
uv run python scripts/run_parsers_on_polled.py
```
