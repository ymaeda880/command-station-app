# command_station_app/pages/176_システムチェック.py
# ============================================================
# システムチェックページ
# ------------------------------------------------------------
# 機能:
# - nginx 実行用ディレクトリの状態確認
# - nginx client_body_temp の状態確認
# - nginx process の起動状態確認
# - client_body_temp 所有者と nginx worker user の一致確認
# - client_body_temp 所有者の書き込み権限確認
# - 問題がある場合の原因と修正方法を表示する
# - 将来的なシステムチェック項目の追加先とする
# ============================================================

from __future__ import annotations

# ============================================================
# import
# ============================================================
from dataclasses import dataclass
from pathlib import Path
import pwd
import stat
import subprocess
import streamlit as st


# ============================================================
# ページ定数
# ============================================================
PAGE_TITLE = "システムチェック"
PAGE_ICON = "🩺"
PAGE_NAME = "820_system_check"

NGINX_RUN_DIR = Path("/opt/homebrew/var/run/nginx")
CLIENT_BODY_TEMP_DIR = Path("/opt/homebrew/var/run/nginx/client_body_temp")

COMMAND_TIMEOUT_SEC = 5


# ============================================================
# 画面初期化
# ============================================================
st.set_page_config(
    page_title="Command Station",
    page_icon=PAGE_ICON,
    layout="wide",
)

st.title("🩺 システムチェック")
st.caption("nginx の client_body_temp 権限や nginx プロセス状態を確認します。")


# ============================================================
# コマンド結果モデル
# ============================================================
@dataclass
class CommandResult:
    command: list[str]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False


# ============================================================
# ディレクトリ状態モデル
# ============================================================
@dataclass
class PathStatus:
    path: Path
    exists: bool
    is_dir: bool
    mode_text: str
    owner_uid: int | None
    owner_name: str
    group_gid: int | None
    error: str = ""


# ============================================================
# 判定結果モデル
# ============================================================
@dataclass
class CheckMessage:
    level: str
    title: str
    detail: str


# ============================================================
# コマンド実行
# ============================================================
def run_command(command: list[str]) -> CommandResult:
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=COMMAND_TIMEOUT_SEC,
        )
        return CommandResult(
            command=command,
            returncode=result.returncode,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
            timed_out=False,
        )
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout if isinstance(e.stdout, str) else ""
        stderr = e.stderr if isinstance(e.stderr, str) else ""

        return CommandResult(
            command=command,
            returncode=None,
            stdout=stdout.strip(),
            stderr=stderr.strip(),
            timed_out=True,
        )
    except Exception as e:
        return CommandResult(
            command=command,
            returncode=None,
            stdout="",
            stderr=str(e),
            timed_out=False,
        )


# ============================================================
# uid からユーザー名取得
# ============================================================
def uid_to_name(uid: int | None) -> str:
    if uid is None:
        return ""

    try:
        return pwd.getpwuid(uid).pw_name
    except Exception:
        return str(uid)


# ============================================================
# パス状態取得
# ============================================================
def get_path_status(path: Path) -> PathStatus:
    if not path.exists():
        return PathStatus(
            path=path,
            exists=False,
            is_dir=False,
            mode_text="",
            owner_uid=None,
            owner_name="",
            group_gid=None,
            error="パスが存在しません。",
        )

    try:
        st_result = path.stat()
        mode_text = stat.filemode(st_result.st_mode)
        owner_name = uid_to_name(st_result.st_uid)

        return PathStatus(
            path=path,
            exists=True,
            is_dir=path.is_dir(),
            mode_text=mode_text,
            owner_uid=st_result.st_uid,
            owner_name=owner_name,
            group_gid=st_result.st_gid,
            error="",
        )
    except Exception as e:
        return PathStatus(
            path=path,
            exists=True,
            is_dir=False,
            mode_text="",
            owner_uid=None,
            owner_name="",
            group_gid=None,
            error=str(e),
        )


# ============================================================
# nginx ps 行抽出
# ============================================================
def extract_nginx_process_lines(ps_output: str) -> list[str]:
    lines: list[str] = []

    for line in ps_output.splitlines():
        if "nginx:" not in line:
            continue
        if "grep nginx" in line:
            continue
        lines.append(line)

    return lines


