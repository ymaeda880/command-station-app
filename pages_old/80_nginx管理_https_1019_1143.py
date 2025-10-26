# pages/80_nginx管理_https.py
# ============================================================
# 🧩 nginx 管理 — SSO(auth_portal) + HTTPS 対応版
# - 証明書発行UIは別ページへ（82_証明書管理.py）
# - nginx.conf の編集/保存/バックアップ/構文チェック/サービス操作
# - secrets.toml / settings.toml / nginx.toml を読み取り UI を自動初期化
# - SSO発行アプリ(location への proxy_cookie_path 挿入)の検証
# ============================================================

from __future__ import annotations
from pathlib import Path
import sys
import re
import toml
import streamlit as st

# Python 3.11+ なら tomllib、3.10以下なら tomli を使用
try:
    import tomllib  # type: ignore
except Exception:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from lib.nginx_utils import (
    SETTINGS_FILE, MINIMAL_NGINX_CONF,
    load_settings, resolve_nginx_conf_path, stat_text,
    atomic_write, make_backup, run_cmd,
    generate_conf_dry_run, diff_current_vs_generated,
    nginx_test, brew_restart
)

st.set_page_config(page_title="nginx 管理 (SSO対応 + HTTPS)", page_icon="🧩", layout="wide")
st.title("🧩 nginx 管理 — SSO(auth_portal) + HTTPS 対応版")

# ---------------- 共通ユーティリティ ----------------
def _get_editor_text() -> str:
    return st.session_state.get("nginx_editor", "")

def _set_editor_text(text: str) -> None:
    st.session_state["nginx_editor"] = text

def _append_editor_text(snippet: str, sep: str = "\n\n"):
    cur = _get_editor_text()
    if cur and not cur.endswith("\n"):
        cur += "\n"
    _set_editor_text(cur + (sep if cur else "") + snippet)

# ---------------- 設定ロード ----------------
# 1) 現在の環境名（Home / Portable / Prec）
try:
    env_name = st.secrets["env"]["location"]
except Exception:
    env_name = "Home"  # フォールバック

# 2) settings.toml を読み込み（全環境分）
try:
    settings = load_settings(Path(SETTINGS_FILE))
    conf_path = resolve_nginx_conf_path(settings)
except Exception as e:
    st.error(f"settings.toml の読み込み／解決に失敗しました: {e}")
    st.stop()

# 3) 現在環境のロケーション辞書を取得
try:
    loc = settings["locations"][env_name]
except KeyError:
    st.error(f"settings.toml に環境 '{env_name}' が見つかりません。")
    st.stop()

SERVER_NAMES: list[str] = loc.get("server_name", [])
CURRENT_USER = loc.get("user", "")
NGINX_TOML   = Path(".streamlit/nginx.toml")

st.caption(f"🖥 現在の環境: **{env_name}**　👤 ユーザー: **{CURRENT_USER}**")
st.caption("🌐 server_name 候補: " + (", ".join(SERVER_NAMES) if SERVER_NAMES else "(なし)"))

colA, colB = st.columns([2, 3])

