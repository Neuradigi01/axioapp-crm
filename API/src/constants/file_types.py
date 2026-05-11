# ── Extension sets ─────────────────────────────────────────────────

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}

ALLOWED_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.txt', '.csv', '.rtf',
    '.zip', '.rar', '.7z',
}

BLOCKED_EXTENSIONS = {
    '.exe', '.dll', '.bat', '.cmd', '.sh', '.ps1', '.vbs',
    '.js', '.msi', '.com', '.scr', '.pif', '.wsf', '.hta',
    '.jar', '.py', '.php', '.asp', '.aspx', '.cgi', '.pl',
}

# ── Limits ────────────────────────────────────────────────────────

MAX_IMAGE_SIZE_BYTES = 2 * 1024 * 1024   # 2 MB
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024       # 10 MB
MAX_ATTACHMENTS = 5

# ── Magic byte signatures ────────────────────────────────────────
# The actual file content is checked, not the client-supplied extension or MIME type.

FILE_MAGIC_BYTES = {
    # Images
    b'\xff\xd8\xff':        'image/jpeg',
    b'\x89PNG\r\n\x1a\n':  'image/png',
    b'GIF87a':              'image/gif',
    b'GIF89a':              'image/gif',
    b'BM':                  'image/bmp',
    b'RIFF':                'image/webp',
    # Documents
    b'%PDF':                'application/pdf',
    b'\xd0\xcf\x11\xe0':   'application/msoffice',  # DOC, XLS, PPT (OLE2)
    b'PK\x03\x04':         'application/zip',        # DOCX, XLSX, PPTX, ZIP
    b'Rar!\x1a\x07':       'application/x-rar-compressed',
    b'7z\xbc\xaf\x27\x1c': 'application/x-7z-compressed',
}

# ── MIME → extension mapping ─────────────────────────────────────

MIME_EXTENSION_MAP = {
    'image/jpeg':                       {'.jpg', '.jpeg'},
    'image/png':                        {'.png'},
    'image/gif':                        {'.gif'},
    'image/bmp':                        {'.bmp'},
    'image/webp':                       {'.webp'},
    'application/pdf':                  {'.pdf'},
    'application/msoffice':             {'.doc', '.xls', '.ppt'},
    'application/zip':                  {'.docx', '.xlsx', '.pptx', '.zip'},
    'application/x-rar-compressed':     {'.rar'},
    'application/x-7z-compressed':      {'.7z'},
}

# Extensions that have no reliable magic bytes (text-based formats)
TEXT_EXTENSIONS = {'.txt', '.csv', '.rtf', '.svg'}
