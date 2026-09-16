from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class FileRecord:
    path: str
    abs_path: Path
    size: int
    sha256: str
    lang: str
    text: bool
    truncated: bool
    content: str
    commit: str | None = None


@dataclass(slots=True)
class ImportEdge:
    type: str
    from_file: str
    to: str
    evidence_line: int
    evidence_text: str
    confidence: str
    external: bool
