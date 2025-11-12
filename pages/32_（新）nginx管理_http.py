# pages/32_（新）nginx管理_http.py

from __future__ import annotations
from pathlib import Path
import sys, re
import toml
import streamlit as st

from lib.nginx_utils_new import (
    SETTINGS_FILE, MINIMAL_NGINX_CONF,
    load_settings, resolve_nginx_conf_path, stat_text,
    atomic_write, make_backup, run_cmd,
    generate_conf_dry_run, diff_current_vs_generated, current_head,
    nginx_test
)

# ============================================================
# 画面初期化
# ============================================================
st.set_page_config(page_title="nginx 管理 (.local 自動注入は generate 側)", page_icon="🧩", layout="wide")
st.title("🧩 nginx 管理 — SSO(auth_portal) ＋ .local は generate 側で自動注入（Bonjour広告なし）")

# ---------------- 設定ロード ----------------
try:
    settings = load_settings(Path(SETTINGS_FILE))
    conf_path = resolve_nginx_conf_path(settings)
except Exception as e:
    st.error(f"settings.toml の読み込み／解決に失敗しました: {e}")
    st.stop()

# 現在の location セクション（[locations.<env>]）を推定
env_loc = None
try:
    env_name = (settings.get("env") or {}).get("location")
    locs = settings.get("locations") or {}
    if env_name and env_name in locs:
        env_loc = locs[env_name]
except Exception:
    env_loc = None

# .local 名（表示＆検証のみ／注入は tools/generate_nginx_conf_new.py に移譲）
local_host_name = None
mdns_fqdn = None
if isinstance(env_loc, dict):
    local_host_name = (env_loc.get("local_host_name") or "").strip() or None
    if local_host_name:
        mdns_fqdn = f"{local_host_name}.local"

# nginx.toml パス（同階層の .streamlit/nginx.toml を想定）
NGINX_TOML = Path(".streamlit/nginx.toml")

colA, colB = st.columns([2, 3])

# ============================================================
# 左：基本操作（ファイル情報・操作）
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
        st.code(out)

    st.caption("※ 権限エラー時は `sudo nginx -t -c ...` を手動実行してください。")

    # -------- SSO 設定チェック（nginx.toml を読む） --------
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
        st.caption("このアプリの location ブロックにだけ `proxy_cookie_path <base>/ / samesite=lax httponly;` が出力される想定です。")

    # -------- 表示のみ：.local 名
    st.markdown("---")
    st.subheader("🔤 .local ホスト名（表示のみ・Bonjour広告は行いません）")
    if mdns_fqdn:
        st.info(f"検出された FQDN: **{mdns_fqdn}**  （例：`http://{mdns_fqdn}/` に自分でアクセス）")
    else:
        st.warning("`local_host_name` が settings.toml で未設定です（[locations.<env>].local_host_name）。")

# ============================================================
# 右：nginx.conf 編集 & 生成
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

    # セッション保持
    if "nginx_orig" not in st.session_state or st.session_state.get("nginx_path") != str(conf_path):
        st.session_state["nginx_orig"] = content
        st.session_state["nginx_path"] = str(conf_path)

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
                st.code(out)
            except PermissionError as e:
                st.error(f"権限エラーで保存できませんでした: {e}")
                st.caption(f"`sudo cp ./nginx.conf {conf_path}` / `sudo chown $(whoami) {conf_path}`")
            except Exception as e:
                st.error(f"保存に失敗しました: {e}")

# ============================================================
# 自動生成（DRY-RUN）— 生成器側で .local 注入 → 差分・検証
# ============================================================
st.markdown("---")
st.header("🧪 自動生成（tools/generate_nginx_conf_new.py が .local を自動注入）")

with st.expander("🔧 生成スクリプト実行（.streamlit/nginx.toml + settings.toml → nginx.conf）", expanded=True):
    st.subheader("🔍 差分プレビュー（生成内容 vs 現行 nginx.conf）")
    code, generated_text = generate_conf_dry_run()  # ← new スクリプトの dry-run
    if code != 0:
        st.error("生成スクリプト（dry-run）が失敗しました ❌")
        st.code(generated_text)
    else:
        # SSO 検証
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

        # .local 名の含有チェック（注入は tools 側で済んでいる想定）
        mdns_ok_msg = ""
        mdns_warn = False
        if mdns_fqdn:
            server_name_lines = re.findall(r"server_name\s+([^;]+);", generated_text or "")
            found = any(mdns_fqdn in ln for ln in server_name_lines)
            if found:
                mdns_ok_msg = f"✅ 生成結果の `server_name` に **{mdns_fqdn}** が含まれています。"
            else:
                mdns_ok_msg = f"⚠️ 生成結果の `server_name` に **{mdns_fqdn}** が含まれていません。tools/generate_nginx_conf_new.py の注入フックを確認してください。"
                mdns_warn = True
        else:
            mdns_ok_msg = "ℹ️ `local_host_name` が未設定のため、.local 検証をスキップしました。"

        # 現行との差分
        current_text = conf_path.read_text(encoding="utf-8", errors="replace") if conf_path.exists() else ""
        diff_txt = diff_current_vs_generated(current_text, generated_text or "")

        if diff_txt:
            tab1, tab2, tab3, tab4 = st.tabs(["差分（unified diff）", "生成プレビュー", "SSO検証", ".local検証"])
            with tab1:
                st.code(diff_txt, language="diff")
            with tab2:
                st.code(generated_text, language="nginx")
            with tab3:
                (st.warning if sso_warn else st.success)(sso_ok_msg)
            with tab4:
                (st.warning if mdns_warn else st.success)(mdns_ok_msg)
        else:
            st.success("差分はありません（生成内容と現行 nginx.conf は同一です／dry-run）")
            if sso_ok_msg:
                (st.warning if sso_warn else st.info)(sso_ok_msg)
            if mdns_ok_msg:
                (st.warning if mdns_warn else st.info)(mdns_ok_msg)

    st.markdown("---")
    st.caption("このボタンは **tools/generate_nginx_conf_new.py による実書き込み**を行い、その後 **構文チェック** を実行します（`.local` 注入は generate 側で実行）。")
    confirm = st.checkbox("書き込みに同意する（バックアップはスクリプト側で行う想定）", value=False)

    if st.button("🧪 生成 → 🔎 構文チェック（書き込みあり）", disabled=not confirm, type="primary"):
        code1, out1 = run_cmd([sys.executable, "tools/generate_nginx_conf_new.py"])  # 書き込みあり
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
