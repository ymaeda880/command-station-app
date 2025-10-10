# lib/nginx_utils.py
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import os
import shutil
import subprocess
import textwrap
import time
import toml
from typing import Tuple, Optional, Dict, Any

# ========= 定数 =========
SETTINGS_FILE = Path(".streamlit/settings.toml")
DEFAULT_CONF_NAME = "nginx.conf"

# 空の場合に編集エリアへ出す最小テンプレート（UI用）
MINIMAL_NGINX_CONF = textwrap.dedent("""
    # --------------------------------------------
    # Minimal nginx.conf (sample)
    # --------------------------------------------
    worker_processes  1;

    events {
        worker_connections  1024;
    }

    http {
        include       mime.types;
        default_type  application/octet-stream;

        sendfile        on;
        keepalive_timeout  65;

        server {
            listen       80;
            server_name  _;

            # ドキュメントルート（必要に応じて変更）
            root   /usr/local/var/www;
            index  index.html;
        }
    }
""").strip() + "\n"


# ========= 共通ユーティリティ =========
def run_cmd(cmd: list[str] | str, shell: bool = False) -> Tuple[int, str]:
    """コマンド実行（stdout+stderr を連結して返す）"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, shell=shell)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, f"[Exception] {e}"


# ---- secrets から location を読む（最優先）----
def _read_location_from_secrets() -> Optional[str]:
    """
    .streamlit/secrets.toml の [env].location を返す。
    - Streamlit 未導入/未起動でも例外は外に出さず None を返す。
    - top-level "location" も互換として一応見る。
    """
    try:
        import streamlit as st  # 遅延インポート
        env_sec: Dict[str, Any] = {}
        try:
            env_sec = dict(st.secrets.get("env", {}))  # type: ignore[arg-type]
        except Exception:
            env_sec = {}
        loc = env_sec.get("location")
        if isinstance(loc, str) and loc.strip():
            return loc.strip()
        try:
            top_loc = st.secrets.get("location", None)  # type: ignore[attr-defined]
            if isinstance(top_loc, str) and top_loc.strip():
                return top_loc.strip()
        except Exception:
            pass
    except Exception:
        pass
    return None


def load_settings(settings_path: Path = SETTINGS_FILE) -> dict:
    """
    settings.toml を読み、[env].location は以下の優先順で上書きして返す：
      1) secrets.toml の [env].location
      2) 環境変数 APP_LOCATION_PRESET
      3) settings.toml の [env].location
    """
    data: dict = {}
    if settings_path.exists():
        try:
            data = toml.load(settings_path)
        except Exception as e:
            raise RuntimeError(f"{settings_path} の読込に失敗: {e}") from e
    else:
        # settings が無い場合は、以後の解決に必要なのでここで明示
        raise FileNotFoundError(f"{settings_path} が見つかりません。")

    # 既存 env
    env = dict(data.get("env", {}))

    # location を決定
    loc = (
        _read_location_from_secrets()
        or os.getenv("APP_LOCATION_PRESET")
        or env.get("location")
    )

    if not loc or not str(loc).strip():
        raise KeyError(
            "location が未設定です。以下のいずれかを設定してください：\n"
            " - .streamlit/secrets.toml の [env].location\n"
            " - 環境変数 APP_LOCATION_PRESET\n"
            " - settings.toml の [env].location"
        )

    env["location"] = str(loc).strip()
    data["env"] = env
    return data


def resolve_nginx_conf_path(settings: dict) -> Path:
    """
    settings から現在のプレセットの nginx_root を取得し、nginx.conf のフルパスを返す。
    厳密なバリデーションと分かりやすいエラーを付与。
    """
    try:
        loc = settings["env"]["location"]
    except KeyError as e:
        raise KeyError("settings['env']['location'] が見つかりません。load_settings の戻り値をそのまま渡してください。") from e

    try:
        loc_block = settings["locations"][loc]
    except KeyError as e:
        keys = list(settings.get("locations", {}).keys())
        raise KeyError(f"[locations].{loc} が settings.toml にありません。候補: {keys}") from e

    nginx_root_raw = loc_block.get("nginx_root")
    if not nginx_root_raw:
        raise KeyError(f"[locations].{loc}.nginx_root が未設定です。")

    nginx_root = Path(str(nginx_root_raw)).expanduser().resolve()
    conf_path = (nginx_root / DEFAULT_CONF_NAME)
    return conf_path


def stat_text(p: Path) -> str:
    if not p.exists():
        return "（ファイルなし）"
    st_ = p.stat()
    sz = st_.st_size
    mtime = datetime.fromtimestamp(st_.st_mtime, tz=timezone.utc).astimezone()
    return f"{sz:,} bytes\n最終更新: {mtime.strftime('%Y-%m-%d %H:%M:%S %Z')}"


def atomic_write(path: Path, data: str) -> None:
    """原子書き込み（tmpに書いてから置換）"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    tmp.replace(path)


def make_backup(path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak.{ts}")
    shutil.copy2(path, backup)
    return backup


# ========= 生成（dry-run）関連 =========
def generate_conf_dry_run(py_exe: str = None) -> Tuple[int, str]:
    """tools/generate_nginx_conf.py を --dry-run で実行し、生成内容（stdout）を返す。"""
    from sys import executable as sys_py
    py = py_exe or sys_py
    gen = Path("tools/generate_nginx_conf.py")
    if not gen.exists():
        return 1, f"生成スクリプトが見つかりません: {gen}"
    return run_cmd([py, str(gen), "--dry-run"])


def diff_current_vs_generated(current_text: str, generated_text: str) -> str:
    """unified diff のテキストを返す（UI側で st.code(diff, language='diff') 予定）"""
    import difflib
    return "".join(difflib.unified_diff(
        current_text.splitlines(keepends=True),
        generated_text.splitlines(keepends=True),
        fromfile="(current nginx.conf)",
        tofile="(generated: dry-run)",
        n=2
    ))


def current_head(conf_path: Path, lines: int = 15) -> str:
    if not conf_path.exists():
        return ""
    try:
        txt = conf_path.read_text(encoding="utf-8", errors="replace")
        return "\n".join(txt.splitlines()[:lines])
    except Exception:
        return ""


# ========= Nginx 操作 =========
def nginx_test(conf_path: Path) -> Tuple[int, str]:
    return run_cmd(["nginx", "-t", "-c", str(conf_path)])


def nginx_reload(conf_path: Path) -> Tuple[int, str]:
    # reload は test 合格後に呼ぶのが安全（UI側で制御）
    return run_cmd(["nginx", "-s", "reload"])


def brew_start() -> Tuple[int, str]:
    return run_cmd("brew services start nginx", shell=True)


def brew_stop() -> Tuple[int, str]:
    return run_cmd("brew services stop nginx", shell=True)


def brew_restart() -> Tuple[int, str]:
    return run_cmd("brew services restart nginx", shell=True)


def brew_services_list() -> str:
    _, out = run_cmd("brew services list", shell=True)
    return out


def pgrep_nginx() -> str:
    _, out = run_cmd(["pgrep", "-ax", "nginx"])
    return out


def lsof_port_80() -> str:
    _, out = run_cmd("lsof -nP -iTCP:80 -sTCP:LISTEN | grep nginx || true", shell=True)
    return out


def tail_log(path: str, n: int) -> str:
    if not os.path.exists(path):
        return ""
    _, out = run_cmd(f"tail -n {int(n)} {path}", shell=True)
    return out


def mtime_str(p: Path) -> str:
    if not p.exists():
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))
