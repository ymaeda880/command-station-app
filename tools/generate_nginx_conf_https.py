# ============================================================
# tools/generate_nginx_conf_https.py
# HTTPS nginx.conf 自動生成スクリプト (.local / TLS 自動注入)
# ============================================================

from __future__ import annotations

# --- sys.path bootstrap: `lib/...` を確実に import 可能にする ---
from pathlib import Path
import sys, argparse
from typing import Dict, Any, List, Tuple

def _add_project_root_to_syspath() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent,      # <project_root>
        here.parent,
        here.parent.parent.parent
    ]
    for base in candidates:
        if base and (base / "lib").exists():
            if str(base) not in sys.path:
                sys.path.insert(0, str(base))
            return base
    return here.parent

PROJECT_ROOT = _add_project_root_to_syspath()

# --- ここから通常 import ---
import toml  # pip install toml

from lib.nginx_utils import (  # type: ignore
    SETTINGS_FILE,
    load_settings,
    resolve_nginx_conf_path,
    atomic_write,
)

NGINX_TOML = PROJECT_ROOT / ".streamlit" / "nginx.toml"

# ---------------- ヘルパ ----------------
def _read_toml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return toml.loads(path.read_text(encoding="utf-8"))

def _unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        if not x:
            continue
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def _resolve_env_casefold(env_name_hint: str | None, locations: Dict[str, Any]) -> str | None:
    if not env_name_hint or not isinstance(locations, dict) or not locations:
        return None
    if env_name_hint in locations:
        return env_name_hint
    hint = env_name_hint.casefold()
    for k in locations.keys():
        if k.casefold() == hint:
            return k
    return None

