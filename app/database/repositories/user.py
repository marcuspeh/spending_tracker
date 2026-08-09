from app.database.models.user import User


class UserRepository:
    async def get_by_chat_id(self, chat_id: int) -> User | None:
        return await User.filter(telegram_chat_id=chat_id, deleted_at__isnull=True).first()

    async def get_by_id(self, user_id: int) -> User | None:
        return await User.filter(id=user_id, deleted_at__isnull=True).first()

    async def list_active(self) -> list[User]:
        return await User.filter(active=True, deleted_at__isnull=True).all()

