# pages/30_nginx管理.py
from __future__ import annotations
from pathlib import Path
import os
import sys
import streamlit as st

# lib から関数を呼び出し
from lib.nginx_utils import (
    SETTINGS_FILE, MINIMAL_NGINX_CONF,
    load_settings, resolve_nginx_conf_path, stat_text,
    atomic_write, make_backup, run_cmd,
    generate_conf_dry_run, diff_current_vs_generated, current_head,
    nginx_test, nginx_reload, brew_start, brew_stop, brew_restart,
    brew_services_list, pgrep_nginx, lsof_port_80, tail_log, mtime_str
)

# ============ 画面初期化 ============
st.set_page_config(page_title="nginx 管理", page_icon="🧩", layout="wide")
st.title("🧩 nginx 管理")

# 設定ロード
try:
    settings = load_settings(Path(SETTINGS_FILE))
    conf_path = resolve_nginx_conf_path(settings)
except Exception as e:
    st.error(f"settings.toml の読み込み／解決に失敗しました: {e}")
    st.stop()

colA, colB = st.columns([2, 3])

# ============ 左：基本操作 ============
with colA:
    st.subheader("設定ファイルとパス")
    st.code(f"settings: {Path(SETTINGS_FILE).resolve()}\nnginx_root: {conf_path.parent}\nnginx.conf: {conf_path}", language="bash")

    st.subheader("nginx.conf 情報")
    st.text(stat_text(conf_path))

    st.subheader("操作")
    if st.button("⚙️ 構文チェック（nginx -t -c ...）", type="primary"):
        code, out = nginx_test(conf_path)
        (st.success if code == 0 else st.error)("構文チェック " + ("✅" if code == 0 else "❌"))
        st.code(out)

    if st.button("🔄 再起動（brew services restart nginx）"):
        code, out = brew_restart()
        (st.success if code == 0 else st.error)("再起動 " + ("✅" if code == 0 else "❌"))
        st.code(out)

    st.caption("※ 権限エラー時は `sudo nginx -t -c ...` / `sudo brew services restart nginx` を手動実行してください。")

# ============ 右：編集 ============
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

# ============ 補足 ============
with st.expander("ℹ️ 補足：よくあるトラブルと対処"):
    st.markdown("""
- **構文エラー**: `http { ... }` に `include mime.types;` がない、`server { ... }` の括弧抜け、`listen` 重複など。  
- **ポート競合**: 既に他プロセスが `:80` を使用していると起動に失敗。`lsof -i :80` で確認。  
- **権限**: `/opt/homebrew/etc/nginx` は環境により要権限。  
- **Streamlit 側のURL**: 逆プロキシなら各アプリの `baseUrlPath` を合わせる（例：`/bot`, `/doc-manager`）。  
""")

# ============ 自動生成（DRY-RUN で無変更） ============
st.markdown("---")
st.header("🧪 自動生成（tools/generate_nginx_conf.py を実行）")

