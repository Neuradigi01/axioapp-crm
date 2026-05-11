import os
import orjson
from sqlalchemy import select
from src.core.db import async_session
from src.core.logger import logger
from src.models.routes import Route
from config import ROUTES_API


async def generate_routes_json():
    async with async_session() as db:
        stmt = select(Route).where(Route.is_active == True).order_by(Route.order_no)
        routes = (await db.execute(stmt)).scalars().all()

    routes_dict = {}
    for r in routes:
        routes_dict[r.control_id] = {
            "id": r.id,
            "parent_id": r.parent_id,
            "control_id": r.control_id,
            "user_type": r.user_type,
            "name": r.name,
            "path": r.path,
            "url": r.url,
            "description": r.description,
            "mat_icon": r.mat_icon,
            "css_classes": r.css_classes,
            "is_nav_menu_item": r.is_nav_menu_item,
            "order_no": r.order_no,
            "nav_parent_id": r.nav_parent_id,
            "is_compulsory": r.is_compulsory,
        }

    json_bytes = orjson.dumps(routes_dict, option=orjson.OPT_INDENT_2)

    os.makedirs(os.path.dirname(ROUTES_API) or ".", exist_ok=True)
    with open(ROUTES_API, "wb") as f:
        f.write(json_bytes)

    logger.info(f"Generated routes.json with {len(routes_dict)} routes")
