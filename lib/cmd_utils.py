# lib/cmd_utils.py
from __future__ import annotations
import shlex
import subprocess
from typing import List, Tuple, Optional

__all__ = [
    "run_safe",
    "git",
    "is_git_repo",
    "git_branch",
    "git_remote_first",
    "git_status_short",
    "git_changed_count",
]

# 許可コマンド（先頭トークン）
ALLOWLIST = {
    "ls", "pwd", "whoami", "df", "du", "diskutil",
    "git", "python", "python3",
}

def run_safe(cmdline: str, *, cwd: Optional[str] = None) -> Tuple[int, str, str]:
    """ALLOWLIST を満たす単一コマンドを shell=False で安全実行。"""
    if not cmdline.strip():
        return 1, "", "⚠️ コマンドが空です。"
    tokens: List[str] = shlex.split(cmdline)
    head = tokens[0]
    if head not in ALLOWLIST:
        return (1, "", f"🚫 許可されていないコマンド: `{head}`")
    try:
        p = subprocess.run(tokens, capture_output=True, text=True, check=False, cwd=cwd)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 1, "", f"💥 実行エラー: {e}"

def git(args: str, *, cwd: Optional[str] = None) -> Tuple[int, str, str]:
    """git サブコマンド用のヘルパ（例: git('status -sb', cwd=...))."""
    return run_safe(f"git {args}", cwd=cwd)

# ---- Git 情報系ユーティリティ ----
def is_git_repo(path: str) -> bool:
    code, out, _ = git("rev-parse --is-inside-work-tree", cwd=path)
    return code == 0 and out == "true"

def git_branch(path: str) -> str:
    code, out, _ = git("rev-parse --abbrev-ref HEAD", cwd=path)
    return out if code == 0 else ""

def git_remote_first(path: str) -> str:
    code, out, _ = git("remote -v", cwd=path)
    return out.splitlines()[0] if code == 0 and out else ""

def git_status_short(path: str) -> str:
    code, out, err = git("status -sb", cwd=path)
    return out or err

def git_changed_count(path: str) -> int:
    code, out, _ = git("status --porcelain=v1", cwd=path)
    return len(out.splitlines()) if code == 0 and out else 0