with st.expander("ℹ️ 各ボタンの動作説明（help）", expanded=False):
    st.markdown("### 🔍 差分プレビュー（比較のみ／DRY-RUN）")
    st.markdown(
        "- `.streamlit/nginx.toml` と `.streamlit/settings.toml` から、"
        "`tools/generate_nginx_conf.py --dry-run` を実行して **生成内容をプレビュー** します。  \n"
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
    st.markdown("---")
    st.markdown("### ⚠️ 注意事項")
    st.markdown(
        "- 本番反映には **必ず再起動** が必要です（`reload` では反映されないケースがあります）。  \n"
        "- エラー時は `error.log` を確認し、設定を修正してから再度生成してください。  \n"
        "- 権限エラーが出る場合は、必要に応じて `sudo` を付けて手動実行してください。"
    )

# ---------------------------------------
# 差分プレビュー＋生成（書き込みあり）
# ---------------------------------------
with st.expander("🔧 生成スクリプト実行（.streamlit/nginx.toml + settings.toml → nginx.conf）", expanded=True):
    st.subheader("🔍 差分プレビュー（生成内容 vs 現行 nginx.conf）")
    code, generated_text = generate_conf_dry_run()
    if code != 0:
        st.error("生成スクリプト（dry-run）が失敗しました ❌")
        st.code(generated_text)
    else:
        current_text = conf_path.read_text(encoding="utf-8", errors="replace") if conf_path.exists() else ""
        diff_txt = diff_current_vs_generated(current_text, generated_text or "")
        if diff_txt:
            tab1, tab2 = st.tabs(["差分（unified diff）", "生成プレビュー"])
            with tab1:
                st.code(diff_txt, language="diff")
            with tab2:
                st.code(generated_text, language="nginx")
            st.caption("※ DRY-RUN のため、nginx.conf は一切変更していません。")
        else:
            st.success("差分はありません（生成内容と現行 nginx.conf は同一です／dry-run）")

    st.markdown("---")
    st.caption("このボタンは **実際に nginx.conf に書き込み**、その後 **構文チェックのみ** 実行します。")
    confirm = st.checkbox("書き込みに同意する（バックアップ作成→生成→構文チェック）", value=False)

    if st.button("🧪 生成 → 🔎 構文チェック（書き込みあり）", disabled=not confirm, type="primary"):
        code1, out1 = run_cmd([sys.executable, "tools/generate_nginx_conf.py"])
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
            st.warning(
                "📝 **再起動をしてください**：設定を反映するには再起動が必要です。\n\n"
                "Homebrew 環境の例：\n"
                "```bash\nbrew services restart nginx\n```",
                icon="⚠️",
            )

# ============ nginx サービス操作 ============
st.markdown("---")
st.header("🛠️ nginx サービス操作（Homebrew 想定）")

NGINX_LOG_DIR = "/opt/homebrew/var/log/nginx"
ERROR_LOG = f"{NGINX_LOG_DIR}/error.log"
ACCESS_LOG = f"{NGINX_LOG_DIR}/access.log"

with st.expander("📊 現在の状態を確認", expanded=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        st.caption("brew services list（抜粋）")
        out = brew_services_list()
        lines = out.splitlines()
        ng_lines = [ln for ln in lines if "nginx" in ln]
        st.code("\n".join(ng_lines or lines), language="bash")
    with c2:
        st.caption("プロセス（pgrep -ax nginx）")
        st.code(pgrep_nginx() or "(プロセスなし)", language="bash")
    with c3:
        st.caption("LISTEN中のポート（:80）")
        st.code(lsof_port_80() or "(ポート:80 で LISTEN している nginx は見つかりません)", language="bash")

with st.expander("⚙️ 操作（start / stop / restart / reload / test）", expanded=True):
    cA, cB, cC, cD, cE = st.columns(5)
    with cA:
        if st.button("▶️ start"):
            code, out = brew_start()
            (st.success if code == 0 else st.error)("start " + ("✅" if code == 0 else "❌"))
            st.code(out)
    with cB:
        if st.button("⏹ stop"):
            code, out = brew_stop()
            (st.success if code == 0 else st.error)("stop " + ("✅" if code == 0 else "❌"))
            st.code(out)
    with cC:
        if st.button("🔄 restart"):
            code, out = brew_restart()
            (st.success if code == 0 else st.error)("restart " + ("✅" if code == 0 else "❌"))
            st.code(out)
    with cD:
        if st.button("♻️ reload (設定再読み込み)"):
            code_t, out_t = nginx_test(conf_path)
            if code_t != 0:
                st.error("構文チェック NG のため reload を中止しました。")
                st.code(out_t)
            else:
                code, out = nginx_reload(conf_path)
                (st.success if code == 0 else st.error)("reload " + ("✅" if code == 0 else "❌"))
                st.code((out_t or "") + ("\n" + out if out else ""))
    with cE:
        if st.button("🧪 test (-t -c)"):
            code, out = nginx_test(conf_path)
            (st.success if code == 0 else st.error)("構文チェック " + ("✅" if code == 0 else "❌"))
            st.code(out)

with st.expander("📜 ログ（error.log / access.log）", expanded=False):
    tabs = st.tabs(["error.log", "access.log"])
    with tabs[0]:
        n = st.slider("表示行数（tail -n）", 50, 2000, 400, key="err_tail")
        out = tail_log(ERROR_LOG, n)
        if out: st.code(out)
        else:   st.warning(f"{ERROR_LOG} が見つかりません。")
    with tabs[1]:
        n2 = st.slider("表示行数（tail -n） ", 50, 2000, 200, key="acc_tail")
        out = tail_log(ACCESS_LOG, n2)
        if out: st.code(out)
        else:   st.warning(f"{ACCESS_LOG} が見つかりません。")

st.caption("メモ: reload は master プロセスを落とさずに設定のみ再読み込み。restart は短時間の中断あり。")

# 🔶 追加：再起動を明確に促す注意文
st.markdown(
    """
    <div style="background-color:#fff8d5;padding:10px;border-radius:8px;margin-top:10px">
    ⚠️ <b>設定を反映するには必ず再起動してください。</b><br>
    Homebrew 環境では次のコマンドを実行してください：<br>
    <pre style="background-color:#f5f5f5;padding:8px;border-radius:6px;margin-top:6px">brew services restart nginx</pre>
    </div>
    """,
    unsafe_allow_html=True,
)
