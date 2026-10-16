# Code review — spending-tracker

Reviewed: `60df52c` ("remove polling logs") on branch `agentrig/6phyy6XIHZzn9sGHB__nj`.
Method: read every module in `app/`, then reproduced each claim below in a script before
reporting it. Anything I could not execute is marked as such.

---

## Verdict

The architecture is good — parser design, repository/service separation, and the
correlation-id logging are all above average. The problem is concentrated in one place:
**the email-ingestion write path is not crash-safe**, and one bug in it will silently
duplicate transactions. Two smaller issues (a crash reachable from a Telegram command and
an SSRF reachable from an email body) are the next most important.

`uv run pytest tests/` reports **380 passed** — but only when three env vars are supplied
by hand. See "Toolchain" below; that is finding #0 because it hides everything else.

---

## Findings

### 0. The test suite does not run on a clean checkout — HIGH

```
$ uv run pytest tests/ -q
23 errors during collection
E   pydantic_core._pydantic_core.ValidationError: 3 validation errors for Settings
E     telegram_bot_token  Value error, TELEGRAM_BOT_TOKEN is required
```

There is no `conftest.py`. `app/logging_setup.py` calls `client()` at **module import**
time (`tags_config_builders.py:27`), which runs `get_settings()` during collection, before
any fixture can supply env vars. Tests only pass because they happen to get lucky on
import order.

```
$ TELEGRAM_BOT_TOKEN=t IMAP_USERNAME=t@t.com IMAP_PASSWORD=t LOG_DISABLED=1 uv run pytest
380 passed
```

**Fix:** add `tests/conftest.py` that `monkeypatch.setenv`s the three required settings
before anything imports `app`. `tests/test_logging_wiring.py:33` already contains exactly
this fixture — it just needs to live at `tests/conftest.py` scope.

---

### 1. Transactions are inserted before the dedup row is written — CRITICAL

`app/services/email_ingestion.py` — order of operations in `process_email`:

```
1. dedup pre-check
2. parser.parse()
3. resolve user_email
4. await transaction_repo.insert(...)          <-- money row written
5. await notification_service.notify(...)      <-- Telegram message sent
6. await imported_email_repo.insert(...)       <-- dedup row written LAST
```

Step 6 is the *only* thing that stops this email from being re-imported forever, and it is
the step most likely to fail (`ImportedEmailRepository.insert` swallows `IntegrityError` and
returns `None` — and if the process dies between 4 and 6, the row is simply gone).

Reproduced — three polls of the same email:

```
poll 1: status=SUCCESS txns_inserted=1
poll 2: status=SUCCESS txns_inserted=2
poll 3: status=SUCCESS txns_inserted=3
```

The `imported_emails` rows written per poll: `[('m1', SUCCESS), ('m1', SUCCESS), ('m1', SUCCESS)]`
(the unique constraint did not save us — the pre-check is `SELECT`, the write is `INSERT`, and
nothing retries the `IntegrityError` path).

This is the worst failure mode in the app: **it is silent and it corrupts the user's data.**
`/today`, `/week`, `/month` totals silently inflate, and there is no way for the user to
notice.

**Fix:** write the dedup row *first*, before inserting the transaction, and update it to
`SUCCESS` afterwards. Cheapest correct form, given the single-writer assumption the README
already makes:

```python
# reserve the message id BEFORE any other write
reserved = await self.imported_email_repo.insert(message_id, ImportStatus.SKIPPED)
if reserved is None:
    return ImportStatus.SKIPPED   # another pass already claimed it
# ... parse, resolve, insert transaction ...
await self.imported_email_repo.set_status(message_id, ImportStatus.SUCCESS)
```

The email is only ever marked read after `SUCCESS`/`SKIPPED`, so the "FAILED" retry semantics
in the spec are unaffected.

---

### 2. `process_email` lets unexpected exceptions escape — HIGH

```python
try:
    parsed = parser.parse(email)
except ParserError:
    ...
```

Only `ParserError` is caught. A `Decimal` overflow, a MySQL `OperationalError`, or an
`httpx` error escapes the whole service. The caller then does this:

```python
except Exception as e:
    await asyncio.to_thread(self._mark_as_read, email)   # gmail.py:154
    log.error("email_failed", ...)
```

