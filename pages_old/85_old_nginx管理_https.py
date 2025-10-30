# pages/80_nginx管理_https.py
# ============================================================
# 🧩 nginx 管理 — SSO(auth_portal) + HTTPS 対応版（“.local” 自動対応）
# - ボタンで挿入したスニペットを DRY-RUN にも反映 → 差分で確認できる
# - server/map は必ず http{} の内側に挿入
# - proxy_pass は末尾スラ無しに統一（URI書き換え事故防止）
# ============================================================

from __future__ import annotations
from pathlib import Path
import sys, re
import toml
import streamlit as st

try:
    import tomllib  # 3.11+
except Exception:
    import tomli as tomllib  # 3.10-

from lib.nginx_utils import (
    SETTINGS_FILE, MINIMAL_NGINX_CONF,
    load_settings, resolve_nginx_conf_path, stat_text,
    atomic_write, make_backup, run_cmd,
    generate_conf_dry_run, diff_current_vs_generated,
    nginx_test, brew_restart
)

st.set_page_config(page_title="nginx 管理 (SSO+HTTPS / .local + 差分反映)", page_icon="🧩", layout="wide")
st.title("🧩 nginx 管理 — SSO(auth_portal) + HTTPS（“.local” 自動対応 & 差分に反映）")

# ========== 小ユーティリティ ==========
def _get_editor_text() -> str:
    return st.session_state.get("nginx_editor", "")

def _set_editor_text(text: str) -> None:
    st.session_state["nginx_editor"] = text

def _indent(block: str, n_spaces: int) -> str:
    pad = " " * n_spaces
    return "\n".join((pad + ln if ln.strip() else ln) for ln in block.splitlines())

def _inject_into_http(editor_text: str, block: str) -> str:
    """
    editor_text 内の http { ... } の『閉じカッコ直前』に block を挿入する。
    見つからなければ末尾に追記（壊さないフォールバック）。
    """
    m = re.search(r'(http\s*\{)([\s\S]*)(\}\s*)$', editor_text)
    if m:
        head, body, tail = m.group(1), m.group(2), m.group(3)
        ins = ("\n" if (body and not body.endswith("\n")) else "") + block.strip() + "\n"
        return head + body + ins + tail
    # フォールバック
    return editor_text + ("\n" if not editor_text.endswith("\n") else "") + block.strip() + "\n"

# ========== 設定ロード ==========
try:
    settings = load_settings(Path(SETTINGS_FILE))
    conf_path = resolve_nginx_conf_path(settings)
except Exception as e:
    st.error(f"settings.toml の読み込み／解決に失敗しました: {e}")
    st.stop()

env_name = (settings.get("env") or {}).get("location") or "Home"
try:
    loc = settings["locations"][env_name]
except KeyError:
    st.error(f"settings.toml に環境 '{env_name}' が見つかりません。")
    st.stop()

# .local 名の自動追加（候補）
base_server_names: list[str] = loc.get("server_name", []) or []
local_host_name = (loc.get("local_host_name") or "").strip() or None
mdns_fqdn = f"{local_host_name}.local" if local_host_name else None
server_names_plus: list[str] = list(base_server_names)
if mdns_fqdn and mdns_fqdn not in server_names_plus:
    server_names_plus.append(mdns_fqdn)

CURRENT_USER = loc.get("user", "")
NGINX_TOML   = Path(".streamlit/nginx.toml")

st.caption(f"🖥 現在の環境: **{env_name}**　👤 ユーザー: **{CURRENT_USER or '(未設定)'}**")
st.caption("🌐 server_name 候補: " + (", ".join(server_names_plus) if server_names_plus else "(なし)"))
if mdns_fqdn:
    st.caption(f"🔤 検出された .local 名: **{mdns_fqdn}**（選択肢に自動追加）")

colA, colB = st.columns([2, 3])

