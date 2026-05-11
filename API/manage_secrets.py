"""
CLI tool to encrypt/decrypt sensitive values in .env file.

Usage:
    python manage_secrets.py encrypt          # Encrypt all sensitive values in .env
    python manage_secrets.py decrypt          # Decrypt all sensitive values in .env
    python manage_secrets.py encrypt-value    # Encrypt a single value (prints result)
    python manage_secrets.py decrypt-value    # Decrypt a single ENC: value (prints result)
"""

import sys
import base64
import hashlib
import getpass
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

ENV_FILE = Path(__file__).parent / ".env"

SENSITIVE_KEYS = [
    "DB_PASSWORD",
    "JWT_SECRET_KEY",
    "FERNET_KEY",
    "RECAPTCHA_SECRET_KEY",
    "IPINFO_TOKEN",
    "EMAIL_PASSWORD",
    "EMAIL_APP_PASSWORD",
    "SMS_API_KEY",
    "FIREBASE_PRIVATE_KEY",
    "FIREBASE_API_KEY",
    "FIREBASE_VAPID_KEY",
]


def get_fernet(master_key: str) -> Fernet:
    derived = hashlib.sha256(master_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_value(f: Fernet, value: str) -> str:
    return "ENC:" + f.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(f: Fernet, value: str) -> str:
    if not value.startswith("ENC:"):
        return value
    return f.decrypt(value[4:].encode("utf-8")).decode("utf-8")


def process_env_file(action: str, f: Fernet) -> None:
    if not ENV_FILE.exists():
        print(f"Error: {ENV_FILE} not found")
        sys.exit(1)

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    updated_lines = []
    changed = 0

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            updated_lines.append(line)
            continue

        key, _, value = line.partition("=")
        key_stripped = key.strip()

        if key_stripped not in SENSITIVE_KEYS or not value.strip():
            updated_lines.append(line)
            continue

        if action == "encrypt" and not value.startswith("ENC:"):
            clean_value = value.strip().strip('"').strip("'")
            updated_lines.append(f"{key}={encrypt_value(f, clean_value)}")
            changed += 1
            print(f"  Encrypted: {key_stripped}")
        elif action == "decrypt" and value.startswith("ENC:"):
            try:
                updated_lines.append(f"{key}={decrypt_value(f, value)}")
                changed += 1
                print(f"  Decrypted: {key_stripped}")
            except InvalidToken:
                print(f"  FAILED (wrong master key?): {key_stripped}")
                updated_lines.append(line)
        else:
            updated_lines.append(line)

    if changed > 0:
        ENV_FILE.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
        print(f"\nDone. {changed} value(s) {action}ed in .env")
    else:
        print(f"\nNo values to {action}.")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("encrypt", "decrypt", "encrypt-value", "decrypt-value"):
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1]
    master_key = getpass.getpass("Enter MASTER_KEY: ")
    if not master_key:
        print("Error: MASTER_KEY cannot be empty")
        sys.exit(1)

    f = get_fernet(master_key)

    if action == "encrypt-value":
        value = input("Enter value to encrypt: ")
        print(f"\nEncrypted: {encrypt_value(f, value)}")

    elif action == "decrypt-value":
        value = input("Enter ENC: value to decrypt: ")
        try:
            print(f"\nDecrypted: {decrypt_value(f, value)}")
        except InvalidToken:
            print("Error: Decryption failed — wrong master key or corrupted value")
            sys.exit(1)

    elif action in ("encrypt", "decrypt"):
        if action == "encrypt":
            confirm_key = getpass.getpass("Confirm MASTER_KEY: ")
            if master_key != confirm_key:
                print("Error: Keys do not match")
                sys.exit(1)
        process_env_file(action, f)


if __name__ == "__main__":
    main()
