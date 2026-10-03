"""Run the LLM-based merchant tagger once against a sample merchant.

This is a one-shot smoke test for the categoriser + tool-calling loop.
It bypasses MySQL (the cache table is materialised on a local SQLite DB
via Tortoise) and config_store (the TagsProvider singleton is built but
its watchers aren't started — the fallback tag list is used).

    uv run python -m scripts.run_categorizer_once "AMZN Mktp US"
    uv run python -m scripts.run_categorizer_once "KOPI TECHONG TIONG BAHRU"

The merchant string is the only required argument. Useful flags:

    --no-cache      Force the LLM call (skip the SQLite cache).
    --reset-cache   Clear the SQLite cache table before starting.

Logs are emitted at INFO so the tool-call exchange is visible.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from tortoise import Tortoise

# Ensure we can import the app package regardless of how the script is
# invoked (uv run / python -m / python scripts/run_categorizer_once.py).
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("merchant", help="Merchant string to tag.")
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip the cache (always call the LLM).",
    )
    p.add_argument(
        "--reset-cache",
        action="store_true",
        help="Truncate the cache table before running.",
    )
    return p


async def _init_sqlite_cache() -> None:
    """Stand up a minimal Tortoise/aiosqlite DB so the cache repo works.

    Uses the SQLite URL Tortoise ships by default; no schema migrations
    are applied — Tortoise's ``generate_schemas`` materialises the
    ``merchant_category_cache`` table from the model definition.
    """
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["app.database.models"]},
        _enable_global_fallback=True,
    )
    await Tortoise.generate_schemas()


async def _shutdown_sqlite_cache() -> None:
    await Tortoise.close_connections()


async def _run(merchant: str, *, no_cache: bool, reset_cache: bool) -> int:
    from app.database.models.merchant_category_cache import MerchantTagCache
    from app.services.categorizer import tag_for
    from app.services.tags_provider import init_tags_provider

    # Stand up the cache backend + a TagsProvider singleton so
    # ``current_tags()`` doesn't raise. The singleton is *not* started, so
    # no config_store polling happens — fallback tags are used.
    await _init_sqlite_cache()
    init_tags_provider()

    if reset_cache:
        await MerchantTagCache.all().delete()

    if no_cache:
        # Drop any cached row for this merchant so we exercise the LLM
        # path. Done via direct SQL because the repo normalises the key.
        from app.services.merchant_normalizer import normalize_merchant
        cache_key = normalize_merchant(merchant)
        await MerchantTagCache.filter(merchant=cache_key).delete()

    tag = await tag_for(merchant)
    print(f"\n>>> tag_for({merchant!r}) -> {tag!r}")

    await _shutdown_sqlite_cache()
    return 0 if tag is not None else 2


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    args = _build_argparser().parse_args()
    code = asyncio.run(_run(args.merchant, no_cache=args.no_cache, reset_cache=args.reset_cache))
    raise SystemExit(code)


if __name__ == "__main__":
    main()