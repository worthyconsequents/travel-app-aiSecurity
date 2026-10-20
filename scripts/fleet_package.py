"""Prepare a minimal build context from tracked application inputs, excluding credentials."""

import shutil
from pathlib import Path

ROOT_FILES = ("pyproject.toml", "uv.lock")
TREES = ("services", "scripts", "scenario-runner", "frontend", "infra/aws-fleet")
EXCLUDED = {"node_modules", ".next", "__pycache__", ".git", "build"}
SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".json",
    ".css",
    ".svg",
    ".png",
    ".jpg",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".template",
}


def image_context(root, destination):
    root, destination = Path(root), Path(destination)
    for relative in ROOT_FILES:
        shutil.copy2(root / relative, destination / relative)
    for tree in TREES:
        for source in (root / tree).rglob("*"):
            relative = source.relative_to(root)
            if not source.is_file() or source.is_symlink() or EXCLUDED.intersection(relative.parts):
                continue
            if source.name.startswith(".env") or source.name.endswith((".key", ".pem")):
                continue
            if source.suffix not in SUFFIXES and not source.name.startswith("Dockerfile"):
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
