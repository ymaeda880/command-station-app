# pages/92_nginx管理_https.py

from __future__ import annotations
from pathlib import Path
import sys, re
import streamlit as st

# toml 読み分け（Py3.11+ は tomllib、その他は tomli）
try:
    import tomllib  # type: ignore
except Exception:  # pragma: no cover
    import tomli as tomllib  # type: ignore

import toml  # .streamlit/nginx.toml 用（書式緩めのため）

# ============================================================
# HTTPS ユーティリティ（HTTP 版と同じ API/戻り値で用意）
# ============================================================
from lib.nginx_utils_https import (
    SETTINGS_FILE, MINIMAL_HTTPS_NGINX_CONF,
    load_settings, resolve_nginx_conf_path, stat_text,
    atomic_write, make_backup, run_cmd,
    generate_conf_https_dry_run, diff_current_vs_generated, current_head,
    nginx_test
)

# 画面初期化
st.set_page_config(page_title="nginx 管理（HTTPS / .local 自動注入は generate 側）", page_icon="🧩", layout="wide")
st.title("🧩 nginx 管理 — HTTPS（SSO + .local は generate 側で自動注入）")

# ============================================================
# 設定取得ヘルパ（env 名のケース非依存解決つき）
# ============================================================
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

def _sanitize_mdns(name: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9-]", "", name or "")

def _settings_path() -> Path:
    # アプリルート/.streamlit/settings.toml を想定
    return Path(__file__).resolve().parents[1] / ".streamlit" / "settings.toml"

def _load_settings_text() -> Dict[str, Any]:
    """settings.toml を tomllib で厳密読込"""
    settings_file = _settings_path()
    try:
        return tomllib.loads(settings_file.read_text(encoding="utf-8"))
    except Exception as e:
        st.error(f"settings.toml の読み込みに失敗しました: {e}")
        st.stop()

def _resolve_env_name_case_insensitive(env_name_hint: Optional[str], locations: Dict[str, Any]) -> Optional[str]:
    """secrets/env などから来た env 名を、locations のキーとケース非依存で突き合わせて正規キーを返す"""
    if not isinstance(locations, dict) or not locations or not env_name_hint:
        return None
    if env_name_hint in locations:
        return env_name_hint
    hint_cf = str(env_name_hint).casefold()
    for k in locations.keys():
        if k.casefold() == hint_cf:
            return k
    return None

def _current_env_name(settings: Dict[str, Any]) -> str:
    """現在の env 名：secrets → settings.env.location → locations 先頭（ケース非依存対応）"""
    locs = settings.get("locations") or {}
    # 1) secrets
    try:
        secret_env = st.secrets["env"]["location"]
    except Exception:
        secret_env = None
    if secret_env:
        resolved = _resolve_env_name_case_insensitive(secret_env, locs)
        if resolved:
            return resolved
    # 2) settings.toml の env.location
    env = settings.get("env") or {}
    if isinstance(env, dict) and env.get("location"):
        resolved = _resolve_env_name_case_insensitive(env.get("location"), locs)
        if resolved:
            return resolved
    # 3) locations の先頭
    if isinstance(locs, dict) and len(locs) > 0:
        return next(iter(locs.keys()))
    st.error("現在環境（env.location）を決定できませんでした。settings.toml または secrets.toml を確認してください。")
    st.stop()

@dataclass
class HttpsSettings:
    env_name: str
    local_host_name: Optional[str]
    mdns_fqdn: Optional[str]
    tls_cert_file: Path
    tls_key_file: Path
    extra_server_names: List[str]
    server_name: List[str]
    base_cn: str  # 証明書名の推定に使った基準（UI 表示用）

