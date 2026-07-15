#!/usr/bin/env python3
"""Runtime bootstrap helpers for repo-local Python execution."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def ensure_repo_python() -> None:
    """Prefer repo-local venv and isolate from user site-packages."""
    current = Path(sys.executable)
    venv_root = ROOT / ".venv"
    venv_python = venv_root / "bin" / "python"
    in_repo_venv = Path(sys.prefix).resolve() == venv_root.resolve()

    if in_repo_venv and os.environ.get("PYTHONNOUSERSITE") == "1":
        return

    if venv_python.exists() and not in_repo_venv:
        os.execve(
            str(venv_python),
            [str(venv_python), *sys.argv],
            {**os.environ, "PYTHONNOUSERSITE": "1"},
        )

    if os.environ.get("PYTHONNOUSERSITE") != "1":
        os.execve(
            str(current),
            [str(current), *sys.argv],
            {**os.environ, "PYTHONNOUSERSITE": "1"},
        )