So a transient database blip **marks the email read and drops the transaction permanently**.
The poller's own error handling turns an infrastructure fault into silent data loss.

Reproduced:

```
RAISED out of process_email: RuntimeError MySQL Gone away
imported_email rows written: 0
```

**Fix:** wrap the body of `process_email` in a broad `except Exception` that records the
email as `FAILED` with the exception text as `reason`, so the email stays unseen and is
retried on the next poll.

---

### 3. Notification is sent before the dedup row exists — MEDIUM (part of #1)

```python
if self.notification_service is not None:
    await self.notification_service.notify_transaction(user_email.user_id, txn)
await self.imported_email_repo.insert(message_id, ImportStatus.SUCCESS)
```

Every duplicate from #1 also re-notifies, so a flapping DB turns into a notification
storm. Also note `NotificationService.notify_transaction` looks users up with
`get_by_id`, which filters only `deleted_at__isnull=True` — it does **not** check
`active`, unlike `UserRepository.list_active` that gates the bot whitelist. Deactivated
users still get emailed.

**Fix:** fixes itself once #1 is fixed. Separately, make `get_by_id` honour `active`, or
add `active` to the filter used by the notification path.

---

### 4. `/latest -5` raises out of the handler — MEDIUM

`app/telegram/handlers/queries.py:26`

```python
def _parse_count(args, default_count=10, max_count=50) -> int:
    if not args:
        return default_count
    try:
        return min(int(args[0]), max_count)
    except ValueError:
        return default_count
```

`min()` caps the top end but nothing floors the bottom. Verified:

```
_parse_count(['0'])  = 0
_parse_count(['-5']) = -5
```

which reaches Tortoise as `LIMIT -5`:

```
tortoise.exceptions.ParamsError: Limit should be non-negative number
```

The user sees nothing at all — PTB swallows the handler exception.

**Fix:** `return max(1, min(int(args[0]), max_count))`.

---

### 5. `curl_website` is an SSRF primitive driven by email content — MEDIUM

`app/services/tools/curl_website.py` validates only that the scheme is `http(s)` and there
is a host:

```python
if parsed.scheme not in ("http", "https") or not parsed.host:
    return {"error": "url must be an absolute http(s) URL"}
```

The URL is chosen by the LLM from the **merchant string, which comes from an inbound email
body**. Anyone who can get a mail delivered to the shared inbox controls it. A merchant
named `http://169.254.169.254/latest/meta-data/iam/security-credentials/` gets fetched by
the container and its response handed straight back to the model. `follow_redirects=True`
also lets a public host bounce to an internal address.

**Fix:** after DNS resolution, reject any address in loopback / link-local / RFC1918 /
`169.254.0.0/16` / unique-local ranges, and re-check after each redirect. A one-line
denylist on resolved IPs is proportionate for a self-hosted app.

---

### 6. Year-boundary transactions land in the wrong year — MEDIUM

`BankParser._extract_date` patches a year-less body date from the email `Date:` header.
When the transaction is late December and the alert arrives 1 January, the body wins on the
month/day and the header wins on the year — the transaction is dated in the future.

Verified:

```
txn body "on 31 Dec", email header 2026-01-01 09:00 UTC
  -> stored 2026-01-01 17:00+08:00      (should be 2025-12-31)
```

This silently moves spend between monthly buckets.

**Fix:** in `_resolve_year`, if the body date is within a few days *ahead* of the header
date (e.g. month/day > header month/day and the gap is < 10 days), use `header.year - 1`.

---

### 7. `/range` silently accepts an inverted range — LOW

`/range 2026-06-25 2026-06-01` passes validation and returns "No transactions found",
which reads like an empty account rather than a typo.

**Fix:** validate `start_date <= end_date` in `range_handler` and reply with a hint.

---

### 8. One IMAP connection per email just to set `\Seen` — LOW

`GmailPoller._mark_as_read` (`gmail.py:200`) opens a fresh login for each email, and it is
called per email (`gmail.py:154`). A 100-email poll means 101 logins every 60 seconds.
`_process_email` only receives a materialised `EmailMessage`, so the mailbox handle has to be
threaded through, or `mailbox.flag` needs the uid set — worth batching per poll cycle.

---

### 9. `_is_ignored` has a latent case-sensitivity asymmetry — LOW (not currently a bug)

