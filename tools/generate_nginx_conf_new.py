# tools/generate_nginx_conf_new.py

from __future__ import annotations
from pathlib import Path
import sys
import argparse
import toml
import os

# ---------- 入力ファイル ----------
SETTINGS_FILE = Path(".streamlit/settings.toml")
NGINX_TOML    = Path(".streamlit/nginx.toml")

# ---------- デフォルト ----------
DEFAULT_CONF_PATH  = "/opt/homebrew/etc/nginx/nginx.conf"
DEFAULT_INDEX_ROOT = "/Users/macmini2025/projects/apps_portal"

# ---------- テンプレ ----------
HTTP_TEMPLATE = """# ===============================================
# nginx.conf（AUTO-GENERATED — do not edit manually）
# Generated from .streamlit/nginx.toml + .streamlit/settings.toml(+secrets)
# ===============================================

{user_line}
worker_processes  1;

events {{
    worker_connections  1024;
}}

http {{
    include       mime.types;
    default_type  application/octet-stream;

    # WebSocket: Upgrade有無でConnectionヘッダを可変化
    map $http_upgrade $connection_upgrade {{
        default upgrade;
        ''      close;
    }}

    # -------------------------------------------
    # 圧縮（運用準拠）
    # -------------------------------------------
    gzip on;
    gzip_types text/plain text/css application/javascript application/json application/xml text/xml;
    gzip_min_length 1024;

    sendfile        on;
    keepalive_timeout  65;

    # 逆プロキシ時のリダイレクト先を相対に（内部URL露出防止）
    absolute_redirect off;

    server {{
        listen       80;
        server_name  {server_name};

        # ポータル（静的HTML）
        root   {index_root};
        index  index.html;

        # ===== メンテナンス制御（maintenance.flag があれば 503 → maintenance.html） =====
        # フラグのパス: {index_root}/maintenance.flag
        # ページのパス: {index_root}/maintenance.html
        if (-f $document_root/maintenance.flag) {{
            return 503;
        }}

        # 静的トップ: 存在ファイル/ディレクトリを優先。無ければ404
        location / {{
            try_files $uri $uri/ =404;
        }}

        # 503 を maintenance.html に内部転送
        error_page 503 @maintenance;
        location @maintenance {{
            rewrite ^(.*)$ /maintenance.html break;
        }}

        # 共通設定（WebSocket, Header, Keep-Alive）
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   X-Forwarded-Host  $host;
        proxy_set_header   X-Forwarded-Port  $server_port;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection $connection_upgrade;

        proxy_read_timeout 86400;
        proxy_redirect off;
        client_max_body_size 200m;

{location_blocks}
        # エラーページ
        error_page   500 502 503 504  /50x.html;
        location = /50x.html {{
            root   /opt/homebrew/var/www/html;
        }}
    }}
}}
"""

LOCATION_BLOCK = """        # ========================================================
        # {title}（Streamlit on :{port}）
        # ========================================================
        location = /{prefix} {{ return 301 /{prefix}/; }}
        location /{prefix}/ {{
            # Streamlit 側: baseUrlPath = "/{base}"
            proxy_pass         http://127.0.0.1:{port};   # ★末尾スラなし！
            proxy_buffering    off;
{extra_cookie_lines}
        }}
"""

# ---------- 設定読み込み ----------
def _load_settings() -> dict:
    """settings.toml と secrets.toml の [env] を統合"""
    data: dict = {}
    if SETTINGS_FILE.exists():
        data = toml.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    secrets_file = Path(".streamlit/secrets.toml")
    if secrets_file.exists():
        secrets = toml.loads(secrets_file.read_text(encoding="utf-8"))
        if "env" in secrets:
            data.setdefault("env", {}).update(secrets["env"])
    return data

def _load_nginx_toml() -> dict:
    if not NGINX_TOML.exists():
        return {}
    return toml.loads(NGINX_TOML.read_text(encoding="utf-8"))

def _active_loc(settings: dict) -> dict:
    env = (settings.get("env") or {}).get("location")
    locs = settings.get("locations") or {}
    if env and isinstance(locs.get(env), dict):
        return locs[env]
    return {}

