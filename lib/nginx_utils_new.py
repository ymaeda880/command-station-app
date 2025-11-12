# lib/nginx_utils_new.py

from __future__ import annotations
from pathlib import Path
import subprocess
import datetime as dt
import difflib
import shutil
import toml
import sys

# ========= パス系 =========
SETTINGS_FILE = ".streamlit/settings.toml"

# Nginx最小テンプレ（存在しない時にUIで表示）
MINIMAL_NGINX_CONF = """user nobody;
worker_processes 1;

events { worker_connections 1024; }

http {
    include mime.types;
    default_type application/octet-stream;
    sendfile on;

    server {
        listen 80;
        server_name localhost;
        root /opt/homebrew/var/www/html;
        index index.html;
    }
}
"""

# ========= ヘルパ =========
def load_settings(path: Path) -> dict:
    data = toml.loads(path.read_text(encoding="utf-8"))
    return data

def resolve_nginx_conf_path(settings: dict) -> Path:
    """
    1) settings.nginx.conf_path 明示
    2) locations.<env>.nginx_root + '/nginx.conf'
    3) Homebrew 既定
    """
    nginx = (settings.get("nginx") or {})
    if nginx.get("conf_path"):
        return Path(nginx["conf_path"]).expanduser().resolve()

    env = (settings.get("env") or {}).get("location")
    locs = settings.get("locations") or {}
    if env and isinstance(locs.get(env), dict):
        root = (locs[env].get("nginx_root") or "").strip()
        if root:
            return Path(root, "nginx.conf").expanduser().resolve()

    return Path("/opt/homebrew/etc/nginx/nginx.conf").resolve()

def stat_text(conf_path: Path) -> str:
    p = conf_path
    if not p.exists():
        return "ファイルが存在しません。"
    s = p.stat()
    mtime = dt.datetime.fromtimestamp(s.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return f"path: {p}\nsize: {s.st_size} bytes\nmtime: {mtime}"

def atomic_write(path: Path, content: str, encoding="utf-8") -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding=encoding)
    tmp.replace(path)

def make_backup(path: Path) -> Path:
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    bk = path.with_suffix(path.suffix + f".{ts}.bak")
    shutil.copy2(path, bk)
    return bk

def run_cmd(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out
    except Exception as e:
        return 1, f"[run_cmd error] {e}"

def generate_conf_dry_run() -> tuple[int, str]:
    script = Path("tools/generate_nginx_conf_new.py")
    if not script.exists():
        return 1, "[generate_conf_dry_run] tools/generate_nginx_conf_new.py が見つかりません。"
    return run_cmd([sys.executable, str(script), "--dry-run"])

def diff_current_vs_generated(current_text: str, generated_text: str) -> str:
    diff = difflib.unified_diff(
        current_text.splitlines(keepends=True),
        generated_text.splitlines(keepends=True),
        fromfile="current",
        tofile="generated",
        n=3,
    )
    return "".join(diff)

def current_head(conf_path: Path, n: int = 80) -> str:
    if not conf_path.exists():
        return ""
    return "".join(conf_path.read_text(encoding="utf-8", errors="replace").splitlines(True)[:n])

def nginx_test(conf_path: Path) -> tuple[int, str]:
    return run_cmd(["nginx", "-t", "-c", str(conf_path)])