# ============================================================
# nginx worker 行抽出
# ============================================================
def extract_nginx_worker_lines(ps_output: str) -> list[str]:
    lines: list[str] = []

    for line in ps_output.splitlines():
        if "nginx: worker process" not in line:
            continue
        lines.append(line)

    return lines


# ============================================================
# ps 行からユーザー抽出
# ============================================================
def extract_users_from_ps_lines(lines: list[str]) -> list[str]:
    users: list[str] = []

    for line in lines:
        parts = line.split()
        if not parts:
            continue

        user = parts[0]
        if user not in users:
            users.append(user)

    return users


# ============================================================
# 権限文字列から所有者書込可否を判定
# ============================================================
def owner_can_write(mode_text: str) -> bool:
    return len(mode_text) >= 4 and mode_text[2] == "w"


# ============================================================
# 権限文字列からグループ書込可否を判定
# ============================================================
def group_can_write(mode_text: str) -> bool:
    return len(mode_text) >= 7 and mode_text[5] == "w"


# ============================================================
# 権限文字列からその他書込可否を判定
# ============================================================
def other_can_write(mode_text: str) -> bool:
    return len(mode_text) >= 10 and mode_text[8] == "w"


# ============================================================
# 権限文字列から所有者進入可否を判定
# ============================================================
def owner_can_enter(mode_text: str) -> bool:
    return len(mode_text) >= 4 and mode_text[3] == "x"