# ========== 左：基本 ==========
with colA:
    st.subheader("設定ファイルとパス")
    st.code(
        f"settings:  {Path(SETTINGS_FILE).resolve()}\n"
        f"nginx_root: {conf_path.parent}\n"
        f"nginx.conf: {conf_path}\n"
        f"nginx.toml: {NGINX_TOML.resolve()}",
        language="bash",
    )

    st.subheader("nginx.conf 情報")
    st.text(stat_text(conf_path))

    st.subheader("操作")
    if st.button("⚙️ 構文チェック（nginx -t -c ...）", type="primary"):
        code, out = nginx_test(conf_path)
        (st.success if code == 0 else st.error)("構文チェック " + ("✅" if code == 0 else "❌"))
        st.code(out or "(no output)", height=420)

    if st.button("🔄 再起動（brew services restart nginx）"):
        code, out = brew_restart()
        (st.success if code == 0 else st.error)("再起動 " + ("✅" if code == 0 else "❌"))
        st.code(out or "(no output)", height=360)

    st.caption("※ 権限エラー時は `sudo nginx -t -c ...` / `sudo brew services restart nginx` を手動実行してください。")

    # SSO発行アプリの検出
    st.markdown("---")
    st.subheader("🔐 SSO 設定チェック（.streamlit/nginx.toml）")

    apps: dict[str, dict] = {}
    sso_app: tuple[str, str, int] | None = None  # (app, base, port)
    if not NGINX_TOML.exists():
        st.warning(".streamlit/nginx.toml が見つかりません。アプリ一覧の自動反映はスキップします。")
    else:
        try:
            nginx_cfg = toml.loads(NGINX_TOML.read_text(encoding="utf-8"))
            for app, cfg in nginx_cfg.items():
                if not isinstance(cfg, dict) or cfg.get("enabled", True) is False:
                    continue
                port = int(cfg.get("port", 0)) or None
                base = cfg.get("base") or f"/{app}"
                apps[app] = {"port": port, "base": base}
                if cfg.get("sso_issuer") is True and port:
                    sso_app = (app, base, port)
        except Exception as e:
            st.error(f"nginx.toml の読み込みに失敗しました: {e}")

    if sso_app:
        app, base, port = sso_app
        st.success(f"SSO発行アプリ: {app} (base={base}, port={port})")
        st.caption("このアプリの location にだけ `proxy_cookie_path <base>/ \"/; SameSite=Lax; HttpOnly\";` を出力します。")
    else:
        st.info("sso_issuer=true のアプリが特定できませんでした。右側のUIで手動選択できます。")

