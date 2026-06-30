from fastapi import Depends, HTTPException, status

from src.core.security.jwt import get_current_user


class AccessGuard:
    def __init__(self, allowed_route_ids: list[int]):
        self.allowed_route_ids = allowed_route_ids

    async def __call__(self, token_payload: dict = Depends(get_current_user)):
        access_rights = token_payload.get("access_rights", "")
        if not access_rights:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )

        user_rights = {int(r) for r in str(access_rights).split(",") if r.strip()}
        required_rights = set(self.allowed_route_ids)

        if not user_rights & required_rights:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )

        return token_payload