# ============================================================
# client_body_temp 判定
# ============================================================
def check_client_body_temp(
    *,
    nginx_run_status: PathStatus,
    client_temp_status: PathStatus,
    nginx_process_lines: list[str],
    nginx_worker_lines: list[str],
) -> list[CheckMessage]:
    messages: list[CheckMessage] = []

    nginx_worker_users = extract_users_from_ps_lines(nginx_worker_lines)

    # ------------------------------------------------------------
    # nginx 実行用ディレクトリ確認
    # ------------------------------------------------------------
    if not nginx_run_status.exists:
        messages.append(
            CheckMessage(
                level="error",
                title="nginx 実行用ディレクトリが存在しません。",
                detail=f"{nginx_run_status.path} が存在しません。",
            )
        )
    elif not nginx_run_status.is_dir:
        messages.append(
            CheckMessage(
                level="error",
                title="nginx 実行用パスがディレクトリではありません。",
                detail=f"{nginx_run_status.path} を確認してください。",
            )
        )
    else:
        messages.append(
            CheckMessage(
                level="success",
                title="nginx 実行用ディレクトリが正常に存在してます。",
                detail=(
                    f"path={nginx_run_status.path} / "
                    f"permission={nginx_run_status.mode_text} / "
                    f"owner={nginx_run_status.owner_name}"
                ),
            )
        )

    # ------------------------------------------------------------
    # nginx process 確認
    # ------------------------------------------------------------
    if not nginx_process_lines:
        messages.append(
            CheckMessage(
                level="error",
                title="nginx プロセスが確認できません。",
                detail="nginx が起動していない可能性があります。",
            )
        )
    else:
        messages.append(
            CheckMessage(
                level="success",
                title="nginx プロセスが正常に起動しています。",
                detail=f"nginx process 行数={len(nginx_process_lines)}",
            )
        )

    # ------------------------------------------------------------
    # nginx worker process 確認
    # ------------------------------------------------------------
    if not nginx_worker_lines:
        messages.append(
            CheckMessage(
                level="error",
                title="nginx worker process が確認できません。",
                detail="アップロード処理を実際に行う worker process が見つかりません。",
            )
        )
    else:
        messages.append(
            CheckMessage(
                level="success",
                title=(
                    "アップロード処理を行う nginx worker process は、"
                    f"ユーザー {', '.join(nginx_worker_users)} "
                    "で動作しています。"
                ),
                detail=(
                    "worker process は実際にアップロード一時ファイルを "
                    "書き込むプロセスです。"
                ),
            )
        )

    # ------------------------------------------------------------
    # client_body_temp 存在確認
    # ------------------------------------------------------------
    if not client_temp_status.exists:
        messages.append(
            CheckMessage(
                level="error",
                title="client_body_temp が存在しません。",
                detail="アップロード時の一時保存先が存在しないため、アップロード失敗の原因になります。",
            )
        )
        return messages

    if not client_temp_status.is_dir:
        messages.append(
            CheckMessage(
                level="error",
                title="client_body_temp がディレクトリではありません。",
                detail=f"{client_temp_status.path} を確認してください。",
            )
        )
        return messages

    # ------------------------------------------------------------
    # client_body_temp 基本情報
    # ------------------------------------------------------------
    mode_text = client_temp_status.mode_text
    owner_name = client_temp_status.owner_name

    messages.append(
        CheckMessage(
            level="success",
            title="client_body_temp （アップロード一時フォルダー）が正常に存在しています．",
            detail=(
                f"path={client_temp_status.path} / "
                f"permission={mode_text} / "
                f"owner={owner_name}"
            ),
        )
    )

    # ------------------------------------------------------------
    # 所有者と nginx worker user の一致確認
    # ------------------------------------------------------------
    if nginx_worker_users:
        if owner_name in nginx_worker_users:
            messages.append(
                CheckMessage(
                    level="success",
                    title="client_body_temp 所有者と nginx worker user が一致しています。",
                    detail=f"owner={owner_name} / worker={', '.join(nginx_worker_users)}",
                )
            )
        else:
            messages.append(
                CheckMessage(
                    level="error",
                    title="client_body_temp 所有者と nginx worker user が不一致です。",
                    detail=f"owner={owner_name} / worker={', '.join(nginx_worker_users)}",
                )
            )

    # ------------------------------------------------------------
    # nginx worker user の書き込み可否確認
    # ------------------------------------------------------------
    if owner_can_write(mode_text):
        messages.append(
            CheckMessage(
                level="success",
                title=(
                    "nginx worker user は、"
                    "client_body_temp 所有者権限で "
                    "書き込み可能です。"
                ),
                detail=(
                    "nginx worker process は、"
                    "自身が動作しているユーザー権限で "
                    "client_body_temp にアップロード一時ファイルを書き込み可能です。 "
                    f"owner={owner_name} / "
                    f"worker={', '.join(nginx_worker_users)} / "
                    f"permission={mode_text}"
                ),
            )
        )
    else:
        messages.append(
            CheckMessage(
                level="error",
                title="client_body_temp 所有者に書き込み権限がありません。",
                detail=f"permission={mode_text}",
            )
        )

    # ------------------------------------------------------------
    # nginx worker user のディレクトリ進入可否確認
    # ------------------------------------------------------------
    if owner_can_enter(mode_text):
        messages.append(
            CheckMessage(
                level="success",
                title=(
                    "nginx worker user は、"
                    "client_body_temp 所有者権限で "
                    "ディレクトリへ進入可能です。"
                ),
                detail=(
                    "nginx worker process は、"
                    "自身が動作しているユーザー権限で "
                    "client_body_temp ディレクトリへ進入可能です。 "
                    f"owner={owner_name} / "
                    f"worker={', '.join(nginx_worker_users)} / "
                    f"permission={mode_text}"
                ),
            )
        )
    else:
        messages.append(
            CheckMessage(
                level="error",
                title="client_body_temp 所有者にディレクトリ進入権限がありません。",
                detail=f"permission={mode_text}",
            )
        )

    # ------------------------------------------------------------
    # 700 権限の扱い
    # ------------------------------------------------------------
    if mode_text.startswith("drwx------"):
        if nginx_worker_users and owner_name in nginx_worker_users and owner_can_write(mode_text):
            messages.append(
                CheckMessage(
                    level="success",
                    title="client_body_temp は 700 権限ですが問題ありません。",
                    detail=(
                        "700 権限（drwx------）は、"
                        "owner のみが読み書き・ディレクトリ進入可能で、"
                        "group や others はアクセスできない設定です。 "
                        "今回は nginx worker user と owner が一致しているため、"
                        "nginx は owner 権限で正常にアップロード一時ファイルを "
                        "書き込みできます。 "
                        f"owner={owner_name} / "
                        f"worker={', '.join(nginx_worker_users)} / "
                        f"permission={mode_text}"
                    ),
                )
            )
        else:
            messages.append(
                CheckMessage(
                    level="error",
                    title="client_body_temp が 700 権限で、nginx worker が使えない可能性があります。",
                    detail="700 自体は問題ではありませんが、所有者と worker user が不一致の場合はアップロード失敗の原因になります。",
                )
            )

    # ------------------------------------------------------------
    # その他ユーザー書き込み可の注意
    # ------------------------------------------------------------
    if other_can_write(mode_text):
        messages.append(
            CheckMessage(
                level="warning",
                title="client_body_temp がその他ユーザー書き込み可です。",
                detail=f"permission={mode_text}。動作はしやすいですが、権限が広すぎる可能性があります。",
            )
        )

    # ------------------------------------------------------------
    # グループ書き込み可の補足
    # ------------------------------------------------------------
    if group_can_write(mode_text):
        messages.append(
            CheckMessage(
                level="info",
                title="client_body_temp はグループ書き込み可です。",
                detail=f"permission={mode_text}",
            )
        )

    return messages


