from src.services.auth.login_history_service import (
    get_login_history,
    logout_current,
    logout_session,
)
from src.services.auth.login_service import authenticate_admin, try_another_way
from src.services.auth.registration_service import verify_captcha_input
from src.services.auth.resolver_service import (
    get_available_2fa_methods,
    resolve_admin,
    resolve_record,
    resolve_user,
)
