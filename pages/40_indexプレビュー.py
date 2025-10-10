# pages/40_indexプレビュー.py
# ============================================================
# 🌐 index.html プレビュー（settings.toml の index_root を使用）
# - 現在の [env].location は secrets.toml を最優先で解決（nginx_utils.load_settings を利用）
# - そのディレクトリ内の index.html をブラウザ埋め込み表示
# ============================================================

from __future__ import annotations
from pathlib import Path
import streamlit as st

# ✅ secrets 優先の設定ローダを再利用（lib/nginx_utils.py で実装済み）
from lib.nginx_utils import load_settings

# =========================
# 定数
# =========================
SETTINGS_FILE = Path(".streamlit/settings.toml")

# =========================
# 関数
# =========================
def resolve_index_html(settings: dict) -> Path:
    """
    現在の環境設定から index.html の絶対パスを取得（厳密エラーメッセージ付き）
    必須:
      - settings["env"]["location"]
      - settings["locations"][<location>]["index_root"]
    """
    try:
        loc = settings["env"]["location"]
    except KeyError as e:
        raise KeyError("settings['env']['location'] が見つかりません。load_settings の戻り値をそのまま渡してください。") from e

    try:
        loc_block = settings["locations"][loc]
    except KeyError as e:
        keys = list(settings.get("locations", {}).keys())
        raise KeyError(f"[locations].{loc} が settings.toml にありません。候補: {keys}") from e

    index_root_raw = loc_block.get("index_root")
    if not index_root_raw:
        raise KeyError(f"[locations].{loc}.index_root が未設定です。")

    index_root = Path(str(index_root_raw)).expanduser().resolve()
    return index_root / "index.html"

def inject_base_tag(html: str, base_href: str) -> str:
    """
    <head> の直後に <base href="..."> を差し込む。
    すでに <base ...> があれば何もしない。
    """
    lower = html.lower()
    if "<base " in lower:
        return html
    head_pos = lower.find("<head")
    if head_pos == -1:
        # <head> が無い場合は先頭に base を置く最低限の対処
        return f'<head><base href="{base_href}"></head>\n' + html
    # <head> タグの終わり（>）を探してその直後に挿入
    gt_pos = html.find(">", head_pos)
    if gt_pos == -1:
        return f'<head><base href="{base_href}"></head>\n' + html
    return html[:gt_pos + 1] + f'\n<base href="{base_href}">\n' + html[gt_pos + 1:]

# =========================
# ページ設定
# =========================
st.set_page_config(page_title="🌐 index.html プレビュー", page_icon="🌐", layout="wide")
st.title("🌐 index.html プレビュー")
st.caption("`.streamlit/secrets.toml` の [env].location を最優先に、`settings.toml` の [locations.<env>].index_root を使って index.html を表示します。")

# =========================
# メイン処理
# =========================
try:
    settings = load_settings(SETTINGS_FILE)  # ← secrets 優先で location を解決
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
            ["埋め込み（iframe 相当 / base 追加可）", "HTMLコードを直接表示"],
            horizontal=True,
        )

        if mode.startswith("埋め込み"):
            col1, col2 = st.columns([3, 2])
            with col2:
                add_base = st.toggle("相対パス解決のため <base href> を追加する", value=True,
                                     help="index.html 内の相対パス（CSS/JS/画像）をローカルの index_root に解決させます。")
            if add_base:
                base_href = index_html_path.parent.as_uri().rstrip("/") + "/"
                html_to_show = inject_base_tag(html_content, base_href)
            else:
                html_to_show = html_content

            # 注意: streamlit.components.v1.html は iframe 相当のサンドボックスで描画します。
            # file:// の相対参照は <base> がないと失敗しがちなので上のオプションで補助しています。
            st.components.v1.html(html_to_show, height=800, scrolling=True)
        else:
            st.text_area("index.html の内容", html_content, height=600)
    else:
        st.error(f"index.html が見つかりません: {index_html_path}")

except Exception as e:
    st.error(f"設定読み込みまたは表示でエラーが発生しました: {e}")