# ============================================================
# 左：基本操作
# ============================================================
with colA:
    st.subheader("設定ファイルとパス")
    st.code(
        f"settings: {Path(SETTINGS_FILE).resolve()}\n"
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

    # -------- .streamlit/nginx.toml を読み込み → SSO / アプリ定義を検出 --------
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
                if not isinstance(cfg, dict):
                    continue
                if cfg.get("enabled", True) is False:
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

# ============================================================
# 右：nginx.conf 編集 & 生成（証明書発行UIは無し）
# ============================================================
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

    # ---- HTTPS スニペット生成（証明書発行は別ページへ移動）----
    with st.expander("🔒 HTTPS 設定（serverブロック生成）", expanded=True):
        c1, c2 = st.columns(2)

        # server_name は複数選択可 → join して server_name ディレクティブに展開
        with c1:
            selected_names = st.multiselect(
                "server_name（複数可 / 例: 'home.local' と 'localhost'）",
                options=SERVER_NAMES or ["localhost"],
                default=SERVER_NAMES or ["localhost"]
            )
            server_name_str = " ".join(selected_names)

            # 証明書パスは先頭名を元に提案
            primary_cn = (selected_names[0] if selected_names else "localhost")
            cert_file = st.text_input(
                "ssl_certificate（.crt）",
                value=str(Path.home() / f"ssl/certs/{primary_cn}.crt")
            )
            key_file  = st.text_input(
                "ssl_certificate_key（.key）",
                value=str(Path.home() / f"ssl/private/{primary_cn}.key")
            )
            hsts      = st.checkbox("HSTS を付与する（自己署名中は推奨しません）", value=False)

        # アプリ（root / auth）を nginx.toml から選択 → upstream/base を自動反映
        app_names = sorted(apps.keys())
        with c2:
            # ルート割り当て
            if app_names:
                root_idx = 0
            else:
                app_names = ["(未定義)"]
                root_idx = 0
            root_app = st.selectbox("ルート（/）に割り当てるアプリ", options=app_names, index=root_idx)
            root_up  = f"http://127.0.0.1:{apps[root_app]['port']}/" if root_app in apps and apps[root_app]["port"] else "http://127.0.0.1:8501/"

            # SSO発行アプリ
            default_auth = (sso_app[0] if sso_app else root_app)
            auth_idx = app_names.index(default_auth) if default_auth in app_names else 0
            auth_app = st.selectbox("SSO 発行アプリ", options=app_names, index=auth_idx)
            auth_base = apps[auth_app]["base"] if auth_app in apps else "/auth_portal"
            auth_up   = f"http://127.0.0.1:{apps[auth_app]['port']}/" if auth_app in apps and apps[auth_app]["port"] else "http://127.0.0.1:8591/"

            extra_locations = st.text_area(
                "追加の location（任意）",
                value="",
                height=180,
                placeholder=(
                    "location /bot/ {\n"
                    "    proxy_pass http://127.0.0.1:8502/;\n"
                    "    proxy_pass_header Set-Cookie;\n"
                    "    proxy_buffering off;\n"
                    "}\n"
                )
            )

        colh2, colh3, colh4 = st.columns(3)

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
                if "map $http_upgrade $connection_upgrade" in txt:
                    st.info("既に map 定義が含まれているため追加しませんでした。")
                else:
                    _append_editor_text(map_snippet)
                    st.success("map スニペットを挿入しました。")

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
                if redirect_server in _get_editor_text():
                    st.info("同一のリダイレクト server が既に含まれています。")
                else:
                    _append_editor_text(redirect_server)
                    st.success("HTTP→HTTPS リダイレクト server を挿入しました。")

        # HTTPS server（443）
        hsts_line = '    add_header Strict-Transport-Security "max-age=31536000" always;\n' if hsts else ""
        https_server = (
f"""server {{
    listen 443 ssl http2;
    server_name {server_name_str};

    ssl_certificate     {cert_file};
    ssl_certificate_key {key_file};

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
{hsts_line.rstrip()}

    proxy_set_header Host              $host;
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
                if f"server_name {server_name_str};" in _get_editor_text() and "listen 443" in _get_editor_text():
                    st.warning("同名 server_name の 443 サーバが既に存在する可能性があります。重複に注意してください。")
                _append_editor_text(https_server)
                st.success("HTTPS server（443）ブロックを挿入しました。")

    # ---- エディタ本体（全幅） ----
    text = st.text_area("ファイル内容", value=content, height=560, key="nginx_editor", placeholder="# ここに nginx.conf を編集")
    changed = (text != st.session_state["nginx_orig"])
    st.caption("変更状態: " + ("🟡 未保存の変更あり" if changed else "⚪ 変更なし"))

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("📥 再読み込み（破棄）"):
            st.session_state.pop("nginx_orig", None)
            st.session_state.pop("nginx_editor", None)
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

# ============================================================
# 補足（トラブルシューティング）
# ============================================================
with st.expander("ℹ️ 補足：よくあるトラブルと対処"):
    st.markdown(
        """
- **構文エラー**: `http { ... }` に `include mime.types;` がない、`server { ... }` の括弧抜け、`listen` 重複など。  
- **ポート競合**: 既に他プロセスが `:80/:443` を使用していると起動に失敗。`lsof -i :80`, `lsof -i :443` で確認。  
- **権限**: `/opt/homebrew/etc/nginx` は環境により要権限。  
- **Streamlit 側のURL**: 逆プロキシなら各アプリの `baseUrlPath` を合わせる（例：`/bot`, `/doc-manager`）。  
- **SSO(cookie_path)**: `sso_issuer=true` の location のみに `proxy_cookie_path <base>/ "/; SameSite=Lax; HttpOnly";` を出す。  
- **WebSocket**: `map $http_upgrade $connection_upgrade` + `proxy_set_header Upgrade/Connection` を忘れない。  
"""
    )

# ============================================================
# 自動生成（DRY-RUN）
# ============================================================
st.markdown("---")
st.header("🧪 自動生成（tools/generate_nginx_conf.py を実行）")

with st.expander("ℹ️ 各ボタンの動作説明（help）", expanded=False):
    st.markdown("### 🔍 差分プレビュー（比較のみ／DRY-RUN）")
    st.markdown(
        "- `.streamlit/nginx.toml` と `.streamlit/settings.toml` から、\n"
        "  `tools/generate_nginx_conf.py --dry-run` を実行して **生成内容をプレビュー** します。  \n"
        "- 現行の `nginx.conf` と **unified diff** で比較します。  \n"
        "- **DRY-RUN のためファイルは一切変更されません**。"
    )
    st.markdown("---")
    st.markdown("### ✅ 生成 → 🔎 構文チェック（書き込みあり）")
    st.markdown(
        "- `nginx.conf` を **実際に生成（書き込み）** した後、`nginx -t -c <conf>` で **構文チェックのみ** 行います。  \n"
        "- **再起動は自動では行いません。設定を反映させるには再起動が必要です。**  \n"
        "  - 例: `brew services restart nginx`（Homebrew）"
    )

with st.expander("🔧 生成スクリプト実行（.streamlit/nginx.toml + settings.toml → nginx.conf）", expanded=True):
    st.subheader("🔍 差分プレビュー（生成内容 vs 現行 nginx.conf）")
    code, generated_text = generate_conf_dry_run()
    if code != 0:
        st.error("生成スクリプト（dry-run）が失敗しました ❌")
        st.code(generated_text or "(no output)")
    else:
        current_text = conf_path.read_text(encoding="utf-8", errors="replace") if conf_path.exists() else ""
        diff_txt = diff_current_vs_generated(current_text, generated_text or "")

        # SSO cookie_path 検証
        sso_ok_msg = ""
        sso_warn = False
        try:
            nginx_cfg2 = toml.loads(NGINX_TOML.read_text(encoding="utf-8")) if NGINX_TOML.exists() else {}
        except Exception:
            nginx_cfg2 = {}
        base_auth = None
        for app, cfg in nginx_cfg2.items():
            if isinstance(cfg, dict) and cfg.get("sso_issuer") is True:
                base_auth = cfg.get("base") or f"/{app}"
                break
        if base_auth:
            pattern = rf"location\s+{re.escape(base_auth)}/\s*\{{[\s\S]*?\}}"
            m = re.search(pattern, generated_text or "")
            if m and "proxy_cookie_path" in m.group(0):
                sso_ok_msg = f"✅ `location {base_auth}/` に `proxy_cookie_path` が出力されています。"
            else:
                sso_ok_msg = f"⚠️ `location {base_auth}/` に `proxy_cookie_path` が見つかりません。"
                sso_warn = True
        else:
            sso_ok_msg = "ℹ️ nginx.toml から sso_issuer の base が特定できませんでした。"

        if diff_txt:
            t1, t2, t3 = st.tabs(["差分（unified diff）", "生成プレビュー", "SSO検証"])
            with t1: st.code(diff_txt, language="diff")
            with t2: st.code(generated_text, language="nginx")
            with t3: (st.warning if sso_warn else st.success)(sso_ok_msg)
        else:
            st.success("差分はありません（生成内容と現行 nginx.conf は同一です／dry-run）")
            if sso_ok_msg:
                (st.warning if sso_warn else st.info)(sso_ok_msg)

    st.markdown("---")
    st.caption("このボタンは **実際に nginx.conf に書き込み**、その後 **構文チェックのみ** 実行します。")
    confirm = st.checkbox("書き込みに同意する（バックアップ作成→生成→構文チェック）", value=False)

    if st.button("🧪 生成 → 🔎 構文チェック（書き込みあり）", disabled=not confirm, type="primary"):
        code1, out1 = run_cmd([sys.executable, "tools/generate_nginx_conf.py"])
        st.code(out1 or "(no output)")
        if code1 != 0:
            st.error("生成に失敗したため構文チェックを中止しました。")
        else:
            code2, out2 = nginx_test(conf_path)
            (st.success if code2 == 0 else st.error)("構文チェック " + ("OK ✅" if code2 == 0 else "NG ❌"))
            st.code(out2 or "(no output)")

