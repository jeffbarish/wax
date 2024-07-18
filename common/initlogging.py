"""Log uncaught exceptions."""

import sys
import logging
from pathlib import Path
from logging import handlers

from common.constants import CONFIG_DIR

logger = logging.getLogger('wax')
# logger.setLevel(logging.WARNING)

logging.basicConfig(level=logging.ERROR)
# format='%(levelname)s:%(module)s:%(message)s')

file_handler = handlers.RotatingFileHandler(
        filename=Path(CONFIG_DIR, 'log', 'wax.log'),
        maxBytes=40000, backupCount=3)
# formatter = logging.Formatter('{asctime} - {levelname} - {message}',
#         style='{')
# file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

if sys.stderr.isatty():
    console_handler = logging.StreamHandler()
    # console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    logger.propagate = False

def log_except_hook(exc_type, exc_value, exc_traceback):
    logger.exception('', exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = log_except_hook