# ============================================================
# 修正コマンド作成
# ============================================================
def build_fix_command() -> str:
    return """sudo mkdir -p /opt/homebrew/var/run/nginx/client_body_temp
sudo chown -R y-maeda:admin /opt/homebrew/var/run/nginx/client_body_temp
sudo chmod -R 755 /opt/homebrew/var/run/nginx/client_body_temp"""


# ============================================================
# コマンド文字列表示
# ============================================================
def command_to_text(command: list[str]) -> str:
    return " ".join(command)


# ============================================================
# コマンド結果表示
# ============================================================
def render_command_result(result: CommandResult) -> None:
    st.caption(f"実行コマンド: `{command_to_text(result.command)}`")

    if result.timed_out:
        st.error("コマンドがタイムアウトしました。")
    elif result.returncode == 0:
        st.success("コマンドは正常終了しました。")
    else:
        st.error(f"コマンドが異常終了しました。returncode={result.returncode}")

    if result.stdout:
        st.code(result.stdout, language="text")
    else:
        st.caption("stdout は空です。")

    if result.stderr:
        st.caption("stderr")
        st.code(result.stderr, language="text")


# ============================================================
# パス状態表示
# ============================================================
def render_path_status(title: str, status: PathStatus) -> None:
    st.subheader(title)

    if not status.exists:
        st.error("存在しません。")
        st.caption(f"path: {status.path}")
        return

    if status.error:
        st.error(status.error)

    st.caption(f"path: {status.path}")
    st.caption(f"directory: {status.is_dir}")
    st.caption(f"permission: {status.mode_text}")
    st.caption(f"owner uid: {status.owner_uid}")
    st.caption(f"owner name: {status.owner_name}")
    st.caption(f"group gid: {status.group_gid}")


# ============================================================
# 判定結果表示
# ============================================================
def render_check_messages(messages: list[CheckMessage]) -> None:
    for msg in messages:
        if msg.level == "success":
            st.success(msg.title)
            st.caption(msg.detail)
        elif msg.level == "warning":
            st.warning(msg.title)
            st.caption(msg.detail)
        elif msg.level == "error":
            st.error(msg.title)
            st.caption(msg.detail)
        else:
            st.info(msg.title)
            st.caption(msg.detail)


# ============================================================
# 説明表示
# ============================================================
with st.expander("このページの見方", expanded=True):
    st.caption("このページでは、nginx のアップロード一時保存先 client_body_temp を確認します。")
    st.caption("PDF、音声、zip などのアップロード失敗時に、権限や nginx プロセス状態を確認するためのページです。")
    st.caption("重要なのは、client_body_temp の所有者と nginx worker user が一致しているか、所有者が書き込めるかです。")
    st.caption("700 権限自体は問題ではありません。所有者と nginx worker user が一致していれば正常です。")
    st.caption("問題がある場合は、画面下部に修正コマンドを表示します。")


# ============================================================
# nginx client_body_temp チェック
# ============================================================
st.header("nginx client_body_temp チェック")

st.caption("以下の3つを確認します。")
st.caption("1. ls -ld /opt/homebrew/var/run/nginx")
st.caption("2. ls -ld /opt/homebrew/var/run/nginx/client_body_temp")
st.caption("3. ps aux | grep nginx")

