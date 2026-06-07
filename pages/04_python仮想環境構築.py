# pages/04_python仮想環境構築.py
from __future__ import annotations
from pathlib import Path
import unicodedata
import re
import subprocess
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

st.warning("git cloneを行う時は，READMEやrequirements.txtなどを作成しない")

st.markdown(
    """
⚠️ 初めてプロジェクトを作成する時<br>
① プロジェクト名（例：sales-tools）を設定して，「xxx_project/xxx_appを作成」ボタンを押す．<br>
その際には「READMEなどを作成」にチェックを入れておく．<br>
② 作成したフォルダーを選択して，「仮想領域を作成する」から.venvを作成する．<br>
<br>
⚠️ 初めてGitからプログラムをcloneする時<br>
① プロジェクト名（例：sales-tools）を設定して，「xxx_project/xxx_appを作成」ボタンを押す．<br>
その際には「READMEなどを作成」に<b>チェックを外して</b>おく．<br>
② <b>「プロジェクト一覧とGit」ページ</b>に移動．<br>
③ 作成したフォルダーを「操作対象」に選ぶ．<br>
④ 「最初のclone」から「リポジトリURL」を設定して，最初のcloneを行う．<br>
⑤ <b>「python仮想環境構築」ページ</b>に移動する．<br>
⑥ 対象フォルダに設定し，仮想環境を設定する．<br>
⑦ streamlitのバージョンを設定する．<br>
⑧ VSCodeからsource .venv/bin/activate，pip install -r requirements.txtを行う．<br>
<br>
⚠️ ２度目以降にGitからpullをする時<br>
""",
    unsafe_allow_html=True,
)

# ============================================================
# 0) 新規プロジェクト雛形の作成: xxx → PROJECT_ROOT/xxx_project/xxx_app
# ============================================================

def slugify(name: str) -> str:
    """日本語・全角も NFKC 正規化→半角化し、英小文字/数字/ハイフン/アンダースコアに制限"""
    s = unicodedata.normalize("NFKC", name).strip().lower()
    s = s.replace(" ", "_")
    # 許可: a-z, 0-9, -, _
    s = re.sub(r"[^a-z0-9\-_]+", "_", s)
    # 連続した _ を圧縮
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "project"

with st.expander("🆕 まずは新規プロジェクトとアプリのフォルダを作る（任意）", expanded=True):
    proj_input = st.text_input("プロジェクト名（例: sales-tools, ocr-viewer など）", key="txt_proj_name")
    col_new = st.columns([1, 1, 2])
    with col_new[0]:
        create_btn = st.button("📁 `xxx_project/xxx_app` を作成", key="btn_create_project")
    with col_new[1]:
        make_skeleton = st.checkbox("README や requirements.txt などを同時作成", value=True, key="chk_skeleton")

    if create_btn:
        slug = slugify(proj_input or "")
        project_dir = Path(PROJECT_ROOT) / f"{slug}_project"
        app_dir = project_dir / f"{slug}_app"
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            app_dir.mkdir(parents=True, exist_ok=True)

            if make_skeleton:
                (app_dir / "README.md").write_text(
                    f"# {slug}_app\n\n"
                    f"- プロジェクトルート: `{project_dir}`\n"
                    f"- アプリディレクトリ: `{app_dir}`\n",
                    encoding="utf-8"
                )

                (app_dir / "requirements.txt").write_text(
                    "# 必要なパッケージを1行ずつ記載してください\n"
                    "streamlit>=1.37\n",
                    encoding="utf-8"
                )

                (app_dir / ".gitignore").write_text(
                    "# Python / Streamlit ignore rules\n"
                    ".venv/\n"
                    "env/\n"
                    "venv/\n"
                    "__pycache__/\n"
                    "*.pyc\n"
                    "*.pyo\n"
                    "*.log\n"
                    ".DS_Store\n"
                    ".vscode/\n"
                    ".idea/\n"
                    ".ipynb_checkpoints/\n"
                    ".streamlit/secrets.toml\n",
                    encoding="utf-8"
                )

                pages_dir = app_dir / "pages"
                pages_dir.mkdir(exist_ok=True)
                (app_dir / "app.py").write_text(
                    'import streamlit as st\n'
                    f'st.set_page_config(page_title="{slug}_app", page_icon="🧪", layout="wide")\n'
                    f'st.title("Hello from {slug}_app")\n',
                    encoding="utf-8"
                )

                st_dir = app_dir / ".streamlit"
                st_dir.mkdir(exist_ok=True)
                (st_dir / "config.toml").write_text(
                    "# .streamlit/config.toml\n"
                    f"# プロジェクト名：{slug}_app\n\n"
                    "[server]\n"
                    "port = 9999\n"
                    'address = "0.0.0.0"\n'
                    f'baseUrlPath = "/{slug}"\n'
                    "enableCORS = false\n"
                    "headless = true\n",
                    encoding="utf-8"
                )

                (st_dir / "settings.toml").write_text(
                    "# settings.toml\n"
                    f"# プロジェクト名：{slug}_app\n",
                    encoding="utf-8"
                )

                (st_dir / "secrets.toml").write_text(
                    "# .streamlit/secrets.toml\n",
                    encoding="utf-8"
                )

            st.success(f"✅ 作成しました: `{app_dir}`")
            st.rerun()
        except Exception as e:
            st.error(f"❌ 作成に失敗しました: {type(e).__name__}: {e}")

