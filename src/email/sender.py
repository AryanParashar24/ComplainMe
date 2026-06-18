import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote, urlencode

from src.models.complaint import ProcessedComplaint

MAX_COMPOSE_URL_LEN = 7500


def _smtp_configured() -> bool:
    return bool(os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD"))


def _split_recipients(
    recipients: list[str],
    cc_extra: list[str] | None = None,
) -> tuple[str, str]:
    """First email goes to To, the rest to Cc."""
    cc = list(recipients[1:]) if len(recipients) > 1 else []
    if cc_extra:
        cc.extend(cc_extra)
    to = recipients[0] if recipients else ""
    cc_str = ",".join(cc)
    return to, cc_str


def build_gmail_compose_url(
    recipients: list[str],
    subject: str,
    body: str,
    cc_extra: list[str] | None = None,
) -> tuple[str, bool]:
    """
    Build a Gmail web compose URL. Opens in browser; uses your logged-in Gmail session.
    Returns (url, body_was_truncated).
    """
    to, cc = _split_recipients(recipients, cc_extra)
    truncated = False

    def _make_url(letter: str) -> str:
        params = {"view": "cm", "fs": "1"}
        if to:
            params["to"] = to
        if cc:
            params["cc"] = cc
        if subject:
            params["su"] = subject
        if letter:
            params["body"] = letter
        return "https://mail.google.com/mail/?" + urlencode(params, quote_via=quote)

    url = _make_url(body)
    if len(url) <= MAX_COMPOSE_URL_LEN:
        return url, truncated

    truncated = True
    note = (
        "[Full complaint letter is shown in the Complain.io app — "
        "copy it from the Formal Letter tab and paste here before sending.]\n\n"
    )
    for length in range(len(body), 0, -200):
        url = _make_url(note + body[:length])
        if len(url) <= MAX_COMPOSE_URL_LEN:
            return url, truncated

    return _make_url(note), truncated


def build_mailto_url(
    recipients: list[str],
    subject: str,
    body: str,
    cc_extra: list[str] | None = None,
) -> tuple[str, bool]:
    """
    Build a mailto: link. On phone this usually opens Gmail app if it is the default mail app.
    Returns (url, body_was_truncated).
    """
    to, cc = _split_recipients(recipients, cc_extra)
    truncated = False

    def _make_url(letter: str) -> str:
        parts = []
        if cc:
            parts.append(f"cc={quote(cc)}")
        if subject:
            parts.append(f"subject={quote(subject)}")
        if letter:
            parts.append(f"body={quote(letter)}")
        query = "&".join(parts)
        return f"mailto:{to}?{query}" if query else f"mailto:{to}"

    url = _make_url(body)
    if len(url) <= MAX_COMPOSE_URL_LEN:
        return url, truncated

    truncated = True
    short_body = body[:1500] + "\n\n[... full letter in Complain.io app — copy from Formal Letter tab ...]"
    return _make_url(short_body), truncated


def get_compose_links(
    processed: ProcessedComplaint,
    cc_emails: list[str] | None = None,
) -> dict:
    """Build Gmail + mailto compose links for the user to send from their own account."""
    recipients = processed.all_emails
    if not recipients:
        return {"success": False, "error": "No recipient emails found."}

    gmail_url, gmail_truncated = build_gmail_compose_url(
        recipients, processed.subject, processed.formal_letter, cc_emails
    )
    mailto_url, mailto_truncated = build_mailto_url(
        recipients, processed.subject, processed.formal_letter, cc_emails
    )

    to, cc = _split_recipients(recipients, cc_emails)
    return {
        "success": True,
        "gmail_url": gmail_url,
        "mailto_url": mailto_url,
        "to": to,
        "cc": cc,
        "cc_list": [e.strip() for e in cc.split(",") if e.strip()] if cc else [],
        "subject": processed.subject,
        "body_truncated": gmail_truncated or mailto_truncated,
        "has_attachments": bool(processed.original.media_paths),
    }


def send_complaint_email_smtp(
    processed: ProcessedComplaint,
    cc_emails: list[str] | None = None,
) -> dict:
    """Optional: send directly via SMTP if credentials are configured."""
    recipients = processed.all_emails
    if not recipients:
        return {"success": False, "error": "No recipient emails found.", "sent_to": []}

    if not _smtp_configured():
        return {"success": False, "error": "SMTP credentials not configured.", "sent_to": []}

    msg = MIMEMultipart()
    msg["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", ""))
    msg["To"] = recipients[0]
    if len(recipients) > 1:
        msg["Cc"] = ", ".join(recipients[1:])
    if cc_emails:
        existing_cc = msg.get("Cc", "")
        extra = ", ".join(cc_emails)
        msg["Cc"] = f"{existing_cc}, {extra}" if existing_cc else extra

    msg["Subject"] = processed.subject
    msg.attach(MIMEText(processed.formal_letter, "plain", "utf-8"))

    for media_path in processed.original.media_paths:
        if not media_path.exists():
            continue
        with open(media_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={media_path.name}")
        msg.attach(part)

    all_recipients = list(recipients)
    if cc_emails:
        all_recipients.extend(cc_emails)

    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(msg["From"], all_recipients, msg.as_string())
        return {"success": True, "sent_to": all_recipients, "subject": processed.subject}
    except smtplib.SMTPException as e:
        return {"success": False, "error": str(e), "sent_to": []}
