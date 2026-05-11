# command_station_app/pages/850_uploadチェック.py
# ============================================================
# アップロード挙動チェックページ
# ------------------------------------------------------------
# 機能:
# - st.file_uploader を3種類表示する
# - PDF専用 / Word専用 / 制限なし の挙動を比較する
# - アップロード後にファイル情報を表示する
# - nginx access_log から PUT /_stcore/upload_file 関連行を抽出する
# - nginx access_log から 404 行を抽出する
# - nginx error_log の直近行を表示する
# - access_log 原文と、分解した読みやすい解説を表示する
# ============================================================

from __future__ import annotations

# ============================================================
# import
# ============================================================
from pathlib import Path
import re
import streamlit as st


# ============================================================
# ページ定数
# ============================================================
PAGE_TITLE = "アップロードチェック"
PAGE_ICON = "🧪"
PAGE_NAME = "850_upload_check"

ACCESS_LOG_PATH = Path("/opt/homebrew/var/log/nginx/access.log")
ERROR_LOG_PATH = Path("/opt/homebrew/var/log/nginx/error.log")

DEFAULT_TAIL_LINES = 500


# ============================================================
# nginx access_log 解析用正規表現
# ============================================================
NGINX_ACCESS_RE = re.compile(
    r'^(?P<client_ip>\S+)\s+\S+\s+\S+\s+'
    r'\[(?P<time>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+(?P<protocol>[^"]+)"\s+'
    r'(?P<status>\d{3})\s+'
    r'(?P<bytes>\S+)\s+'
    r'"(?P<referer>[^"]*)"\s+'
    r'"(?P<user_agent>[^"]*)"'
)


# ============================================================
# 画面初期化
# ============================================================
st.set_page_config(
    page_title="Command Station",
    page_icon=PAGE_ICON,
    layout="wide",
)

st.title("🧪 アップロードチェック")
st.caption("PDF専用・Word専用・制限なしの uploader を比較し、nginx access_log / error_log を確認します。")


# ============================================================
# ログ読み込み関数
# ============================================================
def read_tail_lines(path: Path, max_lines: int = DEFAULT_TAIL_LINES) -> list[str]:
    if not path.exists():
        return []

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    return lines[-max_lines:]


# ============================================================
# access_log 解析関数
# ============================================================
def parse_nginx_access_line(line: str) -> dict[str, str] | None:
    m = NGINX_ACCESS_RE.match(line)
    if not m:
        return None
    return m.groupdict()


# ============================================================
# PUT upload_file ログ抽出関数
# ============================================================
def extract_put_upload_lines(lines: list[str]) -> list[str]:
    results: list[str] = []

    for line in lines:
        if '"PUT ' not in line:
            continue
        if "_stcore/upload_file" not in line:
            continue
        results.append(line)

    return results


# ============================================================
# 404ログ抽出関数
# ============================================================
def extract_404_lines(lines: list[str]) -> list[str]:
    results: list[str] = []

    for line in lines:
        parsed = parse_nginx_access_line(line)
        if parsed is None:
            continue
        if parsed.get("status") == "404":
            results.append(line)

    return results


# ============================================================
# _stcore 関連ログ抽出関数
# ============================================================
def extract_stcore_lines(lines: list[str]) -> list[str]:
    results: list[str] = []

    for line in lines:
        if "_stcore" in line:
            results.append(line)

    return results


# ============================================================
# upload_file 関連ログ抽出関数
# ============================================================
def extract_upload_file_lines(lines: list[str]) -> list[str]:
    results: list[str] = []

    for line in lines:
        if "_stcore/upload_file" in line:
            results.append(line)

    return results


# ============================================================
# ステータス説明関数
# ============================================================
def explain_status(status: str) -> str:
    if status == "204":
        return "204 → 成功です。ファイルは正常に受信されています。"
    if status.startswith("2"):
        return f"{status} → 成功系のレスポンスです。"
    if status == "404":
        return "404 → URLが見つからない状態です。パスのずれ、proxy、baseUrlPath、後続リクエストなどを確認します。"
    if status.startswith("4"):
        return f"{status} → クライアント側またはURL・権限・経路の問題が疑われます。"
    if status.startswith("5"):
        return f"{status} → nginxまたはStreamlit側のサーバーエラーが疑われます。"
    return f"{status} → 通常とは異なるステータスです。"


# ============================================================
# ファイル情報表示関数
# ============================================================
def render_uploaded_files(label: str, files) -> None:
    st.subheader(label)

    if not files:
        st.info("まだファイルはアップロードされていません。")
        return

    for f in files:
        st.caption(f"ファイル名: {f.name}")
        st.caption(f"MIME type: {getattr(f, 'type', '')}")
        st.caption(f"サイズ: {getattr(f, 'size', 0):,} bytes")
        st.markdown("---")


# ============================================================
# access_log 原文表示関数
# ============================================================
def render_raw_logs(title: str, lines: list[str], empty_message: str) -> None:
    st.subheader(title)

    if not lines:
        st.info(empty_message)
        return

    for i, line in enumerate(reversed(lines), start=1):
        with st.expander(f"{title} [{i}]", expanded=(i == 1)):
            st.code(line, language="text")


