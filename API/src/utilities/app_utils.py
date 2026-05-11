import secrets
import orjson
import os
import re
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import aiosmtplib
import httpx
from fastapi import Request
from src.core.logger import logger
from config import (
    APP_NAME, IS_DEVELOPMENT, IPINFO_TOKEN, STATIC_DIR, LOGO_URL,
    EMAIL_ENABLED, EMAIL_SENDER,
    EMAIL_USER, EMAIL_APP_PASSWORD, EMAIL_HOST, EMAIL_PORT,
    SMS_ENABLED, SMS_API_URL, SMS_API_KEY,
)


def get_real_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def get_client_and_sender_ip(request: Request) -> tuple[str, str]:
    """Extract client IP and sender/proxy IP from request headers.
    Returns (client_ip, sender_ip) where sender_ip is the proxy/forwarding IP."""
    client_ip = (
        request.headers.get("x-real-ip")
        or request.headers.get("x-client-ip")
        or ""
    )
    sender_ip = ""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",")]
        if not client_ip:
            client_ip = parts[0]
        if len(parts) > 1:
            sender_ip = parts[-1]

    if not client_ip:
        client_ip = request.client.host if request.client else ""

    return client_ip, sender_ip


async def extract_login_context(request: Request, device_info_model=None) -> dict:
    """Extract all login-related context from a request.
    Returns dict with: client_ip, sender_ip, ip_info, device_info."""
    client_ip, sender_ip = get_client_and_sender_ip(request)
    ip_list = [ip for ip in [client_ip, sender_ip] if ip]
    ip_info = await get_ip_info(",".join(ip_list)) if ip_list else None
    device_info = device_info_model.model_dump() if device_info_model else None
    return {
        "ip_address": client_ip,
        "sender_ip": sender_ip,
        "ip_info": ip_info,
        "device_info": device_info,
    }


def generate_otp(length: int = 6) -> str:
    return ''.join([str(secrets.randbelow(10)) for _ in range(length)])


_template_cache: dict[str, str] = {}


def load_email_template(template_name: str) -> str:
    if template_name in _template_cache:
        return _template_cache[template_name]
    path = os.path.join(STATIC_DIR, "emails", f"{template_name}.html")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    _template_cache[template_name] = content
    return content


def render_email_template(template_name: str, context: dict) -> str:
    html = load_email_template(template_name)
    context.setdefault("app_name", APP_NAME)
    context.setdefault("year", str(datetime.now(timezone.utc).year))
    context.setdefault("logo_url", LOGO_URL)
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(context.get(m.group(1), m.group(0))), html)


def load_json(path: str):
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return orjson.loads(f.read())
    return None


async def get_ip_info(ip_address: str) -> list[dict] | None:
    """Fetch IP geolocation info. Accepts comma-separated IPs and returns a list of details."""
    if IS_DEVELOPMENT or not ip_address or not IPINFO_TOKEN:
        return None
    try:
        results = []
        async with httpx.AsyncClient() as client:
            for ip in ip_address.split(","):
                ip = ip.strip()
                if not ip:
                    continue
                response = await client.get(
                    f"https://ipinfo.io/{ip}/json",
                    params={"token": IPINFO_TOKEN},
                    timeout=5,
                )
                response.raise_for_status()
                results.append(response.json())
        return results if results else None
    except Exception as e:
        logger.error(f"Failed to fetch IP info for {ip_address}: {e}")
        return None


async def send_mail_async(
    recipients: str | list[str],
    subject: str,
    html_body: str,
    attachments: list[str] | None = None,
    in_memory_files: list[tuple[str, bytes]] | None = None,
) -> tuple[bool, str]:
    if not EMAIL_ENABLED:
        logger.warning("Email system is not enabled. Skipping email send.")
        return False, "Email system is not enabled."

    if not recipients:
        logger.error("No recipient email provided.")
        return False, "Receiver email not found!"

    try:
        recipients = recipients if isinstance(recipients, list) else [recipients]

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        if APP_NAME:
            msg["From"] = f"{APP_NAME} <{EMAIL_SENDER}>"
        else:
            msg["From"] = EMAIL_SENDER
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(html_body, "html"))

        if attachments:
            for file_path in attachments:
                with open(file_path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    filename = os.path.basename(file_path)
                    part.add_header("Content-Disposition", f"attachment; filename={filename}")
                    msg.attach(part)

        if in_memory_files:
            for filename, file_bytes in in_memory_files:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(file_bytes)
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={filename}")
                msg.attach(part)

        server = aiosmtplib.SMTP(hostname=EMAIL_HOST, port=EMAIL_PORT, start_tls=True)
        await server.connect()
        await server.login(EMAIL_USER, EMAIL_APP_PASSWORD)
        await server.send_message(msg, sender=EMAIL_USER, recipients=recipients)
        await server.quit()

        logger.info(f"Email sent to {', '.join(recipients)}: {subject}")
        return True, "Email sent successfully!"

    except Exception as e:
        logger.error(f"Failed to send email to {recipients}: {e}")
        return False, f"Unable to send email: {e}"


async def send_sms_async(mobile_no: str, message: str) -> tuple[bool, str]:
    if not SMS_ENABLED:
        logger.warning("SMS system is not enabled. Skipping SMS send.")
        return False, "SMS system is not enabled."

    if not mobile_no:
        logger.error("No mobile number provided.")
        return False, "Receiver mobile number not found!"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                SMS_API_URL,
                json={"to": mobile_no, "message": message},
                headers={"Authorization": f"Bearer {SMS_API_KEY}"},
                timeout=10,
            )
            response.raise_for_status()

        logger.info(f"SMS sent to {mobile_no}")
        return True, "SMS sent successfully!"

    except Exception as e:
        logger.error(f"Failed to send SMS to {mobile_no}: {e}")
        return False, f"Unable to send SMS: {e}"
