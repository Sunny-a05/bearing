# Dock Inbox

Drop incoming material here (PDFs, markdown, notes, exports — any format; the CLI extracts text from pdf/docx/pptx/xlsx/html/epub/odt/rtf and more). Files here are **immutable** — agents dedup, digest, and route them to one of two permanent homes: `../../raw/` (+ a wiki page) via the INGEST workflow, or `../../library/` (thin-digested archive). **Nothing dropped here is ever deleted** — see `../DOCK.md` v3 for the full pipeline.

Note: `<filename>.digest.yaml` files appearing next to inbox items are **draft thin digests** written by `agentos.py digest` — they are working artifacts (the one exception to "nothing new is written here"), and they leave with the item when it's filed.
