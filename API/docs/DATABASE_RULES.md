# Database & ORM Rules & Conventions

> **Purpose:** Rules and conventions for SQLAlchemy ORM models and database development. For full code templates, see `DATABASE_REFERENCE.md`.

---

## 0. Critical Rules

### 0.1 ORM-First Approach
ALL database operations MUST go through SQLAlchemy ORM. No raw SQL unless absolutely necessary (complex aggregations, bulk operations where ORM is too slow).

### 0.2 Async Sessions
ALL database operations MUST use async sessions via `async with get_db() as session:` or FastAPI's `Depends(get_db)`.

### 0.3 Migrations via Alembic
ALL schema changes MUST be managed through Alembic migrations. Never modify the database directly.

---

## 1. Naming Conventions

### Tables
- Prefix: `tbl_` — e.g., `tbl_user_login`, `tbl_user_info`, `tbl_admin`
- Table names in model: `__tablename__ = 'tbl_user_login'`

### Models (Python Classes)
- PascalCase, no prefix — e.g., `UserLogin`, `UserInfo`, `Admin`, `Route`
- File names: snake_case — e.g., `user.py`, `admin.py`, `routes.py`

### Columns
- snake_case — e.g., `user_id`, `first_name`, `created_at`, `is_active`
- Foreign keys: `<referenced_table_entity>_id` — e.g., `member_id`, `admin_id`, `route_id`

### User/Admin Reference Columns (Strict Rule)
- **Text `user_id`/`admin_user_id` columns exist ONLY in `tbl_user_login` and `tbl_admin`** — these are login identifiers
- **All other tables** that reference a user or admin MUST use **integer IDs**: `member_id` (BigInteger → `tbl_user_login.id`) or `admin_id`/`created_by_id` (Integer → `tbl_admin.id`)
- For **polymorphic tables** (referencing both users and admins), use `member_id` (BigInteger) + `user_type` (Text) discriminator. The `member_id` column stores the integer PK from the appropriate table based on `user_type`
- For **admin-only tables** (e.g., news, popups created by admins), use a proper FK: `created_by_id` (Integer, FK → `tbl_admin.id`)
- **API responses** must NEVER expose integer `member_id` to the frontend. The service layer resolves integer → text `user_id` using `resolution_da.py` before returning data
- Use `resolution_da.resolve_member_id()` for write path (text → integer) and `resolution_da.batch_resolve_text_user_ids()` for read path (integer → text)

### Indexes
- Format: `idx_<table>_<column>` — e.g., `idx_tbl_user_login_user_id`

### Relationships
- Relationship name: descriptive noun — e.g., `user_info`, `admin_routes`, `assigned_routes`
- Back-reference: opposite entity name — e.g., `backref='user_login'`

---

## 2. Core Tables (Template)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| Table | Purpose | Key Columns — see model file for full schema |
|-------|---------|----------------------------------------------|
| `tbl_admin` | Admin credentials & settings | → `src/models/admin.py` |
| `tbl_user_login` | User login credentials | → `src/models/user.py` (UserLogin) |
| `tbl_user_info` | User profile data | → `src/models/user.py` (UserInfo) |
| `tbl_routes` | Route/permission definitions | → `src/models/routes.py` (Route) |
| `tbl_admin_routes` | Admin-to-route permission mapping | → `src/models/routes.py` (AdminRoute) |
| `tbl_password_reset_tokens` | Password reset tokens | → `src/models/password_reset.py` |

---

## 3. Model Structure Standards

### Base Model
All models must inherit from a common `Base` class:
```python
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

### Primary Key
```python
id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
```

### Common Audit Columns
```python
created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
is_active: Mapped[bool] = mapped_column(Boolean, default=True)
```

### Foreign Keys
```python
member_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('tbl_user_login.id'), nullable=False)
```

### Relationships
```python
# One-to-One
user_info: Mapped["UserInfo"] = relationship("UserInfo", back_populates="user_login", uselist=False)

# One-to-Many
admin_routes: Mapped[list["AdminRoute"]] = relationship("AdminRoute", back_populates="admin")