# ========== 右：編集 & 生成 ==========
with colB:
    st.subheader("nginx.conf（編集）")

    if conf_path.exists():
        try:
            content = conf_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = conf_path.read_text(encoding="utf-8", errors="replace")
    else:
        content = MINIMAL_NGINX_CONF
        st.info("nginx.conf が存在しないため、最小テンプレートを表示しています。保存すると新規作成されます。")

    if "nginx_orig" not in st.session_state or st.session_state.get("nginx_path") != str(conf_path):
        st.session_state["nginx_orig"] = content
        st.session_state["nginx_path"] = str(conf_path)

    # --- HTTPS スニペット生成（UI選択 → セッションに記録 → DRY-RUNにパッチ） ---
    with st.expander("🔒 HTTPS 設定（serverブロック生成）", expanded=True):
        c1, c2 = st.columns(2)

        with c1:
            options_names = server_names_plus or ["localhost"]
            default_names = server_names_plus or ["localhost"]
            selected_names = st.multiselect(
                "server_name（複数可 / 例: 'home.local' と 'localhost'）",
                options=options_names,
                default=default_names
            )
            server_name_str = " ".join(selected_names) if selected_names else "localhost"

            primary_cn = (selected_names[0] if selected_names else "localhost")
            cert_file = st.text_input("ssl_certificate（.crt）", value=str(Path.home() / f"ssl/certs/{primary_cn}.crt"))
            key_file  = st.text_input("ssl_certificate_key（.key）", value=str(Path.home() / f"ssl/private/{primary_cn}.key"))
            hsts      = st.checkbox("HSTS を付与する（自己署名中は推奨しません）", value=False)

        app_names = sorted(apps.keys())
        with c2:
            root_app = app_names[0] if app_names else "(未定義)"
            root_up  = f"http://127.0.0.1:{apps[root_app]['port']}" if root_app in apps and apps[root_app]["port"] else "http://127.0.0.1:8501"

            default_auth = (sso_app[0] if sso_app else root_app)
            auth_idx = app_names.index(default_auth) if default_auth in app_names else 0
            auth_app = app_names[auth_idx] if app_names else "(未定義)"
            auth_base = apps[auth_app]["base"] if auth_app in apps else "/auth_portal"
            auth_up   = f"http://127.0.0.1:{apps[auth_app]['port']}" if auth_app in apps and apps[auth_app]["port"] else "http://127.0.0.1:8591"

            extra_locations = st.text_area(
                "追加の location（任意）",
                value="",
                height=180,
                placeholder=(
                    "location /bot/ {\n"
                    "    proxy_pass http://127.0.0.1:8502;\n"
                    "    proxy_pass_header Set-Cookie;\n"
                    "    proxy_buffering off;\n"
                    "}\n"
                )
            )

        colh2, colh3, colh4 = st.columns(3)

        # --- セッションに「パッチ」を記録（差分にも反映） ---
        def remember_https_inputs(kind: str):
            """ボタン押下時に、DRY-RUNへ適用するパッチをセッションに記録"""
            st.session_state.setdefault("patches", {})

            if kind == "map":
                st.session_state["patches"]["map"] = True
                st.toast("map を差分生成に反映します。")
            elif kind == "redirect":
                st.session_state["patches"]["redirect"] = {
                    "server_name": server_name_str,
                }
                st.toast("HTTP→HTTPS リダイレクトを差分生成に反映します。")
            elif kind == "https":
                st.session_state["patches"]["https"] = {
                    "server_name": server_name_str,
                    "cert": cert_file,
                    "key": key_file,
                    "hsts": bool(hsts),
                    "auth_base": auth_base.rstrip("/"),
                    "auth_up": auth_up,
                    "root_up": root_up,
                    "extra": extra_locations.strip(),
                }
                st.toast("HTTPS server(443) を差分生成に反映します。")

        # map（http{} 直下）
        map_snippet = (
            "map $http_upgrade $connection_upgrade {\n"
            "    default upgrade;\n"
            "    ''      close;\n"
            "}\n"
        )
        with colh2:
            if st.button("🧩 map（http{} 直下）を挿入"):
                txt = _get_editor_text()
                if "map $http_upgrade $connection_upgrade" not in txt:
                    txt2 = _inject_into_http(txt, _indent(map_snippet, 4))
                    _set_editor_text(txt2)
                remember_https_inputs("map")

        # HTTP→HTTPS リダイレクト
        redirect_server = (
f"""server {{
    listen 80;
    server_name {server_name_str};
    return 301 https://$host$request_uri;
}}"""
        )
        with colh3:
            if st.button("➡️ HTTP→HTTPS リダイレクトを挿入"):
                txt = _get_editor_text()
                txt2 = _inject_into_http(txt, _indent(redirect_server, 8))
                _set_editor_text(txt2)
                remember_https_inputs("redirect")

        # HTTPS server（443）
        hsts_line = '    add_header Strict-Transport-Security "max-age=31536000" always;\n'
        https_server = (
f"""server {{
    listen 443 ssl http2;
    server_name {server_name_str};

    ssl_certificate     {cert_file};
    ssl_certificate_key {key_file};

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
{hsts_line if hsts else ""}    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;

    # ✴︎ SSO発行アプリ
    location {auth_base.rstrip('/')}/ {{
        proxy_pass {auth_up};
        proxy_pass_header Set-Cookie;
        proxy_cookie_path {auth_base.rstrip('/')}/ "/; SameSite=Lax; HttpOnly";
        proxy_buffering off;
    }}

    # ルートに割当
    location / {{
        proxy_pass {root_up};
        proxy_pass_header Set-Cookie;
        proxy_buffering off;
    }}

    # 追加 location
    {extra_locations.strip()}
}}"""
        )
        with colh4:
            if st.button("🔒 HTTPS server（443）を挿入"):
                txt = _get_editor_text()
                txt2 = _inject_into_http(txt, _indent(https_server, 8))
                _set_editor_text(txt2)
                remember_https_inputs("https")

    # ---- エディタ本体 ----
    text = st.text_area("ファイル内容", value=content, height=560, key="nginx_editor", placeholder="# ここに nginx.conf を編集")
    changed = (text != st.session_state["nginx_orig"])
    st.caption("変更状態: " + ("🟡 未保存の変更あり" if changed else "⚪ 変更なし"))

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("📥 再読み込み（破棄）"):
            st.session_state.pop("nginx_orig", None)
            st.session_state.pop("nginx_editor", None)
            st.session_state.pop("patches", None)
            st.rerun()

    with c2:
        if conf_path.exists():
            try:
                data = conf_path.read_bytes()
                st.download_button("🧷 現在の nginx.conf をダウンロード", data=data, file_name="nginx.conf.backup", mime="text/plain")
            except Exception as e:
                st.warning(f"ダウンロード準備に失敗: {e}")

    with c3:
        if st.button("💾 保存（バックアップ作成→原子書き込み）", type="primary"):
            try:
                conf_path.parent.mkdir(parents=True, exist_ok=True)
                if conf_path.exists():
                    backup = make_backup(conf_path)
                    st.success(f"バックアップ作成: {backup.name}")
                atomic_write(conf_path, text)
                st.session_state["nginx_orig"] = text
                st.success("保存しました ✅")
                code, out = nginx_test(conf_path)
                (st.info if code == 0 else st.error)("保存後の構文チェック: " + ("OK ✅" if code == 0 else "エラー ❌"))
                st.code(out or "(no output)", height=420)
            except PermissionError as e:
                st.error(f"権限エラーで保存できませんでした: {e}")
                st.caption(f"`sudo cp ./nginx.conf {conf_path}` / `sudo chown $(whoami) {conf_path}`")
            except Exception as e:
                st.error(f"保存に失敗しました: {e}")

