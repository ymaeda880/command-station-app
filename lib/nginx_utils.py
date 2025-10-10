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
from typing import Tuple

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

def load_settings(settings_path: Path = SETTINGS_FILE) -> dict:
    if not settings_path.exists():
        raise FileNotFoundError(f"{settings_path} が見つかりません。")
    return toml.load(settings_path)

def resolve_nginx_conf_path(settings: dict) -> Path:
    loc = settings["env"]["location"]
    nginx_root = Path(settings["locations"][loc]["nginx_root"])
    return nginx_root / DEFAULT_CONF_NAME

def stat_text(p: Path) -> str:
    if not p.exists():
        return "（ファイルなし）"
    sz = p.stat().st_size
    mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).astimezone()
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
