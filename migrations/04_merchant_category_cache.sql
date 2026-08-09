-- 04_merchant_category_cache.sql
-- Persistent cache of merchant → category mappings, populated only by
-- successful LLM responses. The bot reads from this table before
-- calling the LLM; on a hit it skips the network entirely.
--
-- The cache is read-only from the bot's perspective: the only write
-- path is the categorizer's success branch. To change a row, modify
-- MySQL directly.
--
-- Idempotent: re-running produces a Table already exists error, which
-- is the signal to stop.

CREATE TABLE merchant_category_cache (
    merchant VARCHAR(255) NOT NULL,
    category VARCHAR(32) NOT NULL,
    source VARCHAR(16) NOT NULL DEFAULT 'llm',
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                 ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (merchant)
);
