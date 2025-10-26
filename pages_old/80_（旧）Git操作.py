# pages/02_Git操作.py
from __future__ import annotations
from pathlib import Path
import re
import streamlit as st

from lib.cmd_utils import git

st.set_page_config(page_title="🔧 Git 操作", page_icon="🔧", layout="wide")
st.title("🔧 Git 操作 — status / fetch / pull / add / commit / push / log / stash")

st.caption(
    "リポジトリのパスを指定して、よく使う Git 操作をボタンで実行します。"
    " 認証が必要な push/pull は、事前に ssh-agent / Git Credential Manager 等の設定を済ませてください。"
)

# ------------------------------------------------------------
# 入力: リポジトリパス
# ------------------------------------------------------------
default_repo = st.session_state.get("git_repo_dir", str(Path.cwd()))
repo_dir = st.text_input("リポジトリのパス", default_repo)
st.session_state["git_repo_dir"] = repo_dir

def is_git_repo(path: str) -> bool:
    code, out, err = git("rev-parse --is-inside-work-tree", cwd=path)
    return code == 0 and out.strip() == "true"

# バリデーション
if not Path(repo_dir).exists():
    st.error("指定されたパスが存在しません。")
    st.stop()

if not is_git_repo(repo_dir):
    st.error("このパスは Git リポジトリではありません（.git が見つかりません）。")
    st.stop()

# ------------------------------------------------------------
# 概要: 現在ブランチ / リモート
# ------------------------------------------------------------
col_a, col_b, col_c = st.columns(3)
with col_a:
    code, out, err = git("rev-parse --abbrev-ref HEAD", cwd=repo_dir)
    branch = out if code == 0 else "(不明)"
    st.metric("ブランチ", branch)

with col_b:
    code, out, err = git("remote -v", cwd=repo_dir)
    remote_line = out.splitlines()[0] if out else "(なし)"
    st.metric("リモート", remote_line)

with col_c:
    code, out, err = git("status --porcelain=v1", cwd=repo_dir)
    changed = len(out.splitlines()) if out else 0
    st.metric("変更ファイル数", changed)

st.divider()

# ------------------------------------------------------------
# 1) ステータス／フェッチ／プル／プッシュ
# ------------------------------------------------------------
st.subheader("① ステータス & 同期")

c1, c2, c3, c4 = st.columns(4)
with c1:
    if st.button("📄 status"):
        code, out, err = git("status -sb", cwd=repo_dir)
        st.code(out or err or "(no output)", language="bash")
with c2:
    if st.button("🌿 fetch --all --prune"):
        code, out, err = git("fetch --all --prune", cwd=repo_dir)
        st.code(out or err or "(no output)", language="bash")
with c3:
    if st.button("⬇️ pull"):
        code, out, err = git("pull", cwd=repo_dir)
        st.code(out or err or "(no output)", language="bash")
with c4:
    if st.button("⬆️ push"):
        code, out, err = git("push", cwd=repo_dir)
        st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 2) add / commit / push
# ------------------------------------------------------------
st.subheader("② 追加・コミット・プッシュ")

with st.form("commit_form", clear_on_submit=False):
    add_pattern = st.text_input("add 対象（例: . / src/*.py など）", ".")
    commit_msg = st.text_input("コミットメッセージ", "")
    do_push = st.checkbox("コミット後に push する", value=False)
    submitted = st.form_submit_button("実行")

if submitted:
    # git add
    code, out, err = git(f"add {add_pattern}", cwd=repo_dir)
    st.write("**git add** 結果:")
    st.code(out or err or "(no output)", language="bash")

    # 空コミット防止のため差分有無をチェック
    code, out, err = git("diff --cached --name-only", cwd=repo_dir)
    if not out.strip():
        st.warning("ステージされた変更がありません。コミットをスキップします。")
    else:
        # git commit
        if not commit_msg.strip():
            st.error("コミットメッセージが空です。")
        else:
            safe_msg = shlex.quote(commit_msg)  # ← これで自動的に安全クォートされる
            code, out, err = git(f"commit -m {safe_msg}", cwd=repo_dir)
            st.write("**git commit** 結果:")
            st.code(out or err or "(no output)", language="bash")

            # git push (任意)
            if do_push:
                code, out, err = git("push", cwd=repo_dir)
                st.write("**git push** 結果:")
                st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 3) ログ表示・簡易差分
# ------------------------------------------------------------
st.subheader("③ ログ / 差分")

log_cols = st.columns(3)
with log_cols[0]:
    n = st.number_input("表示するコミット数 (-n)", min_value=1, max_value=100, value=20, step=1)
with log_cols[1]:
    grep = st.text_input("grep（コミットメッセージフィルタ、空で無効）", "")
with log_cols[2]:
    show_diff = st.checkbox("最新コミットの差分を表示", value=False)

import shlex

log_cmd = f"log --oneline -n {int(n)}"
if grep.strip():
    # 安全にクォート（例: grep="fix bug" → 'fix bug'）
    safe_grep = shlex.quote(grep)
    log_cmd += f" --grep={safe_grep} --regexp-ignore-case"


code, out, err = git(log_cmd, cwd=repo_dir)
st.code(out or err or "(no output)", language="bash")

if show_diff:
    code, out, err = git("show --name-status --stat -1", cwd=repo_dir)
    st.subheader("最新コミットの差分（`git show -1`）")
    st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 4) 一時退避（stash）
# ------------------------------------------------------------
st.subheader("④ スタッシュ")

sc1, sc2, sc3 = st.columns(3)
with sc1:
    if st.button("🧺 stash push"):
        code, out, err = git('stash push -m "work-in-progress"', cwd=repo_dir)
        st.code(out or err or "(no output)", language="bash")
with sc2:
    if st.button("🧺 stash list"):
        code, out, err = git("stash list", cwd=repo_dir)
        st.code(out or err or "(no output)", language="bash")
with sc3:
    if st.button("🧺 stash pop"):
        code, out, err = git("stash pop", cwd=repo_dir)
        st.code(out or err or "(no output)", language="bash")
