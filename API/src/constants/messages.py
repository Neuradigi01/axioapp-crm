# ── Generic ──────────────────────────────────────────────────────────
OK = "OK"
UNKNOWN_ERROR = "An unknown error occurred!"
DATABASE_CONNECTION_ERROR = "Database connection error!"
RECORD_NOT_FOUND = "Record not found!"
INVALID_TOKEN = "Invalid token!"
DECRYPTION_FAILED = "Decryption failed"

# ── Auth / Login ─────────────────────────────────────────────────────
INVALID_CREDENTIALS = "Invalid credentials!"
USER_NOT_FOUND = "User not found!"
USER_ID_EXISTS = "User ID already exists!"
EMAIL_EXISTS = "Email already registered!"
ACCOUNT_INACTIVE = "Account is inactive!"
INSUFFICIENT_PERMISSIONS = "Insufficient permissions!"
IMPERSONATE_USER_NOT_FOUND = "User not found for impersonation!"
LOGGED_OUT = "Logged out successfully!"
SESSION_LOGGED_OUT = "Session logged out successfully!"
SESSION_ALREADY_INACTIVE = "Session is already inactive!"

# ── Captcha ──────────────────────────────────────────────────────────
CAPTCHA_REQUIRED = "Captcha verification is required!"
INVALID_CAPTCHA = "Invalid captcha!"
CAPTCHA_DISABLED = "Captcha is disabled"

# ── Password ─────────────────────────────────────────────────────────
OLD_PASSWORD_INCORRECT = "Old password is incorrect!"
PASSWORD_CHANGED = "Password changed successfully!"
PASSWORD_RESET = "Password reset successfully!"
PASSWORD_RESET_LINK_SENT = "If this account exists, a reset link has been sent."
INVALID_RESET_TOKEN = "Invalid or expired reset token!"

# ── Registration ─────────────────────────────────────────────────────
REGISTRATION_SUCCESS = "Registration successful!"
REGISTRATION_SUCCESS_VERIFY_EMAIL = (
    "Registration successful! Please check your email to verify your account."
)
INVALID_REFERRAL_ID = "Invalid referral ID!"

# ── 2FA ──────────────────────────────────────────────────────────────
TWO_FACTOR_REQUIRED = "2FA code required!"
INVALID_OTP = "Invalid or expired OTP!"
TWO_FACTOR_NOT_ENABLED = "Two-factor authentication is not enabled!"
TWO_FACTOR_ENABLED_SUCCESS = "Two-factor authentication enabled!"
TWO_FACTOR_DISABLED_SUCCESS = "Two-factor authentication disabled!"
TWO_FACTOR_METHOD_CHANGED = "Preferred method changed to {}!"
NO_2FA_METHOD_AVAILABLE = "No 2FA method available. Please contact support."
METHOD_NOT_AVAILABLE = "This verification method is not available for your account!"
ALREADY_USING_METHOD = "Already using this method!"
SETUP_AUTHENTICATOR_FIRST = "Please set up authenticator first!"
INVALID_METHOD = "Invalid method!"

# ── OTP / Contact Verification ───────────────────────────────────────
EMAIL_SYSTEM_DISABLED = "Email system is not enabled!"
SMS_SYSTEM_DISABLED = "SMS system is not enabled!"
EMAIL_NOT_AVAILABLE = "Email is not available!"
SMS_NOT_AVAILABLE = "SMS is not available!"
AUTHENTICATOR_NO_OTP = "Authenticator does not require OTP sending!"
OTP_SENT = "OTP sent successfully!"
OTP_SENT_EMAIL = "OTP sent to your email!"
OTP_SENT_PHONE = "OTP sent to your phone!"
VERIFICATION_CODE_SENT = "Verification code sent!"
EMAIL_VERIFICATION_REQUIRED = "Email verification is required!"
MOBILE_VERIFICATION_REQUIRED = "Mobile verification is required!"
VERIFICATION_TOKEN_INVALID = "Verification token is invalid or expired!"
VERIFICATION_TOKEN_MISMATCH = "Verification token does not match the provided value!"
EMAIL_NOT_VERIFIED = "Your email is not verified. A verification email has been sent."
EMAIL_VERIFIED_SUCCESS = "Email verified successfully! You can now login."
VERIFICATION_EMAIL_MISMATCH = "This verification link is no longer valid for this account."

# ── Profile ──────────────────────────────────────────────────────────
PROFILE_UPDATED = "Profile updated successfully!"
PROFILE_IMAGE_UPDATED = "Profile image updated successfully!"
PROFILE_IMAGE_REMOVED = "Profile image removed successfully!"

# ── File Upload ──────────────────────────────────────────────────────
FILE_TYPE_NOT_ALLOWED = "File type not allowed!"
FILE_TOO_LARGE = "File size exceeds the maximum limit!"
FILE_EMPTY = "Uploaded file is empty!"
FILE_CONTENT_MISMATCH = "File content does not match its extension!"
TOO_MANY_ATTACHMENTS = "Too many attachments!"

# ── Admin ────────────────────────────────────────────────────────────
ADMIN_NOT_FOUND = "Admin not found!"
SUB_ADMIN_CREATED = "Sub-admin created successfully!"
SUB_ADMIN_UPDATED = "Sub-admin updated successfully!"
CANNOT_DEACTIVATE_SELF = "Cannot deactivate your own account!"
CANNOT_DEACTIVATE_SUPER_ADMIN = "Cannot deactivate a super admin!"
STATUS_UPDATED = "Status updated successfully!"

# ── Action Verification ──────────────────────────────────────────────
ACTION_2FA_REQUIRED = "Two-factor verification required for this action!"
ACTION_TOKEN_INVALID = "Action verification token is invalid or expired!"
ACTION_TOKEN_ALREADY_USED = "Action verification token has already been used!"
ACTION_VERIFIED = "Action verified successfully!"

# ── Routes ───────────────────────────────────────────────────────────
ROUTES_UPDATED = "Routes updated successfully!"
ROUTE_NOT_FOUND = "Route not found."
PARENT_ROUTE_NOT_FOUND = "Parent route not found."
ROUTE_CREATED = "Route created successfully."
ROUTE_UPDATED = "Route updated successfully."
ROUTE_DELETED = "Route deleted successfully."
ROUTE_CONTROL_ID_EXISTS = "Route with control_id '{}' already exists."
ROUTE_HAS_CHILDREN = "Cannot delete route with children. Remove children first."
ROUTES_CONFIG_NOT_FOUND = "Routes configuration not found."

# ── Tickets ──────────────────────────────────────────────────────────
TICKET_CLOSED = "This ticket is closed and cannot accept new replies!"
INVALID_STATUS = "Invalid status transition!"

# ── Content ──────────────────────────────────────────────────────────
NEWS_CREATED = "News created successfully!"
NEWS_UPDATED = "News updated successfully!"
NEWS_DELETED = "News deleted successfully!"
POPUP_CREATED = "Popup created successfully!"
POPUP_DELETED = "Popup deleted successfully!"