def _select_env_loc(settings: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    locs = settings.get("locations") or {}
    env_hint = (settings.get("env") or {}).get("location")
    env_name = _resolve_env_casefold(env_hint, locs) or (next(iter(locs.keys())) if locs else None)
    if not env_name:
        raise RuntimeError("env.location を決定できません")
    env_loc = locs.get(env_name) or {}
    if not isinstance(env_loc, dict):
        raise RuntimeError(f"locations.{env_name} セクションが見つかりません")
    return env_name, env_loc

def _server_names(env_loc: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    base = env_loc.get("server_name") or []
    if isinstance(base, list):
        names.extend([str(x).strip() for x in base if str(x).strip()])
    local_host = (env_loc.get("local_host_name") or "").strip()
    if local_host:
        names.append(f"{local_host}.local")
    extras = env_loc.get("extra_server_names") or []
    if isinstance(extras, list):
        names.extend([str(x).strip() for x in extras if str(x).strip()])
    names = _unique_keep_order(names)
    return names or ["localhost"]

def _tls_paths(env_loc: Dict[str, Any], server_names: List[str]) -> Tuple[str, str]:
    cert = (env_loc.get("tls_cert_file") or "").strip()
    key  = (env_loc.get("tls_key_file")  or "").strip()
    if cert and key:
        return cert, key
    base_cn = server_names[0] if server_names else "localhost"
    home = Path.home()
    cert_path = str((home / "ssl" / "certs"   / f"{base_cn}.crt").expanduser())
    key_path  = str((home / "ssl" / "private" / f"{base_cn}.key").expanduser())
    return cert_path, key_path

def _detect_sso_app(nginx_cfg: Dict[str, Any]) -> Dict[str, Any] | None:
    for app, cfg in (nginx_cfg or {}).items():
        if isinstance(cfg, dict) and cfg.get("enabled", True) and cfg.get("sso_issuer") is True:
            return {"name": app, "base": cfg.get("base") or f"/{app}", "port": cfg.get("port")}
    return None

def _enabled_apps(nginx_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for app, cfg in (nginx_cfg or {}).items():
        if not isinstance(cfg, dict):
            continue
        if cfg.get("enabled", True) is False:
            continue
        base = cfg.get("base") or f"/{app}"
        port = cfg.get("port")
        out.append({"name": app, "base": base, "port": port})
    return out

def _gen_locations(apps: List[Dict[str, Any]], sso_name: str | None) -> str:
    """
    各アプリの location を組み立てる（末尾スラ無し proxy_pass, WebSocket, buffering off）。
    auth_portal（SSO発行）は除外。
    """
    blocks: List[str] = []
    for a in apps:
        name, base, port = a["name"], a["base"], a["port"]
        if name == sso_name or not port:
            continue
        s = (
            "            location = " + base + " { return 301 " + base + "/; }\n"
            "            location " + base + "/ {\n"
            "                proxy_pass http://127.0.0.1:" + str(port) + ";\n"
            "                proxy_set_header Upgrade $http_upgrade;\n"
            "                proxy_set_header Connection $connection_upgrade;\n"
            "                proxy_buffering off;\n"
            "            }\n"
        )
        blocks.append(s.rstrip())  # ← 文字列に rstrip() をかけてから append する
    return "\n\n".join(blocks)

def _render_conf(
    server_names: List[str],
    tls_cert_file: str,
    tls_key_file: str,
    nginx_cfg: Dict[str, Any],
) -> str:
    names_line = " ".join(server_names)

    sso = _detect_sso_app(nginx_cfg)
    apps = _enabled_apps(nginx_cfg)

    # SSO ブロック（ダブルクォート・1行固定）
    sso_block = ""
    root_block = ""
    if sso and sso.get("port"):
        sso_base = sso["base"]
        sso_port = sso["port"]
        sso_block = (
            "            # SSO issuer\n"
            "            location = " + sso_base + " { return 301 " + sso_base + "/; }\n"
            "            location " + sso_base + "/ {\n"
            "                proxy_pass http://127.0.0.1:" + str(sso_port) + ";\n"
            "                proxy_set_header Upgrade $http_upgrade;\n"
            "                proxy_set_header Connection $connection_upgrade;\n"
            "                proxy_buffering off;\n"
            "                proxy_pass_header  Set-Cookie;\n"
            "                proxy_cookie_path  " + sso_base + "/ \"/; SameSite=Lax; HttpOnly\";\n"
            "                proxy_cookie_path  " + sso_base + "  \"/; SameSite=Lax; HttpOnly\";\n"
            "            }\n"
        ).rstrip()
        root_block = (
            "            # Route / to SSO\n"
            "            location / {\n"
            "                proxy_pass http://127.0.0.1:" + str(sso_port) + ";\n"
            "                proxy_set_header Upgrade $http_upgrade;\n"
            "                proxy_set_header Connection $connection_upgrade;\n"
            "                proxy_buffering off;\n"
            "                proxy_pass_header Set-Cookie;\n"
            "            }\n"
        ).rstrip()

    other_locations = _gen_locations(apps, sso_name=(sso["name"] if sso else None))

    tls_lines = [
        f"ssl_certificate     {tls_cert_file};",
        f"ssl_certificate_key {tls_key_file};",
        "ssl_protocols TLSv1.2 TLSv1.3;",
        "ssl_prefer_server_ciphers on;",
    ]
    tls_block = "                " + "\n                ".join(tls_lines)


    conf = (
        "worker_processes auto;\n"
        "events {\n"
        "    worker_connections 1024;\n"
        "}\n"
        "\n"
        "http {\n"
        "    include       mime.types;\n"
        "    default_type  application/octet-stream;\n"
        "\n"
        "    gzip on;\n"
        "    gzip_types text/plain text/css application/javascript application/json application/xml text/xml application/font-woff2 image/svg+xml;\n"
        "    gzip_min_length 1024;\n"
        "    gzip_vary on;\n"
        "    gzip_proxied any;\n"
        "\n"
        "    sendfile on;\n"
        "    keepalive_timeout 65;\n"
        "\n"
        "    absolute_redirect off;\n"
        "    server_tokens off;\n"
        "\n"
        "    client_max_body_size 200m;\n"
        "\n"
        "    map $http_upgrade $connection_upgrade {\n"
        "        default upgrade;\n"
        "        ''      close;\n"
        "    }\n"
        "\n"
        "    proxy_http_version 1.1;\n"
        "    proxy_set_header   Host              $host;\n"
        "    proxy_set_header   X-Real-IP         $remote_addr;\n"
        "    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;\n"
        "    proxy_set_header   X-Forwarded-Proto $scheme;\n"
        "    proxy_set_header   X-Forwarded-Host  $host;\n"
        "    proxy_set_header   X-Forwarded-Port  $server_port;\n"
        "    proxy_redirect     off;\n"
        "    proxy_read_timeout 86400;\n"
        "\n"
        "    server {\n"
        "        listen 80;\n"
        f"        server_name {names_line};\n"
        "        return 301 https://$host$request_uri;\n"
        "    }\n"
        "\n"
        "    server {\n"
        "        listen 443 ssl;\n"
        "        http2 on;\n"
        f"        server_name {names_line};\n"
        "\n"
        f"{tls_block}\n"
        "\n"
        "        # Optional: static portal at /\n"
        "        # root   /path/to/portal/root;\n"
        "        # index  index.html;\n"
        "        # location = / { try_files /index.html =404; }\n"
        "\n"
        f"{sso_block}\n"
        "\n"
        f"{root_block}\n"
        "\n"
        "        # Streamlit apps\n"
        f"{other_locations}\n"
        "\n"
        "        error_page   500 502 503 504  /50x.html;\n"
        "        location = /50x.html {\n"
        "            root /opt/homebrew/var/www/html;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


    # 余分な空行の整理
    conf = "\n".join(ln.rstrip() for ln in conf.splitlines())
    while "\n\n\n" in conf:
        conf = conf.replace("\n\n\n", "\n\n")
    return conf

# ---------------- main ----------------
def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    settings = load_settings(Path(SETTINGS_FILE))
    env_name, env_loc = _select_env_loc(settings)

    server_names = _server_names(env_loc)
    tls_cert, tls_key = _tls_paths(env_loc, server_names)
    nginx_cfg = _read_toml(NGINX_TOML)

    conf_text = _render_conf(server_names, tls_cert, tls_key, nginx_cfg)

    if args.dry_run:
        sys.stdout.write(conf_text)
        return 0

    conf_path = resolve_nginx_conf_path(settings)
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(conf_path, conf_text)
    print(f"Wrote HTTPS nginx.conf -> {conf_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
