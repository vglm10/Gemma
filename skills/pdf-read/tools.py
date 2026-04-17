import os

MAX_CHARS = 40_000

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "skill__pdf_read__extract",
            "description": (
                "Extract the full text of a PDF file as Markdown. "
                "Returns headings, lists, and tables where the PDF has a text layer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to a .pdf file",
                    }
                },
                "required": ["path"],
            },
        },
    }
]


def execute(name, args, ctx):
    if name != "skill__pdf_read__extract":
        return f"Error: unknown tool {name}"
    path = os.path.expanduser(args.get("path", ""))
    if not path:
        return "Error: path is required"
    if not os.path.isfile(path):
        return f"Error: file not found: {path}"
    if not path.lower().endswith(".pdf"):
        return f"Error: not a .pdf file: {path}"

    try:
        import pymupdf4llm
    except ImportError:
        return "Error: pymupdf4llm is not installed"

    try:
        md = pymupdf4llm.to_markdown(path)
    except Exception as e:
        return f"Error: failed to read PDF: {e}"

    if len(md) > MAX_CHARS:
        return md[:MAX_CHARS] + f"\n\n[Truncated — {len(md)} total chars]"
    return md
