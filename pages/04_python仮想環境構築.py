# pages/04_python仮想環境構築.py
from __future__ import annotations
from pathlib import Path
import subprocess
import shlex
import streamlit as st

from config.path_config import PROJECT_ROOT
from lib.project_scan import discover_apps   # 既存のスキャナを再利用
from lib.ui_utils import thick_divider

st.set_page_config(page_title="🧰 フォルダ初期化 & 依存インストール", page_icon="🧰", layout="wide")
st.title("🧰 フォルダ初期化 & 依存インストール")

st.caption(
    "※ ブラウザではドラッグ&ドロップからローカルの実パスは取得できません。"
    " ここでは **`.venv` が未作成の `_app`** をリスト表示し、ラジオで選択して実行します。"
    "（手動パス入力のフォールバックも用意）"
)

st.info(f"現在の project_root: `{PROJECT_ROOT}`")

# -----------------------------
# 小さなコマンド実行ユーティリティ
# -----------------------------
def run(cmd: str | list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    if isinstance(cmd, str):
        cmd_list = cmd.split(" ")
    else:
        cmd_list = cmd
    try:
        p = subprocess.run(cmd_list, cwd=cwd, capture_output=True, text=True, check=False)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"

# -----------------------------
# 対象フォルダの指定UI（`.venv`未作成の_appをラジオで選択）
# -----------------------------
st.subheader("📂 対象フォルダを選択（`.venv` 未作成の `_app`）")

apps = discover_apps(PROJECT_ROOT)
no_venv_apps = [app for app in apps if not (app.app_path / ".venv").exists() and app.kind == "app"]

if no_venv_apps:
    labels = [f"{a.name} — {a.app_path}" for a in no_venv_apps]
    values = [str(a.app_path) for a in no_venv_apps]
    options = ["（選択しない：手動入力を使う）"] + values
    selection = st.radio(
        "以下から1つ選んでください",
        options=options,
        index=0,
        key="radio_no_venv_apps",
        horizontal=False,
    )
else:
    st.success("✅ `.venv` 未作成の `_app` は見つかりませんでした。")
    selection = "（選択しない：手動入力を使う）"

thick_divider("#007ACC", 2)

# 手動入力フォールバック
st.subheader("🖊️ 手動でパスを指定（任意）")
target_path_str = st.text_input(
    "フォルダパス（例）/Users/you/projects/your_project/your_app",
    value="",
    key="txt_manual_path"
)

# 最終決定パスの決定ロジック
if selection != "（選択しない：手動入力を使う）":
    final_path = Path(selection)
elif target_path_str.strip():
    final_path = Path(target_path_str).expanduser()
else:
    final_path = None

if not final_path:
    st.warning("左のラジオで `_app` を選ぶか、手動でフォルダパスを入力してください。")
    st.stop()

st.write(f"**対象フォルダ**: `{final_path}`")

if not final_path.exists() or not final_path.is_dir():
    st.error("指定パスが存在しないか、フォルダではありません。")
    st.stop()

thick_divider("#007ACC", 3)

# -----------------------------
# (1) 仮想環境の作成
# -----------------------------
st.subheader("① 仮想環境を作成する")
st.caption("実行内容: `pyenv local 3.12.2` → `python -m venv .venv`")

col_env = st.columns(3)
with col_env[0]:
    do_pyenv_local = st.checkbox("pyenv local 3.12.2 を実行", value=True, key="chk_pyenv")
with col_env[1]:
    py_cmd = st.text_input("python 実行コマンド", value="python", key="txt_pycmd",
                           help="例: python / python3 / ~/.pyenv/versions/3.12.2/bin/python など")
with col_env[2]:
    st.caption("既存の .venv がある場合は上書きされません。")

c1, c2 = st.columns([1,1])
with c1:
    if st.button("🛠️ 仮想環境を作成（venv）", key="btn_make_venv"):
        # 1) pyenv local 3.12.2（任意）
        if do_pyenv_local:
            code, out, err = run(["pyenv", "local", "3.12.2"], cwd=final_path)
            st.markdown("**pyenv local 3.12.2**")
            st.code(out or err or "(no output)", language="bash")
            if code != 0:
                st.warning("pyenv の実行に失敗しました。pyenv未インストールの場合はこのチェックを外してください。")

        # 2) python -m venv .venv
        code, out, err = run([py_cmd, "-m", "venv", ".venv"], cwd=final_path)
        st.markdown("**python -m venv .venv**")
        st.code(out or err or "(no output)", language="bash")
        if code == 0:
            st.success("✅ 仮想環境 .venv を作成しました。")
        else:
            st.error("❌ 仮想環境の作成に失敗しました。")

with c2:
    if st.button("🧪 venv存在チェック", key="btn_check_venv"):
        venv_pip = final_path / ".venv" / "bin" / "pip"
        st.write(f"pip path: `{venv_pip}`")
        st.success("存在します。") if venv_pip.exists() else st.error("見つかりません。")

thick_divider("#007ACC", 3)

# -----------------------------
# (2) 依存のインストール
# -----------------------------
st.subheader("② 依存（requirements.txt）をインストールする")
st.caption(
    "実行内容: `.venv/bin/pip install --upgrade pip` → `.venv/bin/pip install -r requirements.txt`\n"
    "※ 仮想環境の『有効化（source …）』は不要です。venv直指定で実行します。"
)

req_path = final_path / "requirements.txt"
st.write(f"requirements.txt: `{req_path}`")

col_inst = st.columns(2)
with col_inst[0]:
    if st.button("⬆️ pip をアップグレード", key="btn_pip_upgrade"):
        venv_pip = final_path / ".venv" / "bin" / "pip"
        if not venv_pip.exists():
            st.error("`.venv/bin/pip` が見つかりません。先に『仮想環境を作成』してください。")
        else:
            code, out, err = run([str(venv_pip), "install", "--upgrade", "pip"], cwd=final_path)
            st.markdown("**pip install --upgrade pip**")
            st.code(out or err or "(no output)", language="bash")
            st.success("✅ pip をアップグレードしました。" if code == 0 else "❌ 失敗しました。")

with col_inst[1]:
    if st.button("📦 requirements.txt をインストール", key="btn_install_requirements"):
        venv_pip = final_path / ".venv" / "bin" / "pip"
        if not venv_pip.exists():
            st.error("`.venv/bin/pip` が見つかりません。先に『仮想環境を作成』してください。")
        elif not req_path.exists():
            st.error("`requirements.txt` が見つかりません。フォルダを確認してください。")
        else:
            code, out, err = run([str(venv_pip), "install", "-r", "requirements.txt"], cwd=final_path)
            st.markdown("**pip install -r requirements.txt**")
            st.code(out or err or "(no output)", language="bash")
            st.success("✅ インストール完了。" if code == 0 else "❌ 失敗しました。")

thick_divider("#999", 2)

# -----------------------------
# 一括実行ボタン
# -----------------------------
st.subheader("🚀 まとめて実行")
if st.button("① venv作成 → ② pip upgrade → ③ -r インストール（まとめて）", key="btn_all"):
    # 1) venv
    if do_pyenv_local:
        code, out, err = run(["pyenv", "local", "3.12.2"], cwd=final_path)
        st.markdown("**pyenv local 3.12.2**")
        st.code(out or err or "(no output)", language="bash")
    code, out, err = run([py_cmd, "-m", "venv", ".venv"], cwd=final_path)
    st.markdown("**python -m venv .venv**")
    st.code(out or err or "(no output)", language="bash")

    # 2) pip upgrade
    venv_pip = final_path / ".venv" / "bin" / "pip"
    if not venv_pip.exists():
        st.error("`.venv/bin/pip` が見つかりません。venv 作成に失敗している可能性があります。")
    else:
        code, out, err = run([str(venv_pip), "install", "--upgrade", "pip"], cwd=final_path)
        st.markdown("**pip install --upgrade pip**")
        st.code(out or err or "(no output)", language="bash")

        # 3) -r install
        if req_path.exists():
            code, out, err = run([str(venv_pip), "install", "-r", "requirements.txt"], cwd=final_path)
            st.markdown("**pip install -r requirements.txt**")
            st.code(out or err or "(no output)", language="bash")
        else:
            st.warning("requirements.txt が見つかりませんでした。③ はスキップしました。")

# フッター
st.caption("Tips: ターミナル相当の有効化は不要。`.venv/bin/pip` や `.venv/bin/python` を直接呼び出すのが確実です。")
