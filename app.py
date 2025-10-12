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
            
---

使用方法（projectの作成）
---

**新たにprojectを作成するとき**

1. [python仮想環境構築]で，アプリのフォルダを作る（READMEなども同時作成）
1. [python仮想環境構築]で，仮想環境を構築
            
**git cloneするprojectを作成するとき**            
1. [python仮想環境構築]で，アプリのフォルダを作る（READMEなどは作成しない）
1. [プロジェクト一覧とGit]でgit clone
1. [python仮想環境構築]で，仮想環境を構築
1. [インストール用コマンド] install実行

使用方法（projectのデプロイ）
---

portは8501~8599
                       
1. nginx.confの作成の準備
            
nginx.tmol（command_station_app）の設定

---- 各アプリのポート定義（nginx.confの作成） ----

```
[bot]
port = 8501
enabled = true     # 起動対象
```

2. config.toml（各アプリ）の設定

```        
# .streamlit/config.toml
# プロジェクト名：command_station_app

[server]
port = 8505
address = "0.0.0.0"
baseUrlPath = "/command_station"
enableCORS = false
headless = true
```

3. index.htmlの設定





一般的な操作
---
            
- アプリケーションフォルダーの作成
            
プロジェクトフォルダーを作成しその中にアプリケーションフォルダーを作成する．
            
- 新しいアプリケーションの時
            
「python仮想環境構築」より仮想環境を構築し，ライブラリーのインポートなどを行う
            
- アプリケーションをgitクローンするとき
            
    1. 「プロジェクト走査とGit操作」より，プリケーションフォルダーを操作対象として「git clone」を行う．

    1. 「python仮想環境構築」より仮想環境を構築し，ライブラリーのインポートなどを行う．
            
    1. secrets.tomlの作成と設定
""")

