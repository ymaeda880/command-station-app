# pages/72_メンテナンス.py
# ============================================================
# 🛠 メンテナンス切替（flag 作成/削除 + nginx reload）
#
# - secrets.toml を最優先に env.location を解決
# - settings.toml の [locations.<env>].index_root を使用
# - index.html 側で maintenance.flag を検知する想定
# ============================================================

from __future__ import annotations
from pathlib import Path
import subprocess
import streamlit as st

# secrets 優先の設定ローダ（既存実装を再利用）
from lib.nginx_utils import load_settings

# =========================
# 定数
# =========================
SETTINGS_FILE = Path(".streamlit/settings.toml")
NGINX_BIN = "nginx"   # PATH が通っていればOK（例: /opt/homebrew/bin/nginx）

# =========================
# ヘルパ関数
# =========================
def resolve_index_root(settings: dict) -> Path:
    """
    settings から index_root を解決する。
    必須:
      - settings["env"]["location"]
      - settings["locations"][<location>]["index_root"]
    """
    try:
        loc = settings["env"]["location"]
    except KeyError as e:
        raise KeyError(
            "settings['env']['location'] が見つかりません。"
            "load_settings の戻り値をそのまま渡してください。"
        ) from e

    try:
        loc_block = settings["locations"][loc]
    except KeyError as e:
        keys = list(settings.get("locations", {}).keys())
        raise KeyError(
            f"[locations].{loc} が settings.toml にありません。候補: {keys}"
        ) from e

    index_root_raw = loc_block.get("index_root")
    if not index_root_raw:
        raise KeyError(f"[locations].{loc}.index_root が未設定です。")

    return Path(str(index_root_raw)).expanduser().resolve()


def sh(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


# =========================
# ページ設定
# =========================
st.set_page_config(page_title="🛠 メンテ切替", page_icon="🛠", layout="centered")
st.title("🛠 メンテナンス切替（最小版）")

# =========================
# メイン処理
# =========================
try:
    # 設定読み込み（secrets.toml 優先）
    settings = load_settings(SETTINGS_FILE)

    # index_root 解決
    INDEX_ROOT = resolve_index_root(settings)
    FLAG_PATH = INDEX_ROOT / "maintenance.flag"

    # 状態表示
    st.write({
        "env": settings["env"]["location"],
        "index_root": str(INDEX_ROOT),
        "flag_path": str(FLAG_PATH),
        "flag_exists": FLAG_PATH.exists(),
    })

    col1, col2 = st.columns(2)

    # -------------------------
    # メンテ開始
    # -------------------------
    with col1:
        if st.button("🚧 メンテ開始（flag作成 → reload）"):
            try:
                FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
                FLAG_PATH.touch(exist_ok=True)

                rc1, out1, err1 = sh([NGINX_BIN, "-t"])
                rc2, out2, err2 = (
                    sh([NGINX_BIN, "-s", "reload"])
                    if rc1 == 0
                    else (1, "", "nginx -t failed")
                )

                if rc1 == 0 and rc2 == 0:
                    st.success("✅ メンテ開始しました（flag作成＆nginx reload 成功）")
                else:
                    st.error("⚠️ nginx reload でエラーが発生しました")
                    st.code((out1 + err1 + out2 + err2).strip(), language="bash")

            except Exception as e:
                st.error(f"❌ 失敗: {e}")

    # -------------------------
    # メンテ終了
    # -------------------------
    with col2:
        if st.button("🟢 メンテ終了（flag削除 → reload）"):
            try:
                if FLAG_PATH.exists():
                    FLAG_PATH.unlink()

                rc1, out1, err1 = sh([NGINX_BIN, "-t"])
                rc2, out2, err2 = (
                    sh([NGINX_BIN, "-s", "reload"])
                    if rc1 == 0
                    else (1, "", "nginx -t failed")
                )

                if rc1 == 0 and rc2 == 0:
                    st.success("✅ メンテ終了しました（flag削除＆nginx reload 成功）")
                else:
                    st.error("⚠️ nginx reload でエラーが発生しました")
                    st.code((out1 + err1 + out2 + err2).strip(), language="bash")

            except Exception as e:
                st.error(f"❌ 失敗: {e}")

except Exception as e:
    st.error(f"❌ 初期化エラー: {e}")

st.caption(
    "※ `nginx -s reload` に権限が必要な環境では失敗します。"
    "その場合は NGINX_BIN を実際のバイナリに変更するか、"
    "brew services / systemctl 等で再起動してください。"
)
