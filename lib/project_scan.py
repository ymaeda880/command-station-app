# lib/project_scan.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple
import re
import subprocess
import pandas as pd

from config.path_config import PROJECT_ROOT


# ============================================================
# データクラス定義
# ============================================================

@dataclass
class AppDir:
    """_project/_app 構造のアプリ情報"""
    name: str           # 表示名（例: command_station_app）
    app_path: Path      # *_app ディレクトリへのパス
    project_path: Path  # *_project ディレクトリ
    kind: str           # "app" or "portal"


@dataclass
class AppRepoInfo:
    """Git情報付きアプリ情報"""
    name: str
    path: Path
    kind: str
    branch: str
    dirty: int
    ahead: int
    behind: int
    short_status: str
    is_repo: bool


# ============================================================
# 内部ユーティリティ
# ============================================================

def _is_git_repo(p: Path) -> bool:
    """指定パスがGitリポジトリかを確認"""
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
    """サブプロセス安全実行（例外を吸収）"""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"


# ============================================================
# Git情報取得
# ============================================================

def git_status_summary(repo: Path) -> dict:
    """
    指定リポジトリの主要Git情報を取得
    - branch: 現在のブランチ名
    - dirty: 未コミット変更ファイル数
    - ahead/behind: upstreamとの差分
    - short_status: status -sb の出力
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

    # ブランチ名
    _, out, _ = _safe_run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo)
    info["branch"] = out or ""

    # 未コミットファイル数
    _, out, _ = _safe_run(["git", "status", "--porcelain=v1"], repo)
    info["dirty"] = len(out.splitlines()) if out else 0

    # upstream との ahead/behind
    code, out, _ = _safe_run(["git", "rev-parse", "--abbrev-ref", "@{u}"], repo)
    if code == 0 and out:
        code2, out2, _ = _safe_run(["git", "rev-list", "--left-right", "--count", "@{u}...HEAD"], repo)
        if code2 == 0 and out2:
            parts = re.split(r"\s+", out2.strip())
            if len(parts) >= 2:
                info["behind"] = int(parts[0])
                info["ahead"] = int(parts[1])

    # 短縮ステータス
    _, out, _ = _safe_run(["git", "status", "-sb"], repo)
    info["short_status"] = out or ""

    return info


# ============================================================
# アプリ探索
# ============================================================
def discover_apps(project_root: Path = PROJECT_ROOT) -> List[AppDir]:
    results: List[AppDir] = []

    # *_project/*_app を探索
    for proj in sorted(project_root.glob("*_project")):
        if not proj.is_dir():
            continue
        # プロジェクト直下の *_app を探索（app.py がなくてもOKに変更）
        for app_dir in sorted(proj.glob("*_app")):
            if app_dir.is_dir():
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



# ============================================================
# Git情報付き探索
# ============================================================

def discover_apps_with_git(project_root: Path = PROJECT_ROOT) -> List[AppRepoInfo]:
    """
    *_project 配下の *_app と apps_portal を探索し、
    各ディレクトリについて Git 情報を付加した一覧を返す。
    """
    apps = discover_apps(project_root)
    results: List[AppRepoInfo] = []

    for app in apps:
        info = git_status_summary(app.app_path)
        results.append(
            AppRepoInfo(
                name=app.name,
                path=app.app_path,
                kind=app.kind,
                branch=info["branch"],
                dirty=info["dirty"],
                ahead=info["ahead"],
                behind=info["behind"],
                short_status=info["short_status"],
                is_repo=info["is_repo"],
            )
        )

    return results


# ============================================================
# DataFrame化ヘルパー
# ============================================================

def apps_git_dataframe(project_root: Path = PROJECT_ROOT) -> pd.DataFrame:
    """
    Git情報付きアプリ一覧を pandas.DataFrame で返す。
    """
    rows = [asdict(r) for r in discover_apps_with_git(project_root)]
    if not rows:
        return pd.DataFrame(columns=[
            "name", "path", "kind", "branch", "dirty",
            "ahead", "behind", "short_status", "is_repo"
        ])
    return pd.DataFrame(rows)
