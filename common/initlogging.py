"""Log uncaught exceptions."""

import sys
import logging
from pathlib import Path
from logging import handlers

from .constants import CONFIG_DIR

logger = logging.getLogger('wax')

formatter = logging.Formatter(
        style='{',
        datefmt='%Y-%m-%d %H:%M:%S',
        fmt='\n{asctime}\n{message}')

file_handler = handlers.RotatingFileHandler(
        filename=Path(CONFIG_DIR, 'log', 'wax.log'),
        maxBytes=40000, backupCount=3)
file_handler.setLevel(logging.ERROR)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

if sys.stderr.isatty():
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)
    logger.addHandler(console_handler)
    logger.propagate = False

def log_except_hook(exc_type, exc_value, exc_traceback):
    logger.exception('', exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = log_except_hook

