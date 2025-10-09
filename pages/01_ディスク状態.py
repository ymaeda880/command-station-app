# pages/01_ディスク状態.py
from __future__ import annotations
import shutil
import platform
import streamlit as st
import subprocess
import pandas as pd

from lib.cmd_utils import run_safe

st.set_page_config(page_title="💽 ディスク状態", page_icon="💽", layout="wide")
st.title("💽 ディスク状態 — ディスク容量・マウント情報")

st.caption("`df -h` や `diskutil list` を安全に実行して、Web上に結果を表示します。")

# -------------------------------
# df -h 実行
# -------------------------------
st.subheader("📊 `df -h` の出力")
code, out, err = run_safe("df -h")
if out:
    st.code(out, language="bash")
if err:
    st.error(err)

# -------------------------------
# diskutil list (macOS限定)
# -------------------------------
if platform.system() == "Darwin":
    st.subheader("🧩 `diskutil list` の出力")
    code, out, err = run_safe("diskutil list")
    if out:
        st.code(out, language="bash")
    if err:
        st.error(err)
else:
    st.info("このコマンドは macOS 専用です。")

# -------------------------------
# shutil.disk_usage による空き容量
# -------------------------------
st.divider()
st.subheader("📁 `shutil.disk_usage` による空き容量チェック")

target = st.text_input("対象パス", "/")
try:
    total, used, free = shutil.disk_usage(target)
    def h(b): return f"{b / (1024**3):.2f} GB"
    st.write(f"**Path**: `{target}`")
    st.write(f"- 総容量: {h(total)}")
    st.write(f"- 使用済: {h(used)}")
    st.write(f"- 空き: {h(free)}")
except Exception as e:
    st.error(f"取得に失敗しました: {e}")
