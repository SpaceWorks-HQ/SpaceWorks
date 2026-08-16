"""Write non-circular source/build identity inside the backend image."""

import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path("/app")
EXCLUDED = {"BUILD_INFO.json", ".env"}


def source_hash():
    digest = hashlib.sha256()
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.name in EXCLUDED or any(
            part in {".venv", "__pycache__", "staticfiles"} for part in path.parts
        ):
            continue
        relative = path.relative_to(ROOT).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


payload = {
    "git_sha": os.environ.get("BUILD_GIT_SHA", "unknown"),
    "git_describe": os.environ.get("BUILD_GIT_DESCRIBE", "unknown"),
    "built_at": datetime.now(timezone.utc).isoformat(),
    "source_hash": source_hash(),
}
(ROOT / "BUILD_INFO.json").write_text(
    json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8"
)

