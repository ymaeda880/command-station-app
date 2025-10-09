# pages/03_プロジェクト走査とGit操作.py
from __future__ import annotations
from pathlib import Path
import shlex
import streamlit as st
import pandas as pd

from config.path_config import PROJECT_ROOT
from lib.cmd_utils import (
    git, is_git_repo, git_branch, git_remote_first, git_status_short, git_changed_count
)

st.set_page_config(page_title="📁 走査＆Git操作", page_icon="📁", layout="wide")
st.title("📁 プロジェクト走査 ＋ 🔧 Git 操作")

st.caption(
    "- `settings.toml` の location から **project_root** を取得\n"
    "- `*_project/` 直下の `*_app/`（かつ `app.py` を含む）を検出\n"
    "- さらに `apps_portal/` も Git 対象に含める\n"
    "- 一覧で Git ステータスを表示 → 選択に対して一括操作（fetch/pull/push/commit）"
)

st.info(f"現在の project_root: `{PROJECT_ROOT}`")

# ------------------------------------------------------------
# 1) 走査: *_project / *_app / app.py
# ------------------------------------------------------------
def discover_app_repos(root: Path) -> list[dict]:
    rows: list[dict] = []
    # *_project 直下の *_app
    for proj_dir in sorted([p for p in root.glob("*_project") if p.is_dir()]):
        for app_dir in sorted([a for a in proj_dir.glob("*_app") if a.is_dir()]):
            if (app_dir / "app.py").exists():
                rows.append({"name": app_dir.name, "path": app_dir})
    # apps_portal も対象に追加
    portal = root / "apps_portal"
    if portal.exists() and portal.is_dir():
        rows.append({"name": "apps_portal", "path": portal})
    return rows

repos = discover_app_repos(PROJECT_ROOT)

if not repos:
    st.warning("対象フォルダが見つかりませんでした。`*_project` / `*_app` / `apps_portal` を確認してください。")
    st.stop()

# Git メタデータ収集
records = []
for r in repos:
    path = str(r["path"])
    repo_flag = is_git_repo(path)
    branch = git_branch(path) if repo_flag else ""
    remote = git_remote_first(path) if repo_flag else ""
    changed = git_changed_count(path) if repo_flag else None
    status = git_status_short(path) if repo_flag else "(not a git repo)"
    records.append({
        "選択": False,
        "名前": r["name"],
        "パス": path,
        "Git": "Yes" if repo_flag else "No",
        "ブランチ": branch,
        "リモート": remote,
        "変更数": changed,
        "status": status,
    })

df = pd.DataFrame(records)

st.subheader("🔎 検出結果 & ステータス")
st.dataframe(df.drop(columns=["status"]), width="stretch")

with st.expander("各リポジトリの `git status -sb` 出力（詳細）", expanded=False):
    for rec in records:
        st.markdown(f"**{rec['名前']}** — `{rec['パス']}`")
        st.code(rec["status"], language="bash")

# ------------------------------------------------------------
# 2) 操作対象の選択
# ------------------------------------------------------------
st.divider()
st.subheader("✅ 操作対象を選ぶ")
sel = []
for i, rec in enumerate(records):
    c1, c2 = st.columns([1, 7])
    with c1:
        checked = st.checkbox("", key=f"sel_{i}")
    with c2:
        git_badge = "🟢 Git" if rec["Git"] == "Yes" else "⚪️ not Git"
        st.write(
            f"**{rec['名前']}** — `{rec['パス']}`  | {git_badge} | "
            f"ブランチ: `{rec['ブランチ'] or '-'}` | 変更: {rec['変更数'] if rec['変更数'] is not None else '-'}"
        )
    # ✅ Gitかどうかに関係なく選択に追加
    if checked:
        sel.append(rec)

if not sel:
    st.info("少なくとも1つのフォルダを選択してください。")
else:
    st.success(f"{len(sel)} 件選択中。")

# 選択確認の出力（任意）
if sel:
    st.markdown("### 🧩 現在選択中の対象")
    for rec in sel:
        st.markdown(f"- **{rec['名前']}** — `{rec['パス']}` （Git: {rec['Git']}）")


# ------------------------------------------------------------
# 3) 一括Git操作（fetch / pull / push）
# ------------------------------------------------------------
st.divider()
st.subheader("🛠️ 一括 Git 操作")

git_targets = [r for r in sel if r["Git"] == "Yes"]
if sel and not git_targets:
    st.warning("選択に Git リポジトリが含まれていません。（fetch/pull/push は Git リポジトリのみ対象）")

