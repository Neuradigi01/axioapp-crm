"""SMTP connectivity probe for Brevo. Login + NOOP + QUIT — no message sent.

Run as:
    sops exec-env secrets.enc.env "python _debug_smtp_check.py"
"""
from __future__ import annotations

import os
import smtplib
import ssl
import sys

with open("config.env", "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

host = os.environ["EMAIL_HOST"]
port = int(os.environ["EMAIL_PORT"])
user = os.environ["EMAIL_USER"]
pwd = os.environ.get("EMAIL_APP_PASSWORD") or os.environ.get("EMAIL_PASSWORD")
sender = os.environ["EMAIL_SENDER"]

print(f"EMAIL_HOST    = {host}")
print(f"EMAIL_PORT    = {port}")
print(f"EMAIL_USER    = {user}")
print(f"EMAIL_SENDER  = {sender}")
print(f"app_pass set  = {bool(pwd)}  (length={len(pwd) if pwd else 0})")
print()

try:
    print("Connecting...")
    s = smtplib.SMTP(host, port, timeout=15)
    s.set_debuglevel(1)
    print("\nEHLO #1")
    s.ehlo()
    print("\nSTARTTLS")
    s.starttls(context=ssl.create_default_context())
    print("\nEHLO #2")
    s.ehlo()
    print("\nLOGIN")
    s.login(user, pwd)
    print("\nNOOP")
    code, msg = s.noop()
    print(f"NOOP -> {code} {msg}")
    print("\nQUIT")
    s.quit()
    print("\nSMTP creds are VALID.")
except Exception as exc:
    print(f"\nFAILURE: {type(exc).__name__}: {exc}")
    sys.exit(2)
