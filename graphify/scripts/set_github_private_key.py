#!/usr/bin/env python3
"""Write GITHUB_PRIVATE_KEY into graphify/.env from a downloaded PEM file.

Hand-pasting a multi-line PEM directly into .env silently breaks: dotenv
only captures the first line as the value, and every subsequent PEM line
becomes its own bogus, unrelated key. This script reads the actual .pem
file GitHub gave you and writes it into .env as a single quoted line with
\\n escapes, which dotenv decodes back into real newlines correctly.

Usage:
    python3 scripts/set_github_private_key.py /path/to/downloaded-key.pem
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ENV_KEY_LINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: set_github_private_key.py <path-to-pem-file>", file=sys.stderr)
        raise SystemExit(1)

    pem_path = Path(sys.argv[1]).expanduser()
    if not pem_path.is_file():
        print(f"error: no such file: {pem_path}", file=sys.stderr)
        raise SystemExit(1)

    pem = pem_path.read_text()
    if "BEGIN" not in pem or "END" not in pem or "PRIVATE KEY" not in pem:
        print(
            "error: this doesn't look like a PEM private key "
            "(missing BEGIN/END PRIVATE KEY markers) — did you point at the right file?",
            file=sys.stderr,
        )
        raise SystemExit(1)

    escaped = pem.strip("\n").replace("\n", "\\n")
    new_line = f'GITHUB_PRIVATE_KEY="{escaped}"\n'

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        print(f"error: no .env at {env_path} — copy .env.example first", file=sys.stderr)
        raise SystemExit(1)

    lines = env_path.read_text().splitlines(keepends=True)

    # Replace the existing GITHUB_PRIVATE_KEY= line plus any stray
    # continuation lines left behind by a prior bad multi-line paste. A
    # continuation line is anything that doesn't itself look like a new
    # KEY=value assignment — checked as "starts with an identifier
    # immediately followed by =", not just "contains =", since base64 PEM
    # lines can end in "=" padding without being a real assignment.
    start = next((i for i, line in enumerate(lines) if line.startswith("GITHUB_PRIVATE_KEY=")), None)

    if start is None:
        env_path.write_text("".join(lines) + new_line)
    else:
        end = start + 1
        while end < len(lines) and not _ENV_KEY_LINE.match(lines[end]):
            end += 1
        lines[start:end] = [new_line]
        env_path.write_text("".join(lines))

    print(f"Wrote GITHUB_PRIVATE_KEY ({len(pem)} bytes from {pem_path.name}) into {env_path}")


if __name__ == "__main__":
    main()
