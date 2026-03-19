#!/usr/bin/env python3
"""Gmail MCP Server - Python implementation.

Provides Gmail and Calendar tools via MCP protocol.
Runs as subprocess, communicates via stdio.
Receives OAuth token via environment variable (never stored on disk).
"""

import asyncio
import base64
import email.encoders
import json
import mimetypes
import os
import sys
from datetime import datetime
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class GmailMCPServer:
    """MCP Server for Gmail and Calendar."""

    def __init__(self, token_data: dict, download_dir: str):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

        # Build credentials from token data
        self.credentials = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get(
                "token_uri", "https://oauth2.googleapis.com/token"
            ),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes", []),
        )

        # Build services
        self.gmail = build("gmail", "v1", credentials=self.credentials)
        self.calendar = build("calendar", "v3", credentials=self.credentials)

        # Get user info
        self.user_email = ""
        self.user_name = ""
        self._init_user_info()

        self.tools = self._build_tools()

    def _init_user_info(self):
        """Get user email and name."""
        try:
            profile = self.gmail.users().getProfile(userId="me").execute()
            self.user_email = profile.get("emailAddress", "unknown")

            # Try to get display name
            try:
                send_as = (
                    self.gmail.users().settings().sendAs().list(userId="me").execute()
                )
                primary = next(
                    (s for s in send_as.get("sendAs", []) if s.get("isPrimary")), None
                )
                self.user_name = primary.get("displayName", "") if primary else ""
            except Exception:
                pass

            # Fallback: capitalize email prefix
            if not self.user_name:
                prefix = self.user_email.split("@")[0]
                self.user_name = " ".join(p.capitalize() for p in prefix.split("."))
        except Exception as e:
            sys.stderr.write(f"Error getting user info: {e}\n")

    def _build_tools(self) -> list:
        """Build tool definitions."""
        email = self.user_email
        return [
            {
                "name": "list_emails",
                "description": f"List emails from Gmail inbox ({email}). Returns subject, from, date and message ID.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Gmail search query (e.g., 'has:attachment', 'from:someone@example.com')",
                        },
                        "maxResults": {
                            "type": "number",
                            "description": "Maximum number of emails to return (default: 10)",
                        },
                    },
                },
            },
            {
                "name": "get_email",
                "description": f"Get details of a specific email from {email}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "messageId": {
                            "type": "string",
                            "description": "The ID of the email message",
                        }
                    },
                    "required": ["messageId"],
                },
            },
            {
                "name": "list_attachments",
                "description": f"List all attachments of a specific email from {email}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "messageId": {
                            "type": "string",
                            "description": "The ID of the email message",
                        }
                    },
                    "required": ["messageId"],
                },
            },
            {
                "name": "download_attachment",
                "description": f"Download an email attachment from {email}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "messageId": {
                            "type": "string",
                            "description": "The ID of the email message",
                        },
                        "attachmentId": {
                            "type": "string",
                            "description": "The ID of the attachment",
                        },
                        "filename": {
                            "type": "string",
                            "description": "The filename to save as",
                        },
                    },
                    "required": ["messageId", "attachmentId", "filename"],
                },
            },
            {
                "name": "send_email",
                "description": f"Send an email from {email}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "Recipient email address",
                        },
                        "subject": {"type": "string", "description": "Email subject"},
                        "body": {
                            "type": "string",
                            "description": "Email body (plain text)",
                        },
                        "cc": {
                            "type": "string",
                            "description": "CC recipients (comma-separated, optional)",
                        },
                        "bcc": {
                            "type": "string",
                            "description": "BCC recipients (comma-separated, optional)",
                        },
                        "from_alias": {
                            "type": "string",
                            "description": "Send from this email alias",
                        },
                        "from_name": {
                            "type": "string",
                            "description": "Display name for sender",
                        },
                        "attachments": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "List of absolute file paths to attach "
                                "(e.g. ['/app/data/playwright/page-123.png']). "
                                "Files must be under /app/data/."
                            ),
                        },
                    },
                    "required": ["to", "subject", "body"],
                },
            },
            {
                "name": "reply_email",
                "description": (
                    f"Reply to an existing email in {email}. "
                    "Keeps the message in the same thread."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "messageId": {
                            "type": "string",
                            "description": "ID of the email to reply to",
                        },
                        "body": {
                            "type": "string",
                            "description": "Reply body (plain text)",
                        },
                        "cc": {
                            "type": "string",
                            "description": "CC recipients (comma-separated, optional)",
                        },
                        "bcc": {
                            "type": "string",
                            "description": "BCC recipients (comma-separated, optional)",
                        },
                        "from_alias": {
                            "type": "string",
                            "description": "Send from this email alias",
                        },
                        "from_name": {
                            "type": "string",
                            "description": "Display name for sender",
                        },
                        "attachments": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "List of absolute file paths to attach "
                                "(e.g. ['/app/data/playwright/page-123.png']). "
                                "Files must be under /app/data/."
                            ),
                        },
                    },
                    "required": ["messageId", "body"],
                },
            },
            {
                "name": "mark_as_read",
                "description": f"Mark one or more emails as read in {email}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "messageIds": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of message IDs to mark as read",
                        },
                    },
                    "required": ["messageIds"],
                },
            },
            {
                "name": "list_calendar_events",
                "description": f"List upcoming calendar events for {email}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "maxResults": {
                            "type": "number",
                            "description": "Maximum events to return (default: 10)",
                        },
                        "timeMin": {
                            "type": "string",
                            "description": "Start time filter in ISO format",
                        },
                        "timeMax": {
                            "type": "string",
                            "description": "End time filter in ISO format",
                        },
                        "query": {
                            "type": "string",
                            "description": "Free text search query",
                        },
                    },
                },
            },
            {
                "name": "get_calendar_event",
                "description": f"Get details of a specific calendar event for {email}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "eventId": {
                            "type": "string",
                            "description": "The ID of the calendar event",
                        }
                    },
                    "required": ["eventId"],
                },
            },
            {
                "name": "create_calendar_event",
                "description": f"Create a new calendar event for {email}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "Event title"},
                        "description": {
                            "type": "string",
                            "description": "Event description",
                        },
                        "startDateTime": {
                            "type": "string",
                            "description": "Start date/time in ISO format",
                        },
                        "endDateTime": {
                            "type": "string",
                            "description": "End date/time in ISO format",
                        },
                        "location": {"type": "string", "description": "Event location"},
                        "attendees": {
                            "type": "string",
                            "description": "Comma-separated attendee emails",
                        },
                    },
                    "required": ["summary", "startDateTime", "endDateTime"],
                },
            },
            {
                "name": "update_calendar_event",
                "description": f"Update an existing calendar event for {email}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "eventId": {
                            "type": "string",
                            "description": "The ID of the event to update",
                        },
                        "summary": {"type": "string", "description": "New event title"},
                        "description": {
                            "type": "string",
                            "description": "New event description",
                        },
                        "startDateTime": {
                            "type": "string",
                            "description": "New start date/time",
                        },
                        "endDateTime": {
                            "type": "string",
                            "description": "New end date/time",
                        },
                        "location": {
                            "type": "string",
                            "description": "New event location",
                        },
                    },
                    "required": ["eventId"],
                },
            },
            {
                "name": "delete_calendar_event",
                "description": f"Delete a calendar event for {email}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "eventId": {
                            "type": "string",
                            "description": "The ID of the event to delete",
                        }
                    },
                    "required": ["eventId"],
                },
            },
        ]

    def _get_header(self, headers: list, name: str) -> str:
        """Get header value by name."""
        for h in headers or []:
            if h.get("name", "").lower() == name.lower():
                return h.get("value", "")
        return ""

    def _get_text_content(self, payload: dict) -> str:
        """Extract text content from email payload.

        Prefers text/plain; falls back to text/html (stripped to plain text).
        """
        plain = self._get_mime_content(payload, "text/plain")
        if plain:
            return plain

        html = self._get_mime_content(payload, "text/html")
        if html:
            return self._html_to_text(html)

        return ""

    def _get_mime_content(self, payload: dict, mime_type: str) -> str:
        """Recursively extract content for a specific MIME type."""
        if payload.get("mimeType") == mime_type and payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")

        for part in payload.get("parts", []):
            text = self._get_mime_content(part, mime_type)
            if text:
                return text
        return ""

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convert HTML to readable plain text using stdlib only."""
        import re as _re
        from html.parser import HTMLParser
        from io import StringIO

        class _HTMLStripper(HTMLParser):
            def __init__(self):
                super().__init__()
                self._out = StringIO()
                self._skip = False

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style"):
                    self._skip = True
                elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4"):
                    self._out.write("\n")

            def handle_endtag(self, tag):
                if tag in ("script", "style"):
                    self._skip = False
                elif tag in ("p", "div", "tr", "table"):
                    self._out.write("\n")

            def handle_data(self, data):
                if not self._skip:
                    self._out.write(data)

        stripper = _HTMLStripper()
        stripper.feed(html)
        text = stripper._out.getvalue()
        # Collapse whitespace runs but preserve line breaks
        text = _re.sub(r"[^\S\n]+", " ", text)
        text = _re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _get_attachments(self, payload: dict) -> list:
        """Extract attachment info from email payload."""
        attachments = []
        if payload.get("filename") and payload.get("body", {}).get("attachmentId"):
            attachments.append(
                {
                    "attachmentId": payload["body"]["attachmentId"],
                    "filename": payload["filename"],
                    "mimeType": payload.get("mimeType", "application/octet-stream"),
                    "size": payload.get("body", {}).get("size", 0),
                }
            )
        for part in payload.get("parts", []):
            attachments.extend(self._get_attachments(part))
        return attachments

    def list_emails(self, query: str = "", max_results: int = 10) -> dict:
        """List emails from inbox."""
        response = (
            self.gmail.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )

        emails = []
        for msg in response.get("messages", []):
            detail = (
                self.gmail.users()
                .messages()
                .get(
                    userId="me",
                    id=msg["id"],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Date"],
                )
                .execute()
            )
            headers = detail.get("payload", {}).get("headers", [])
            emails.append(
                {
                    "id": msg["id"],
                    "subject": self._get_header(headers, "Subject"),
                    "from": self._get_header(headers, "From"),
                    "date": self._get_header(headers, "Date"),
                }
            )
        return emails

    def get_email(self, message_id: str) -> dict:
        """Get email details."""
        response = (
            self.gmail.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        payload = response.get("payload", {})
        headers = payload.get("headers", [])
        body = self._get_text_content(payload)
        attachments = self._get_attachments(payload)

        return {
            "id": response.get("id"),
            "subject": self._get_header(headers, "Subject"),
            "from": self._get_header(headers, "From"),
            "to": self._get_header(headers, "To"),
            "date": self._get_header(headers, "Date"),
            "body": body,
            "bodyPreview": body[:500] + ("..." if len(body) > 500 else ""),
            "hasAttachments": len(attachments) > 0,
            "attachmentCount": len(attachments),
        }

    def list_attachments(self, message_id: str) -> list:
        """List attachments of an email."""
        response = (
            self.gmail.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        return self._get_attachments(response.get("payload", {}))

    def download_attachment(
        self, message_id: str, attachment_id: str, filename: str
    ) -> dict:
        """Download attachment and save to file."""
        response = (
            self.gmail.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )

        data = base64.urlsafe_b64decode(response["data"])
        filepath = self.download_dir / filename
        filepath.write_bytes(data)

        return {"path": str(filepath), "size": len(data)}

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str = None,
        bcc: str = None,
        from_alias: str = None,
        from_name: str = None,
        attachments: list[str] | None = None,
    ) -> dict:
        """Send email, optionally with file attachments."""
        sender_email = from_alias or self.user_email
        sender_name = from_name or self.user_name

        if attachments:
            message = MIMEMultipart()
            message.attach(MIMEText(body))
            for file_path in attachments:
                p = Path(file_path)
                if not p.is_file():
                    raise FileNotFoundError(f"Attachment not found: {file_path}")
                if not str(p.resolve()).startswith("/app/data"):
                    raise ValueError(
                        f"Attachment path must be under /app/data: {file_path}"
                    )
                content_type = (
                    mimetypes.guess_type(str(p))[0] or "application/octet-stream"
                )
                maintype, subtype = content_type.split("/", 1)
                part = MIMEBase(maintype, subtype)
                part.set_payload(p.read_bytes())
                email.encoders.encode_base64(part)
                part.add_header("Content-Disposition", "attachment", filename=p.name)
                message.attach(part)
        else:
            message = MIMEText(body)

        message["to"] = to
        message["subject"] = subject
        message["from"] = (
            f"{sender_name} <{sender_email}>" if sender_name else sender_email
        )
        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        response = (
            self.gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
        )

        attached_names = [Path(f).name for f in (attachments or [])]
        return {
            "id": response.get("id"),
            "to": to,
            "subject": subject,
            "attachments": attached_names,
        }

    def reply_email(
        self,
        message_id: str,
        body: str,
        cc: str = None,
        bcc: str = None,
        from_alias: str = None,
        from_name: str = None,
        attachments: list[str] | None = None,
    ) -> dict:
        """Reply to an existing email, keeping the thread intact."""
        # Fetch original message for thread info and headers
        original = (
            self.gmail.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["Subject", "From", "To", "Message-ID", "References"],
            )
            .execute()
        )

        thread_id = original.get("threadId")
        orig_headers = original.get("payload", {}).get("headers", [])
        orig_subject = self._get_header(orig_headers, "Subject") or ""
        orig_from = self._get_header(orig_headers, "From") or ""
        orig_message_id = self._get_header(orig_headers, "Message-ID") or ""
        orig_references = self._get_header(orig_headers, "References") or ""

        # Reply goes to the original sender
        reply_to = orig_from
        # Build References chain
        references = (
            f"{orig_references} {orig_message_id}".strip()
            if orig_references
            else orig_message_id
        )
        # Subject with Re: prefix
        subject = (
            orig_subject if orig_subject.startswith("Re:") else f"Re: {orig_subject}"
        )

        sender_email = from_alias or self.user_email
        sender_name = from_name or self.user_name

        if attachments:
            message = MIMEMultipart()
            message.attach(MIMEText(body))
            for file_path in attachments:
                p = Path(file_path)
                if not p.is_file():
                    raise FileNotFoundError(f"Attachment not found: {file_path}")
                if not str(p.resolve()).startswith("/app/data"):
                    raise ValueError(
                        f"Attachment path must be under /app/data: {file_path}"
                    )
                content_type = (
                    mimetypes.guess_type(str(p))[0] or "application/octet-stream"
                )
                maintype, subtype = content_type.split("/", 1)
                part = MIMEBase(maintype, subtype)
                part.set_payload(p.read_bytes())
                email.encoders.encode_base64(part)
                part.add_header("Content-Disposition", "attachment", filename=p.name)
                message.attach(part)
        else:
            message = MIMEText(body)

        message["to"] = reply_to
        message["subject"] = subject
        message["from"] = (
            f"{sender_name} <{sender_email}>" if sender_name else sender_email
        )
        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc
        if orig_message_id:
            message["In-Reply-To"] = orig_message_id
        if references:
            message["References"] = references

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_body = {"raw": raw}
        if thread_id:
            send_body["threadId"] = thread_id

        response = (
            self.gmail.users().messages().send(userId="me", body=send_body).execute()
        )

        attached_names = [Path(f).name for f in (attachments or [])]
        return {
            "id": response.get("id"),
            "threadId": response.get("threadId"),
            "to": reply_to,
            "subject": subject,
            "attachments": attached_names,
        }

    def mark_as_read(self, message_ids: list[str]) -> dict:
        """Mark emails as read by removing the UNREAD label."""
        results = []
        for mid in message_ids:
            self.gmail.users().messages().modify(
                userId="me",
                id=mid,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
            results.append(mid)
        return {"markedAsRead": results, "count": len(results)}

    def list_calendar_events(
        self,
        max_results: int = 10,
        time_min: str = None,
        time_max: str = None,
        query: str = None,
    ) -> list:
        """List calendar events."""
        params = {
            "calendarId": "primary",
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
            "timeMin": time_min or datetime.utcnow().isoformat() + "Z",
        }
        if time_max:
            params["timeMax"] = time_max
        if query:
            params["q"] = query

        response = self.calendar.events().list(**params).execute()

        return [
            {
                "id": e.get("id"),
                "summary": e.get("summary"),
                "description": e.get("description"),
                "location": e.get("location"),
                "start": e.get("start", {}).get("dateTime")
                or e.get("start", {}).get("date"),
                "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
                "attendees": [a.get("email") for a in e.get("attendees", [])],
                "htmlLink": e.get("htmlLink"),
            }
            for e in response.get("items", [])
        ]

    def get_calendar_event(self, event_id: str) -> dict:
        """Get calendar event details."""
        e = self.calendar.events().get(calendarId="primary", eventId=event_id).execute()
        return {
            "id": e.get("id"),
            "summary": e.get("summary"),
            "description": e.get("description"),
            "location": e.get("location"),
            "start": e.get("start", {}).get("dateTime")
            or e.get("start", {}).get("date"),
            "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
            "attendees": [
                {"email": a.get("email"), "responseStatus": a.get("responseStatus")}
                for a in e.get("attendees", [])
            ],
            "organizer": e.get("organizer", {}).get("email"),
            "created": e.get("created"),
            "updated": e.get("updated"),
            "htmlLink": e.get("htmlLink"),
        }

    def create_calendar_event(
        self,
        summary: str,
        start_dt: str,
        end_dt: str,
        description: str = None,
        location: str = None,
        attendees: str = None,
    ) -> dict:
        """Create calendar event."""
        body = {
            "summary": summary,
            "start": {"dateTime": start_dt},
            "end": {"dateTime": end_dt},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": e.strip()} for e in attendees.split(",")]

        e = self.calendar.events().insert(calendarId="primary", body=body).execute()
        return {"id": e.get("id"), "summary": summary, "htmlLink": e.get("htmlLink")}

    def update_calendar_event(
        self,
        event_id: str,
        summary: str = None,
        description: str = None,
        start_dt: str = None,
        end_dt: str = None,
        location: str = None,
    ) -> dict:
        """Update calendar event."""
        existing = (
            self.calendar.events().get(calendarId="primary", eventId=event_id).execute()
        )

        body = {
            "summary": summary or existing.get("summary"),
            "description": description
            if description is not None
            else existing.get("description"),
            "location": location if location is not None else existing.get("location"),
            "start": {"dateTime": start_dt} if start_dt else existing.get("start"),
            "end": {"dateTime": end_dt} if end_dt else existing.get("end"),
        }

        e = (
            self.calendar.events()
            .update(calendarId="primary", eventId=event_id, body=body)
            .execute()
        )
        return {
            "id": e.get("id"),
            "summary": e.get("summary"),
            "htmlLink": e.get("htmlLink"),
        }

    def delete_calendar_event(self, event_id: str) -> dict:
        """Delete calendar event."""
        self.calendar.events().delete(calendarId="primary", eventId=event_id).execute()
        return {"deleted": event_id}

    async def handle_request(self, request: dict) -> dict:
        """Handle MCP JSON-RPC request."""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        try:
            if method == "initialize":
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {
                            "name": f"gmail-{self.user_email}",
                            "version": "2.0.0",
                        },
                    },
                }

            elif method == "tools/list":
                return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.tools}}

            elif method == "tools/call":
                tool_name = params.get("name", "")
                args = params.get("arguments", {})
                result = self._call_tool(tool_name, args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(result, indent=2)}
                        ]
                    },
                }

            elif method == "notifications/initialized":
                return None

            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(e)},
            }

    def _track_operation(self, name: str, args: dict, result: dict) -> None:
        """Track operation for context persistence."""
        try:
            state_file = self.download_dir / "gmail_context.json"

            # Load existing state
            state = {}
            if state_file.exists():
                try:
                    with open(state_file, "r") as f:
                        state = json.load(f)
                except (json.JSONDecodeError, IOError):
                    state = {}

            user_id = self.user_email
            if user_id not in state:
                state[user_id] = {
                    "operations": [],
                    "working_email": None,
                    "working_event": None,
                }

            timestamp = datetime.now().isoformat()

            # Extract relevant info based on operation
            op_record = {
                "timestamp": timestamp,
                "operation": name,
            }

            if name == "get_email" and isinstance(result, dict):
                email_data = result
                op_record["message_id"] = args.get("messageId", "")
                op_record["subject"] = email_data.get("subject", "")
                op_record["from"] = email_data.get("from", "")
                op_record["snippet"] = email_data.get("snippet", "")[:200]

                # Set as working email
                state[user_id]["working_email"] = {
                    "message_id": args.get("messageId", ""),
                    "subject": email_data.get("subject", ""),
                    "from": email_data.get("from", ""),
                    "to": email_data.get("to", ""),
                    "date": email_data.get("date", ""),
                    "snippet": email_data.get("snippet", "")[:500],
                    "body_preview": email_data.get("body", "")[:1000]
                    if email_data.get("body")
                    else "",
                    "timestamp": timestamp,
                }

            elif name == "list_emails" and isinstance(result, list):
                op_record["count"] = len(result)
                if result:
                    op_record["first_subject"] = result[0].get("subject", "")

            elif name == "get_calendar_event" and isinstance(result, dict):
                op_record["event_id"] = args.get("eventId", "")
                op_record["summary"] = result.get("summary", "")

                state[user_id]["working_event"] = {
                    "event_id": args.get("eventId", ""),
                    "summary": result.get("summary", ""),
                    "start": result.get("start", ""),
                    "end": result.get("end", ""),
                    "description": result.get("description", "")[:500]
                    if result.get("description")
                    else "",
                    "timestamp": timestamp,
                }

            elif name in ("send_email", "reply_email"):
                op_record["to"] = args.get("to", "")
                op_record["subject"] = args.get("subject", "")

            # Add to operations list
            state[user_id]["operations"].insert(0, op_record)
            state[user_id]["operations"] = state[user_id]["operations"][:10]

            # Save state
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2)

        except Exception:
            # Don't fail tool calls due to tracking errors
            pass

    def _call_tool(self, name: str, args: dict):
        """Route tool call to appropriate method."""
        result = self._call_tool_impl(name, args)

        # Track operations
        self._track_operation(name, args, result)

        return result

    def _call_tool_impl(self, name: str, args: dict):
        """Implementation of tool routing."""
        if name == "list_emails":
            return self.list_emails(args.get("query", ""), args.get("maxResults", 10))
        elif name == "get_email":
            return self.get_email(args["messageId"])
        elif name == "list_attachments":
            return self.list_attachments(args["messageId"])
        elif name == "download_attachment":
            return self.download_attachment(
                args["messageId"], args["attachmentId"], args["filename"]
            )
        elif name == "send_email":
            return self.send_email(
                args["to"],
                args["subject"],
                args["body"],
                args.get("cc"),
                args.get("bcc"),
                args.get("from_alias"),
                args.get("from_name"),
                args.get("attachments"),
            )
        elif name == "reply_email":
            return self.reply_email(
                args["messageId"],
                args["body"],
                args.get("cc"),
                args.get("bcc"),
                args.get("from_alias"),
                args.get("from_name"),
                args.get("attachments"),
            )
        elif name == "mark_as_read":
            return self.mark_as_read(args["messageIds"])
        elif name == "list_calendar_events":
            return self.list_calendar_events(
                args.get("maxResults", 10),
                args.get("timeMin"),
                args.get("timeMax"),
                args.get("query"),
            )
        elif name == "get_calendar_event":
            return self.get_calendar_event(args["eventId"])
        elif name == "create_calendar_event":
            return self.create_calendar_event(
                args["summary"],
                args["startDateTime"],
                args["endDateTime"],
                args.get("description"),
                args.get("location"),
                args.get("attendees"),
            )
        elif name == "update_calendar_event":
            return self.update_calendar_event(
                args["eventId"],
                args.get("summary"),
                args.get("description"),
                args.get("startDateTime"),
                args.get("endDateTime"),
                args.get("location"),
            )
        elif name == "delete_calendar_event":
            return self.delete_calendar_event(args["eventId"])
        else:
            raise ValueError(f"Unknown tool: {name}")

    async def run(self):
        """Run the MCP server on stdio."""
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            try:
                line = await reader.readline()
                if not line:
                    break

                request = json.loads(line.decode("utf-8"))
                response = await self.handle_request(request)

                if response:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()

            except json.JSONDecodeError:
                continue
            except Exception as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"},
                }
                sys.stdout.write(json.dumps(error_response) + "\n")
                sys.stdout.flush()


def main():
    # Token data passed via environment variable (JSON)
    token_json = os.environ.get("GMAIL_TOKEN_DATA", "")
    download_dir = os.environ.get("GMAIL_DOWNLOAD_DIR", "/app/data/attachments")

    if not token_json:
        sys.stderr.write("Error: GMAIL_TOKEN_DATA environment variable not set\n")
        sys.exit(1)

    try:
        token_data = json.loads(token_json)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"Error: Invalid GMAIL_TOKEN_DATA JSON: {e}\n")
        sys.exit(1)

    server = GmailMCPServer(token_data, download_dir)
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
