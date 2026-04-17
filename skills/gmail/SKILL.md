---
name: gmail
description: Search Gmail, read messages, create drafts (no send), list labels.
version: 0.2
emoji: "📧"
requires:
  bins: []
  env: []
  python: [google.auth, googleapiclient]
tools_module: tools.py
auth:
  kind: oauth
  connector: gmail
---

# gmail

Use this skill when the user wants to search their email, read a specific
message, draft a reply, or see their labels. Four tools; **no send tool** —
drafts always stay in Gmail until the user sends them manually.

## Important: what "inbox" means on Gmail

Gmail's search without `in:inbox` hits **every folder** — Archive, Spam,
Trash, Drafts, everything. That's almost never what the user means when they
ask about "their inbox." **Always start with `in:inbox`** for casual asks.

Gmail's Inbox is also split into tabs (Primary / Promotions / Social /
Updates / Forums). The unread count the user sees in Gmail is the sum across
*all tabs in the Inbox* — so `in:inbox is:unread` is the query that matches
what they see. If they want just Primary, add `category:primary`.

Messages that auto-skip the inbox (filters, muted threads) are Archived.
`in:inbox` won't find those — that's usually correct.

## Intent → query mapping

Use these defaults when the user is casual. Ask for clarification only if
the first result set is clearly wrong.

| User says | Use `query=` |
|---|---|
| "unread emails" / "any new email" / "what's in my inbox" | `in:inbox is:unread` |
| "unread in Primary" | `in:inbox category:primary is:unread` |
| "unread in promotions" | `category:promotions is:unread` |
| "all my unread" / "every unread email" | `is:unread` (explicitly all folders) |
| "latest / recent emails" | `in:inbox newer_than:7d` |
| "emails from Alice" | `from:alice` |
| "emails from Alice this week" | `from:alice newer_than:7d` |
| "emails about the budget" | `budget in:inbox` |
| "important / starred" | `in:inbox is:starred` |
| "emails with attachments" | `in:inbox has:attachment` |
| "the email from Bob with the PDF" | `from:bob has:attachment filename:pdf` |

When the user's ask is vague ("show me my emails"), use `in:inbox
newer_than:7d` and mention the window.

## Search operators (reference)

- Sender/recipient: `from:`, `to:`, `cc:`, `bcc:`
- Subject: `subject:"exact phrase"`
- State: `is:unread`, `is:read`, `is:starred`, `is:important`
- Location: `in:inbox`, `in:sent`, `in:drafts`, `in:anywhere`, `in:spam`, `in:trash`
- Category: `category:primary`, `category:promotions`, `category:social`, `category:updates`, `category:forums`
- Label: `label:<name>` (user-defined labels)
- Attachments: `has:attachment`, `filename:pdf`, `filename:"report.xlsx"`
- Time: `newer_than:7d`, `older_than:1y`, `after:2026/01/01`, `before:2026/04/01`
- Size: `larger:5M`, `smaller:1M`
- Combine: space = AND, `OR`, `-` for NOT. Quote phrases.

## Tools

### `skill__gmail__search`

`(query: string, max_results: int = 10) -> string`

Results include a `[location]` tag for each message — e.g. `[Inbox/Primary]`,
`[Inbox/Promotions]`, `[Archived]`, `[Spam]`. Use this to tell the user
*where* each match lives, especially if some aren't in Primary.

### `skill__gmail__get`

`(message_id: string) -> string`

Returns From/To/Cc/Subject/Date/threadId and the plain-text body. Pass the
`id` from a search result. Body is capped at ~10,000 characters — say so if
truncated.

### `skill__gmail__create_draft`

`(to: string, subject: string, body: string, thread_id?: string, cc?: string) -> string`

Creates a draft in the user's Drafts folder. Never says sent — the user must
send manually from Gmail. For replies: pass the `thread_id` from `get`, and
prefix the subject with `Re: ` unless it already starts with `Re:`.

**Drafts are free and reversible — create them eagerly.** When the user gives
you a recipient and a rough intent, produce your best draft and create it.
Do *not* ask for subject and body before drafting. Show the user what you
drafted afterwards so they can edit or discard it in Gmail.

## Drafting without asking

When the user says something like *"draft an email to X saying Y"* or *"send
a note to X about Y"* — just write it. Don't interrogate them for subject,
salutation, closing, tone, etc. Your job is to produce a reasonable first
pass; they'll edit in Gmail before sending.

Inference rules:

- **Subject**: if the user's intent is a single word or phrase ("saying
  hello"), use a matching short subject ("Hello", "Hi", "Checking in").
  For specific topics ("about the budget"), use that as the subject
  ("Budget question"). If truly unclear, use the first meaningful words
  of the body. Never use "(no subject)".
- **Salutation**: `Hi <first name>,` if you can parse the first name from
  the recipient email (e.g. `alice@…` → `Hi Alice,`). Otherwise `Hi,` is
  fine. For professional contexts, `Hello,` or `Dear <name>,`.
- **Body**: match the tone of the ask. "Saying hello" → one or two short
  lines. "Quick update" → 2–4 sentences. Don't pad.
- **Closing**: `Thanks,` or `Best,` on its own line, followed by the user's
  name if known. If you don't know their name, just the closing word.
- **Tone**: casual unless the recipient looks professional (company domain,
  formal context) or the user explicitly asked for formal.

Example — user says: *"draft an email to bob@acme.com saying I'll be late
tomorrow"*. You call:

```
create_draft(
  to="bob@acme.com",
  subject="Running late tomorrow",
  body="Hi Bob,\n\nJust a quick heads-up — I'll be running late tomorrow. I'll ping you as soon as I'm in.\n\nThanks,\n"
)
```

Then tell the user: *"Draft created. Subject: 'Running late tomorrow'. Edit
and send from Gmail Drafts when ready."*

**Only ask a clarifying question** when something critical is genuinely
ambiguous — e.g. the user said "reply to the email" but multiple recent
emails could be the target, or they asked for content you have no basis to
write ("draft a reply to Alice's proposal" and you haven't read it yet —
`get` the message first, then draft).

### `skill__gmail__list_labels`

`() -> string` — system + user labels.

## Things to do

- Report the `[location]` tag for each result, especially when any are
  outside Primary: e.g. "1 unread in Updates, none in Primary."
- If a search returns 0 and the user clearly expected hits, broaden once —
  e.g. drop `in:inbox` — and tell the user what you changed.
- For reply drafts: keep it short, match the tone of the thread, always
  end with a sign-off line.
- When asked to draft an email, just draft it — don't ask for subject/body
  first. See the "Drafting without asking" section above.

## Things not to do

- Never claim you sent an email. You can only create drafts.
- Don't dump 20 emails with full bodies — search returns metadata, then let
  the user pick one to `get`.
- Don't silently search all folders when the user asked about "inbox" —
  use `in:inbox` by default.
- **You cannot download attachments.** If the user asks, tell them to open
  the email in Gmail and download from there. This is a deliberate safety
  boundary — attachments from email are an attack vector and must stay
  under the user's manual control.
- If a tool returns `Error: Gmail is not authenticated`, tell the user to
  click Connect in the Skills panel. Do not retry.
