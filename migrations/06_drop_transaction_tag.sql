-- 06_drop_transaction_tag.sql
-- Drop the free-form ``tag`` column from transactions. The /tag command
-- has been removed in favour of the LLM-driven /category. Existing
-- rows lose their tag value — the column was nullable, so this is safe.
--
-- Idempotent: re-running fails with "check that column/key exists"
-- because the index is already gone, which is the signal to stop.

ALTER TABLE transactions DROP INDEX idx_tag;
ALTER TABLE transactions DROP COLUMN tag;