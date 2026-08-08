"""One-shot migration: add the `tag` nullable column to `transactions`.

Tortoise's ``generate_schemas`` only creates new tables; it doesn't
ALTER existing ones. So we run this once to add the new column.

Run with:
    docker exec -it spending-tracker python /app/scripts/add_tag_column.py
"""

import asyncio

from tortoise import Tortoise

from app.config.settings import get_settings


async def main() -> None:
    await Tortoise.init(
        db_url=get_settings().database_url,
        modules={"models": ["app.database.models"]},
        _enable_global_fallback=True,
    )
    conn = Tortoise.get_connection("default")

    # Idempotent: only add if missing.
    await conn.execute_query(
        """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'transactions'
          AND column_name = 'tag'
        """
    )
    rows = await conn.execute_query(
        """
        SELECT COUNT(*) AS n
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'transactions'
          AND column_name = 'tag'
        """
    )
    exists = rows[1][0]["n"]
    if exists:
        print("tag column already exists — nothing to do.")
    else:
        await conn.execute_query(
            "ALTER TABLE transactions ADD COLUMN tag VARCHAR(64) NULL, ADD INDEX idx_tag (tag)"
        )
        print("Added transactions.tag column + idx_tag.")

    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())