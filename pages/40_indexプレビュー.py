# pages/40_indexプレビュー.py
# ============================================================
# 🌐 index.html プレビュー（settings.toml の index_root を使用）
# - 現在の [env].location に対応する index_root を取得
# - そのディレクトリ内の index.html をブラウザ埋め込み表示
# ============================================================

from __future__ import annotations
from pathlib import Path
import toml
import streamlit as st

# =========================
# 定数
# =========================
SETTINGS_FILE = Path(".streamlit/settings.toml")

# =========================
# 関数
# =========================
def load_settings(settings_path: Path) -> dict:
    """settings.toml を読み込む"""
    if not settings_path.exists():
        raise FileNotFoundError(f"{settings_path} が見つかりません。")
    return toml.load(settings_path)

def resolve_index_html(settings: dict) -> Path:
    """現在の環境設定から index.html の絶対パスを取得"""
    loc = settings["env"]["location"]
    index_root = Path(settings["locations"][loc]["index_root"])
    index_html = index_root / "index.html"
    return index_html

# =========================
# ページ設定
# =========================
st.set_page_config(page_title="🌐 index.html プレビュー", page_icon="🌐", layout="wide")
st.title("🌐 index.html プレビュー")
st.caption("settings.toml の [locations.<env>].index_root を使用して index.html を表示します。")

# =========================
# メイン処理
# =========================
try:
    settings = load_settings(SETTINGS_FILE)
    index_html_path = resolve_index_html(settings)
    st.code(
        f"環境: {settings['env']['location']}\nindex_root: {index_html_path.parent}\nindex.html: {index_html_path}",
        language="bash",
    )

    if index_html_path.exists():
        # HTML の読み込み
        html_content = index_html_path.read_text(encoding="utf-8", errors="ignore")

        # 表示方法選択
        mode = st.radio(
            "表示モードを選択",
            ["埋め込み（iframe）", "HTMLコードを直接表示"],
            horizontal=True,
        )

        if mode == "埋め込み（iframe）":
            st.components.v1.html(html_content, height=800, scrolling=True)
        else:
            st.text_area("index.html の内容", html_content, height=600)
    else:
        st.error(f"index.html が見つかりません: {index_html_path}")

except Exception as e:
    st.error(f"設定読み込みまたは表示でエラーが発生しました: {e}")