def read_https_settings_from_settings() -> HttpsSettings:
    """
    settings.toml（現在環境）から HTTPS 関連のフィールドをまとめて取得。
    tls_cert_file / tls_key_file は設定が無い場合、
    **server_name 先頭** → 無ければ **<local_host_name>.local** → それも無ければ **localhost**
    の順でベース名を決め、`~/ssl/{certs,private}/<base_cn>.{crt,key}` を自動推定。
    （= pages/82_証明書管理.py の CN 既定値と同じ優先順位）
    """
    settings_toml = _load_settings_text()
    env_name = _current_env_name(settings_toml)
    locations = settings_toml.get("locations") or {}
    loc = locations.get(env_name)
    if not isinstance(loc, dict):
        st.error(f"settings.toml の locations.{env_name} が見つかりません。")
        st.stop()

    # server_name / extra_server_names
    server_name_raw = loc.get("server_name") or []
    server_name: List[str] = [str(x).strip() for x in server_name_raw if isinstance(x, (str, int)) and str(x).strip()]

    extras_raw = loc.get("extra_server_names") or []
    extra_server_names: List[str] = [str(x).strip() for x in extras_raw if isinstance(x, (str, int)) and str(x).strip()]

    # local_host_name → .local 生成（SAN 追加用）
    local_host_name = loc.get("local_host_name")
    if isinstance(local_host_name, str):
        local_host_name = _sanitize_mdns(local_host_name.strip()) or None
    else:
        local_host_name = None
    mdns_fqdn = f"{local_host_name}.local" if local_host_name else None

    # SAN 候補リストを 82 と同じルールで作成（server_name をベースに、mdns を必要に応じて追加）
    san_candidates: List[str] = list(server_name)
    if mdns_fqdn and mdns_fqdn not in san_candidates:
        san_candidates.append(mdns_fqdn)

    # tls_* は設定優先、無ければ san_candidates[0] をベースに推定
    def _to_path_or_none(x: Any) -> Optional[Path]:
        if isinstance(x, str) and x.strip():
            return Path(x).expanduser()
        return None

    tls_cert_from_cfg = _to_path_or_none(loc.get("tls_cert_file"))
    tls_key_from_cfg  = _to_path_or_none(loc.get("tls_key_file"))

    if tls_cert_from_cfg and tls_key_from_cfg:
        base_cn = (san_candidates[0] if san_candidates else "localhost")
        tls_cert_file = tls_cert_from_cfg
        tls_key_file  = tls_key_from_cfg
    else:
        base_cn = (san_candidates[0] if san_candidates else "localhost")
        home = Path.home()
        tls_cert_file = (home / "ssl" / "certs" / f"{base_cn}.crt").expanduser()
        tls_key_file  = (home / "ssl" / "private" / f"{base_cn}.key").expanduser()

    return HttpsSettings(
        env_name=env_name,
        local_host_name=local_host_name,
        mdns_fqdn=mdns_fqdn,
        tls_cert_file=tls_cert_file,
        tls_key_file=tls_key_file,
        extra_server_names=extra_server_names,
        server_name=server_name,
        base_cn=base_cn,
    )

# ---------------- 設定ロード（既存ユーティリティ + HTTPS 設定の抽出） ----------------
try:
    settings = load_settings(Path(SETTINGS_FILE))
    conf_path = resolve_nginx_conf_path(settings)  # ← HTTPS 用の nginx.conf の想定パス
except Exception as e:
    st.error(f"settings.toml の読み込み／解決に失敗しました: {e}")
    st.stop()

hs = read_https_settings_from_settings()

# nginx.toml パス
NGINX_TOML = Path(".streamlit/nginx.toml")

colA, colB = st.columns([2, 3])

