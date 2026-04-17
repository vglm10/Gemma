---
name: pdf-read
description: Extract clean Markdown from PDF files on disk.
version: 0.1
emoji: "📄"
requires:
  bins: []
  env: []
  python: [pymupdf4llm]
tools_module: tools.py
auth:
  kind: none
---

# pdf-read

When the user asks you to read, summarize, quote from, or extract content
from a PDF on disk, use `skill__pdf_read__extract`.

## Tool

`skill__pdf_read__extract(path: string) -> string`

- `path` must be an absolute path to a `.pdf` file (expand `~` yourself before
  calling — pass the expanded form).
- Returns the whole document as Markdown, with headings, lists, and tables
  preserved. Output is capped at roughly 40,000 characters; longer PDFs are
  truncated and flagged.

## Usage notes

- If the user gives you a relative path or just a filename, first use
  `list_directory` or `search_files` to find the absolute path.
- One call returns the whole document. Do not re-call for additional pages;
  just read the single returned string.
- If the PDF is a scanned image with no text layer, you will get little or no
  output. Say so plainly instead of guessing.
