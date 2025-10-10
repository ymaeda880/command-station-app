# pages/06_インストール用コマンド.py
from __future__ import annotations
from pathlib import Path
import streamlit as st

from config.path_config import PROJECT_ROOT
from lib.project_scan import discover_apps
from lib.ui_utils import thick_divider

st.set_page_config(page_title="📋 ターミナルで手動実行（コピペ用）", page_icon="📋", layout="wide")
st.title("📋 ターミナルで手動実行（コピペ用）")
st.caption("対象の `_app` を選んで、下のコマンドを **コピペ**してターミナルでそのまま実行してください。")

st.info(f"現在の project_root: `{PROJECT_ROOT}`")

# =========================
# _app の一覧をラジオ表示
# =========================
apps = discover_apps(PROJECT_ROOT)
app_options = [str(a.app_path) for a in apps if a.kind == "app"]

if not app_options:
    st.warning("`_app` ディレクトリが見つかりませんでした。先に雛形を作成してください。")
    st.stop()

selected = st.radio("対象の `_app` を選択", app_options, key="radio_apps_for_terminal")

final_path = Path(selected)
venv_path = final_path / ".venv"
req_path = final_path / "requirements.txt"

thick_divider("#007ACC", 2)
st.write(f"**作業ディレクトリ:** `{final_path}`")

# 参考警告（あれば）
if not venv_path.exists():
    st.warning("`.venv` が見つかりません。先に『仮想環境を作成』を行ってください。")
if not req_path.exists():
    st.warning("`requirements.txt` が見つかりません。必要なら先に作成してください。")

thick_divider("#007ACC", 2)

# =========================
# コピペ用コマンドの表示（コピー専用UI）
# =========================

quoted_path = f'"{final_path}"'

multi_line = (
    f"cd {quoted_path}\n"
    f"source .venv/bin/activate\n"
    f"pip install --upgrade pip\n"
    f"pip install -r requirements.txt\n"
)

one_liner = (
    f"cd {quoted_path} && "
    f"source .venv/bin/activate && "
    f"pip install --upgrade pip && "
    f"pip install -r requirements.txt"
)

st.markdown("#### 🧩 複数行コマンド（順に実行）")
# ✅ テキストエリアなら、フォーカス→⌘/Ctrl+C で確実にその中だけコピーできます
_ = st.text_area("この中身を丸ごとコピー", value=multi_line, height=120, label_visibility="collapsed")

st.markdown("&nbsp;", unsafe_allow_html=True)

st.markdown("#### ⚡ 1行コマンド（コピペ実行可）")
# ✅ 1行は text_input が一番トラブル少ないです
_ = st.text_input("この行をコピー", value=one_liner, label_visibility="collapsed")

# おまけ：.sh としてダウンロード
st.download_button(
    "⬇️ setup_venv.sh をダウンロード",
    data="#!/usr/bin/env bash\nset -euo pipefail\n" + multi_line,
    file_name="setup_venv.sh",
    mime="text/x-shellscript",
)

st.caption("ヒント：テキスト欄をクリックしてから ⌘/Ctrl + C でコピーしてください。")
