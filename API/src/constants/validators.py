class VALIDATORS:
    USER_TYPE = ["Admin", "User"]
    USER_TYPE_ALL = ["All", "Admin", "User"]
    STATUS_ALL = ["All", "Active", "Inactive", "Blocked"]
    TWO_FACTOR_METHODS = ["authenticator", "email", "sms"]
    TICKET_STATUS = ["Open", "In Progress", "Resolved", "Closed"]
    TICKET_PRIORITY = ["Low", "Normal", "High", "Urgent"]

    ALLOWED_FILE_EXTENSIONS = {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".webp",
        ".svg",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".txt",
        ".csv",
        ".rtf",
        ".zip",
        ".rar",
        ".7z",
    }

    BLOCKED_FILE_EXTENSIONS = {
        ".exe",
        ".dll",
        ".bat",
        ".cmd",
        ".sh",
        ".ps1",
        ".vbs",
        ".js",
        ".msi",
        ".com",
        ".scr",
        ".pif",
        ".wsf",
        ".hta",
    }