# Many-to-One (reverse side)
admin: Mapped["Admin"] = relationship("Admin", back_populates="admin_routes")
```

---

## 4. Column Type Mapping

| Python Type | SQLAlchemy Type | Use For |
|-------------|----------------|---------|
| `int` | `BigInteger` | IDs, counters |
| `str` | `Text` | All string columns (PostgreSQL has no performance difference between Text and String) |
| `bool` | `Boolean` | Flags |
| `float` | `Numeric(precision, scale)` | Money, decimals |
| `datetime` | `DateTime(timezone=True)` | Timestamps |
| `date` | `Date` | Date only |
| `dict` | `JSONB` | JSON data (use `from sqlalchemy.dialects.postgresql import JSONB`) |

> **Note:** Do NOT use `String(n)` — always use `Text` for all string columns. PostgreSQL stores `Text` and `String(n)` identically, and `Text` avoids arbitrary length limits.

---

## 5. Query Conventions

### Select Single Record
```python
stmt = select(UserLogin).where(UserLogin.user_id == user_id)
result = await db.execute(stmt)
user = result.scalar_one_or_none()
```

### Select Multiple Records
```python
stmt = select(UserLogin).where(UserLogin.is_active == True).order_by(UserLogin.created_at.desc())
result = await db.execute(stmt)
users = result.scalars().all()
```

### Select with Join
```python
stmt = (
    select(UserLogin, UserInfo)
    .join(UserInfo, UserLogin.id == UserInfo.member_id)
    .where(UserLogin.user_id == user_id)
)
result = await db.execute(stmt)
row = result.one_or_none()
```

### Pagination Pattern
```python
# Count
count_stmt = select(func.count()).select_from(Model).where(conditions)
total = (await db.execute(count_stmt)).scalar()

# Data
data_stmt = select(Model).where(conditions).offset(page_index * page_size).limit(page_size)
rows = (await db.execute(data_stmt)).scalars().all()
```

### Insert
```python
new_record = Model(column1=value1, column2=value2)
db.add(new_record)
await db.flush()  # Get auto-generated ID before commit
await db.commit()
```

### Update
```python
stmt = select(Model).where(Model.id == record_id)
result = await db.execute(stmt)
record = result.scalar_one_or_none()
record.column = new_value
await db.commit()
```

### Delete
```python
stmt = delete(Model).where(Model.id == record_id)
await db.execute(stmt)
await db.commit()
```

---

## 6. Alembic Migration Rules

1. **Always auto-generate:** `alembic revision --autogenerate -m "description"`
2. **Review generated migration** before running — auto-generate doesn't catch everything
3. **One migration per feature** — don't mix unrelated changes
4. **Migration naming:** Use descriptive messages — `"add_user_referral_id"`, `"create_admin_routes_table"`
5. **Never edit applied migrations** — create a new migration instead
6. **Test migrations:** Run `alembic upgrade head` and `alembic downgrade -1` to verify

---

## 7. Performance Considerations

- **Create indexes** on foreign keys and frequently filtered/searched columns
- **Use `selectinload`** or `joinedload` for eager loading relationships to avoid N+1 queries
- **Use `func.count()`** for counting instead of loading all records
- **Limit query columns** — select only needed columns with `select(Model.col1, Model.col2)`
- **Use bulk operations** for mass inserts/updates
- **Use connection pooling** — configured in `create_async_engine(pool_size=20, max_overflow=10)`

---

## 8. Quick Reference Checklists

### When Creating a New Model
1. Create file in `src/models/`
2. Inherit from `Base`
3. Set `__tablename__` with `tbl_` prefix
4. Add primary key (`BigInteger`, autoincrement)
5. Add audit columns (`created_at`, `updated_at`, `is_active`)
6. Define relationships with `relationship()`
7. Add indexes on foreign keys and filter columns
8. Import model in `src/models/__init__.py`
9. Generate Alembic migration

### When Creating a New Query
1. Use async session from `Depends(get_db)`
2. Build query with `select()`, `where()`, `join()`
3. Use `scalar_one_or_none()` for single record
4. Use `scalars().all()` for multiple records
5. Handle `None` results gracefully

### When Modifying a Model
1. Make changes in the model file
2. Generate migration: `alembic revision --autogenerate -m "description"`
3. Review the generated migration file
4. Run migration: `alembic upgrade head`

---

> For full code templates and examples, see `DATABASE_REFERENCE.md`.
