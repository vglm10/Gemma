import base64
from email.message import EmailMessage

from connectors import gmail as gmail_connector

MAX_BODY_CHARS = 10_000

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "skill__gmail__search",
            "description": "Search Gmail using standard search syntax. Returns a compact list of matching messages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Gmail search query, e.g. 'from:alice is:unread'"},
                    "max_results": {"type": "integer", "description": "Max results (default 10, cap 50)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill__gmail__get",
            "description": "Fetch a Gmail message by id: headers, thread id, and plain-text body.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Gmail message id from a search result"},
                },
                "required": ["message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill__gmail__create_draft",
            "description": "Create a Gmail draft. User must send it manually from Gmail.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email(s), comma-separated"},
                    "subject": {"type": "string"},
                    "body": {"type": "string", "description": "Plain-text body"},
                    "thread_id": {"type": "string", "description": "Optional: attach to existing thread"},
                    "cc": {"type": "string", "description": "Optional: CC recipients"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill__gmail__list_labels",
            "description": "List the user's Gmail labels (system + user labels).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def execute(name, args, ctx):
    conn = gmail_connector.get()
    if not conn.is_configured():
        return (
            "Error: Gmail is not configured. Drop the OAuth client JSON at "
            "data/google_oauth.json (from Google Cloud Console, Desktop App credentials)."
        )
    if not conn.is_authed():
        return (
            "Error: Gmail is not authenticated. "
            "Open the Skills panel and click Connect on the Gmail row."
        )

    try:
        svc = conn.service()
    except Exception as e:
        return f"Error: could not build Gmail service: {e}"

    try:
        if name == "skill__gmail__search":
            return _search(svc, args)
        if name == "skill__gmail__get":
            return _get(svc, args)
        if name == "skill__gmail__create_draft":
            return _create_draft(svc, args)
        if name == "skill__gmail__list_labels":
            return _list_labels(svc)
    except Exception as e:
        return f"Gmail API error: {e}"
    return f"Error: unknown tool {name}"


_CATEGORY_NAMES = {
    "CATEGORY_PERSONAL": "Primary",
    "CATEGORY_PROMOTIONS": "Promotions",
    "CATEGORY_SOCIAL": "Social",
    "CATEGORY_UPDATES": "Updates",
    "CATEGORY_FORUMS": "Forums",
}


def _describe_location(label_ids: list) -> str:
    """Turn a Gmail labelIds list into a short, user-facing 'where it lives' string.
    Tells the model whether a message is in Inbox/Primary/Promotions/etc."""
    ids = set(label_ids or [])
    parts = []
    if "INBOX" in ids:
        # Find the category if any — most messages will have exactly one.
        cat = next((_CATEGORY_NAMES[c] for c in _CATEGORY_NAMES if c in ids), "")
        parts.append(f"Inbox{'/' + cat if cat else ''}")
    else:
        if "SPAM" in ids:
            parts.append("Spam")
        elif "TRASH" in ids:
            parts.append("Trash")
        else:
            parts.append("Archived")
    if "STARRED" in ids:
        parts.append("starred")
    if "IMPORTANT" in ids:
        parts.append("important")
    return ",".join(parts)


def _search(svc, args) -> str:
    q = (args.get("query") or "").strip()
    if not q:
        return "Error: query is required"
    n = int(args.get("max_results") or 10)
    n = max(1, min(n, 50))

    resp = svc.users().messages().list(userId="me", q=q, maxResults=n).execute()
    msgs = resp.get("messages", [])
    if not msgs:
        return f"No messages found for: {q}"

    lines = [
        f"Found {len(msgs)} message(s) for query: {q}",
        "(Gmail's search covers all folders — use `in:inbox` to limit to the inbox.)",
    ]
    for m in msgs:
        meta = svc.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = {h["name"]: h["value"] for h in meta.get("payload", {}).get("headers", [])}
        snippet = (meta.get("snippet") or "").replace("\n", " ").strip()
        if len(snippet) > 140:
            snippet = snippet[:140] + "…"
        location = _describe_location(meta.get("labelIds", []))
        lines.append(
            f"- id={m['id']} thread={meta.get('threadId','')} [{location}]\n"
            f"  from: {headers.get('From','?')}\n"
            f"  subj: {headers.get('Subject','(no subject)')}\n"
            f"  date: {headers.get('Date','?')}\n"
            f"  snippet: {snippet}"
        )
    return "\n".join(lines)


def _get(svc, args) -> str:
    mid = (args.get("message_id") or "").strip()
    if not mid:
        return "Error: message_id is required"
    msg = svc.users().messages().get(userId="me", id=mid, format="full").execute()

    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    body = _extract_plain_text(msg.get("payload", {}))
    truncated = False
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS]
        truncated = True

    out = [
        f"id: {msg.get('id')}",
        f"threadId: {msg.get('threadId')}",
        f"From: {headers.get('From','?')}",
        f"To: {headers.get('To','?')}",
    ]
    if headers.get("Cc"):
        out.append(f"Cc: {headers['Cc']}")
    out.append(f"Subject: {headers.get('Subject','(no subject)')}")
    out.append(f"Date: {headers.get('Date','?')}")
    out.append("")
    out.append(body)
    if truncated:
        out.append(f"\n[Body truncated to {MAX_BODY_CHARS} chars]")
    return "\n".join(out)


def _create_draft(svc, args) -> str:
    to = (args.get("to") or "").strip()
    subject = args.get("subject") or ""
    body = args.get("body") or ""
    thread_id = (args.get("thread_id") or "").strip()
    cc = (args.get("cc") or "").strip()

    if not to:
        return "Error: to is required"

    msg = EmailMessage()
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg.set_content(body)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    draft_body = {"message": {"raw": raw}}
    if thread_id:
        draft_body["message"]["threadId"] = thread_id

    created = svc.users().drafts().create(userId="me", body=draft_body).execute()
    did = created.get("id", "?")
    mid = created.get("message", {}).get("id", "?")
    return (
        f"Draft created (draft_id={did}, message_id={mid}).\n"
        f"To: {to}\n"
        + (f"Cc: {cc}\n" if cc else "")
        + f"Subject: {subject}\n"
        + ("(attached to existing thread)\n" if thread_id else "")
        + "Open Gmail to send it."
    )


def _list_labels(svc) -> str:
    resp = svc.users().labels().list(userId="me").execute()
    labels = resp.get("labels", [])
    if not labels:
        return "No labels."
    system = [l for l in labels if l.get("type") == "system"]
    user = [l for l in labels if l.get("type") == "user"]
    lines = [f"Labels ({len(labels)}):"]
    if system:
        lines.append("  System:")
        for l in system:
            lines.append(f"    - {l['name']} (id={l['id']})")
    if user:
        lines.append("  User:")
        for l in user:
            lines.append(f"    - {l['name']} (id={l['id']})")
    return "\n".join(lines)


def _extract_plain_text(payload: dict) -> str:
    """Walk a Gmail message payload and return the best plain-text body.
    Prefers text/plain parts; falls back to the first text/* part found."""
    fallback = ""

    def walk(part):
        nonlocal fallback
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if data and mime.startswith("text/"):
            try:
                decoded = base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")
            except Exception:
                decoded = ""
            if mime == "text/plain":
                return decoded
            if not fallback:
                fallback = decoded
        for sub in part.get("parts", []) or []:
            found = walk(sub)
            if found:
                return found
        return ""

    found = walk(payload)
    return found or fallback or "(no text body)"
