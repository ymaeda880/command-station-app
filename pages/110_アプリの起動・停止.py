# pages/70_アプリの起動・停止.py
# ============================================================
# 🌅 朝の起動 & 🌇 夕方の停止（lib/* に分離してシンプルに）
# ============================================================

from __future__ import annotations
from pathlib import Path
import streamlit as st

# 🔧 Nginx は util に委譲
from lib.nginx_utils import (
    load_settings,
    resolve_nginx_conf_path,
    nginx_test,
    nginx_reload,
    brew_start as brew_start_nginx,
    brew_stop as brew_stop_nginx,
    brew_restart as brew_restart_nginx,
)

# 🔧 アプリ操作は app_manager に委譲
from lib.app_manager import (
    app_spec_list,
    start_one_app,
    stop_one_app,
)

# ---------- 設定ファイル ----------
SETTINGS_TOML = Path(".streamlit/settings.toml")
NGINX_TOML    = Path(".streamlit/nginx.toml")

# Python 3.11+ 前提（tomllib：nginx.toml 用）
try:
    import tomllib
except ModuleNotFoundError:
    st.error("Python 3.11+ が必要です（tomllib が見つかりません）")
    st.stop()

def read_nginx_map() -> dict:
    with NGINX_TOML.open("rb") as f:
        return tomllib.load(f)

def open_browser_to_root():
    import webbrowser
    webbrowser.open_new_tab("http://localhost/")

# ======================== 画面 ========================
st.set_page_config(page_title="毎日の起動・停止", page_icon="🗓️", layout="wide")
st.title("🗓️ 毎日の起動・停止（手順ごとに1ボタン）")

# 設定読み込み（lib 利用）
try:
    settings = load_settings(SETTINGS_TOML)
    apps_map = read_nginx_map()
    conf_path = resolve_nginx_conf_path(settings)
except Exception as e:
    st.error(f"設定の読み込みに失敗しました: {e}")
    st.stop()

loc = settings["env"]["location"]
project_root = Path(settings["locations"][loc]["project_root"])
index_root = Path(settings["locations"][loc]["index_root"])
st.caption(f"環境: **{loc}**｜project_root: `{project_root}`｜index_root: `{index_root}`")

# アプリ一覧（enabled=true）
specs = app_spec_list(settings, apps_map)

with st.expander("📋 起動対象アプリ（enabled=true）", expanded=True):
    if not specs:
        st.warning("対象アプリがありません（.streamlit/nginx.toml の enabled=true を確認）")
    else:
        for sp in specs:
            st.markdown(f"- **/{sp['name']}** : port **{sp['port']}**  @ `{sp['app_dir']}`")

st.markdown("---")

# ========== (1) Nginx 確認・起動 ==========
st.subheader("① Nginx を確認・起動")
c1, c2, c3, c4 = st.columns(4)
with c1:
    if st.button("🔎 構文チェック (nginx -t)", width="stretch"):
        code, out = nginx_test(conf_path)
        (st.success if code == 0 else st.error)("構文チェック " + ("OK ✅" if code == 0 else "NG ❌"))
        st.code(out)
with c2:
    if st.button("▶️ 起動 (brew services start nginx)", width="stretch"):
        code, out = brew_start_nginx()
        (st.success if code == 0 else st.error)("Nginx 起動 " + ("OK ✅" if code == 0 else "NG ❌"))
        st.code(out)
with c3:
    if st.button("🔁 再起動 (brew services restart nginx)", width="stretch"):
        code, out = brew_restart_nginx()
        (st.success if code == 0 else st.error)("Nginx 再起動 " + ("OK ✅" if code == 0 else "NG ❌"))
        st.code(out)
with c4:
    if st.button("🔄 reload (nginx -s reload)", width="stretch"):
        code, out = nginx_reload(conf_path)
        (st.success if code == 0 else st.error)("reload " + ("OK ✅" if code == 0 else "NG ❌"))
        st.code(out)

st.caption("※ 反映には基本的に **再起動（restart）** が確実。reload は master を落とさず設定再読み込み。")

# ========== (2) 各アプリを起動 ==========
st.subheader("② 各アプリを起動（個別/一括）")
cA, cB = st.columns(2)

with cA:
    st.markdown("**個別起動**")
    for sp in specs:
        if st.button(f"🚀 起動 /{sp['name']} (:{sp['port']})", key=f"start_{sp['name']}", width="stretch"):
            ok, msg = start_one_app(sp)
            (st.success if ok else st.error)(msg)

with cB:
    st.markdown("**一括起動**")
    if st.button("🚀 全アプリ起動（enabled=true）", type="primary", width="stretch"):
        results = []
        for sp in specs:
            ok, msg = start_one_app(sp)
            results.append((ok, msg))
        if all(ok for ok, _ in results):
            st.success("全アプリ起動：OK ✅")
        else:
            st.warning("一部アプリでエラーがありました。")
        st.code("\n".join(m for _, m in results))

# ========== (3) ブラウザで動作確認 ==========
st.subheader("③ ブラウザでポータルを確認（/ を開く）")
if st.button("🌐 ポータルを開く（/）", width="stretch"):
    try:
        open_browser_to_root()
        st.success("ブラウザで http://localhost/ を開きました ✅")
    except Exception as e:
        st.error(f"ブラウザを開けませんでした: {e}")

st.markdown("---")


# ========== (3.5) 稼働中アプリの一覧 ==========
st.subheader("③.5 稼働中アプリの一覧")

# ちょいユーティリティ
import subprocess

def _sh(cmd: list[str]) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"

def _pid_alive(pid: int) -> bool:
    # macOS (BSD ps)
    code, _, _ = _sh(["ps", "-p", str(pid), "-o", "pid="])
    return code == 0

