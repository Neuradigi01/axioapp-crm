import logging
import os
from logging.handlers import TimedRotatingFileHandler

from config import IS_DEVELOPMENT

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_LEVEL = logging.INFO if IS_DEVELOPMENT else logging.WARNING

file_handler = TimedRotatingFileHandler(
    filename=os.path.join(LOG_DIR, "app.log"),
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8",
)
file_handler.suffix = "%Y-%m-%d"
file_handler.setLevel(LOG_LEVEL)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))

console_handler = logging.StreamHandler()
console_handler.setLevel(LOG_LEVEL)
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))

logger = logging.getLogger("template_api")
logger.setLevel(LOG_LEVEL)
logger.addHandler(file_handler)
logger.addHandler(console_handler)
logger.propagate = False
