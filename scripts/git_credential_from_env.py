#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def main() -> None:
    token = read_token(Path(".env"))
    if not token:
        return
    print("username=x-access-token")
    print(f"password={token}")


def read_token(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == "GITHUB_TOKEN":
            return value.strip().strip('"').strip("'")
    return None


if __name__ == "__main__":
    main()
