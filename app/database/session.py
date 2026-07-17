from tortoise import Tortoise

from app.config.settings import get_settings

TORTOISE_ORM = {
    "connections": {"default": get_settings().database_url},
    "apps": {
        "app": {
            "models": [
                "app.database.models",
                "aerich.models"
            ],
            "default_connection": "default",
        },
    },
}


async def init_db():
    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas()


async def close_db():
    await Tortoise.close_connections()
