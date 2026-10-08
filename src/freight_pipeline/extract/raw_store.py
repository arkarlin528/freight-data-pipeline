"""
The raw zone: every downloaded document is saved as-is, per run and source. A parser bug can then be
fixed and the run replayed from disk (`freight replay <run-id>`) without crawling the carriers again.
Local disk here; the same layout maps 1:1 to S3 keys (s3://bucket/raw/<run-id>/<source>/<name>).
"""

from __future__ import annotations

from pathlib import Path


class RawStore:
    def __init__(self, root: Path, run_id: str):
        self.run_dir = root / run_id

    def save(self, source: str, name: str, content: bytes) -> str:
        path = self.run_dir / source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return f"{source}/{name}"

    def documents(self, source: str) -> list[tuple[str, bytes]]:
        folder = self.run_dir / source
        if not folder.exists():
            return []
        return [(f"{source}/{p.name}", p.read_bytes()) for p in sorted(folder.iterdir(), key=_natural_key)]


def _natural_key(path: Path) -> tuple[str, int]:
    stem = path.stem
    digits = "".join(ch for ch in stem if ch.isdigit())
    return (stem.rstrip("0123456789-"), int(digits) if digits else 0)
