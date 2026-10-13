"""Importers for macOS data sources (WhatsApp, Messages, Mail, etc.).

All importers follow: read-only access, propose-then-approve, local-only.
"""  # noqa: D400

from . import whatsapp, messages, mail, contacts, calendar, photos, notes

__all__ = [
    "whatsapp",
    "messages",
    "mail",
    "contacts",
    "calendar",
    "photos",
    "notes",
]
