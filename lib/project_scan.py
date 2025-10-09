# lib/project_scan.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
import re
import subprocess

from config.path_config import PROJECT_ROOT

@dataclass
class AppDir:
    name: str           # 表示名（例: command_station_app）
    app_path: Path      # *_app ディレクトリへのパス
    project_path: Path  # *_project ディレクトリ
    kind: str           # "app" or "portal"

def _is_git_repo(p: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=p,
            capture_output=True,
            text=True,
            check=False,
        )
        return r.returncode == 0 and r.stdout.strip() == "true"
    except Exception:
        return False

def _safe_run(cmd: list[str], cwd: Optional[Path]) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"

def git_status_summary(repo: Path) -> dict:
    """
    主要情報をまとめて取得
      - branch
      - dirty（未コミット差分）
      - ahead/behind（追跡ブランチとの差）
      - short_status（status -sb 相当）
    """
    info = {
        "branch": "",
        "dirty": 0,
        "ahead": 0,
        "behind": 0,
        "short_status": "",
        "is_repo": _is_git_repo(repo),
    }
    if not info["is_repo"]:
        return info

    # ブランチ
    _, out, _ = _safe_run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo)
    info["branch"] = out or ""

    # 変更ファイル数
    _, out, _ = _safe_run(["git", "status", "--porcelain=v1"], repo)
    info["dirty"] = len(out.splitlines()) if out else 0

    # upstream との ahead/behind
    # まず upstream があるか確認
    code, out, _ = _safe_run(["git", "rev-parse", "--abbrev-ref", "@{u}"], repo)
    if code == 0 and out:
        code2, out2, _ = _safe_run(["git", "rev-list", "--left-right", "--count", "@{u}...HEAD"], repo)
        if code2 == 0 and out2:
            # 形式: "<behind>\t<ahead>"
            parts = re.split(r"\s+", out2.strip())
            if len(parts) >= 2:
                info["behind"] = int(parts[0])
                info["ahead"] = int(parts[1])

    # 短縮 status
    _, out, _ = _safe_run(["git", "status", "-sb"], repo)
    info["short_status"] = out or ""
    return info

def discover_apps(project_root: Path = PROJECT_ROOT) -> List[AppDir]:
    results: List[AppDir] = []

    # *_project/*_app を探索
    for proj in sorted(project_root.glob("*_project")):
        if not proj.is_dir():
            continue
        # プロジェクト直下の *_app を探索
        for app_dir in sorted(proj.glob("*_app")):
            if app_dir.is_dir() and (app_dir / "app.py").exists():
                results.append(
                    AppDir(
                        name=app_dir.name,
                        app_path=app_dir,
                        project_path=proj,
                        kind="app",
                    )
                )

    # apps_portal も対象に含める
    portal = project_root / "apps_portal"
    if portal.exists() and portal.is_dir():
        results.append(
            AppDir(
                name="apps_portal",
                app_path=portal,
                project_path=portal,
                kind="portal",
            )
        )

    return results