col = st.columns(3)
if git_targets:
    with col[0]:
        if st.button("🌿 fetch --all --prune（選択分）"):
            for rec in git_targets:
                code, out, err = git("fetch --all --prune", cwd=rec["パス"])
                st.markdown(f"**{rec['名前']}**"); st.code(out or err or "(no output)", language="bash")
    with col[1]:
        if st.button("⬇️ pull（選択分）"):
            for rec in git_targets:
                code, out, err = git("pull", cwd=rec["パス"])
                st.markdown(f"**{rec['名前']}**"); st.code(out or err or "(no output)", language="bash")
    with col[2]:
        if st.button("⬆️ push（選択分）"):
            for rec in git_targets:
                code, out, err = git("push", cwd=rec["パス"])
                st.markdown(f"**{rec['名前']}**"); st.code(out or err or "(no output)", language="bash")


# ------------------------------------------------------------
# 💡 ヘルプセクション（折りたたみ）
# ------------------------------------------------------------
with st.expander("💡 一括 Git 操作の使い方（ヘルプを開く）", expanded=False):
    st.markdown("""
### 🧭 使い方概要
このページでは、選択した複数リポジトリに対して Git 操作を一括実行できます。  
上段ボタン（fetch/pull/push）と下段フォーム（add/commit/push）の2段構成です。

---

### 🌿 ② 一括 Git 操作ボタンの意味（上段）

| ボタン | 実行されるコマンド | 意味 |
|--------|--------------------|------|
| 🌿 **fetch --all --prune（選択分）** | `git fetch --all --prune` | リモートの最新情報を取得し、不要なブランチを削除 |
| ⬇️ **pull（選択分）** | `git pull` | リモートの最新変更をローカルに反映（マージ） |
| ⬆️ **push（選択分）** | `git push` | ローカルのコミットをリモートに反映 |

---

### ✍️ ③ add / commit / push（下段フォーム）

このブロックでは、「git add → git commit → git push」を一括実行できます。

| 入力欄 | 内容 |
|--------|------|
| **add 対象** | 追加したいファイルのパターン。例: `.`（全ファイル） / `src/*.py` |
| **コミットメッセージ** | 例: `Update README` や `Fix: path config error` |
| **☑ コミット後に push する** | チェックすると commit のあと push まで自動実行 |

---

### 🧩 操作例

1. 対象アプリをチェック  
2. 上段の **pull** ボタンで最新取得  
3. 下段フォームで `add 対象`=`.`、メッセージを入力  
4. 「コミット後に push する」にチェック  
5. 「実行」でコミット＆push

結果は各アプリごとに出力されます。
""")


col = st.columns(3)
if sel:
    with col[0]:
        if st.button("🌿 fetch --all --prune（選択分）"):
            for rec in sel:
                code, out, err = git("fetch --all --prune", cwd=rec["パス"])
                st.markdown(f"**{rec['名前']}**")
                st.code(out or err or "(no output)", language="bash")
    with col[1]:
        if st.button("⬇️ pull（選択分）"):
            for rec in sel:
                code, out, err = git("pull", cwd=rec["パス"])
                st.markdown(f"**{rec['名前']}**")
                st.code(out or err or "(no output)", language="bash")
    with col[2]:
        if st.button("⬆️ push（選択分）"):
            for rec in sel:
                code, out, err = git("push", cwd=rec["パス"])
                st.markdown(f"**{rec['名前']}**")
                st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 4) add / commit / push（選択分）
# ------------------------------------------------------------
st.subheader("✍️ add / commit / push（選択分）")
with st.form("commit_form", clear_on_submit=False):
    add_pattern = st.text_input("add 対象（例: `.` や `src/*.py`）", ".")
    commit_msg = st.text_input("コミットメッセージ", "")
    do_push = st.checkbox("コミット後に push する", value=False)
    submitted = st.form_submit_button("実行")

if submitted:
    if not git_targets:
        st.error("選択に Git リポジトリが含まれていません。")
    elif not commit_msg.strip():
        st.error("コミットメッセージが空です。")
    else:
        for rec in git_targets:
            st.markdown(f"**{rec['名前']}** — `{rec['パス']}`")
            code, out, err = git(f"add {add_pattern}", cwd=rec["パス"])
            st.code(out or err or "(no output)", language="bash")
            code, out, err = git("diff --cached --name-only", cwd=rec["パス"])
            if not out.strip():
                st.info("ステージされた変更がありません。commit をスキップ。")
                continue
            safe_msg = shlex.quote(commit_msg)
            code, out, err = git(f"commit -m {safe_msg}", cwd=rec["パス"])
            st.code(out or err or "(no output)", language="bash")
            if do_push:
                code, out, err = git("push", cwd=rec["パス"])
                st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 5) 補助: ステータス再読み込み
# ------------------------------------------------------------
st.divider()
cols_refresh = st.columns([1, 3])
with cols_refresh[0]:
    if st.button("🔁 ステータス再読み込み"):
        st.rerun()

