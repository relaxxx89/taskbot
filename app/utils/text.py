from __future__ import annotations

from collections.abc import Iterable


def parse_tags(raw: str) -> list[str]:
    if not raw.strip() or raw.strip() in {"-", "none", "нет", "skip"}:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in raw.split(","):
        tag = item.strip().lower()
        if not tag:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    return result


def split_command_args(text: str | None) -> tuple[str, str]:
    if not text:
        return "", ""
    parts = text.split(maxsplit=1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def chunk_lines(lines: Iterable[str], limit: int = 3800) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) + 1 > limit and current:
            chunks.append("\n".join(current))
            current = []
            size = 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks
