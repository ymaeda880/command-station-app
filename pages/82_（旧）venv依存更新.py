# pages/05_venv依存更新.py
from __future__ import annotations
from pathlib import Path
import subprocess
import streamlit as st

from config.path_config import PROJECT_ROOT
from lib.project_scan import discover_apps
from lib.ui_utils import thick_divider


st.set_page_config(page_title="🧩 venv依存更新ツール", page_icon="🧩", layout="wide")
st.title("🧩 venv依存更新ツール")
st.caption("全 `_app` フォルダを対象に、venv の pip アップグレードと requirements.txt インストールを行います。")

st.info(f"現在の project_root: `{PROJECT_ROOT}`")

# ============================================================
# ユーティリティ関数
# ============================================================

def run(cmd: str | list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """コマンドを実行して (returncode, stdout, stderr) を返す"""
    if isinstance(cmd, str):
        cmd = ["/bin/bash", "-lc", cmd]  # source が含まれるときは bash 経由で実行
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"

def get_pwd(cwd: Path) -> str:
    """pwd を取得"""
    code, out, err = run(["/bin/pwd"], cwd)
    return out or str(cwd)

def show_result(title: str, code: int, out: str, err: str):
    """結果を整形して表示"""
    st.markdown(f"### {title}")
    st.write(f"**終了コード:** {code}")
    if out:
        st.markdown("**標準出力:**")
        st.code(out, language="bash")
    if err:
        st.markdown("**標準エラー:**")
        st.code(err, language="bash")
    if code == 0:
        _ = st.success("✅ 成功しました。")
    else:
        _ = st.error("❌ 失敗しました。")

# ============================================================
# アプリ選択
# ============================================================

st.subheader("📂 対象アプリの選択")

apps = discover_apps(PROJECT_ROOT)
if not apps:
    st.warning("アプリが見つかりません。")
    st.stop()

app_options = [str(a.app_path) for a in apps if a.kind == "app"]
selected_app = st.radio("対象の `_app` フォルダを選択してください", app_options, key="radio_select_app")

final_path = Path(selected_app)
venv_path = final_path / ".venv"
pip_path = venv_path / "bin" / "pip"
req_path = final_path / "requirements.txt"

thick_divider("#007ACC", 3)
st.write(f"**作業ディレクトリ:** `{get_pwd(final_path)}`")

# ============================================================
# 個別実行ステップ
# ============================================================

st.subheader("🧱 ステップ実行")

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("① venvを有効化（source）", key="btn_source"):
        cmd = f"source {venv_path}/bin/activate && echo $VIRTUAL_ENV"
        code, out, err = run(cmd, cwd=final_path)
        show_result("① venvを有効化", code, out, err)

with col2:
    if st.button("② pipをアップグレード", key="btn_pip_upgrade"):
        if not pip_path.exists():
            st.error("`.venv/bin/pip` が見つかりません。先に仮想環境を作成してください。")
        else:
            cmd = f"source {venv_path}/bin/activate && pip install --upgrade pip"
            code, out, err = run(cmd, cwd=final_path)
            show_result("② pipアップグレード", code, out, err)

with col3:
    if st.button("③ requirements.txt をインストール", key="btn_req_install"):
        if not req_path.exists():
            st.error("`requirements.txt` が見つかりません。")
        elif not pip_path.exists():
            st.error("`.venv/bin/pip` が見つかりません。")
        else:
            cmd = f"source {venv_path}/bin/activate && pip install -r requirements.txt"
            code, out, err = run(cmd, cwd=final_path)
            show_result("③ requirements.txt インストール", code, out, err)

thick_divider("#999", 2)

# ============================================================
# 🚀 まとめて実行
# ============================================================

st.subheader("🚀 まとめて実行（1→3連続実行）")

if st.button("▶️ まとめて実行", key="btn_all"):
    st.markdown(f"**作業ディレクトリ:** `{get_pwd(final_path)}`")

    cmds = [
        f"source {venv_path}/bin/activate && echo $VIRTUAL_ENV",
        f"source {venv_path}/bin/activate && pip install --upgrade pip",
        f"source {venv_path}/bin/activate && pip install -r requirements.txt",
    ]

    for i, cmd in enumerate(cmds, start=1):
        st.markdown(f"#### Step {i}: {cmd}")
        code, out, err = run(cmd, cwd=final_path)
        show_result(f"Step {i}", code, out, err)
        if code != 0:
            st.error(f"❌ Step {i} で失敗したため中断します。")
            break
    else:
        st.success("✅ すべてのステップが完了しました。")

st.caption("Tips: source を使って環境変数を引き継ぐため、bash -lc 経由で実行しています。")
