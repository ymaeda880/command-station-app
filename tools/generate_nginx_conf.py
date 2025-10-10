# tools/generate_nginx_conf.py
#!/usr/bin/env python3
"""
nginx.conf 自動生成スクリプト（現行手動 nginx.conf の挙動に準拠）

入力:
  - .streamlit/nginx.toml     … アプリ名 → port / enabled のマッピング
  - .streamlit/settings.toml  … 環境プリセット（index_root, server_name, nginx_root, user 等）

出力:
  - <nginx_root>/nginx.conf

メモ:
  - server_name は配列/文字列どちらも可
  - location = /app → 301 /app/ リダイレクト（末尾スラ統一）
  - proxy_pass は末尾スラなし（現行運用に合わせる）
  - WebSocket/Forwarded/Buffering 等の共通ヘッダは現行に合わせて設定
  - gzip/absolute_redirect/client_max_body_size/error_page も現行に合わせて設定
"""

from __future__ import annotations
from pathlib import Path
import argparse
import shutil
import sys

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    print("ERROR: Python 3.11+ が必要です（tomllib が見つかりません）。", file=sys.stderr)
    sys.exit(1)

NGINX_TOML = Path(".streamlit/nginx.toml")
SETTINGS_TOML = Path(".streamlit/settings.toml")

# --- テンプレート（中括弧 {} はこのプレースホルダのために使用。locationブロックの {} は別でケアする） ---
HTTP_TEMPLATE = """# ===============================================
# nginx.conf（AUTO-GENERATED — do not edit manually）
# Generated from .streamlit/nginx.toml + .streamlit/settings.toml
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

# location ブロックは、Python 置換衝突を避けるために {{ }} で逃がしておき、後で { } に戻す
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
# ↑ LOCATION_BLOCK 内の {{ / }} は、render 後に .replace("{{","{").replace("}}","}") で“本来の {}”へ戻す

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
        enabled = cfg.get("enabled", True)
        if not enabled:
            continue
        title = TITLE_FALLBACKS.get(app_name, f"{app_name} アプリ")
        # まずテンプレ文字列を .replace で埋める（.format は使わない）
        b = (
            LOCATION_BLOCK
            .replace("{title}", title)
            .replace("{prefix}", str(app_name))
            .replace("{port}", str(int(port)))
        )
        # ここでテンプレ中の {{ と }} を単一の { / } に戻す（Nginx 構文の中括弧）
        b = b.replace("{{", "{").replace("}}", "}")
        blocks.append(b)
    return "\n".join(blocks).rstrip()

def build_body(settings: dict, apps: dict) -> str:
    loc_key = settings["env"]["location"]
    locs = settings["locations"][loc_key]

    index_root = Path(locs["index_root"]).as_posix()
    server_name_value = locs.get("server_name", "_")
    # server_name は配列/文字列両対応
    if isinstance(server_name_value, list):
        server_name = " ".join(server_name_value)
    else:
        server_name = str(server_name_value or "_")

    # 追加: 実行ユーザー（未指定ならコメント行）
    user_value = str(locs.get("user", "")).strip()
    user_line = f"user {user_value};" if user_value else "# user nobody;"

    location_blocks = render_locations(apps)

    body = (
        HTTP_TEMPLATE
        .replace("{user_line}", user_line)
        .replace("{index_root}", index_root)
        .replace("{server_name}", server_name)
        .replace("{location_blocks}", location_blocks)
    )
    return body

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

    if not NGINX_TOML.exists() or not SETTINGS_TOML.exists():
        print("ERROR: .streamlit/nginx.toml または .streamlit/settings.toml が見つかりません。", file=sys.stderr)
        return 1

    apps = load_toml(NGINX_TOML)
    settings = load_toml(SETTINGS_TOML)

    # 出力先決定
    loc_key = settings["env"]["location"]
    nginx_root = Path(settings["locations"][loc_key]["nginx_root"])
    out_path = nginx_root / "nginx.conf"

    body = build_body(settings, apps)

    if args.dry_run:
        # そのまま標準出力へ（差分プレビュー用）
        sys.stdout.write(body)
        return 0

    write_out(out_path, body, backup=(not args.no_backup))
    print("\n構文チェック＆再起動：\n  nginx -t -c {}\n  brew services restart nginx".format(out_path))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