# ============================================================
# 左：基本操作（ファイル情報・操作・TLS/SSOチェック）
# ============================================================
with colA:
    st.subheader("設定ファイルとパス")
    st.code(
        f"settings: {Path(SETTINGS_FILE).resolve()}\n"
        f"env.location(resolved): {hs.env_name}\n"
        f"nginx_root: {conf_path.parent}\n"
        f"nginx.conf(HTTPS): {conf_path}\n"
        f"nginx.toml: {NGINX_TOML.resolve()}",
        language="bash",
    )

    if hs.server_name or hs.extra_server_names or hs.base_cn:
        st.caption("server_name / extra_server_names / 推定CN（証明書名）")
        sn = ", ".join(hs.server_name) if hs.server_name else "(none)"
        ex = ", ".join(hs.extra_server_names) if hs.extra_server_names else "(none)"
        st.code(f"server_name         = {sn}\nextra_server_names  = {ex}\nbase_CN (guessed)  = {hs.base_cn}", language="bash")

    st.subheader("nginx.conf（HTTPS）情報")
    st.text(stat_text(conf_path))

    st.subheader("操作")
    if st.button("⚙️ 構文チェック（nginx -t -c ...）", type="primary"):
        code, out = nginx_test(conf_path)
        (st.success if code == 0 else st.error)("構文チェック " + ("✅" if code == 0 else "❌"))
        st.code(out)
    st.caption("※ 権限エラー時は `sudo nginx -t -c ...` を手動実行してください。")

    # -------- TLS 設定チェック --------
    st.markdown("---")
    st.subheader("🔒 TLS 設定チェック（settings.toml / 自動推定）")
    cert_ok = hs.tls_cert_file.exists()
    key_ok  = hs.tls_key_file.exists()
    (st.success if cert_ok else st.error)(f"証明書: {hs.tls_cert_file} " + ("✅" if cert_ok else "❌ not found"))
    (st.success if key_ok  else st.error)(f"秘密鍵  : {hs.tls_key_file} " + ("✅" if key_ok  else "❌ not found"))
    if not (cert_ok and key_ok):
        st.caption(f"※ 推定 CN は `{hs.base_cn}` です。82_証明書管理ページでこの CN で自己署名を発行し、上記パスに配置してください。")
    else:
        st.caption("証明書と秘密鍵のファイルが確認できました。")

    # -------- SSO 設定チェック（nginx.toml） --------
    st.markdown("---")
    st.subheader("🔐 SSO 設定チェック（nginx.toml の sso_issuer）")
    if not NGINX_TOML.exists():
        st.warning(".streamlit/nginx.toml が見つかりません。SSO チェックをスキップします。")
        nginx_cfg = {}
    else:
        try:
            nginx_cfg = toml.loads(NGINX_TOML.read_text(encoding="utf-8"))
        except Exception as e:
            st.error(f"nginx.toml の読み込みに失敗しました: {e}")
            nginx_cfg = {}

    sso_apps = []
    for app, cfg in (nginx_cfg or {}).items():
        if not isinstance(cfg, dict):
            continue
        if cfg.get("enabled") is False:
            continue
        if cfg.get("sso_issuer") is True:
            base = cfg.get("base") or f"/{app}"
            port = cfg.get("port")
            sso_apps.append((app, base, port))

    if len(sso_apps) == 0:
        st.error("sso_issuer=true のアプリが見つかりません。auth_portal の定義に `sso_issuer = true` を追加してください。")
    elif len(sso_apps) > 1:
        st.error("sso_issuer=true のアプリが複数あります。1つのみにしてください。")
        st.code("\n".join([f"- {a} (base={b}, port={p})" for a, b, p in sso_apps]))
    else:
        app, base, port = sso_apps[0]
        st.success(f"SSO発行アプリ: {app} (base={base}, port={port})")
        st.caption("このアプリの location ブロックにだけ `proxy_cookie_path <base>/ \"/; SameSite=Lax; HttpOnly\";` が出力される想定です。")

    # -------- 表示のみ：.local 名 --------
    st.markdown("---")
    st.subheader("🔤 .local ホスト名（表示のみ・Bonjour広告は行いません）")
    if hs.local_host_name:
        st.info(f"検出された FQDN: **{hs.local_host_name}.local**  （例：`https://{hs.local_host_name}.local/` に自分でアクセス）")
    else:
        st.warning("`local_host_name` が settings.toml で未設定です（[locations.<env>].local_host_name）。")

