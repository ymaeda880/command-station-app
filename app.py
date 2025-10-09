# app.py
import streamlit as st

st.set_page_config(page_title="🛰️ Command Station", page_icon="🛰️", layout="wide")

st.title("🛰️ Command Station")
st.markdown("""
社内サーバやローカルマシン上のコマンド実行・状態確認を行うためのツールです。  
安全に実行できる範囲に限定し、出力はWeb上で確認できます。

---

### 🔧 利用できるページ
- **ディスク状態**：接続ディスク・容量の確認  
- （将来）**Git操作**, **サービス再起動**, **ログ確認** などを追加予定

---

📂 ディレクトリ構成：
---
💡 コマンド実行関数は `lib/cmd_utils.py` に切り出されています。
""")