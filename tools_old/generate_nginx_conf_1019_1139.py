# tools/generate_nginx_conf.py
#!/usr/bin/env python3
"""
nginx.conf 自動生成スクリプト（AUTO-GENERATED）

入力:
  - .streamlit/nginx.toml     … アプリ定義（app → {port, enabled, base, sso_issuer}）
  - .streamlit/settings.toml  … 環境プリセット（index_root, server_name, nginx_root, user 等）
    ※ 読み込みは lib/nginx_utils.load_settings() を通し、secrets と環境変数を考慮

出力:
  - <nginx_root>/nginx.conf
"""

from __future__ import annotations
from pathlib import Path
import argparse
import shutil
import sys

# projects配下のlibをimportできるように（本スクリプトの1つ上がアプリルート想定）
APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    print("ERROR: Python 3.11+ が必要です（tomllib が見つかりません）", file=sys.stderr)
    sys.exit(1)

from lib.nginx_utils import load_settings, resolve_nginx_conf_path, SETTINGS_FILE

NGINX_TOML = Path(".streamlit/nginx.toml")

# ---------------- Templates ----------------
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
        location = /50x.html {{
            root   /opt/homebrew/var/www/html;
        }}
    }}
}}
"""

# {{ }} は format() 後に実 { } になる
LOCATION_BLOCK = """        # ========================================================
        # {title}（Streamlit on :{port}）
        # ========================================================
        location = /{prefix} {{ return 301 /{prefix}/; }}
        location /{prefix}/ {{
            # Streamlit 側: baseUrlPath = "/{base}"
            proxy_pass         http://127.0.0.1:{port};   # ★末尾スラなし！
            proxy_set_header   Upgrade $http_upgrade;
            proxy_set_header   Connection "upgrade";
            proxy_set_header   X-Forwarded-Proto $scheme;
            proxy_buffering    off;
{extra_cookie_lines}
        }}
"""

TITLE_FALLBACKS = {
    "bot": "Bot アプリ",
    "minutes": "Minutes アプリ",
    "doc-manager": "Doc-Manager アプリ",
    "image-maker": "Image-Maker アプリ",
    "command": "Command アプリ",
    "auth_portal": "Auth-Portal（SSO発行）",
}

# ---------------- Helpers ----------------
def load_toml(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)

def _norm_base(app_name: str, cfg: dict) -> tuple[str, str]:
    """
    nginx.toml の base を正規化。
      - 指定なし → "/{app_name}"
      - 先頭/は必ず付与、末尾/は付与しない
    返り値: (base, prefix) 例: ("/auth_portal", "auth_portal")
    """
    raw = cfg.get("base") or f"/{app_name}"
    base = "/" + str(raw).strip().strip("/")
    prefix = base.strip("/")
    return base, prefix

def _sso_cookie_lines(base: str, is_sso_issuer: bool) -> str:
    """
    SSO発行アプリのみ Cookie Path を / に正規化。
    base == "/" の場合は不要なので出力しない。
    """
    if not is_sso_issuer or base == "/":
        return ""
    # 末尾スラあり/なし双方に対応
    return (
        "            proxy_pass_header  Set-Cookie;\n"
        f"            proxy_cookie_path  {base}/ \"/; SameSite=Lax; HttpOnly\";\n"
        f"            proxy_cookie_path  {base}  \"/; SameSite=Lax; HttpOnly\";"
    )

def render_locations(apps: dict) -> str:
    blocks: list[str] = []
    # 安定した出力のためキーでソート
    for app_name, cfg in sorted(apps.items(), key=lambda x: x[0]):
        if not isinstance(cfg, dict):
            continue
        if not cfg.get("enabled", True):
            continue
        port = cfg.get("port")
        if port is None:
            continue

        title = TITLE_FALLBACKS.get(app_name, f"{app_name} アプリ")
        base, prefix = _norm_base(app_name, cfg)
        extra_cookie_lines = _sso_cookie_lines(base, bool(cfg.get("sso_issuer")))

        block = LOCATION_BLOCK.format(
            title=title,
            port=int(port),
            prefix=prefix,
            base=prefix,  # コメント用表示（"/{base}"）
            extra_cookie_lines=extra_cookie_lines,
        )
        blocks.append(block)
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

    body = HTTP_TEMPLATE.format(
        user_line=user_line,
        index_root=index_root,
        server_name=server_name,
        location_blocks=location_blocks,
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

# ---------------- Main ----------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate nginx.conf from TOML settings.")
    parser.add_argument("--dry-run", action="store_true", help="ファイルへ書かず、生成内容を標準出力へ出す")
    parser.add_argument("--no-backup", action="store_true", help="既存 nginx.conf のバックアップを作らない")
    args = parser.parse_args(argv)

    if not NGINX_TOML.exists():
        print("ERROR: .streamlit/nginx.toml が見つかりません。", file=sys.stderr)
        return 1
    if not Path(SETTINGS_FILE).exists():
        print(f"ERROR: {SETTINGS_FILE} が見つかりません。", file=sys.stderr)
        return 1

    settings = load_settings(Path(SETTINGS_FILE))
    apps = load_toml(NGINX_TOML)

    out_path = resolve_nginx_conf_path(settings)
    body = build_body(settings, apps)

    if args.dry_run:
        sys.stdout.buffer.write(body.encode("utf-8"))
        sys.stdout.flush()
        return 0

    write_out(out_path, body, backup=(not args.no_backup))
    print("\n構文チェック＆再起動：\n  nginx -t -c {}\n  brew services restart nginx".format(out_path))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
