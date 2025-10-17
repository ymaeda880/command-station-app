# tools/generate_nginx_conf.py
#!/usr/bin/env python3
"""
nginx.conf 自動生成スクリプト（現行手動 nginx.conf の挙動に準拠）

入力:
  - .streamlit/nginx.toml     … アプリ名 → port / enabled のマッピング
  - .streamlit/settings.toml  … 環境プリセット（index_root, server_name, nginx_root, user 等）
    ※ 読み込みは lib/nginx_utils.load_settings() を通じて行い、
       `.streamlit/secrets.toml` の [env].location / 環境変数 を考慮する

出力:
  - <nginx_root>/nginx.conf
"""

from __future__ import annotations
from pathlib import Path
import argparse
import shutil
import sys

# --- ここを追加 ---
APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    print("ERROR: Python 3.11+ が必要です（tomllib が見つかりません）。", file=sys.stderr)
    sys.exit(1)

# 🔧 追加：nginx_utils から設定ローダとパス解決を利用
from lib.nginx_utils import load_settings, resolve_nginx_conf_path, SETTINGS_FILE

NGINX_TOML = Path(".streamlit/nginx.toml")

# --- テンプレート ---
HTTP_TEMPLATE = """# ===============================================
# nginx.conf（AUTO-GENERATED — do not edit manually）
# Generated from .streamlit/nginx.toml + .streamlit/settings.toml(+secrets)
# ===============================================

{user_line}
worker_processes  1;

events {
    worker_connections  1024;
}

http {
    include       mime.types;
    default_type  application/octet-stream;

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

    server {
        listen       80;
        server_name  {server_name};

        # ポータル（静的HTML）
        root   {index_root};
        index  index.html;

        # 共通設定（WebSocket, Header, Keep-Alive）
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   X-Forwarded-Host  $host;
        proxy_set_header   X-Forwarded-Port  $server_port;

        proxy_read_timeout 86400;
        proxy_redirect off;
        client_max_body_size 200m;

{location_blocks}

        # エラーページ
        error_page   500 502 503 504  /50x.html;
        location = /50x.html {
            root   /opt/homebrew/var/www/html;
        }
    }
}
"""

# location ブロックは {{ }} を後で { } に戻す
LOCATION_BLOCK = """        # ========================================================
        # {title}（Streamlit on :{port}）
        # ========================================================
        location = /{prefix} {{ return 301 /{prefix}/; }}
        location /{prefix}/ {{
            # Streamlit 側: baseUrlPath = "/{prefix}"
            proxy_pass         http://127.0.0.1:{port};   # ★末尾スラなし！
            proxy_set_header   Upgrade $http_upgrade;
            proxy_set_header   Connection "upgrade";
            proxy_set_header   X-Forwarded-Proto $scheme;
            proxy_buffering    off;
        }}
"""

TITLE_FALLBACKS = {
    "bot": "Bot アプリ",
    "minutes": "Minutes アプリ",
    "doc-manager": "Doc-Manager アプリ",
    "image-maker": "Image-Maker アプリ",
    "command": "Command アプリ",
}

def load_toml(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)

def render_locations(apps: dict) -> str:
    blocks: list[str] = []
    for app_name, cfg in apps.items():
        if not isinstance(cfg, dict):
            continue
        port = cfg.get("port")
        if port is None:
            continue
        if not cfg.get("enabled", True):
            continue
        title = TITLE_FALLBACKS.get(app_name, f"{app_name} アプリ")
        b = (
            LOCATION_BLOCK
            .replace("{title}", title)
            .replace("{prefix}", str(app_name))
            .replace("{port}", str(int(port)))
        )
        b = b.replace("{{", "{").replace("}}", "}")
        blocks.append(b)
    return "\n".join(blocks).rstrip()

def build_body(settings: dict, apps: dict) -> str:
    loc_key = settings["env"]["location"]
    locs = settings["locations"][loc_key]

    index_root = Path(locs["index_root"]).as_posix()
    server_name_value = locs.get("server_name", "_")
    server_name = " ".join(server_name_value) if isinstance(server_name_value, list) else str(server_name_value or "_")

    user_value = str(locs.get("user", "")).strip()
    user_line = f"user {user_value};" if user_value else "# user nobody;"

    location_blocks = render_locations(apps)

    return (
        HTTP_TEMPLATE
        .replace("{user_line}", user_line)
        .replace("{index_root}", index_root)
        .replace("{server_name}", server_name)
        .replace("{location_blocks}", location_blocks)
    )

def write_out(path: Path, text: str, backup: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        bak = path.with_suffix(".conf.bak")
        shutil.copy2(path, bak)
        print(f"バックアップ作成: {bak}")
    path.write_text(text, encoding="utf-8")
    print(f"書き出し完了: {path}")

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate nginx.conf from TOML settings.")
    parser.add_argument("--dry-run", action="store_true", help="ファイルへ書かず、生成内容を標準出力へ出す")
    parser.add_argument("--no-backup", action="store_true", help="既存 nginx.conf のバックアップを作らない")
    args = parser.parse_args(argv)

    # 存在チェック
    if not NGINX_TOML.exists():
        print("ERROR: .streamlit/nginx.toml が見つかりません。", file=sys.stderr)
        return 1
    if not Path(SETTINGS_FILE).exists():
        print(f"ERROR: {SETTINGS_FILE} が見つかりません。", file=sys.stderr)
        return 1

    # ✅ ここが肝：secrets( [env].location ) / 環境変数 / settings を考慮して読込
    settings = load_settings(Path(SETTINGS_FILE))
    apps = load_toml(NGINX_TOML)

    # 出力先決定（nginx_root + nginx.conf を厳密解決）
    out_path = resolve_nginx_conf_path(settings)

    body = build_body(settings, apps)

    if args.dry_run:
        # ★ Streamlit 警告を避けるため、stdout を明示的に flush / 書き込み限定
        sys.stdout.buffer.write(body.encode("utf-8"))
        sys.stdout.flush()
        return 0

    write_out(out_path, body, backup=(not args.no_backup))
    print("\n構文チェック＆再起動：\n  nginx -t -c {}\n  brew services restart nginx".format(out_path))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
