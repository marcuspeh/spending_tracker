# Expense Tracker - MVP Specification

## Goal

Build a self-hosted expense tracker that automatically imports transactions from forwarded emails and allows users to query and manage expenses through Telegram.

This is a personal project running on a home Ubuntu server.

The system should be simple, maintainable, and optimized for a small number of users (less than 20).

All times are handled in **Singapore Time (SGT, `Asia/Singapore`)** — input, output, and date math. The only exception is database storage, where timestamps are converted to and stored in **GMT+0 (UTC)**. All transactions are assumed to be in **SGD**.

The application runs as a **single instance**. The Gmail mailbox is used exclusively by this application — no other IMAP clients should connect to it.

---

## Architecture

Single Python application containing:

1. Email Poller
2. Email Parsers
3. Telegram Bot
4. MySQL Persistence Layer

No REST API.

No web UI.

No AI categorization.

No budgeting features.

The application will run in a single Docker container.

MySQL 8 already exists in a separate Docker container.

Refunds and credits are both registered as transactions. Amounts are signed — negative values represent refunds/credits so that `/today`, `/week`, `/thismonth`, and `/range` aggregate correctly.

---

## Supported Transaction Sources

Initial support only:

1. PayNow emails (incoming transfers, outgoing payments, refunds)
2. PayLah emails (credits, debits, refunds)
3. UOB card transaction emails (purchases, refunds, credits)

Design the parser architecture so additional banks can be added later.

---

## High-Level Flow

1. Users configure Gmail to forward bank transaction emails (auto-forward rule or manual forward) to a shared Gmail inbox.
2. The shared Gmail mailbox is accessed exclusively by this application.
3. Email poller checks the mailbox every 60 seconds.
4. Unprocessed emails are parsed. The original bank sender is preserved in the message headers; the forwarder's address is used to identify the owning user.
5. Parsed transactions are stored in MySQL.
6. Telegram bot allows users to query, edit, and delete their transactions.

---

## User Ownership Model

A transaction belongs to a user based on the email address of the person who **forwarded** the email to the shared inbox — not the original bank sender.

Example:

User: Marcus

Registered forwarder emails:

* [marcus@gmail.com](mailto:marcus@gmail.com)
* [marcus.work@gmail.com](mailto:marcus.work@gmail.com)

If Marcus forwards a DBS PayNow email from his personal Gmail to the shared inbox, all parsed transactions are attributed to Marcus.

A user may register multiple forwarding email addresses.

User onboarding is performed via direct database changes for the MVP (no admin command, no Telegram registration flow). The application loads the whitelist from the `users` table on startup.

---

## Database Schema

### users

Fields:

* id
* telegram_chat_id (unique)
* telegram_username
* name
* active
* created_at
* updated_at
* deleted_at (nullable)

Purpose:
Stores whitelisted Telegram users.

User onboarding is performed via direct database changes for the MVP.

---

### user_emails

Fields:

* id
* user_id
* email (unique)
* created_at
* updated_at
* deleted_at (nullable)

Purpose:
Maps forwarding email addresses to users.

One user may have multiple emails.

---

### transactions

Fields:

* id
* user_id
* amount (signed; negative for refunds/credits)
* merchant
* payment_method (enum: `MANUAL`, `PAYLAH_DEBIT`, `DBS_PAYNOW_DEBIT`, `DBS_PAYNOW_CREDIT`, `UOB_PAYNOW_DEBIT`, `UOB_PAYNOW_CREDIT`, `UOB_CC`, `UOB_CC_REFUND`, `DBS_CC`, `DBS_CC_REFUND`)
* transaction_time (stored in UTC / GMT+0; presented to the user in SGT)
* description (nullable; freeform note)
* created_at
* updated_at
* deleted_at (nullable)

Purpose:
Stores parsed and manual transactions.

---

### imported_emails

Fields:

* message_id (primary key)
* sender_email (original bank sender)
* forwarder_email (the Gmail user who forwarded the email)
* subject
* imported_at
* status (enum: `SUCCESS`, `FAILED`, `SKIPPED`)
* created_at
* updated_at
* deleted_at (nullable)

Purpose:

* Prevent duplicate imports
* Track processing history
* Assist debugging

Status semantics:

* `SUCCESS` — a parser matched (`can_parse()` returned True) and `parse()` completed; at least one transaction was inserted.
* `FAILED` — a parser matched but raised an exception during `parse()`. No further parsers are tried.
* `SKIPPED` — no parser matched (`can_parse()` returned False for all parsers). Typically a notification or non-transaction email.

---

## Parser Architecture

Create a BaseParser interface.

Methods:

* `can_parse(email) -> bool`
* `parse(email) -> ParsedTransaction`

Implement:

* `PayNowParser`
* `PayLahParser`
* `UOBParser`

Parser selection rules:

* Parsers are iterated in registration order.
* The first parser whose `can_parse()` returns True is selected.
* If no parser matches, the email is recorded with status `SKIPPED`.
* If the selected parser's `parse()` raises an exception, the email is recorded with status `FAILED` and no further parsers are tried.
* On successful parse, the email is recorded with status `SUCCESS` and the resulting transaction(s) are inserted.

