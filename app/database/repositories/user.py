from app.database.models.user import User


class UserRepository:
    async def get_by_chat_id(self, chat_id: int) -> User | None:
        return await User.filter(telegram_chat_id=chat_id, deleted_at__isnull=True).first()

    async def list_active(self) -> list[User]:
        return await User.filter(active=True, deleted_at__isnull=True).all()

    async def insert(
        self,
        telegram_chat_id: int,
        name: str,
        telegram_username: str | None = None,
    ) -> User:
        user = await User.create(
            telegram_chat_id=telegram_chat_id,
            name=name,
            telegram_username=telegram_username,
            active=True,
        )
        return user
