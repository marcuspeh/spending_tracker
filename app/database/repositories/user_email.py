from app.database.models.user_email import UserEmail


class UserEmailRepository:
    async def find_by_email(self, email: str) -> UserEmail | None:
        return await UserEmail.filter(email=email, deleted_at__isnull=True).first()

    async def list_for_user(self, user_id: int) -> list[UserEmail]:
        return await UserEmail.filter(user_id=user_id, deleted_at__isnull=True).all()

    async def insert(self, user_id: int, email: str) -> UserEmail:
        user_email = await UserEmail.create(user_id=user_id, email=email)
        return user_email
