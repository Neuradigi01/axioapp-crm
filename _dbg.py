import asyncio
import json
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ORG_ID = "41f9ede9-41b3-44ce-b489-3004566d4068"


async def main() -> None:
    url = (
        f"postgresql+asyncpg://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
        f"@{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_NAME']}"
    )
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        print("=== LAST 8 WA MESSAGES ===")
        r = await conn.execute(
            text(
                "SELECT m.direction, LEFT(m.text, 50) AS text, m.payload->'interactive' AS interactive, m.created_at "
                "FROM tbl_messages m JOIN tbl_conversations c ON c.id = m.conversation_id "
                "WHERE c.org_id = :o AND c.channel = 'whatsapp' "
                "ORDER BY m.created_at DESC LIMIT 8"
            ),
            {"o": ORG_ID},
        )
        for row in r:
            print(json.dumps(dict(row._mapping), default=str, indent=2))

        print()
        print("=== LAST 10 TRIGGER DIAGNOSTICS ===")
        r = await conn.execute(
            text(
                "SELECT bot_id::text, reason, detail, created_at "
                "FROM tbl_chatbot_trigger_diagnostics WHERE org_id = :o "
                "ORDER BY created_at DESC LIMIT 10"
            ),
            {"o": ORG_ID},
        )
        for row in r:
            print(json.dumps(dict(row._mapping), default=str, indent=2))

        print()
        print("=== RUN STATE + PARK ===")
        r = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'tbl_chatbot_runs' ORDER BY ordinal_position"
            )
        )
        cols = [row[0] for row in r]
        print("cols:", cols)

        r = await conn.execute(
            text(
                "SELECT * FROM tbl_chatbot_runs WHERE org_id = :o "
                "ORDER BY started_at DESC LIMIT 3"
            ),
            {"o": ORG_ID},
        )
        for row in r:
            d = dict(row._mapping)
            print(json.dumps(d, default=str, indent=2))

    await engine.dispose()


asyncio.run(main())
