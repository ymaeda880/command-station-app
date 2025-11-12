# pages/72_メンテナンス.py
# 最小実装：メンテ開始/終了ボタン + nginx リロード
from __future__ import annotations
from pathlib import Path
import subprocess
import streamlit as st

# ここはあなたの既存設定と同じにしておく
INDEX_ROOT = "/Users/macmini2025/projects/apps_portal"   # DEFAULT_INDEX_ROOT と同じ
NGINX_BIN  = "nginx"  # PATHが通っていればこのままでOK。必要なら"/opt/homebrew/bin/nginx"等に。

FLAG_PATH = Path(INDEX_ROOT) / "maintenance.flag"

st.set_page_config(page_title="メンテ切替", page_icon="🛠", layout="centered")
st.title("🛠 メンテナンス切替（最小版）")

def sh(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr

st.write({"index_root": str(INDEX_ROOT),
          "flag_path": str(FLAG_PATH),
          "flag_exists": FLAG_PATH.exists()})

col1, col2 = st.columns(2)

with col1:
    if st.button("🚧 メンテ開始（flag作成 → reload）", use_container_width=True):
        try:
            FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
            FLAG_PATH.touch(exist_ok=True)
            rc1, out1, err1 = sh([NGINX_BIN, "-t"])
            rc2, out2, err2 = sh([NGINX_BIN, "-s", "reload"]) if rc1 == 0 else (1,"","nginx -t failed")
            if rc1 == 0 and rc2 == 0:
                st.success("✅ メンテ開始しました（flag作成＆nginx reload 成功）")
            else:
                st.error("⚠️ リロードでエラー。ログを確認してください。")
                st.code((out1+err1+out2+err2).strip(), language="bash")
        except Exception as e:
            st.error(f"❌ 失敗: {e}")

with col2:
    if st.button("🟢 メンテ終了（flag削除 → reload）", use_container_width=True):
        try:
            if FLAG_PATH.exists():
                FLAG_PATH.unlink()
            rc1, out1, err1 = sh([NGINX_BIN, "-t"])
            rc2, out2, err2 = sh([NGINX_BIN, "-s", "reload"]) if rc1 == 0 else (1,"","nginx -t failed")
            if rc1 == 0 and rc2 == 0:
                st.success("✅ メンテ終了しました（flag削除＆nginx reload 成功）")
            else:
                st.error("⚠️ リロードでエラー。ログを確認してください。")
                st.code((out1+err1+out2+err2).strip(), language="bash")
        except Exception as e:
            st.error(f"❌ 失敗: {e}")

st.caption("※ `nginx -s reload` に権限が必要な環境では失敗します。その場合は NGINX_BIN を実際のバイナリに変更するか、サービス管理で再起動してください。")
