from pathlib import Path

CONFIG_DIR = Path('.config')
QUEUEFILES = Path(CONFIG_DIR, 'queuefiles')
TRANSFER = Path(CONFIG_DIR, 'transfer')

DATABASE = Path('recordings')
DOCUMENTS = Path(DATABASE, 'documents')
IMAGES = Path(DATABASE, 'images')
SOUND = Path(DATABASE, 'sound')

# Only the folders in METADATA get checkpointed by waxconfig (which is why
# COMPLETERS is here).
METADATA = Path(DATABASE, 'metadata')
SHORT = Path(METADATA, 'short')
LONG = Path(METADATA, 'long')
CONFIG = Path(METADATA, 'config')
COMPLETERS = Path(METADATA, 'completers')

IMAGES_DIR = Path('data', 'images')

STATES = ['VOID_PENDING', 'NULL', 'READY', 'PAUSED', 'PLAYING']

PROPS_REC = ['source', 'codec', 'sample rate', 'resolution', 'date created']
PROPS_WRK = ['times played', 'date played']

# Border for images in Edit mode image viewer.
BORDER = 6     # border for cover art

THUMBNAIL_SIZE = (74, 74)

# MAIN_WINDOW_SIZE = (800, 480)
# RIGHT_PANEL_VBOX_WIDTH = 341
# PANED_POSITION = 254
# MAIN_WINDOW_SIZE = (890, 600) # 650 for iPad
# RIGHT_PANEL_VBOX_WIDTH = 360
# PANED_POSITION = 320
# IMPORT_PANED_POSITION = 180

METADATA_CLASSES = ('primary', 'secondary')

NOEXPAND = (False, False, 0)

SND_EXT = ('.wav', '.flac', '.ogg', '.mp3')
JPG_EXT = ('.jpg', '.jpeg', '.png')
PDF_EXT = ('.pdf',)
