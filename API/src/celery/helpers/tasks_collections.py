import logging

logger = logging.getLogger(__name__)


async def run_every_2_minutes():
    pass


async def run_every_day():
    """Daily maintenance jobs. Add new tasks here as the project
    grows; keep each one wrapped in a try/except so one failing job
    doesn't take the rest down.
    """
    try:
        from src.app.core.embed.log_service import (
            purge_old_embed_submissions,
        )

        deleted = await purge_old_embed_submissions()
        logger.info("daily.purge_old_embed_submissions deleted=%d", deleted)
    except Exception:
        logger.exception("daily.purge_old_embed_submissions failed")
