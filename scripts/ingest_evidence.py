"""Load raw chat exports into the evidence table.

Facts in this system carry a confidence number, which is a claim about how much
to trust something. Confidence without the source line behind it is an opinion.
This loads the actual messages so a stored fact can be traced back to the text
it came from.

Reads WhatsApp .txt exports. Idempotent: each line is hashed on its fields, so
re-running an unchanged export adds nothing. Nothing leaves the machine; the
database is gitignored and the exports are read, never copied into this repo.

Privacy: raw third-party messages are stored verbatim because retrieval that
rewrites a quotation is retrieval that cannot be checked. Access is local-only.
The database is never pushed.

Usage:
    .venv/bin/python scripts/ingest_evidence.py                  # default dir
    .venv/bin/python scripts/ingest_evidence.py path/to/exports
    .venv/bin/python scripts/ingest_evidence.py --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atif_assistant import db  # noqa: E402

# "19/04/2026, 3:57 am - Speaker: body", also the bracketed iOS variant
# "[19/04/2026, 3:57:58 am] Speaker: body".
_LINE = re.compile(
    r"^[\[\(]?(?P<date>\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}),"
    r"\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?)[\]\)]?"
    r"\s+-\s+(?P<rest>.*)$",
    re.IGNORECASE,
)
_SPEAKER = re.compile(r"^(?P<speaker>[^:]{1,80}?):\s?(?P<body>.*)$", re.DOTALL)

# Export noise that is not a message.
_NOISE = (
    "messages and calls are end-to-end encrypted",
    "<media omitted>",
    "<this message was deleted>",
    "waiting for this message",
    "you deleted this message",
    "null",
)

# Zero-width and bidi formatting characters: invisible marks that break exact
# matching and can leave a "message" that renders as nothing. Written with
# escapes so the set is unambiguous: zero-width space/joiners, LRM/RLM, the
# bidi embedding/override/isolate ranges, invisible operators, and the BOM.
_INVISIBLE = re.compile(
    "[\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]"
)


def normalize_ts(date: str, time: str) -> str:
    """Return an ISO-ish sortable timestamp, or the raw text if unparseable.

    Kept as text rather than converted to UTC: the export is local time and
    nothing in this system does date arithmetic across zones. A sortable
    string is enough to order events and to show the user what they said when.
    """
    d = date.replace("-", "/").replace(".", "/")
    parts = d.split("/")
    if len(parts) != 3:
        return f"{date} {time}".strip()
    day, month, year = parts
    if len(year) == 2:
        year = "20" + year
    # Narrow no-break space (U+202F) is what modern exports put before "am"/"pm".
    # It is invisible but survives into the stored string and breaks display.
    t = re.sub(r"[\s\u202f\u00a0]+", "", time.strip().lower())
    return f"{year}-{int(month):02d}-{int(day):02d} {t}"


def parse_file(path: Path) -> list[tuple[str | None, str | None, str, str]]:
    """Yield (occurred_at, speaker, body, source) for each real message."""
    out: list[tuple[str | None, str | None, str, str]] = []
    source = str(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"  ! cannot read {path}: {exc}", file=sys.stderr)
        return out

    current_ts: str | None = None
    current_speaker: str | None = None
    current_body: list[str] = []

    def flush() -> None:
        body = "\n".join(current_body).strip()
        if not body or current_speaker is None:
            return
        low = body.lower()
        if any(n in low for n in _NOISE):
            return
        # Drop messages that are nothing but direction marks / zero-width
        # joiners. (The old check compared a regex Match to a string, which was
        # never true, so this filter never actually ran.)
        if not _INVISIBLE.sub("", body).strip():
            return
        out.append((current_ts, current_speaker, body, source))

    for raw in text.splitlines():
        line = raw.rstrip()
        m = _LINE.match(line)
        if m:
            flush()
            current_body = []
            current_speaker = None
            current_ts = normalize_ts(m.group("date"), m.group("time"))
            rest = m.group("rest").strip()
            if not rest:
                # A bare timestamp with no speaker is a system notice, e.g. the
                # encryption banner or "Waiting for this message".
                current_ts = None
                continue
            sm = _SPEAKER.match(rest)
            if sm:
                current_speaker = sm.group("speaker").strip()
                current_body = [sm.group("body")]
            else:
                # Continuation of the previous message, i.e. a multi-line send.
                current_body = [rest]
            continue
        if current_speaker is not None and line.strip():
            current_body.append(line.strip())
    flush()
    return out


def looks_like_export(path: Path) -> bool:
    """True if the first chunk of the file parses as chat messages.

    A blanket `rglob("*.txt")` over a home directory sweeps in licences, build
    artifacts and test fixtures; that found 848 files, 800 of them unrelated.
    Sniffing a small prefix instead keeps the default safe to run.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(8192)
    except OSError:
        return False
    for line in head.splitlines()[:40]:
        if _LINE.match(line.rstrip()):
            return True
    return False


def find_exports(root: Path, sniff: bool = True) -> list[Path]:
    if root.is_file():
        return [root]
    files = sorted(p for p in root.rglob("*.txt") if p.is_file())
    if not sniff:
        return files
    return [p for p in files if looks_like_export(p)]


def ingest(paths: list[Path], dry_run: bool = False) -> dict[str, int]:
    totals = {"files": 0, "parsed": 0, "added": 0, "skipped": 0}
    if not dry_run:
        db.init_db()

    for path in paths:
        rows = parse_file(path)
        totals["files"] += 1
        totals["parsed"] += len(rows)
        added = 0
        for occurred_at, speaker, body, source in rows:
            if dry_run:
                added += 1
                continue
            if db.add_evidence(
                source=source, body=body, occurred_at=occurred_at, speaker=speaker
            ):
                added += 1
        totals["added"] += added
        totals["skipped"] += len(rows) - added
        print(f"  {path.name}: {len(rows)} messages, {added} new")

    if not dry_run:
        orphans = db.prune_fts_orphans()
        if orphans:
            print(f"  pruned {orphans} orphaned index rows")
    return totals


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "paths",
        nargs="*",
        help="export files or directories (default: ~/Downloads)",
    )
    ap.add_argument("--dry-run", action="store_true", help="parse only, write nothing")
    ap.add_argument(
        "--all-txt",
        action="store_true",
        help="skip the export sniff and take every .txt under the given paths",
    )
    args = ap.parse_args()

    roots = [Path(p).expanduser() for p in args.paths] or [Path.home() / "Downloads"]
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            print(f"! not found: {root}", file=sys.stderr)
            return 1
        paths.extend(find_exports(root, sniff=not args.all_txt))

    if not paths:
        print("no .txt exports found")
        return 1

    print(f"{'dry run: ' if args.dry_run else ''}reading {len(paths)} file(s)")
    t = ingest(paths, dry_run=args.dry_run)
    verb = "would add" if args.dry_run else "added"
    print(
        f"\n{t['files']} files, {t['parsed']} messages parsed, "
        f"{verb} {t['added']}, already stored {t['skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())