# ============================================================
# 右：nginx.conf 編集 & 生成（HTTPS）
# ============================================================
with colB:
    st.subheader("nginx.conf（HTTPS／編集）")

    if conf_path.exists():
        try:
            content = conf_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = conf_path.read_text(encoding="utf-8", errors="replace")
    else:
        content = MINIMAL_HTTPS_NGINX_CONF
        st.info("HTTPS 用 nginx.conf が存在しないため、最小テンプレートを表示しています。保存すると新規作成されます。")

    # セッション保持
    if "nginx_https_orig" not in st.session_state or st.session_state.get("nginx_https_path") != str(conf_path):
        st.session_state["nginx_https_orig"] = content
        st.session_state["nginx_https_path"] = str(conf_path)

    text = st.text_area(
        "ファイル内容",
        value=content,
        height=560,
        key="nginx_https_editor",
        placeholder="# ここに HTTPS 用 nginx.conf を編集"
    )
    changed = (text != st.session_state["nginx_https_orig"])
    st.caption("変更状態: " + ("🟡 未保存の変更あり" if changed else "⚪ 変更なし"))

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("📥 再読み込み（破棄）", key="https_reload"):
            st.session_state.pop("nginx_https_orig", None)
            st.session_state.pop("nginx_https_editor", None)
            st.rerun()

    with c2:
        if conf_path.exists():
            try:
                data = conf_path.read_bytes()
                st.download_button(
                    "🧷 現在の HTTPS nginx.conf をダウンロード",
                    data=data,
                    file_name="nginx.https.conf.backup",
                    mime="text/plain",
                    key="https_download"
                )
            except Exception as e:
                st.warning(f"ダウンロード準備に失敗: {e}")

    with c3:
        if st.button("💾 保存（バックアップ作成→原子書き込み）", type="primary", key="https_save"):
            try:
                conf_path.parent.mkdir(parents=True, exist_ok=True)
                if conf_path.exists():
                    backup = make_backup(conf_path)
                    st.success(f"バックアップ作成: {backup.name}")
                atomic_write(conf_path, text)
                st.session_state["nginx_https_orig"] = text
                st.success("保存しました ✅")
                code, out = nginx_test(conf_path)
                (st.info if code == 0 else st.error)("保存後の構文チェック: " + ("OK ✅" if code == 0 else "エラー ❌"))
                st.code(out)
            except PermissionError as e:
                st.error(f"権限エラーで保存できませんでした: {e}")
                st.caption(f"`sudo cp ./nginx.conf {conf_path}` / `sudo chown $(whoami) {conf_path}`")
            except Exception as e:
                st.error(f"保存に失敗しました: {e}")

# ============================================================
# 自動生成（DRY-RUN）— 生成器側で .local/TLS を自動注入 → 差分・検証
# ============================================================
st.markdown("---")
st.header("🧪 自動生成（tools/generate_nginx_conf_https.py が .local/TLS を自動注入）")