# ========== 補足 ==========
with st.expander("ℹ️ 補足：よくあるトラブルと対処"):
    st.markdown(
        """
- **構文エラー**: `http { ... }` に `include mime.types;` がない、`server { ... }` の括弧抜け、`listen` 重複など。  
- **ポート競合**: 既に他プロセスが `:80/:443` を使用していると起動に失敗。`lsof -i :80`, `lsof -i :443` で確認。  
- **権限**: `/opt/homebrew/etc/nginx` は環境により要権限。  
- **SSO(cookie_path)**: `sso_issuer=true` の location のみに `proxy_cookie_path <base>/ "/; SameSite=Lax; HttpOnly";` を出す。  
- **WebSocket**: `map $http_upgrade $connection_upgrade` + `proxy_set_header Upgrade/Connection` を忘れない。  
"""
    )

# ========== DRY-RUN（差分にパッチを反映） ==========
st.markdown("---")
st.header("🧪 自動生成（DRY-RUNに“挿入パッチ”を反映）")

def apply_patches_to_generated(gen: str) -> str:
    """generate の出力に対し、sessionの patches を http{} の末尾に差し込む"""
    patches = st.session_state.get("patches") or {}
    if not patches:
        return gen

    inserts = []

    # map
    if patches.get("map"):
        inserts.append(_indent(
            "map $http_upgrade $connection_upgrade {\n"
            "    default upgrade;\n"
            "    ''      close;\n"
            "}\n", 4
        ))

    # redirect
    if "redirect" in patches:
        sn = patches["redirect"]["server_name"]
        inserts.append(_indent(
f"""server {{
    listen 80;
    server_name {sn};
    return 301 https://$host$request_uri;
}}""", 8
        ))

    # https
    if "https" in patches:
        p = patches["https"]
        hsts_line = '    add_header Strict-Transport-Security "max-age=31536000" always;\n' if p.get("hsts") else ""
        extr = (p.get("extra") or "").rstrip()
        inserts.append(_indent(
f"""server {{
    listen 443 ssl http2;
    server_name {p['server_name']};

    ssl_certificate     {p['cert']};
    ssl_certificate_key {p['key']};

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
{hsts_line}    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;

    # ✴︎ SSO発行アプリ
    location {p['auth_base']}/ {{
        proxy_pass {p['auth_up']};
        proxy_pass_header Set-Cookie;
        proxy_cookie_path {p['auth_base']}/ "/; SameSite=Lax; HttpOnly";
        proxy_buffering off;
    }}

    # ルートに割当
    location / {{
        proxy_pass {p['root_up']};
        proxy_pass_header Set-Cookie;
        proxy_buffering off;
    }}

    # 追加 location
    {extr}
}}""", 8
        ))

    if not inserts:
        return gen

    # http{} の閉じカッコ直前にまとめて注入
    m = re.search(r'(http\s*\{)([\s\S]*)(\}\s*)$', gen)
    if m:
        head, body, tail = m.group(1), m.group(2), m.group(3)
        return head + body + "\n" + "\n".join(inserts) + "\n" + tail

    # フォールバック：末尾に足す
    return gen + "\n" + "\n".join(inserts) + "\n"

