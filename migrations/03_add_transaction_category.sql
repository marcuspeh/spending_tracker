-- 03_add_transaction_category.sql
-- Adds the LLM-generated `category` column to transactions.
-- Idempotent: re-running produces a Duplicate column name error, which
-- is the signal to stop.

ALTER TABLE transactions
    ADD COLUMN category VARCHAR(32) NULL,
    ADD INDEX idx_category (category);
