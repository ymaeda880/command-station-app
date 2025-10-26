# pages/82_証明書管理.py
# ==========================================
# 🔐 証明書管理（自己署名の発行 / 再発行 / 情報表示）
# - 複数 SAN（全server_name）を含めて発行
# ==========================================

from __future__ import annotations
from pathlib import Path
import streamlit as st
import tomllib
import tempfile
from lib.nginx_utils import run_cmd

st.set_page_config(page_title="証明書管理（自己署名）", page_icon="🔐", layout="centered")
st.title("🔐 証明書管理 — 自己署名の発行 / 再発行")

# ======== 1️⃣ 現在の環境を取得 ========
env_name = st.secrets["env"]["location"]

# ======== 2️⃣ settings.toml を読み込み ========
SETTINGS_FILE = Path(__file__).parents[1] / ".streamlit" / "settings.toml"
with open(SETTINGS_FILE, "rb") as f:
    settings = tomllib.load(f)

loc = settings["locations"][env_name]
server_names: list[str] = loc["server_name"]
user = loc.get("user", "(unknown)")

# ======== 3️⃣ ページ表示 ========
st.caption(f"🖥 現在の環境: **{env_name}**（ユーザー: {user}）")

st.markdown("### 🌐 ホスト名（すべて）")
for s in server_names:
    st.markdown(f"- `{s}`")

# ======== 4️⃣ 入力フォーム ========
col1, col2 = st.columns(2)
with col1:
    cn = st.text_input("CN（Common Name / 主ホスト名）", value=server_names[0],
                       help="証明書のメイン名（nginxのserver_nameの先頭と一致）")
    days = st.number_input("有効日数", min_value=1, max_value=7300, value=365)
with col2:
    cert_path = st.text_input("証明書ファイル（.crt）", value=str(Path.home() / f"ssl/certs/{cn}.crt"))
    key_path  = st.text_input("秘密鍵ファイル（.key）", value=str(Path.home() / f"ssl/private/{cn}.key"))

st.caption("💡 上記ホスト名はすべて SAN に含まれます。既存ファイルがある場合は上書き。")

# ======== 5️⃣ SAN全部入り自己署名証明書の発行 ========
def create_self_signed_cert_all_san(cert_path: Path, key_path: Path, days: int, cn: str, sans: list[str]):
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    san_entries = ",".join(f"DNS:{s}" for s in sans)

    config_text = f"""
    [req]
    default_bits       = 2048
    prompt             = no
    default_md         = sha256
    req_extensions     = req_ext
    distinguished_name = dn

    [dn]
    CN = {cn}

    [req_ext]
    subjectAltName = {san_entries}

    [v3_ext]
    subjectAltName = {san_entries}
    """

    with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
        tmp.write(config_text)
        cfg_path = Path(tmp.name)

    cmd = [
        "openssl", "req", "-x509", "-nodes",
        "-newkey", "rsa:2048",
        "-keyout", str(key_path),
        "-out", str(cert_path),
        "-days", str(days),
        "-config", str(cfg_path),
        "-extensions", "v3_ext",
    ]
    return run_cmd(cmd)

# ======== 6️⃣ ボタン群 ========
# 先にボタンだけをcolumnsに配置
cA, cB, cC = st.columns(3)
with cA:
    gen = st.button("📜 SAN全部入り証明書を発行 / 再発行", type="primary")
with cB:
    show_detail = st.button("🔎 証明書情報を表示（詳細）")
with cC:
    show_expiry = st.button("⏱ 有効期限のみ表示")

# columnsの外（全幅）で結果を出す
if gen:
    code, out = create_self_signed_cert_all_san(
        cert_path=Path(cert_path),
        key_path=Path(key_path),
        days=int(days),
        cn=cn,
        sans=server_names,
    )
    (st.success if code == 0 else st.error)("発行 " + ("✅" if code == 0 else "❌"))
    st.code(out or "(no output)", height=600)

elif show_detail:
    code, out = run_cmd(["openssl", "x509", "-in", cert_path, "-text", "-noout"])
    (st.success if code == 0 else st.error)("表示 " + ("✅" if code == 0 else "❌"))
    st.code(out or "(no output)", height=600)

elif show_expiry:
    code, out = run_cmd(["openssl", "x509", "-in", cert_path, "-noout", "-enddate"])
    (st.success if code == 0 else st.error)("表示 " + ("✅" if code == 0 else "❌"))
    st.code(out or "(no output)", height=200)


st.divider()
st.info(
    "発行後は **nginx 管理ページ** に戻り、"
    "`ssl_certificate` と `ssl_certificate_key` に上記パスを指定し、"
    "443番ポートのサーバーブロックを保存 → 構文チェック → 再起動してください。"
)
