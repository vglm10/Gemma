---
name: documents
description: Create PDF and Excel documents on disk.
version: 0.1
emoji: "📝"
requires:
  bins: []
  env: []
  python: [fpdf, openpyxl]
tools_module: tools.py
auth:
  kind: none
---

# documents

Use this skill when the user asks you to produce a PDF or Excel file.
Two tools are available.

## `skill__documents__create_pdf`

`(path: string, title: string, body: string) -> string`

- `path` — absolute path where the PDF is written.
- `title` — rendered centered and bold at the top of the first page.
- `body` — plain text. Line breaks in `body` are preserved.

Example: when the user says "make me a PDF of today's notes at ~/Desktop/notes.pdf",
expand the path yourself and call with `path="/Users/.../Desktop/notes.pdf"`.

## `skill__documents__create_excel`

`(path: string, title: string, headers_json: string, rows_json: string) -> string`

- `headers_json` — a JSON array of column header strings, e.g. `["Name","Age"]`.
- `rows_json` — a JSON array of arrays, e.g. `[["Ada",36],["Bob",41]]`.
- Headers are bolded on the first row. Sheet title is truncated to 31 chars.

## Usage notes

- Always use absolute paths. If the user says "in my Documents folder," expand
  the path before calling.
- Excel: pass valid JSON strings, not Python-literal strings. Double-quoted keys
  and strings only.
- Return values are single-line confirmations like "PDF created: /path (N chars)".
