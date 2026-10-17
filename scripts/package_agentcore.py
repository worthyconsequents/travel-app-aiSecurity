"""Create a reviewable Lambda ZIP locally; performs no uploads or deployment."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "build/agentcore-interceptor.zip"
FILES = [
    "services/__init__.py",
    "services/agentcore/__init__.py",
    "services/agentcore/inspection.py",
    "services/agentcore/interceptor.py",
]
OUTPUT.parent.mkdir(exist_ok=True)
with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
    for name in FILES:
        archive.write(ROOT / name, name)
print("Created local Lambda package:", OUTPUT)
