# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import os
import shlex
import subprocess


RSYNC = "/opt/homebrew/bin/rsync"

RSYNC_EXCLUDES = [
    "--exclude=.DS_Store",
    "--exclude=_preview_cache/",
]


@dataclass
class RunResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    cmd: list[str]


def run_result_to_dict(result: RunResult) -> dict:
    return {
        "ok": result.ok,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "cmd": result.cmd,
    }


def run_result_from_dict(value: object) -> Optional[RunResult]:
    if not isinstance(value, dict):
        return None

    try:
        return RunResult(
            ok=bool(value["ok"]),
            returncode=int(value["returncode"]),
            stdout=str(value.get("stdout", "")),
            stderr=str(value.get("stderr", "")),
            cmd=list(value.get("cmd", [])),
        )
    except Exception:
        return None


def sh(cmd: list[str]) -> RunResult:
    env = dict(os.environ)
    env["LANG"] = "en_US.UTF-8"
    env["LC_ALL"] = "en_US.UTF-8"

    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    return RunResult(
        ok=(p.returncode == 0),
        returncode=p.returncode,
        stdout=p.stdout or "",
        stderr=p.stderr or "",
        cmd=cmd,
    )


def fmt_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(x) for x in cmd)


def build_backup_latest_path(
    *,
    mount: Path,
    location: str,
    name: str,
) -> Path:
    return mount / "aisv_Backups" / str(location) / "backups" / str(name) / "latest"


def build_restore_cmd(
    *,
    restore_from: Path,
    restore_to: Path,
) -> list[str]:
    return [
        RSYNC,
        "-a",
        "--delete",
        "--itemize-changes",
        *RSYNC_EXCLUDES,
        f"{restore_from}/",
        f"{restore_to}/",
    ]


def build_diff_cmd(
    *,
    restore_from: Path,
    restore_to: Path,
) -> list[str]:
    return [
        RSYNC,
        "-a",
        "--delete",
        "--dry-run",
        "--itemize-changes",
        *RSYNC_EXCLUDES,
        f"{restore_from}/",
        f"{restore_to}/",
    ]


def has_no_diff(result: RunResult) -> bool:
    return result.ok and not result.stdout.strip()