The parser returns:

`ParsedTransaction`:

* `amount` (signed; negative for refunds/credits)
* `merchant`
* `payment_method` (one of the `transactions.payment_method` enum values)
* `transaction_time` (datetime in SGT)
* `description` (optional)

Requirements:

* Strong typing
* Clear parser separation
* Easy to add new banks later

---

## Email Poller

Requirements:

* Use IMAP
* Gmail App Password authentication
* Poll every 60 seconds
* Only process unseen emails
* Skip emails already present in `imported_emails`
* Mark emails as read **only after successful processing** (status `SUCCESS`). Emails that fail or are skipped remain unseen and will be retried on the next poll.
* Log all failures
* Continue processing if one email fails

Operational notes:

* The shared Gmail mailbox is accessed exclusively by this application. No other IMAP clients should connect.
* Only one application instance is expected to run. No concurrency control or leader election is required.
* Configuration through environment variables.

---

## Telegram Bot

Only whitelisted users may use commands.

Whitelist is determined by `telegram_chat_id` in the `users` table.

Reject all unknown users.

All users may only access their own transactions.

All times shown to the user are formatted in **SGT**. All date inputs are interpreted in **SGT**.

The Telegram bot also serves as the **healthcheck endpoint**. The `/ping` command returns `pong` and is used by the Docker healthcheck.

---

## Telegram Commands

All times are handled in **SGT** — date inputs, date boundaries, and formatted output. Timestamps are converted to **UTC** at the storage boundary only.

Amounts may be negative for refunds and credits, and aggregates include them.

### /start

Display a welcome message and a short summary of available commands.

---

### /help

Display detailed help for all commands, with usage examples.

---

### /ping

Returns `pong`. Used as the primary healthcheck signal.

---

### /latest [count]

Return the latest N transactions for the requesting user, newest first.

* Default: `10`
* Maximum: `50`

Example:

1. Starbucks $5.20
2. Grab $14.30
3. PayNow John $20.00

---

### /today

Return total spending for today, where "today" is the current SGT calendar day. The query window is `[today 00:00 SGT, tomorrow 00:00 SGT)` converted to UTC for storage lookup.

---

### /week

Return total spending for this week, from Monday 00:00 SGT through now (UTC conversion applied at the storage boundary).

---

### /thismonth

Return total spending for this month, from the 1st 00:00 SGT through now (UTC conversion applied at the storage boundary).

---

### /range <start_date> <end_date>

Return all transactions within the inclusive date range.

Date format: `YYYY-MM-DD`. Dates are interpreted in SGT and converted to UTC at the storage boundary.

Example:

/range 2026-06-01 2026-06-15

---

### /search <merchant>

Return all transactions whose merchant contains the search term (case-insensitive substring match), newest first.

Example:

/search starbucks

---

### /add <amount> <merchant> [description] [date]

Create a manual transaction.

Examples:

/add 12.50 Lunch
/add 12.50 "Lunch with client" 2026-06-24

Fields:

* `amount` — required; signed (negative for refunds)
* `merchant` — required
* `description` — optional freeform note (quote if it contains spaces)
* `date` — optional; `YYYY-MM-DD` in SGT; defaults to today

Resulting transaction:

* `payment_method = MANUAL`
* `transaction_time` = supplied date at 00:00 SGT, or now (in SGT)

---

### /edit <transaction_id> <field> <value>

Edit a transaction owned by the requesting user.

Editable fields:

* `amount`
* `merchant`
* `description`
* `transaction_time` — `YYYY-MM-DD` or `YYYY-MM-DD HH:MM` (interpreted in SGT, converted to UTC for storage)

Example:

/edit 42 merchant "Starbucks Reserve"

Users cannot edit transactions belonging to other users.

---

### /delete <transaction_id>

Initiate deletion of a transaction owned by the requesting user.

Requires confirmation (two-step flow to prevent accidental deletion):

1. First call returns a confirmation prompt:
   `Delete transaction 42 (Starbucks $5.20 on 2026-06-24)? Reply /confirm 42 to proceed.`
2. The user replies with `/confirm <transaction_id>` to execute the deletion.

Users cannot delete transactions belonging to other users.

---

### /confirm <transaction_id>

Confirm a pending deletion. See `/delete`.

---

## Security Requirements

Users may only view their own transactions.

All database queries must filter by user_id.

Telegram chat IDs must be validated before executing commands.

Reject unknown users with a clear error message.

---

## Database Access

Use Tortoise-ORM exclusively.

Requirements:
- Tortoise-ORM async ORM
- Declarative models
- Repository pattern for database operations
- No raw SQL except where absolutely necessary

Repositories should include:
- UserRepository
- UserEmailRepository
- TransactionRepository
- ImportedEmailRepository

Business logic should not directly interact with Tortoise querysets or database connections.

---

## Database Migrations

Use Tortoise-ORM's built-in migration support.

Target database: **MySQL 8.0**.

