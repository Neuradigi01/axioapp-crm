"""Read-only diagnostic for the password-reset flow.

Connects to the live DB using config.env + secrets.enc.env (via sops exec-env),
checks whether ajaygogane224@gmail.com resolves through the same lookup the
forgot-password endpoint uses, and shows the most recent password_reset_tokens
row for that user.

Run as:
    sops exec-env secrets.enc.env "python _debug_reset_check.py"
"""
from __future__ import annotations

import os
import sys

import psycopg2

TARGET_EMAIL = "ajaygogane224@gmail.com"

# Load non-secret vars from config.env (sops only injects the secret set).
with open("config.env", "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

cfg = {
    "host": os.environ["DB_HOST"],
    "port": int(os.environ["DB_PORT"]),
    "dbname": os.environ["DB_NAME"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "sslmode": os.environ.get("DB_SSLMODE", "prefer"),
    "connect_timeout": 10,
}

print(f"Connecting to {cfg['host']}:{cfg['port']}/{cfg['dbname']} as {cfg['user']} ...")
conn = psycopg2.connect(**cfg)
conn.autocommit = True
cur = conn.cursor()

print("\n[1] Direct match on tbl_user_info.email")
cur.execute(
    """
    SELECT ui.id, ui.member_id, ui.email, ui.first_name, ui.last_name,
           ui.is_email_verified, ul.is_active, ul.user_id
    FROM tbl_user_info ui
    LEFT JOIN tbl_user_login ul ON ul.id = ui.member_id
    WHERE LOWER(ui.email) = LOWER(%s)
    """,
    (TARGET_EMAIL,),
)
rows = cur.fetchall()
if not rows:
    print("  NO ROW — email not present in tbl_user_info (lookup will silently no-op)")
else:
    for r in rows:
        print(f"  {r}")

print("\n[2] Match using the exact lookup the forgot-password service runs")
cur.execute(
    """
    SELECT ul.id, ui.email, ul.is_active
    FROM tbl_user_login ul
    LEFT JOIN tbl_user_info ui ON ui.member_id = ul.id
    WHERE ul.is_active = true
      AND (ul.user_id = %s OR ui.email = %s)
    LIMIT 1
    """,
    (TARGET_EMAIL, TARGET_EMAIL),
)
row = cur.fetchone()
if not row:
    print("  NO ROW — forgot-password service would silently return (no email sent)")
else:
    print(f"  member_id={row[0]}  email={row[1]}  is_active={row[2]}")
    member_id = row[0]

    print("\n[3] Most recent password_reset_tokens rows for that member")
    cur.execute(
        """
        SELECT id, user_type, LEFT(token, 12) AS token_prefix,
               expires_at, is_used, created_at
        FROM tbl_password_reset_tokens
        WHERE member_id = %s
        ORDER BY created_at DESC
        LIMIT 5
        """,
        (member_id,),
    )
    trows = cur.fetchall()
    if not trows:
        print("  NO ROWS — no reset token was ever written for this user")
    else:
        for tr in trows:
            print(f"  id={tr[0]}  type={tr[1]}  token_prefix={tr[2]}  "
                  f"expires_at={tr[3]}  used={tr[4]}  created_at={tr[5]}")

cur.close()
conn.close()
print("\nDone.")
