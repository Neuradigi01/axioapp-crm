from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import all models here so Alembic can detect them
from src.models.action_token import UsedActionToken
from src.models.admin import Admin
from src.models.contact_us import ContactUs
from src.models.device_token import DeviceToken
from src.models.error_log import ErrorLog
from src.models.location import Country, State
from src.models.login_history import LoginHistory
from src.models.news import News
from src.models.newsletter import Newsletter
from src.models.notification import Notification
from src.models.otp import OtpRequest
from src.models.password_change_history import PasswordChangeHistory
from src.models.password_reset import PasswordResetToken
from src.models.popup import Popup
from src.models.profile_change_history import ProfileChangeHistory
from src.models.routes import AdminRoute, Route
from src.models.ticket import Ticket, TicketAttachment, TicketReply
from src.models.user import UserInfo, UserLogin