# ============================================================
# access_log 解説表示関数
# ============================================================
def render_explained_access_logs(title: str, lines: list[str], empty_message: str) -> None:
    st.subheader(title)

    if not lines:
        st.info(empty_message)
        return

    for i, line in enumerate(reversed(lines), start=1):
        parsed = parse_nginx_access_line(line)

        with st.expander(f"{title} [{i}]", expanded=(i == 1)):
            if parsed is None:
                st.warning("このログ行は自動分解できませんでした。原文を確認してください。")
                st.code(line, language="text")
                continue

            client_ip = parsed["client_ip"]
            time_text = parsed["time"]
            method = parsed["method"]
            path = parsed["path"]
            protocol = parsed["protocol"]
            status = parsed["status"]
            bytes_text = parsed["bytes"]
            referer = parsed["referer"]
            user_agent = parsed["user_agent"]

            st.caption(f"クライアントIP: {client_ip}")
            st.caption("→ アクセスまたはアップロードを行ったPCです。")

            st.caption(f"時刻: {time_text}")
            st.caption("→ この時刻に通信が発生しています。")

            st.caption(f"通信メソッド: {method}")
            if method == "PUT":
                st.caption("→ PUT は、ファイル本体をサーバーへ送信する通信です。")
            elif method == "GET":
                st.caption("→ GET は、画面・JS・CSS・後続データなどを取得する通信です。")
            elif method == "POST":
                st.caption("→ POST は、フォーム送信やAPI実行などで使われる通信です。")
            else:
                st.caption("→ HTTP通信の種類です。")

            st.caption(f"リクエスト先: {path}")
            if "_stcore/upload_file" in path:
                st.caption("→ _stcore/upload_file は、Streamlit のファイルアップロード用URLです。")
            elif "_stcore" in path:
                st.caption("→ _stcore は、Streamlit の内部通信です。")
            else:
                st.caption("→ nginxが受け取ったURLパスです。")

            st.caption(f"プロトコル: {protocol}")
            st.caption("→ HTTP通信のバージョンです。")

            st.caption(f"ステータスコード: {status}")
            if status == "204":
                st.success(explain_status(status))
            elif status.startswith("2"):
                st.info(explain_status(status))
            elif status.startswith("4") or status.startswith("5"):
                st.error(explain_status(status))
            else:
                st.warning(explain_status(status))

            st.caption(f"レスポンスサイズ: {bytes_text}")
            st.caption("→ nginxが返したレスポンス本文のサイズです。204の場合は 0 が正常です。")

            st.caption(f"操作画面・参照元: {referer}")
            st.caption("→ どの画面から発生した通信かを示します。")

            st.caption(f"ブラウザ情報: {user_agent}")
            st.caption("→ 使用ブラウザやOSの情報です。")

            st.markdown("#### 全体の意味")
            st.code(
                "ブラウザ（クライアントPC）\n"
                "  ↓\n"
                "nginx\n"
                "  ↓\n"
                "Streamlit または 静的ファイル\n"
                "  ↓\n"
                f"ステータスコード {status}",
                language="text",
            )


# ============================================================
# error_log 表示関数
# ============================================================
def render_error_log(lines: list[str]) -> None:
    st.subheader("nginx error_log 原文")

    if not lines:
        st.info("error_log は空、または読み込めませんでした。")
        return

    st.caption("直近の error_log です。アップロード時刻付近に upstream / connect / permission / client intended to send too large body などがないか確認します。")
    st.code("\n".join(lines), language="text")


# ============================================================
# サイド情報
# ============================================================
with st.expander("このページの見方", expanded=True):
    st.caption("PDF専用、Word専用、制限なしの3つの uploader で挙動を比較します。")
    st.caption("アップロード直後に nginx access_log の PUT /_stcore/upload_file 行を確認します。")
    st.caption("204 が出ていれば、アップロード通信は nginx 経由で正常に処理されています。")
    st.caption("404 が出る場合は、どのURLで404になっているかを確認します。")
    st.caption("PUT行が出ない場合は、nginxに届く前で止まっている可能性があります。")
    st.caption("error_log に upstream やサイズ制限などの情報が出ていないかも確認します。")


# ============================================================
# uploader 表示
# ============================================================
col1, col2, col3 = st.columns(3)

with col1:
    pdf_files = st.file_uploader(
        "PDF専用 uploader",
        type=["pdf"],
        accept_multiple_files=True,
        key=f"{PAGE_NAME}__pdf_uploader",
        help="type=['pdf'] の uploader です。",
    )

with col2:
    word_files = st.file_uploader(
        "Word専用 uploader",
        type=["doc", "docx"],
        accept_multiple_files=True,
        key=f"{PAGE_NAME}__word_uploader",
        help="type=['doc', 'docx'] の uploader です。",
    )

