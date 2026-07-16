"""Email delivery for call summaries.

Sends via SMTP (Gmail by default) using an app password from the environment —
never a real account password, never hardcoded. The summary Markdown becomes a
formatted HTML email body; the transcript and summary files ride along as
attachments.
"""

from __future__ import annotations

import html
import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger(__name__)

APP_PASSWORD_ENV = "GMAIL_APP_PASSWORD"

# Summary sections that must never reach participants — facilitator-only.
FACILITATOR_ONLY_SECTIONS = ("Facilitator signal",)


def strip_facilitator_sections(md: str) -> str:
    """Remove facilitator-only '## <heading>' sections (through the next '## ')."""
    for heading in FACILITATOR_ONLY_SECTIONS:
        md = re.sub(
            rf"^## {re.escape(heading)}\s*\n.*?(?=^## |\Z)", "",
            md, flags=re.MULTILINE | re.DOTALL,
        )
    return md


def markdown_to_html(md: str) -> str:
    """Small converter for our known summary shape: ## headings, bullets, bold.

    Deliberately minimal — no external dependency, no untrusted-HTML risk
    (everything is escaped first).
    """
    out: list[str] = []
    in_list = False
    for raw in md.splitlines():
        line = html.escape(raw.rstrip())
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{stripped[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if stripped.startswith("### "):
            out.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("## "):
            out.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("# "):
            out.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped in ("---", "***"):
            out.append("<hr>")
        elif stripped:
            out.append(f"<p>{stripped}</p>")
    if in_list:
        out.append("</ul>")
    body = "\n".join(out)
    # No font-family override: the email renders in the client's default font
    # (Gmail's own sans-serif), so it looks like a native message.
    return (
        "<html><body style='max-width: 640px; margin: 0 auto; line-height: 1.5;'>"
        f"{body}</body></html>"
    )


def send_summary_email(cfg: dict, *, subject: str, summary_md: str,
                       attachments: list[Path] | None = None,
                       to: list[str] | None = None) -> list[str]:
    """Send the summary. Returns the recipient list on success; raises on failure."""
    email_cfg = cfg.get("email", {})
    sender = email_cfg.get("from", "").strip()
    if not sender:
        raise ValueError("email.from is not set in config.yaml")
    recipients = [r.strip() for r in (to or email_cfg.get("to") or [sender]) if r.strip()]
    password = os.environ.get(APP_PASSWORD_ENV, "")
    if not password:
        raise ValueError(
            f"{APP_PASSWORD_ENV} is not set — add it to your .env file "
            "(Google Account -> Security -> App passwords)."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(summary_md)                       # plain-text fallback
    msg.add_alternative(markdown_to_html(summary_md), subtype="html")

    for path in attachments or []:
        path = Path(path)
        if not path.is_file():
            continue
        msg.add_attachment(
            path.read_bytes(),
            maintype="text", subtype="markdown",
            filename=path.name,
        )

    host = email_cfg.get("smtp_host", "smtp.gmail.com")
    port = int(email_cfg.get("smtp_port", 587))
    # macOS Pythons often lack system CA certs; use certifi's bundle (already
    # installed as a dependency of the anthropic SDK) so TLS verification works.
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=context)
        server.login(sender, password)
        server.send_message(msg)
    log.info("Emailed summary to %s", ", ".join(recipients))
    return recipients
