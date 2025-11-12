# pages/90_証明書管理.py
# ==========================================
# 🔐 証明書管理（自己署名の発行 / 再発行 / 情報表示）
# - settings.toml の server_name をすべて SAN に入れる
# - local_host_name が定義されていれば <name>.local を SAN に追加
# - X509v3 拡張: SAN / SKI / AKI / keyUsage / extendedKeyUsage / basicConstraints
# ==========================================

from __future__ import annotations
from pathlib import Path
import re
import tempfile

import streamlit as st

# Python 3.11+ は tomllib、3.10 以下は tomli を利用
try:
    import tomllib  # type: ignore
except Exception:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from lib.nginx_utils import run_cmd

# ---------------- 画面初期化 ----------------
st.set_page_config(page_title="証明書管理（自己署名）", page_icon="🔐", layout="wide")
st.title("🔐 証明書管理 — 自己署名の発行 / 再発行")


# ---------------- ヘルパー ----------------
def _settings_path() -> Path:
    # アプリルート/.streamlit/settings.toml を想定
    return Path(__file__).resolve().parents[1] / ".streamlit" / "settings.toml"

def _sanitize_mdns(name: str) -> str:
    # mDNS名(LocalHostName)は英数字とハイフンのみ
    return re.sub(r"[^A-Za-z0-9-]", "", name or "")

def _split_dns_ip(items: list[str]) -> tuple[list[str], list[str]]:
    """ '1.2.3.4' や '::1' は IP、それ以外は DNS とみなす """
    dns, ips = [], []
    for s in items:
        s = (s or "").strip()
        if not s:
            continue
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", s) or ":" in s:
            ips.append(s)
        else:
            dns.append(s)
    return dns, ips

def _unique_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for x in items:
        if x not in seen and x:
            seen.add(x)
            out.append(x)
    return out

def build_san_list_from_settings() -> tuple[str, dict, list[str]]:
    """
    settings.toml と secrets から現在環境を決定し、
    - server_name をベースに
    - local_host_name があれば <name>.local を追加
    を行った SAN 一覧を返す。
    戻り値: (env_name, loc(dict), sans(list[str]))
    """
    # 現在環境（secrets が無い場合は最初の locations）
    try:
        env_name = st.secrets["env"]["location"]
    except Exception:
        env_name = None

    settings_file = _settings_path()
    try:
        settings = tomllib.loads(settings_file.read_text(encoding="utf-8"))
    except Exception as e:
        st.error(f"settings.toml の読み込みに失敗しました: {e}")
        st.stop()

    locations = settings.get("locations", {})
    if not env_name:
        env_name = next(iter(locations.keys()), None)
        if not env_name:
            st.error("settings.toml に locations が見つかりません。")
            st.stop()

    loc = locations.get(env_name)
    if not isinstance(loc, dict):
        st.error(f"settings.toml の locations.{env_name} が見つかりません。")
        st.stop()

    # server_name（ベース）
    names = list(loc.get("server_name", []))

    # local_host_name が明示されている場合のみ *.local を追加
    lh = loc.get("local_host_name")
    if isinstance(lh, str) and lh.strip():
        mdns = _sanitize_mdns(lh.strip()) + ".local"
        if mdns not in names:
            names.append(mdns)

    sans = _unique_keep_order(names)
    return env_name, loc, sans


def issue_self_signed_with_san(cert_path: Path, key_path: Path, days: int, cn: str, sans: list[str]):
    """
    SAN（DNS と IP を混在可）/ SKI / AKI / Usage を付けた自己署名を発行
    """
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    dns_list, ip_list = _split_dns_ip(sans)
    san_line = ",".join(
        [*(f"DNS:{d}" for d in dns_list), *(f"IP:{ip}" for ip in ip_list)]
    ) or f"DNS:{cn}"

    openssl_conf = f"""
[req]
default_bits       = 2048
prompt             = no
default_md         = sha256
distinguished_name = dn
x509_extensions    = v3_ext

[dn]
CN = {cn}

[v3_ext]
subjectAltName          = {san_line}
basicConstraints        = CA:FALSE
keyUsage                = digitalSignature, keyEncipherment
extendedKeyUsage        = serverAuth
subjectKeyIdentifier    = hash
authorityKeyIdentifier  = keyid,issuer
"""

    with tempfile.NamedTemporaryFile("w+", delete=False) as fp:
        fp.write(openssl_conf)
        cfg_path = Path(fp.name)

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


