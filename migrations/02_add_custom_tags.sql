-- 02_add_custom_tags.sql
-- Adds the user-defined free-form `tag` column to transactions.
-- Idempotent: re-running produces a Duplicate column name error, which
-- is the signal to stop.

ALTER TABLE transactions
    ADD COLUMN tag VARCHAR(64) NULL,
    ADD INDEX idx_tag (tag);
