# config/path_config.py
from __future__ import annotations
from pathlib import Path
import os
import tomllib
from typing import Optional, Dict, Any

# このファイルの位置 … <app_root>/config/path_config.py
APP_ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------
# 内部ユーティリティ
# ------------------------------------------------------------
def _candidate_paths() -> list[Path]:
    """settings.toml を探す候補パスを優先順で返す。"""
    paths: list[Path] = []

    # 1) 環境変数で明示指定（最優先）
    env_path = os.getenv("APP_SETTINGS_FILE")
    if env_path:
        paths.append(Path(env_path).expanduser())

    # 2) プロジェクト直下
    paths.append(APP_ROOT / "settings.toml")

    # 3) .streamlit/ 配下
    paths.append(APP_ROOT / ".streamlit" / "settings.toml")

    # 4) config/ 配下（保険）
    paths.append(APP_ROOT / "config" / "settings.toml")

    return paths


def _load_toml(path: Path) -> Dict[str, Any]:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _read_location_from_secrets() -> Optional[str]:
    """
    .streamlit/secrets.toml の [env].location を読み取って返す。
    - Streamlit 実行外 / secrets 未設定でも例外を外に投げない。
    - 空文字は無視して None を返す。
    """
    try:
        import streamlit as st  # 遅延インポート（未導入環境に配慮）
        env_sec = {}
        try:
            # 標準の配置: [env].location
            env_sec = dict(st.secrets.get("env", {}))  # type: ignore[arg-type]
        except Exception:
            env_sec = {}
        loc = env_sec.get("location")
        if isinstance(loc, str) and loc.strip():
            return loc.strip()

        # 互換: top-level "location"（推奨しないが一応対応）
        try:
            top_loc = st.secrets.get("location", None)  # type: ignore[attr-defined]
            if isinstance(top_loc, str) and top_loc.strip():
                return top_loc.strip()
        except Exception:
            pass
        return None
    except Exception:
        return None


# ------------------------------------------------------------
# 公開関数
# ------------------------------------------------------------
def load_settings() -> dict:
    """
    settings.toml を候補パスから読み込む。
    見つからない場合は詳細な案内付きで FileNotFoundError。
    """
    for p in _candidate_paths():
        if p.exists():
            return _load_toml(p)

    tried = [str(p) for p in _candidate_paths()]
    raise FileNotFoundError(
        "設定ファイル settings.toml が見つかりませんでした。\n"
        "探した場所:\n- " + "\n- ".join(tried) + "\n\n"
        "対処: 次のいずれかを実施してください。\n"
        "  1) settings.toml をプロジェクト直下 or .streamlit/ or config/ に置く\n"
        "  2) 環境変数 APP_SETTINGS_FILE で絶対パスを指定する\n"
        "     例: export APP_SETTINGS_FILE=\"$PWD/.streamlit/settings.toml\""
    )


def get_project_root() -> Path:
    """
    現在の location を以下の優先順で決定し、その location セクションの project_root を返す。
      1) .streamlit/secrets.toml の [env].location
      2) 環境変数 APP_LOCATION_PRESET
      3) settings.toml の [env].location
    """
    s = load_settings()

    # 1) secrets 最優先
    loc_from_secrets = _read_location_from_secrets()

    # 2) env var
    loc_from_env = os.getenv("APP_LOCATION_PRESET")

    # 3) settings.toml
    loc_from_settings = None
    try:
        loc_from_settings = s.get("env", {}).get("location")
    except Exception:
        loc_from_settings = None

    # 決定
    env = next(
        (x for x in (loc_from_secrets, loc_from_env, loc_from_settings) if x and str(x).strip()),
        None,
    )
    if not env:
        raise KeyError(
            "location が特定できませんでした。secrets.toml か settings.toml の [env].location を設定してください。"
        )

    # locations セクション
    try:
        locs = s["locations"]
    except KeyError:
        raise KeyError("settings.toml に [locations] セクションがありません。")

    if env not in locs:
        raise KeyError(f"未知の location: {env}（候補: {list(locs.keys())}）")

    # project_root（pproject_root のタイポにもフォールバック）
    root_str = locs[env].get("project_root") or locs[env].get("pproject_root")
    if not root_str:
        raise ValueError(f"{env} に project_root が定義されていません。")

    root = Path(str(root_str)).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"project_root が存在しません: {root}")

    return root.resolve()


# 即時解決して他モジュールから import 利用
PROJECT_ROOT = get_project_root()