if st.button("チェック実行", key=f"{PAGE_NAME}__run_nginx_client_body_temp_check"):
    # ------------------------------------------------------------
    # 状態取得
    # ------------------------------------------------------------
    nginx_run_status = get_path_status(NGINX_RUN_DIR)
    client_temp_status = get_path_status(CLIENT_BODY_TEMP_DIR)

    # ------------------------------------------------------------
    # コマンド実行
    # ------------------------------------------------------------
    result_nginx_run = run_command(["ls", "-ld", str(NGINX_RUN_DIR)])
    result_client_temp = run_command(["ls", "-ld", str(CLIENT_BODY_TEMP_DIR)])
    result_ps = run_command(["bash", "-lc", "ps aux | grep nginx"])

    # ------------------------------------------------------------
    # nginx process 解析
    # ------------------------------------------------------------
    nginx_process_lines = extract_nginx_process_lines(result_ps.stdout)
    nginx_worker_lines = extract_nginx_worker_lines(result_ps.stdout)
    nginx_users = extract_users_from_ps_lines(nginx_process_lines)
    nginx_worker_users = extract_users_from_ps_lines(nginx_worker_lines)

    # ------------------------------------------------------------
    # 判定
    # ------------------------------------------------------------
    messages = check_client_body_temp(
        nginx_run_status=nginx_run_status,
        client_temp_status=client_temp_status,
        nginx_process_lines=nginx_process_lines,
        nginx_worker_lines=nginx_worker_lines,
    )

    has_problem = any(msg.level in {"error", "warning"} for msg in messages)

    # ------------------------------------------------------------
    # 判定結果
    # ------------------------------------------------------------
    st.markdown("---")
    st.header("判定結果")
    render_check_messages(messages)

    # ------------------------------------------------------------
    # 要約
    # ------------------------------------------------------------
    st.markdown("---")
    st.header("状態の要約")

    col1, col2, col3 = st.columns(3)

    with col1:
        render_path_status("nginx 実行用ディレクトリ", nginx_run_status)

    with col2:
        render_path_status("client_body_temp", client_temp_status)

    with col3:
        st.subheader("nginx プロセス")
        st.caption(f"nginx process 行数: {len(nginx_process_lines)}")
        st.caption(f"nginx worker 行数: {len(nginx_worker_lines)}")
        st.caption(f"nginx users: {', '.join(nginx_users) if nginx_users else '-'}")
        st.caption(f"nginx worker users: {', '.join(nginx_worker_users) if nginx_worker_users else '-'}")

    # ------------------------------------------------------------
    # 問題がある場合の解決方法
    # ------------------------------------------------------------
    if has_problem:
        st.markdown("---")
        st.header("解決方法")

        st.caption("client_body_temp の権限・所有者が原因の場合は、ターミナルで以下を実行してください。")
        st.code(build_fix_command(), language="bash")

        st.caption("実行後、このページで再度「チェック実行」を押して状態を確認してください。")

    # ------------------------------------------------------------
    # コマンド結果
    # ------------------------------------------------------------
    st.markdown("---")
    st.header("コマンド実行結果")

    with st.expander("1. ls -ld /opt/homebrew/var/run/nginx", expanded=False):
        render_command_result(result_nginx_run)

    with st.expander("2. ls -ld /opt/homebrew/var/run/nginx/client_body_temp", expanded=False):
        render_command_result(result_client_temp)

    with st.expander("3. ps aux | grep nginx", expanded=False):
        render_command_result(result_ps)

    # ------------------------------------------------------------
    # nginx process 原文
    # ------------------------------------------------------------
    st.markdown("---")
    st.header("nginx process 原文")

    if nginx_process_lines:
        st.code("\n".join(nginx_process_lines), language="text")
    else:
        st.info("nginx process 行は見つかりませんでした。")


# ============================================================
# 今後追加するチェック項目
# ============================================================
st.markdown("---")
st.header("今後追加するシステムチェック")

st.caption("このページに、今後以下のようなチェックを追加していきます。")
st.caption("・Streamlit 起動状態チェック")
st.caption("・ポート使用状況チェック")
st.caption("・nginx 設定ファイルチェック")
st.caption("・nginx access_log / error_log チェック")