Requirements:
- Initial schema creation via Tortoise models
- Future schema changes handled through Tortoise migrations
- Migration instructions documented in README

Provide:
- Tortoise-ORM model definitions
- Initial migration
- Migration configuration

A fresh database should be fully bootstrapped through Tortoise migration.

---

## Service Layer

Create a service layer between repositories and application logic.

Examples:

ExpenseService:

* add_transaction()
* delete_transaction()
* get_latest_transactions()
* get_today_spending()
* get_month_spending()

Repositories should only handle persistence.

Business logic belongs in services.

---

## Logging

Use structured logging.

Log:

* Email polling start/end
* Email processing
* Parser selected
* Transaction inserted
* Telegram command execution
* Errors and exceptions

Logs should be Docker-friendly and written to stdout.

---

## Configuration Management

Use Pydantic Settings.

Requirements:

* Centralized configuration class
* Validation of required settings
* Typed configuration
* Environment variable loading
* `.env` support

Example:

```python
class Settings(BaseSettings):
    timezone: str = "Asia/Singapore"
    log_level: str = "INFO"

    mysql_host: str
    mysql_port: int
    mysql_database: str
    mysql_user: str
    mysql_password: str

    telegram_bot_token: str

    imap_host: str
    imap_port: int
    imap_username: str
    imap_password: str

    poll_interval_seconds: int = 60
```

---

## Environment File Support

Provide a `.env.example` file.

Include:

```
MYSQL_HOST=
MYSQL_PORT=
MYSQL_DATABASE=
MYSQL_USER=
MYSQL_PASSWORD=

TELEGRAM_BOT_TOKEN=

IMAP_HOST=
IMAP_PORT=
IMAP_USERNAME=
IMAP_PASSWORD=

POLL_INTERVAL_SECONDS=60

TIMEZONE=Asia/Singapore
LOG_LEVEL=INFO
```

The application must support both:

* docker compose
* local execution via Python

using the same configuration.

---

## Dependency Management

Use uv for dependency management.

Requirements:

* pyproject.toml
* uv.lock
* Reproducible builds
* Clear installation instructions

Do not use requirements.txt as the primary dependency management mechanism.

---

## Unit Testing

Use pytest.

Provide parser tests for:

### PayNow Parser

Test:

* Valid transaction email
* Invalid email
* Missing amount
* Missing merchant

### PayLah Parser

Test:

* Valid transaction email
* Invalid email
* Missing amount
* Missing merchant

### UOB Parser

Test:

* Valid transaction email
* Invalid email
* Missing amount
* Missing merchant

Requirements:

* Sample email fixtures
* Edge case coverage
* Clear assertions

Tests should run independently without MySQL, IMAP, or Telegram dependencies.

---

## Docker

Provide:

* `Dockerfile`
* `docker-compose.yml` example

Container requirements:

* `restart: unless-stopped`
* environment variable support
* healthcheck command that verifies the Telegram bot is alive

The application should connect to an existing **MySQL 8** container on the same Docker network.

Do not provision MySQL in `docker-compose.yml`.

### Healthcheck

Health is verified by sending `/ping` to the configured Telegram bot and confirming a `pong` response within the timeout window.

The container must expose a CLI command to perform this check:

```
python -m app.cli healthcheck
```

This command exits 0 on success, non-zero on failure.

Docker healthcheck example:

```
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD python -m app.cli healthcheck || exit 1
```

Note: a successful healthcheck requires that at least one whitelisted Telegram user has previously sent a command to the bot (Telegram bots can only initiate conversations in response to user action).

---

## Recommended Project Structure

expense-tracker/

├── app/
│   ├── config/
│   │   └── settings.py
│   │
│   ├── database/
│   │   ├── models/
│   │   ├── repositories/
│   │   └── session.py
│   │
│   ├── poller/
│   │   ├── gmail.py
│   │   └── parsers/
│   │
│   ├── telegram/
│   │   └── commands/
│   │
│   ├── services/
│   │
│   └── main.py
│
├── tests/
│   ├── parsers/
│   └── fixtures/
│
├── migrations/
│
├── alembic.ini
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md

---

## Deliverables

Implement a fully working MVP including:

* Database models (with `created_at` / `updated_at` / `deleted_at` on all tables)
* Alembic migrations targeting **MySQL 8**
* Repository layer
* Service layer
* IMAP email polling (single instance, app-exclusive mailbox)
* `PayNowParser`
* `PayLahParser`
* `UOBParser`
* Telegram bot with commands: `/start`, `/help`, `/ping`, `/latest`, `/today`, `/week`, `/thismonth`, `/range`, `/search`, `/add`, `/edit`, `/delete`, `/confirm`
* User authorization (whitelist via the `users` table; manual DB onboarding)
* SGT for all time handling (input, output, date math); UTC only at the DB storage boundary
* Signed `amount` (negative for refunds/credits)
* Docker deployment with healthcheck via `python -m app.cli healthcheck`
* Unit tests
* Documentation

Prioritize simplicity, maintainability, and reliability over premature optimization.

The code should be production-ready for a personal self-hosted deployment on Ubuntu Server.