with st.expander("🔧 生成スクリプト実行（.streamlit/nginx.toml + settings.toml → nginx.conf）", expanded=True):
    st.subheader("🔍 差分プレビュー（生成内容 vs 現行 nginx.conf）")
    code, gen_text_raw = generate_conf_dry_run()
    if code != 0:
        st.error("生成スクリプト（dry-run）が失敗しました ❌")
        st.code(gen_text_raw or "(no output)")
    else:
        # “挿入パッチ” を適用 → 差分に反映
        generated_text = apply_patches_to_generated(gen_text_raw or "")

        current_text = conf_path.read_text(encoding="utf-8", errors="replace") if conf_path.exists() else ""
        diff_txt = diff_current_vs_generated(current_text, generated_text or "")

        # SSO cookie_path 検証
        sso_ok_msg = ""; sso_warn = False
        try:
            nginx_cfg2 = toml.loads(NGINX_TOML.read_text(encoding="utf-8")) if NGINX_TOML.exists() else {}
        except Exception:
            nginx_cfg2 = {}
        base_auth = None
        for app, cfg in (nginx_cfg2 or {}).items():
            if isinstance(cfg, dict) and cfg.get("sso_issuer") is True:
                base_auth = cfg.get("base") or f"/{app}"; break
        if base_auth:
            m2 = re.search(rf"location\s+{re.escape(base_auth)}/\s*\{{[\s\S]*?\}}", generated_text or "")
            if m2 and "proxy_cookie_path" in m2.group(0):
                sso_ok_msg = f"✅ `location {base_auth}/` に `proxy_cookie_path` が出力されています。"
            else:
                sso_ok_msg = f"⚠️ `location {base_auth}/` に `proxy_cookie_path` が見つかりません。"; sso_warn = True
        else:
            sso_ok_msg = "ℹ️ nginx.toml から sso_issuer の base が特定できませんでした。"

        # .local 検証
        mdns_msg = ""; mdns_warn = False
        if mdns_fqdn:
            sn_lines = re.findall(r"server_name\s+([^;]+);", generated_text or "")
            if any(mdns_fqdn in ln for ln in sn_lines):
                mdns_msg = f"✅ 生成結果の `server_name` に **{mdns_fqdn}** が含まれています。"
            else:
                mdns_msg = f"⚠️ 生成結果の `server_name` に **{mdns_fqdn}** が含まれていません。"; mdns_warn = True
        else:
            mdns_msg = "ℹ️ `local_host_name` が未設定のため、.local 検証をスキップしました。"

        if diff_txt:
            t1, t2, t3, t4 = st.tabs(["差分（unified diff）", "生成プレビュー（パッチ適用後）", "SSO検証", ".local検証"])
            with t1: st.code(diff_txt, language="diff")
            with t2: st.code(generated_text, language="nginx")
            with t3: (st.warning if sso_warn else st.success)(sso_ok_msg)
            with t4: (st.warning if mdns_warn else st.info)(mdns_msg)
        else:
            st.success("差分はありません（生成内容と現行 nginx.conf は同一です／パッチ適用後）")
            if sso_ok_msg: (st.warning if sso_warn else st.info)(sso_ok_msg)
            if mdns_msg:   (st.warning if mdns_warn else st.info)(mdns_msg)

    st.markdown("---")
    st.caption("このボタンは **実際に nginx.conf に書き込み**、その後 **構文チェックのみ** 実行します。")
    confirm = st.checkbox("書き込みに同意する（バックアップ作成→生成→構文チェック）", value=False)

    if st.button("🧪 生成 → 🔎 構文チェック（書き込みあり）", disabled=not confirm, type="primary"):
        code1, out1 = run_cmd([sys.executable, "tools/generate_nginx_conf.py"])
        st.code(out1 or "(no output)")
        if code1 != 0:
            st.error("生成に失敗しました。")
        else:
            code2, out2 = nginx_test(conf_path)
            (st.success if code2 == 0 else st.error)("構文チェック " + ("OK ✅" if code2 == 0 else "NG ❌"))
            st.code(out2 or "(no output)")
