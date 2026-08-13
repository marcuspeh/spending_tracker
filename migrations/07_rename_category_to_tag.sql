-- 07_rename_category_to_tag.sql
-- Rename the LLM-derived category column to ``tag`` (rename, not drop).
-- The user-facing concept stays the same: each transaction carries a
-- single label chosen by the LLM from a fixed set of values.
--
-- Why a rename: the bot is shipped as /tag — a single command that
-- works on insertion and edits. /edit uses the column name as its
-- argument, so the field has to be named ``tag``.
--
-- Idempotent: re-running fails with "Unknown column" or "Duplicate
-- key name" — both are signals to stop.

ALTER TABLE transactions
    CHANGE COLUMN category tag VARCHAR(32) NULL;
ALTER TABLE transactions
    DROP INDEX idx_category;
ALTER TABLE transactions
    ADD INDEX idx_tag (tag);

-- Same rename on the cache table so the categorizer's INSERT keeps
-- working with the new column name.
ALTER TABLE merchant_category_cache
    CHANGE COLUMN category tag VARCHAR(32) NOT NULL;