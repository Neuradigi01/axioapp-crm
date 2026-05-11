from fastapi import Depends, HTTPException, status
from src.core.security.jwt import get_current_user


class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    async def __call__(self, token_payload: dict = Depends(get_current_user)):
        if token_payload.get("role") not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return token_payload
