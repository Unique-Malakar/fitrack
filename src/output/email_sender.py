"""Multipart email delivery over SMTP.

Defaults to Gmail SMTP, which needs an App Password (not the account password) with
2FA enabled. Any SMTP host works via env vars. Dry-run mode writes the rendered
message to disk instead of sending, which is how the pipeline is verified without
credentials.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

DEFAULT_HOST = "smtp.gmail.com"
DEFAULT_PORT = 587


class EmailConfig(object):
    __slots__ = ("host", "port", "user", "password", "sender", "recipients")

    def __init__(self, host, port, user, password, sender, recipients):
        self.host, self.port, self.user, self.password = host, port, user, password
        self.sender, self.recipients = sender, recipients

    @property
    def configured(self):
        return bool(self.host and self.user and self.password and self.recipients)

    @classmethod
    def from_env(cls):
        raw = os.environ.get("EMAIL_TO", "") or os.environ.get("SMTP_USER", "")
        recipients = [a.strip() for a in raw.split(",") if a.strip()]
        user = os.environ.get("SMTP_USER", "")
        return cls(
            host=os.environ.get("SMTP_HOST", DEFAULT_HOST),
            port=int(os.environ.get("SMTP_PORT", DEFAULT_PORT)),
            user=user,
            password=os.environ.get("SMTP_PASSWORD", ""),
            sender=os.environ.get("EMAIL_FROM", user),
            recipients=recipients,
        )


def build_message(cfg, subject, text_body, html_body):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.sender or cfg.user
    msg["To"] = ", ".join(cfg.recipients)
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    return msg


def send(cfg, subject, text_body, html_body):
    if not cfg.configured:
        raise RuntimeError(
            "email not configured: need SMTP_USER, SMTP_PASSWORD and EMAIL_TO")

    msg = build_message(cfg, subject, text_body, html_body)
    context = ssl.create_default_context()

    if cfg.port == 465:
        with smtplib.SMTP_SSL(cfg.host, cfg.port, context=context, timeout=45) as smtp:
            smtp.login(cfg.user, cfg.password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(cfg.host, cfg.port, timeout=45) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(cfg.user, cfg.password)
            smtp.send_message(msg)
    return msg["To"]


def write_preview(out_dir, subject, text_body, html_body, stem="brief"):
    """Dry-run output: the exact bodies that would have been sent."""
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    html_path = os.path.join(out_dir, stem + ".html")
    text_path = os.path.join(out_dir, stem + ".txt")
    with open(html_path, "w") as fh:
        fh.write("<!doctype html><meta charset='utf-8'><title>%s</title>%s" % (subject, html_body))
    with open(text_path, "w") as fh:
        fh.write(subject + "\n\n" + text_body)
    return html_path, text_path
