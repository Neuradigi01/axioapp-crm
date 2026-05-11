# Database & ORM Code Templates & Reference

> **Purpose:** Code patterns and templates for SQLAlchemy ORM. Read `DATABASE_RULES.md` first for conventions.

---

## 1. Base Model Setup

```python
# src/models/__init__.py

from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

# Import all models here so Alembic can detect them
from src.models.admin import Admin
from src.models.user import UserLogin, UserInfo
# ... (all models must be imported for Alembic)
```

---

## 2. Model Files — Source of Truth

> **For actual schema details (columns, types, relationships), read the model file directly.**
> Do NOT duplicate field lists here — the model files ARE the schema definition.

| Model File | Classes | Table(s) | Purpose |
|-----------|---------|----------|---------|
| `src/models/user.py` | `UserLogin`, `UserInfo` | `tbl_user_login`, `tbl_user_info` | User credentials + profile |
| `src/models/admin.py` | `Admin` | `tbl_admin` | Admin credentials + settings |
| `src/models/routes.py` | `Route`, `AdminRoute` | `tbl_routes`, `tbl_admin_routes` | Route/permission definitions |
| `src/models/password_reset.py` | `PasswordResetToken` | `tbl_password_reset_tokens` | Password reset tokens |
| `src/models/login_history.py` | `LoginHistory` | `tbl_login_history` | Login history tracking |
| `src/models/otp.py` | `OtpRequest` | `tbl_otp_requests` | OTP requests for 2FA |
| `src/models/ticket.py` | `Ticket`, `TicketReply`, `TicketAttachment` | `tbl_tickets`, `tbl_ticket_replies`, `tbl_ticket_attachments` | Support ticket system |
| `src/models/action_token.py` | `UsedActionToken` | `tbl_used_action_tokens` | Action verification tokens |
| `src/models/profile_change_history.py` | `ProfileChangeHistory` | `tbl_profile_change_history` | Profile change audit log |
| `src/models/password_change_history.py` | `PasswordChangeHistory` | `tbl_password_change_history` | Password change audit log |
| `src/models/contact_us.py` | `ContactUs` | `tbl_contact_us` | Contact form submissions |
| `src/models/newsletter.py` | `Newsletter` | `tbl_newsletter` | Newsletter subscriptions |
| `src/models/news.py` | `News` | `tbl_news` | News/announcements |
| `src/models/popup.py` | `Popup` | `tbl_popups` | Popup announcements |
| `src/models/notification.py` | `Notification` | `tbl_notifications` | In-app notifications |
| `src/models/device_token.py` | `DeviceToken` | `tbl_device_tokens` | FCM push notification tokens |
| `src/models/location.py` | `Country`, `State` | `tbl_countries`, `tbl_states` | Location/geography data |
| `src/models/error_log.py` | `ErrorLog` | `tbl_error_logs` | Application error logs |

---

## 3. New Model Template

When creating a new model, follow this exact pattern:

```python
# src/models/<name>.py

from datetime import datetime
from sqlalchemy import BigInteger, Integer, Text, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from src.models import Base


class ModelName(Base):
    __tablename__ = 'tbl_model_name'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Required audit columns
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Polymorphic user/admin reference (use integer member_id, not text user_id)
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_type: Mapped[str] = mapped_column(Text, nullable=False, default='User')

    # Admin-only reference (use proper FK)
    # created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey('tbl_admin.id'), nullable=True)

    # Indexes
    __table_args__ = (
        Index('idx_tbl_model_name_member_id', 'member_id'),
    )
```

**After creating:** Import the model in `src/models/__init__.py` and run `alembic revision --autogenerate`.

---

## 4. Query Pattern Examples

### 4.1 Select Single Record
```python
stmt = select(UserLogin).where(UserLogin.user_id == user_id)
result = await db.execute(stmt)
user = result.scalar_one_or_none()
```

### 4.2 Select with Relationship Loaded
```python
from sqlalchemy.orm import selectinload
stmt = (
    select(UserLogin)
    .options(selectinload(UserLogin.user_info))
    .where(UserLogin.user_id == user_id)
)
result = await db.execute(stmt)
user = result.scalar_one_or_none()
# Access: user.user_info.first_name
```

### 4.3 Pagination with Count
```python
# Count
count_stmt = select(func.count()).select_from(base_query.subquery())
total = (await db.execute(count_stmt)).scalar()

# Data
data_stmt = base_query.order_by(Model.created_at.desc()).offset(page_index * page_size).limit(page_size)
records = (await db.execute(data_stmt)).scalars().all()
```

### 4.4 Insert
```python
new_record = Model(column1=value1, column2=value2)
db.add(new_record)
await db.flush()  # Get auto-generated ID before commit
# Commit happens in the SERVICE layer, not DA
```

### 4.5 Bulk Update
```python
from sqlalchemy import update
stmt = (
    update(Model)
    .where(Model.id == record_id)
    .values(column=new_value)
)
result = await db.execute(stmt)
return result.rowcount > 0  # DA returns bool
# Commit happens in the SERVICE layer
```

### 4.6 Delete
```python
from sqlalchemy import delete
stmt = delete(Model).where(Model.id == record_id)
result = await db.execute(stmt)
return result.rowcount > 0  # DA returns bool
# Commit happens in the SERVICE layer
```

---

## 5. Transaction Patterns

### 5.1 Standard (Service Layer Commits)
```python
# Service layer
async def create_user_with_info(db: AsyncSession, ...):
    user = UserLogin(...)
    db.add(user)
    await db.flush()  # Need ID for child record

    info = UserInfo(member_id=user.id, ...)
    db.add(info)

    await db.commit()  # Commits both records atomically
```

### 5.2 Explicit Rollback
```python
try:
    # mutations...
    await db.commit()
except Exception as e:
    await db.rollback()
    return {'success': False, 'message': str(e)}
```

---

## 6. Relationship Loading Strategies

### selectinload (Separate SELECT IN query — preferred for collections)
```python
from sqlalchemy.orm import selectinload
stmt = select(UserLogin).options(selectinload(UserLogin.user_info)).where(...)
```

### joinedload (Single JOIN query — preferred for single relations)
```python
from sqlalchemy.orm import joinedload
stmt = select(Admin).options(joinedload(Admin.admin_routes).joinedload(AdminRoute.route)).where(...)
result = await db.execute(stmt)
admin = result.unique().scalar_one_or_none()
```

---

## 7. Model Serialization

```python
def model_to_dict(model_instance, exclude: list[str] = None):
    exclude = exclude or []
    return {
        column.name: getattr(model_instance, column.name)
        for column in model_instance.__table__.columns
        if column.name not in exclude
    }
```

---

## 8. Alembic Migration Commands

```bash
# Generate migration from model changes
alembic revision --autogenerate -m "add user referral_id column"

# Apply all pending migrations
alembic upgrade head

# Rollback last migration
alembic downgrade -1

# View current version / history
alembic current
alembic history
```

---

> For rules and conventions, see `DATABASE_RULES.md`.
