"""Record the environment a result was produced in.

A reported number is only reproducible if the versions behind it are known.
This captures the Python, library, OS and container versions at run time and
writes them alongside the experiment artifacts.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"

PACKAGES = ["numpy", "pandas", "scikit-learn", "scipy", "joblib", "fastapi", "pydantic"]


def package_version(name: str) -> str | None:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None


def command_output(*args: str) -> str | None:
    try:
        out = subprocess.run(args, capture_output=True, timeout=30, check=False)
        text = (out.stdout or out.stderr).decode("utf-8", "replace").strip()
        return text.splitlines()[0] if text else None
    except Exception:
        return None


def main() -> int:
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "python": {
            "version": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "packages": {name: package_version(name) for name in PACKAGES},
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": __import__("os").cpu_count(),
        },
        "tooling": {
            "docker": command_output("docker", "--version"),
            "docker_compose": command_output("docker", "compose", "version"),
            "git_commit": command_output("git", "rev-parse", "HEAD"),
            "git_dirty": bool(command_output("git", "status", "--porcelain")),
        },
        "note": (
            "Timing results depend on this hardware. Classification results "
            "depend on the library versions and the recorded seeds, not on the "
            "machine."
        ),
    }

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = ARTIFACTS / "environment.json"
    out.write_text(json.dumps(payload, indent=2))
    print(f"[ok] wrote {out}")
    print(f"     python {payload['python']['version']} on "
          f"{payload['platform']['system']} {payload['platform']['machine']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