with st.expander("🔧 生成スクリプト実行（.streamlit/nginx.toml + settings.toml → HTTPS nginx.conf）", expanded=True):
    st.subheader("🔍 差分プレビュー（生成内容 vs 現行 nginx.conf）")

    code, generated_text = generate_conf_https_dry_run()
    if code != 0:
        st.error("生成スクリプト（dry-run）が失敗しました ❌")
        st.code(generated_text)
    else:
        # 1) SSO 検証
        sso_ok_msg = ""
        sso_warn = False
        try:
            nginx_cfg2 = toml.loads(NGINX_TOML.read_text(encoding="utf-8")) if NGINX_TOML.exists() else {}
        except Exception:
            nginx_cfg2 = {}

        base_auth = None
        for app, cfg in (nginx_cfg2 or {}).items():
            if isinstance(cfg, dict) and cfg.get("sso_issuer") is True:
                base_auth = cfg.get("base") or f"/{app}"
                break
        if base_auth:
            pattern = rf"location\s+{re.escape(base_auth)}/\s*\{{[\s\S]*?\}}"
            m = re.search(pattern, generated_text or "")
            if m:
                block = m.group(0)
                if "proxy_cookie_path" in block and base_auth in block:
                    sso_ok_msg = f"✅ `location {base_auth}/` に `proxy_cookie_path` が出力されています。"
                else:
                    sso_ok_msg = f"⚠️ `location {base_auth}/` に `proxy_cookie_path` が見つかりません。テンプレ生成ロジックを確認してください。"
                    sso_warn = True
            else:
                sso_ok_msg = f"⚠️ 生成結果に `location {base_auth}/` が見つかりません。baseUrlPath の不一致や生成ロジックを確認してください。"
                sso_warn = True
        else:
            sso_ok_msg = "ℹ️ nginx.toml から sso_issuer の base が特定できませんでした。"

        # 2) .local 名の含有チェック
        mdns_ok_msg = ""
        mdns_warn = False
        if hs.local_host_name:
            want = f"{hs.local_host_name}.local"
            server_name_lines = re.findall(r"server_name\s+([^;]+);", generated_text or "")
            found = any(want in ln for ln in server_name_lines)
            if found:
                mdns_ok_msg = f"✅ 生成結果の `server_name` に **{want}** が含まれています。"
            else:
                mdns_ok_msg = f"⚠️ 生成結果の `server_name` に **{want}** が含まれていません。tools/generate_nginx_conf_https.py の注入フックを確認してください。"
                mdns_warn = True
        else:
            mdns_ok_msg = "ℹ️ `local_host_name` が未設定のため、.local 検証をスキップしました。"

        # 3) HTTPS リスンの検証（443 / ssl / http2）
        https_ok_msg = ""
        https_warn = False
        listen_443 = re.search(r"listen\s+443\s+(ssl\s+)?(http2\s+)?;", generated_text or "")
        has_cert   = re.search(r"ssl_certificate\s+[^;]+;", generated_text or "")
        has_key    = re.search(r"ssl_certificate_key\s+[^;]+;", generated_text or "")
        if listen_443 and has_cert and has_key:
            https_ok_msg = "✅ `listen 443 ssl http2;` と `ssl_certificate` / `ssl_certificate_key` が確認できました。"
        else:
            https_ok_msg = "⚠️ `listen 443 ssl http2;` または `ssl_certificate(_key)` が不足しています。テンプレ生成ロジックを確認してください。"
            https_warn = True

        # 4) 80→443 リダイレクト有無（任意）
        has_80_redirect = re.search(r"server\s*\{[\s\S]*?listen\s+80\s*;[\s\S]*?return\s+301\s+https://\$host\$request_uri\s*;[\s\S]*?\}", generated_text or "")
        redirect_ok_msg = "ℹ️ `80→443` のリダイレクト server ブロックが含まれています。" if has_80_redirect else "ℹ️ `80→443` のリダイレクトは見つかりませんでした（不要であれば問題ありません）。"

        # 現行との差分
        current_text = conf_path.read_text(encoding="utf-8", errors="replace") if conf_path.exists() else ""
        diff_txt = diff_current_vs_generated(current_text, generated_text or "")

        if diff_txt:
            tab1, tab2, tab3, tab4, tab5 = st.tabs(
                ["差分（unified diff）", "生成プレビュー", "SSO検証", ".local検証", "HTTPS検証"]
            )
            with tab1:
                st.code(diff_txt, language="diff")
            with tab2:
                st.code(generated_text, language="nginx")
            with tab3:
                (st.warning if sso_warn else st.success)(sso_ok_msg)
            with tab4:
                (st.warning if mdns_warn else st.success)(mdns_ok_msg)
            with tab5:
                (st.warning if https_warn else st.success)(https_ok_msg)
                st.caption(redirect_ok_msg)
        else:
            st.success("差分はありません（生成内容と現行 HTTPS nginx.conf は同一です／dry-run）")
            if sso_ok_msg:
                (st.warning if sso_warn else st.info)(sso_ok_msg)
            if mdns_ok_msg:
                (st.warning if mdns_warn else st.info)(mdns_ok_msg)
            if https_ok_msg:
                (st.warning if https_warn else st.info)(https_ok_msg)
            st.caption(redirect_ok_msg)

    st.markdown("---")
    st.caption("このボタンは **tools/generate_nginx_conf_https.py による実書き込み**を行い、その後 **構文チェック** を実行します（`.local` / TLS 注入は generate 側で実行）。")
    confirm = st.checkbox("書き込みに同意する（バックアップはスクリプト側で行う想定）", value=False, key="https_confirm")

    if st.button("🧪 生成 → 🔎 構文チェック（書き込みあり）", disabled=not confirm, type="primary", key="https_apply"):
        code1, out1 = run_cmd([sys.executable, "tools/generate_nginx_conf_https.py"])
        st.code(out1)
        if code1 != 0:
            st.error("生成に失敗したため構文チェックを中止しました。")
        else:
            code2, out2 = nginx_test(conf_path)
            if code2 == 0:
                st.success("構文チェック OK ✅")
            else:
                st.error("構文チェック NG ❌")
            st.code(out2)