# ---------------- 設定読み込み & 表示 ----------------
env_name, loc, san_candidates = build_san_list_from_settings()
user = loc.get("user", "(unknown)")

st.caption(f"🖥 現在の環境: **{env_name}**　👤 ユーザー: **{user}**")
st.markdown("### 🌐 SAN 候補（settings.toml 由来）")
if san_candidates:
    st.code("\n".join(san_candidates), language="bash")
else:
    st.warning("server_name が空です。最低でも 'localhost' を settings.toml に入れてください。")


# ---------------- 入力フォーム ----------------
col1, col2 = st.columns(2)
with col1:
    # デフォルト CN: 候補の先頭（先頭に使いたい FQDN を settings 側で並べてください）
    default_cn = san_candidates[0] if san_candidates else "localhost"
    cn = st.selectbox(
        "CN（Common Name / 主ホスト名）",
        options=san_candidates or ["localhost"],
        index=(san_candidates.index(default_cn) if san_candidates else 0),
        help="証明書の主ホスト名。SAN にも同名を含めます。",
    )

    days = st.number_input("有効日数（days）", min_value=1, max_value=825, value=365, step=1,
                           help="Let’s Encrypt 相当の上限 825 日を上限目安にしています。")

with col2:
    cert_path = st.text_input(
        "証明書ファイル（.crt）",
        value=str(Path.home() / f"ssl/certs/{cn}.crt"),
        help="書き込み可能な場所を指定。既存ファイルは上書きされます。"
    )
    key_path  = st.text_input(
        "秘密鍵ファイル（.key）",
        value=str(Path.home() / f"ssl/private/{cn}.key"),
        help="秘密鍵のパス。既存ファイルは上書きされます。"
    )

# SAN 選択（CN を必ず含める）
san_selected = st.multiselect(
    "SAN（複数可：ここに入った名前/IPだけがブラウザ検証で許可されます）",
    options=san_candidates or ["localhost"],
    default=san_candidates or ["localhost"],
)
if cn not in san_selected:
    san_selected = [cn] + san_selected

st.caption("💡 **SAN には実際にアクセスするホスト名/IPをすべて入れてください。** "
           "開発用に IP 直打ちも想定するなら `192.168.x.y` を `server_name` に入れておきましょう。")


# ---------------- アクションボタン（横並び） ----------------
cA, cB, cC = st.columns(3)
with cA:
    do_issue = st.button("📜 証明書を発行 / 再発行", type="primary")
with cB:
    show_detail = st.button("🔎 証明書情報を表示（openssl x509 -text）")
with cC:
    show_expiry = st.button("⏱ 有効期限のみ表示（notAfter）")


# ---------------- 実行結果（全幅に表示） ----------------
if do_issue:
    code, out = issue_self_signed_with_san(
        cert_path=Path(cert_path),
        key_path=Path(key_path),
        days=int(days),
        cn=cn,
        sans=_unique_keep_order(san_selected),
    )
    (st.success if code == 0 else st.error)("発行 " + ("✅" if code == 0 else "❌"))
    st.code(out or "(no output)", height=520)

elif show_detail:
    code, out = run_cmd(["openssl", "x509", "-in", cert_path, "-text", "-noout"])
    (st.success if code == 0 else st.error)("表示 " + ("✅" if code == 0 else "❌"))
    st.code(out or "(no output)", height=520)

elif show_expiry:
    code, out = run_cmd(["openssl", "x509", "-in", cert_path, "-noout", "-enddate"])
    (st.success if code == 0 else st.error)("表示 " + ("✅" if code == 0 else "❌"))
    st.code(out or "(no output)", height=200)


# ---------------- 注意書き ----------------
st.divider()
st.info(
    "発行後は **nginx 管理ページ** に戻り、"
    "`ssl_certificate` と `ssl_certificate_key` に上記パスを指定し、"
    "443番ポートの server ブロックを保存 → 構文チェック → 再起動してください。\n\n"
    "※ 開発時は HSTS を付けない方が安全です。自己署名は常に警告対象です。"
)