```python
def _is_ignored(self, body_lower: str) -> bool:
    return any(kw.lower() in body_lower for kw in self._IGNORE_KEYWORDS)
```

To be clear about scope: I checked every call site and **this is not misbehaving today.**
All seven callers pass already-lowercased text — six pass `combined` from
`_combined_lower()`, and `DBSCCParser.can_parse` passes `body.lower()` — so the substring
test behaves correctly, which the fixtures confirm (`bill payment made` is rejected).

The issue is purely that the contract is implicit and fragile: the parameter is named
`body_lower` but nothing enforces it, and the one-sided `kw.lower()` reads as if it does.
The next caller who passes a raw body silently gets no ignore-matching at all — which, for
a `"Bill Payment Made"` email, means a transaction is recorded that should have been
skipped. Rename the parameter to `text`, lowercase both sides, and drop the misleading
`kw.lower()`.

---

### 10. `_strptime` accepts trailing garbage — LOW

```
_strptime("04 Jan 2026 16:55 ZZZ", "%d %b %Y %H:%M")
  -> datetime(2026, 1, 4, 16, 55)
```

The `tail` check compares `fmt[fmt_pos:]`, which is empty for every format used, so
nothing constrains the end of the string. A stricter `text_pos == len(text)` after the loop
would make the parser honest.

---

### 11. The poller has no tests at all — LOW

`tests/poller/` contains only `__init__.py`. The IMAP loop, the dedup pre-check, the
mark-as-read policy, and the correlation-id nesting — all untested. Given that finding #1
and #2 both live in this area, this is the gap that let them through.

---

## Toolchain issues

- **`aerich` is unusable.** It is a dependency and the README documents
  `uv run aerich migrate --name "..."`, but there is no Tortoise config anywhere:
  ```
  $ uv run aerich migrate --name test
  Error: Failed to load tortoise config from config_file(pyproject.toml)
  ```
  Migrations are hand-written `.sql` files applied by hand, and `generate_schemas()` runs
  at boot. Either add `[tool.aerich]` + `py-aerich.toml`, or drop the dependency and fix the
  README. Right now the documented workflow fails.
- **Lint does not pass.** `uv run ruff check .` → 40 errors (36 × `W292` missing trailing
  newline, 2 × `I001`, 1 × `F401` unused `typing.Any`, 1 × `N818`), and `ruff format --check` wants to
  reformat 52 files. CI would be red on day one.
- `N818` on `InvalidEditValue` (should be `…Error`) — rename or add to the ignore list.

---

## What's working well — worth keeping

- **Parser architecture.** `BankParser` + per-channel regex configuration, with a
  deliberately ordered registry (`DBSScanPayParser` before `DBSCCParser`, `DBSPayNowParser`
  before `PayLahParser`) and comments explaining *why* the order matters. `dateparser.py`
  hand-rolls `strptime` to avoid the `LC_TIME` dependency — thoughtful.
- **Fixtures.** `tests/fixtures/email_samples/` with real bank emails plus
  `test_table_driven.py` is the right way to make regex parsers maintainable.
- **`notification.py` swallows its own errors** (`log.error` + `return False`) so a Telegram
  outage can't block ingestion. Deliberate and correct.
- **Ownership never guesses.** `email_ingestion.py` trusts only `to`/`cc` and ignores `from`,
  with a comment explaining that SMTP headers are spoofable. Exactly right.
- **Correlation ids** (`app/logging_setup.py`) scoped per poll cycle and per email, with
  nesting. Rare and genuinely useful.
- **Every query filters `user_id` and `deleted_at`**; business logic never touches Tortoise
  querysets directly.

## Suggested order of work

1. `tests/conftest.py` — unblocks CI and finding #1's regression test. (5 min)
2. Fix #1 (dedup row first) and add a test asserting 3 polls → 1 transaction. (30 min)
3. Fix #2 (broad `except` in `process_email`). (15 min)
4. Fix #4 (`_parse_count` floor). (2 min)
5. Fix #5 (SSRF guard). (30 min)
6. Fix #6 (year boundary). (20 min)
7. Toolchain: decide on aerich, run `ruff check --fix` + `ruff format`. (20 min)
8. Add `tests/poller/test_gmail.py` covering dedup + mark-as-read. (1 h)