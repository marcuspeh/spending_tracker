#!/usr/bin/env python3
"""
Fetch sample emails from Gmail and save them as text files.

Usage:
    python scripts/fetch_sample_emails.py --limit 10
    python scripts/fetch_sample_emails.py --output tests/fixtures/email_samples
"""

import argparse
import sys
from pathlib import Path

from imap_tools import AND, MailBox

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.settings import get_settings
from app.utils.html import strip_html


def sanitize_filename(subject: str) -> str:
    """Convert subject to a safe filename."""
    keepcharacters = (" ", ".", "_", "-")
    return "".join(c for c in subject if c.isalnum() or c in keepcharacters).rstrip()[:50]


def fetch_emails(limit: int = 10, unseen_only: bool = True) -> list:
    """Fetch emails from Gmail."""
    settings = get_settings()

    with MailBox(settings.imap_host, port=settings.imap_port) as mailbox:
        mailbox.login(settings.imap_username, settings.imap_password)
        if unseen_only:
            return list(mailbox.fetch(AND(seen=False), limit=limit))
        else:
            # Fetch all emails (seen and unseen)
            return list(mailbox.fetch(AND(all=True), limit=limit))


def email_to_text(email) -> str:
    """Convert an email object to a text file format matching the existing fixtures."""
    body = email.text or (strip_html(email.html) if email.html else "") or ""
    lines = [
        f"Subject: {email.subject}",
        "",
        f"From: {email.from_}",
        "",
        f"To: {email.to}",
        "",
        f"Date: {email.date}",
        "",
        f"{body}",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Fetch sample emails from Gmail")
    parser.add_argument(
        "--limit", "-n", type=int, default=10, help="Number of emails to fetch (default: 10)"
    )
    parser.add_argument(
        "--output", "-o", type=str, default="email_samples", help="Output directory"
    )
    parser.add_argument("--dry-run", action="store_true", help="Print emails without saving")
    parser.add_argument(
        "--all", "-a", action="store_true", help="Fetch all emails (not just unseen)"
    )
    args = parser.parse_args()

    settings = get_settings()
    print(f"Connecting to {settings.imap_host}...")

    try:
        emails = fetch_emails(args.limit, unseen_only=not args.all)
    except Exception as e:
        print(f"Error fetching emails: {e}")
        sys.exit(1)

    print(f"Fetched {len(emails)} emails")

    if args.dry_run:
        for i, email in enumerate(emails, 1):
            print(f"\n--- Email {i} ---")
            print(f"Subject: {email.subject}")
            print(f"From: {email.from_}")
            print(f"Preview: {email.text[:200]}..." if email.text else "No body")
        return

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    for email in emails:
        filename = sanitize_filename(email.subject)
        # Avoid duplicates
        candidate = output_dir / f"{filename}.txt"
        if candidate.exists():
            counter = 1
            while candidate.exists():
                candidate = output_dir / f"{filename}_{counter}.txt"
                counter += 1

        text = email_to_text(email)
        candidate.write_text(text)
        print(f"Saved: {candidate.name}")

    print(f"\nSaved {len(emails)} emails to {output_dir}")


if __name__ == "__main__":
    main()