thick_divider("#007ACC", 2)

# -----------------------------
# 小さなコマンド実行ユーティリティ
# -----------------------------
def run(cmd: str | list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    cmd_list = cmd if isinstance(cmd, list) else cmd.split(" ")
    try:
        p = subprocess.run(cmd_list, cwd=cwd, capture_output=True, text=True, check=False)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"

# -----------------------------
# 対象フォルダ選択
# -----------------------------
st.subheader("📂 対象フォルダを選択（`.venv` 未作成の `_app`）")
apps = discover_apps(PROJECT_ROOT)
no_venv_apps = [app for app in apps if not (app.app_path / ".venv").exists() and app.kind == "app"]

if no_venv_apps:
    options = ["（選択しない：手動入力を使う）"] + [str(a.app_path) for a in no_venv_apps]
    selection = st.radio("以下から1つ選んでください", options=options, index=0, key="radio_no_venv_apps")
else:
    st.success("✅ `.venv` 未作成の `_app` は見つかりませんでした。")
    selection = "（選択しない：手動入力を使う）"

thick_divider("#007ACC", 2)

st.subheader("🖊️ 手動でパスを指定（任意）")
target_path_str = st.text_input("フォルダパス（例）/Users/you/projects/your_project/your_app", value="", key="txt_manual_path")

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
# (1) 仮想環境の作成のみ
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

col_make = st.columns([1, 1])
with col_make[0]:
    if st.button("🛠️ 仮想環境を作成（venv）", key="btn_make_venv"):
        if do_pyenv_local:
            code, out, err = run(["pyenv", "local", "3.12.2"], cwd=final_path)
            st.markdown("**pyenv local 3.12.2**")
            st.code(out or err or "(no output)", language="bash")
            if code != 0:
                st.warning("pyenv の実行に失敗しました。pyenv未インストールの場合はこのチェックを外してください。")

        code, out, err = run([py_cmd, "-m", "venv", ".venv"], cwd=final_path)
        st.markdown("**python -m venv .venv**")
        st.code(out or err or "(no output)", language="bash")
        if code == 0:
            st.success("✅ 仮想環境 .venv を作成しました。")
        else:
            st.error("❌ 仮想環境の作成に失敗しました。")

# with col_make[1]:
#     if st.button("🧪 venv存在チェック", key="btn_check_venv"):
#         venv_pip = final_path / ".venv" / "bin" / "pip"
#         st.write(f"pip path: `{venv_pip}`")
#         st.success("存在します。") if venv_pip.exists() else st.error("見つかりません。")
