# config/path_config.py
from __future__ import annotations
from pathlib import Path
import os
import tomllib

# このファイルの位置 … <app_root>/config/path_config.py
APP_ROOT = Path(__file__).resolve().parents[1]

def _candidate_paths() -> list[Path]:
    """settings.toml を探す候補パスを優先順で返す。"""
    paths: list[Path] = []

    # 1) 環境変数で明示指定（最優先）
    env_path = os.getenv("APP_SETTINGS_FILE")
    if env_path:
        paths.append(Path(env_path).expanduser())

    # 2) プロジェクト直下
    paths.append(APP_ROOT / "settings.toml")

    # 3) .streamlit/ 配下（今回あなたの配置）
    paths.append(APP_ROOT / ".streamlit" / "settings.toml")

    # 4) config/ 配下（保険）
    paths.append(APP_ROOT / "config" / "settings.toml")

    return paths

def load_settings() -> dict:
    for p in _candidate_paths():
        if p.exists():
            with open(p, "rb") as f:
                data = tomllib.load(f)
            return data
    # どこにも無ければ詳しく案内
    tried = [str(p) for p in _candidate_paths()]
    raise FileNotFoundError(
        "設定ファイル settings.toml が見つかりませんでした。\n"
        "探した場所:\n- " + "\n- ".join(tried) + "\n\n"
        "対処: 次のいずれかを実施してください。\n"
        "  1) settings.toml をプロジェクト直下 or .streamlit/ に置く\n"
        "  2) 環境変数 APP_SETTINGS_FILE で絶対パスを指定する\n"
        "     例: export APP_SETTINGS_FILE=\"$PWD/.streamlit/settings.toml\""
    )

def get_project_root() -> Path:
    s = load_settings()
    env = s["env"]["location"]
    locs = s["locations"]
    if env not in locs:
        raise KeyError(f"未知の location: {env}（候補: {list(locs.keys())}）")

    # pproject_root のタイポにもフォールバック
    root_str = locs[env].get("project_root") or locs[env].get("pproject_root")
    if not root_str:
        raise ValueError(f"{env} に project_root が定義されていません。")

    root = Path(root_str).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"project_root が存在しません: {root}")
    return root.resolve()

# 即時解決して他モジュールから import 利用
PROJECT_ROOT = get_project_root()
