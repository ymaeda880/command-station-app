# lib/nginx_utils_https.py
from __future__ import annotations
from pathlib import Path
import sys

# 既存の HTTP 汎用ユーティリティを再利用
from lib.nginx_utils import (  # type: ignore
    SETTINGS_FILE,
    load_settings,
    resolve_nginx_conf_path,
    stat_text,
    atomic_write,
    make_backup,
    run_cmd,
    diff_current_vs_generated,
    current_head,
    nginx_test,
)

# HTTPS 用の最小テンプレート（初回編集時に出すプレースホルダ）
MINIMAL_HTTPS_NGINX_CONF = """\
# minimal https nginx.conf (placeholder)
# このファイルは空テンプレです。右側エディタで編集するか、下の「生成」から自動出力してください。
http {
    include       mime.types;
    default_type  application/octet-stream;
    gzip on;
    gzip_types text/plain text/css application/javascript application/json application/xml text/xml application/font-woff2 image/svg+xml;
    gzip_min_length 1024;
    gzip_vary on;
    gzip_proxied any;

    sendfile on;
    keepalive_timeout 65;

    absolute_redirect off;
    server_tokens off;

    client_max_body_size 200m;

    map $http_upgrade $connection_upgrade {
        default upgrade;
        ''      close;
    }

    proxy_http_version 1.1;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_set_header   X-Forwarded-Host  $host;
    proxy_set_header   X-Forwarded-Port  $server_port;
    proxy_redirect     off;
    proxy_read_timeout 86400;

    server { listen 80; return 301 https://$host$request_uri; }

    server {
        listen 443 ssl http2;
        # server_name は生成器で注入されます
        # ssl_certificate     ...;
        # ssl_certificate_key ...;
    }
}
""".rstrip() + "\n"


def generate_conf_https_dry_run() -> tuple[int, str]:
    """
    HTTPS用生成スクリプトの dry-run。
    戻り値: (return_code, stdout+stderr)
    """
    return run_cmd([sys.executable, "tools/generate_nginx_conf_https.py", "--dry-run"])