# ------------------------------------------------------------
# 6) 直近ログプレビュー（選択分）
# ------------------------------------------------------------
st.subheader("📜 直近ログプレビュー（選択分）")
log_n = st.number_input("表示するコミット数 (-n)", min_value=1, max_value=100, value=10, step=1)
if sel and st.button("ログを表示"):
    for rec in sel:
        st.markdown(f"**{rec['名前']}** — `{rec['パス']}`")
        code, out, err = git(f"log --oneline -n {int(log_n)}", cwd=rec["パス"])
        st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 7) pull --rebase（選択分）
# ------------------------------------------------------------
st.subheader("⬇️ pull --rebase（選択分）")
st.caption("マージコミットを作らずに履歴を整える場合はこちら。")
if sel and st.button("pull --rebase を実行"):
    for rec in sel:
        st.markdown(f"**{rec['名前']}** — `{rec['パス']}`")
        code, out, err = git("pull --rebase", cwd=rec["パス"])
        st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 8) 💣 強制リセット（選択分）：fetch origin → reset --hard origin/<branch>
# ------------------------------------------------------------
st.subheader("💣 強制リセット（危険・選択分）")
st.caption(
    "各リポジトリを **リモートの最新状態に完全一致** させます。"
    " ローカルの未コミット変更や push していないコミットは失われます。"
)

col_reset = st.columns([2, 2, 3])
with col_reset[0]:
    really = st.checkbox("実行内容を理解した")
with col_reset[1]:
    confirm_text = st.text_input("確認のため `RESET` と入力", "")
with col_reset[2]:
    st.write("実行手順: ①`git fetch origin` → ②`git reset --hard origin/<現在ブランチ>`")

if sel and st.button("💥 強制リセットを実行"):
    if not really or confirm_text.strip().upper() != "RESET":
        st.error("確認が未完了です。チェックを入れ、`RESET` と入力してください。")
    else:
        for rec in sel:
            st.markdown(f"**{rec['名前']}** — `{rec['パス']}`")
            # ① fetch origin
            code1, out1, err1 = git("fetch origin", cwd=rec["パス"])
            st.code(out1 or err1 or "(no output)", language="bash")

            # ② reset --hard origin/<branch>
            #   ブランチ名は走査時に取得した値を使う
            branch = rec.get("ブランチ") or "main"
            remote_ref = shlex.quote(f"origin/{branch}")
            code2, out2, err2 = git(f"reset --hard {remote_ref}", cwd=rec["パス"])
            st.code(out2 or err2 or "(no output)", language="bash")

        st.success("強制リセットが完了しました。🔁『ステータス再読み込み』で状態を更新してください。")
# ------------------------------------------------------------
# 9) 新規リポジトリ初期化（git init）
# ------------------------------------------------------------
st.divider()
st.subheader("🆕 新規 Git リポジトリ初期化（選択分）")
st.caption(
    "選択したフォルダに `.git` が存在しない場合に `git init` を実行します。"
    " すでに Git 管理下にあるフォルダではスキップします。"
)

# 入力・設定UI
col_init = st.columns([1, 2, 2])
with col_init[0]:
    confirm_init = st.checkbox("実行を許可する", value=False)
with col_init[1]:
    remote_url = st.text_input(
        "（任意）初期リモートURL",
        placeholder="例：https://github.com/user/repo.git",
    )
with col_init[2]:
    auto_commit = st.checkbox("初回 commit も行う（add . → commit）", value=False)

# 実行ボタン
run_init = st.button("🚀 git init を実行（選択分）", use_container_width=True)

if run_init:
    init_targets = [r for r in sel if r["Git"] == "No"]  # ← 未Gitのみ
    if not sel:
        st.error("対象フォルダが選択されていません。")
    elif not init_targets:
        st.warning("選択の中に Git 未初期化フォルダがありません。")
    elif not confirm_init:
        st.error("実行を許可するチェックをオンにしてください。")
    else:
        for rec in init_targets:
            repo_path = Path(rec["パス"])
            st.markdown(f"**{rec['名前']}** — `{repo_path}`")

            code, out, err = git("init", cwd=repo_path)
            st.code(out or err or "(no output)", language="bash")

            if remote_url.strip():
                code, out, err = git(f"remote add origin {shlex.quote(remote_url)}", cwd=repo_path)
                st.code(out or err or "(no output)", language="bash")

            if auto_commit:
                code, out, err = git("add .", cwd=repo_path)
                st.code(out or err or "(no output)", language="bash")
                code, out, err = git("commit -m 'Initial commit'", cwd=repo_path)
                st.code(out or err or "(no output)", language="bash")

            st.success("✅ git init 完了")

        st.info("必要に応じてリモート設定や push を行ってください。")