with col3:
    any_files = st.file_uploader(
        "制限なし uploader",
        type=None,
        accept_multiple_files=True,
        key=f"{PAGE_NAME}__any_uploader",
        help="type=None の uploader です。PDF/Word/zip/mp3などを比較できます。",
    )


# ============================================================
# アップロードファイル情報表示
# ============================================================
st.markdown("---")
st.header("アップロードされたファイル情報")

file_col1, file_col2, file_col3 = st.columns(3)

with file_col1:
    render_uploaded_files("PDF専用 uploader", pdf_files)

with file_col2:
    render_uploaded_files("Word専用 uploader", word_files)

with file_col3:
    render_uploaded_files("制限なし uploader", any_files)


# ============================================================
# nginxログ設定表示
# ============================================================
st.markdown("---")
st.header("nginx ログ確認")

log_path_col1, log_path_col2 = st.columns(2)

with log_path_col1:
    st.caption(f"access_log path: {ACCESS_LOG_PATH}")
    if ACCESS_LOG_PATH.exists():
        st.success("access_log を確認できます。")
    else:
        st.error("access_log が見つかりません。パスを確認してください。")

with log_path_col2:
    st.caption(f"error_log path: {ERROR_LOG_PATH}")
    if ERROR_LOG_PATH.exists():
        st.success("error_log を確認できます。")
    else:
        st.warning("error_log が見つかりません。パスを確認してください。")


# ============================================================
# nginxログ読み込み
# ============================================================
tail_lines = read_tail_lines(ACCESS_LOG_PATH, DEFAULT_TAIL_LINES)
error_lines = read_tail_lines(ERROR_LOG_PATH, 120)

put_lines = extract_put_upload_lines(tail_lines)
upload_file_lines = extract_upload_file_lines(tail_lines)
stcore_lines = extract_stcore_lines(tail_lines)
not_found_lines = extract_404_lines(tail_lines)


# ============================================================
# nginxログサマリー表示
# ============================================================
summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)

with summary_col1:
    st.metric("access_log 読み込み行数", f"{len(tail_lines):,}")

with summary_col2:
    st.metric("PUT upload_file 行数", f"{len(put_lines):,}")

with summary_col3:
    st.metric("404 行数", f"{len(not_found_lines):,}")

with summary_col4:
    latest_status = "-"
    if put_lines:
        parsed_latest = parse_nginx_access_line(put_lines[-1])
        if parsed_latest:
            latest_status = parsed_latest.get("status", "-")
    st.metric("最新PUTステータス", latest_status)


# ============================================================
# 判定メモ表示
# ============================================================
st.markdown("---")
st.header("簡易判定メモ")

if put_lines:
    parsed_latest_put = parse_nginx_access_line(put_lines[-1])
    latest_put_status = parsed_latest_put.get("status", "-") if parsed_latest_put else "-"

    if latest_put_status == "204":
        st.success("最新の PUT /_stcore/upload_file は 204 です。アップロード本体は成功しています。")
    elif latest_put_status == "404":
        st.error("最新の PUT /_stcore/upload_file が 404 です。アップロードURL、baseUrlPath、proxy_pass、経路の確認が必要です。")
    else:
        st.warning(f"最新の PUT /_stcore/upload_file は {latest_put_status} です。詳細ログを確認してください。")
else:
    st.warning("PUT /_stcore/upload_file のログがありません。nginxにアップロード本体が届いていない可能性があります。")

if not_found_lines:
    st.error("404行があります。404になっているURLとメソッドを必ず確認してください。")
else:
    st.info("直近ログ内では404行は見つかりませんでした。")


# ============================================================
# タブ表示
# ============================================================
st.markdown("---")
st.header("ログ詳細")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    [
        "PUT原文",
        "PUT解説",
        "404原文",
        "404解説",
        "_stcore関連",
        "error_log",
    ]
)

with tab1:
    render_raw_logs(
        title="nginx access_log 原文（PUT / upload_file）",
        lines=put_lines,
        empty_message="PUT /_stcore/upload_file 関連のログは見つかりませんでした。",
    )

with tab2:
    render_explained_access_logs(
        title="PUTログのわかりやすい解説",
        lines=put_lines,
        empty_message="解説対象のPUTログがありません。",
    )

with tab3:
    render_raw_logs(
        title="nginx access_log 原文（404）",
        lines=not_found_lines,
        empty_message="404 のログは見つかりませんでした。",
    )

with tab4:
    render_explained_access_logs(
        title="404ログのわかりやすい解説",
        lines=not_found_lines,
        empty_message="解説対象の404ログがありません。",
    )

with tab5:
    render_raw_logs(
        title="nginx access_log 原文（_stcore関連）",
        lines=stcore_lines,
        empty_message="_stcore 関連のログは見つかりませんでした。",
    )

with tab6:
    render_error_log(error_lines)


# ============================================================
# 全ログ確認
# ============================================================
with st.expander("直近のaccess_log全体を表示", expanded=False):
    if not tail_lines:
        st.info("表示できるログがありません。")
    else:
        st.code("\n".join(tail_lines), language="text")