def _find_pid_by_port(port: int) -> list[int]:
    # lsof -ti tcp:PORT → PIDの羅列（なければ空）
    code, out, _ = _sh(["lsof", "-ti", f"tcp:{port}"])
    if code != 0 or not out:
        return []
    try:
        return [int(x) for x in out.splitlines() if x.strip().isdigit()]
    except Exception:
        return []

def _cmdline(pid: int) -> str:
    # コマンドライン表示（情報用）
    code, out, _ = _sh(["ps", "-p", str(pid), "-o", "command="])
    return out if code == 0 else ""

rows = []
for sp in specs:
    name = sp["name"]
    port = sp["port"]
    app_dir = Path(sp["app_dir"])
    pid_file = app_dir / ".run" / f"{name}.pid"

    status = "STOPPED"
    pid = None
    via = "-"
    cmd = ""

    # 1) pidfile から確認
    if pid_file.exists():
        try:
            pid_txt = pid_file.read_text(encoding="utf-8").strip()
            if pid_txt.isdigit():
                pid = int(pid_txt)
                if _pid_alive(pid):
                    status = "RUNNING"
                    via = "pidfile"
                    cmd = _cmdline(pid)
        except Exception:
            pass

    # 2) 見つからなければポートから逆引き
    if status != "RUNNING":
        pids = _find_pid_by_port(port)
        if pids:
            pid = pids[0]
            if _pid_alive(pid):
                status = "RUNNING"
                via = "port"
                cmd = _cmdline(pid)

    open_url = f"http://localhost/{name}"
    direct_url = f"http://localhost:{port}"

    rows.append({
        "app": f"/{name}",
        "port": port,
        "status": "🟢 RUNNING" if status == "RUNNING" else "⚪ STOPPED",
        "pid": pid if pid else "-",
        "found_by": via,
        "open (proxy)": open_url,
        "open (direct)": direct_url,
        "command": cmd[:140] + ("…" if len(cmd) > 140 else ""),
    })

import pandas as pd

# 表示
if rows:
    # DataFrame化して Arrow エラー対策
    df = pd.DataFrame(rows)

    # pid列をすべて文字列化（Noneや数値混在の対策）
    if "pid" in df.columns:
        df["pid"] = df["pid"].astype(str)

    st.dataframe(df, width="stretch")  # ← use_container_width → width に変更済み
else:
    st.info("表示するアプリがありません。")

cR1, cR2 = st.columns([1,3])
with cR1:
    if st.button("🔄 再スキャン", width="stretch"):
        st.rerun()
with cR2:
    st.caption("検出順序: pidfile → port（lsof）。pidfile が壊れている場合は削除してください。")


# ========== (4) 夕方の停止 ==========
st.subheader("④ 夕方の停止（アプリ停止 → Nginx 停止）")
st.error("comannd_stationは停止しないでください．このアプリが落ちます．")

cS, cT = st.columns(2)
with cS:
    st.markdown("**個別停止**")
    for sp in specs:
        if st.button(f"🛑 停止 /{sp['name']} (:{sp['port']})", key=f"stop_{sp['name']}", width="stretch"):
            ok, msg = stop_one_app(sp)
            (st.success if ok else st.error)(msg)

with cT:
    st.markdown("**一括停止（安全版）**")
    if st.button("🛑 /command_station (:8505) 以外を全部停止", key="stop_all_except_cs", type="secondary", width="stretch"):
        results = []
        skipped  = []

        for sp in specs:
            # 「command_station :8505」を停止対象から除外
            if sp.get("name") == "command_station" or sp.get("port") == 8505:
                skipped.append(f"/{sp['name']} (:{sp['port']})")
                continue

            ok, msg = stop_one_app(sp)
            results.append((ok, msg))

        if not results:
            st.info("停止対象アプリがありません。")
        elif all(ok for ok, _ in results):
            st.success("command_station 以外は停止：OK ✅")
        else:
            st.warning("一部アプリで停止に失敗しました。")

        # ログをまとめて表示（停止結果＋スキップ情報）
        lines = [m for _, m in results]
        if skipped:
            lines.append("")
            lines.append("== Skipped (not stopped) ==")
            lines.extend(skipped)
        st.code("\n".join(lines))

    st.markdown("**一括停止（全て）**")
    if st.button("🛑 全アプリ停止（enabled=true）", key="stop_all_enabled", type="secondary", width="stretch"):
        results = []
        for sp in specs:
            ok, msg = stop_one_app(sp)
            results.append((ok, msg))
        if all(ok for ok, _ in results):
            st.success("全アプリ停止：OK ✅")
        else:
            st.warning("一部アプリで停止に失敗しました。")
        st.code("\n".join(m for _, m in results))


st.markdown("")
if st.button("⏹️ Nginx 停止 (brew services stop nginx)", width="stretch"):
    code, out = brew_stop_nginx()
    (st.success if code == 0 else st.error)("Nginx 停止 " + ("OK ✅" if code == 0 else "NG ❌"))
    st.code(out)

with st.expander("ℹ️ ヒント/注意", expanded=False):
    st.markdown("""
- **アプリのディレクトリ規約**: `<project_root>/<app>_project/<app>_app/` に `app.py` と `.venv/` がある前提です。
- **PID 管理**: `app_dir/.run/<app>.pid` に PID を保存。壊れている場合は削除されます。
- **ポート競合**: 同ポートにプロセスがいる場合はスキップ（`lsof -ti tcp:PORT` 検出）。
- **Nginx**: location と `--server.baseUrlPath` は一致させ、`proxy_pass` は末尾スラ **なし** 推奨。
""")