# ---------- 出力値の解決 ----------
def _server_name_from_settings(settings: dict) -> str:
    loc = _active_loc(settings)

    names = []
    # local_host_name 優先
    local = (loc.get("local_host_name") or "").strip()
    if local:
        names.append(f"{local}.local")

    # settings.toml の server_name があれば追加
    if isinstance(loc.get("server_name"), list):
        names.extend(loc["server_name"])

    # デフォルト補完
    defaults = ["localhost"]
    for d in defaults:
        names.append(d)

    # 重複除去（順序維持）
    names = list(dict.fromkeys([n for n in names if n]))

    return " ".join(names)

def _user_line(settings: dict) -> str:
    """
    master が root のときだけ user ディレクティブを出す。
    Homebrew の非 root 運用では出さない（警告回避）。
    """
    if os.geteuid() != 0:
        return ""  # 非root運用では user 行を出さない
    loc = _active_loc(settings)
    u = (loc.get("user") or (settings.get("nginx") or {}).get("user") or "nobody")
    return f"user {u};"

def _index_root_from_settings(settings: dict) -> str:
    loc = _active_loc(settings)
    return (loc.get("index_root")
            or (settings.get("nginx") or {}).get("index_root")
            or DEFAULT_INDEX_ROOT)

def _conf_path_from_settings(settings: dict) -> Path:
    """
    1) settings.nginx.conf_path 明示
    2) locations.<env>.nginx_root + '/nginx.conf'
    3) DEFAULT_CONF_PATH
    """
    nginx = (settings.get("nginx") or {})
    if nginx.get("conf_path"):
        p = nginx["conf_path"]
    else:
        loc = _active_loc(settings)
        root = (loc.get("nginx_root") or "").strip()
        p = f"{root}/nginx.conf" if root else DEFAULT_CONF_PATH
    return Path(p).expanduser().resolve()

# ---------- locationブロック ----------
def _sso_cookie_lines(base: str, is_sso_issuer: bool) -> str:
    """
    SSO発行アプリのみ Cookie Path を / に正規化。
    一部の nginx では samesite/httponly 拡張が未対応のため、最小形のみ出力する。
    """
    if not is_sso_issuer or base == "/":
        return ""
    return (
        "            proxy_pass_header  Set-Cookie;\n"
        f"            proxy_cookie_path  {base}/ /;\n"
        f"            proxy_cookie_path  {base}  /;"
    )

def build_location_blocks(nginx_cfg: dict) -> str:
    """ .streamlit/nginx.toml を読み、enabled アプリを location ブロックにする """
    blocks: list[str] = []
    for app, cfg in (nginx_cfg or {}).items():
        if not isinstance(cfg, dict):
            continue
        if cfg.get("enabled") is False:
            continue

        base = cfg.get("base") or f"/{app}"     # 例: /bot
        prefix = base.lstrip("/")               # 例: bot
        port = int(cfg.get("port") or 0)
        title = cfg.get("title") or app
        is_sso = bool(cfg.get("sso_issuer") is True)

        extra = _sso_cookie_lines(base, is_sso)
        block = LOCATION_BLOCK.format(
            title=title, port=port, prefix=prefix, base=prefix, extra_cookie_lines=extra
        )
        blocks.append(block)
    return "".join(blocks)

# ---------- 生成 ----------
def generate_conf_text() -> str:
    settings = _load_settings()
    nginx_cfg = _load_nginx_toml()
    server_name = _server_name_from_settings(settings)
    index_root  = _index_root_from_settings(settings)
    user_line   = _user_line(settings)
    location_blocks = build_location_blocks(nginx_cfg)

    text = HTTP_TEMPLATE.format(
        user_line=user_line,
        server_name=server_name,
        index_root=index_root,
        location_blocks=location_blocks,
    )
    return text

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    conf_text = generate_conf_text()
    if args.dry_run:
        sys.stdout.write(conf_text)
        return 0

    # 書き込み
    settings = _load_settings()
    conf_path = _conf_path_from_settings(settings)
    conf_path.parent.mkdir(parents=True, exist_ok=True)

    # バックアップ（既存があれば）
    if conf_path.exists():
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        bak = conf_path.with_suffix(conf_path.suffix + f".{ts}.bak")
        bak.write_text(conf_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

    conf_path.write_text(conf_text, encoding="utf-8")
    print(f"[generate_nginx_conf_new] wrote: {conf_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
