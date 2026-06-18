import base64
import mimetypes
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from src.models.complaint import ProcessedComplaint


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


def _attach_file(msg: MIMEMultipart, path: Path) -> None:
    if not path.exists():
        return
    mime = _guess_mime(path)
    maintype, _, subtype = mime.partition("/")
    with open(path, "rb") as f:
        if maintype == "text":
            part = MIMEText(f.read().decode("utf-8", errors="replace"), _subtype=subtype or "plain")
        else:
            part = MIMEBase(maintype, subtype or "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=path.name)
    msg.attach(part)


def build_mime_message(
    processed: ProcessedComplaint,
    cc_emails: list[str] | None = None,
    from_email: str = "",
) -> MIMEMultipart:
    recipients = processed.all_emails
    to = recipients[0] if recipients else ""
    cc_parts = list(recipients[1:]) if len(recipients) > 1 else []
    if cc_emails:
        cc_parts.extend(cc_emails)

    msg = MIMEMultipart("mixed")
    if from_email:
        msg["From"] = from_email
    if to:
        msg["To"] = to
    if cc_parts:
        msg["Cc"] = ", ".join(cc_parts)
    msg["Subject"] = processed.subject
    msg.attach(MIMEText(processed.formal_letter, "plain", "utf-8"))

    for media_path in processed.original.media_paths:
        _attach_file(msg, media_path)

    return msg


def build_eml_bytes(
    processed: ProcessedComplaint,
    cc_emails: list[str] | None = None,
    from_email: str = "",
) -> bytes:
    return build_mime_message(processed, cc_emails, from_email).as_bytes()


def build_gmail_raw_message(
    processed: ProcessedComplaint,
    cc_emails: list[str] | None = None,
    from_email: str = "",
) -> str:
    raw = build_eml_bytes(processed, cc_emails, from_email)
    return base64.urlsafe_b64encode(raw).decode()


def load_attachment_payloads(processed: ProcessedComplaint) -> list[dict]:
    """Return attachment dicts for Web Share: name, bytes, mime."""
    payloads = []
    for path in processed.original.media_paths:
        if not path.exists():
            continue
        payloads.append(
            {
                "name": path.name,
                "data": path.read_bytes(),
                "mime": _guess_mime(path),
            }
        )
    return payloads
