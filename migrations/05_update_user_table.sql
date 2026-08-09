-- 05_update_user_table.sql
-- Two changes to the users table:
--   1. Widen telegram_chat_id from INT (signed 32-bit, max 2.1B) to
--      BIGINT (signed 64-bit). Telegram channel / supergroup IDs reach
--      past 2.1B; INT truncates them and inserts fail with:
--        ERROR 1264 (22003): Out of range value for column 'telegram_chat_id'
--   2. Drop telegram_username — the model no longer declares it.
--
-- Both changes are safe: widening INT to BIGINT is metadata-only in
-- MySQL 8 (no table copy). DROP COLUMN is fine if the column is unused.
--
-- Idempotent: re-running fails with "Out of range" if MySQL already
-- has the column at BIGINT, which is the signal to stop.

ALTER TABLE users
    MODIFY COLUMN telegram_chat_id BIGINT NOT NULL,
    DROP COLUMN telegram_username;

