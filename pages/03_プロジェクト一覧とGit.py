# pages/03_プロジェクト走査とGit操作.py
from __future__ import annotations
from pathlib import Path
import shlex
import streamlit as st
import pandas as pd

from config.path_config import PROJECT_ROOT
from lib.cmd_utils import git
from lib.ui_utils import thick_divider
from lib.project_scan import apps_git_dataframe

# ------------------------------------------------------------
# ページ設定
# ------------------------------------------------------------
st.set_page_config(page_title="📁 走査＆Git操作", page_icon="📁", layout="wide")
st.title("📁 プロジェクト走査 ＋ 🔧 Git 操作")

st.warning("GitHubとの差分を見る前に、まず『🌿 fetch --all --prune』を実行してください（リモート参照の整理）")

st.caption(
    "- `settings.toml` の location から **project_root** を取得\n"
    "- `*_project/` 直下の `*_app/`（かつ `app.py` を含む）を検出\n"
    "- さらに `apps_portal/` と `common_lib/` も Git 対象に含める\n"
    "- 一覧で Git ステータスを表示 → 選択に対して一括操作（fetch/pull/push/commit/init/clone）"
)
st.info(f"現在の project_root: `{PROJECT_ROOT}`")

# ------------------------------------------------------------
# 初回表示時の自動 fetch
# ------------------------------------------------------------
AUTO_FETCH_STATE_KEY = "auto_fetch_all_prune_done_03_git_page"

if AUTO_FETCH_STATE_KEY not in st.session_state:
    st.session_state[AUTO_FETCH_STATE_KEY] = False

# ------------------------------------------------------------
# 0) ユーティリティ
# ------------------------------------------------------------
def _dir_is_effectively_empty(path: Path) -> bool:
    """
    clone 先の中身が「実質的に空」か判定。
    許容: .DS_Store / .gitkeep / .venv / .run / __pycache__
    それ以外があれば NG（安全のため）
    """
    allowed = {".DS_Store", ".gitkeep", ".venv", ".run", "__pycache__"}
    if not path.exists():
        return True
    for p in path.iterdir():
        if p.name not in allowed:
            return False
    return True

# ------------------------------------------------------------
# 5) ステータス再読み込み（サイドバーへ移動）
# ------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🔁 Git ステータス")
    st.caption("Git の変更を再読み込みします。いつでも実行できます。")

    if st.button("🔁 ステータスを更新", key="btn_reload_status_sidebar"):
        st.rerun()

# ------------------------------------------------------------
# 1) プロジェクト走査＋Git情報取得（.gitサイズ表示対応版）
# ------------------------------------------------------------
df = apps_git_dataframe(PROJECT_ROOT)

# ------------------------------------------------------------
# 初回表示時のみ fetch --all --prune を自動実行
# ------------------------------------------------------------
if not st.session_state.get(AUTO_FETCH_STATE_KEY, False):
    st.info("初回表示のため、GitHub側の最新情報を取得しています。")

    fetch_logs = []

    for _, rec in df.iterrows():
        if not rec.get("is_repo", False):
            continue

        code, out, err = git("fetch --all --prune", cwd=rec["path"])
        fetch_logs.append({
            "name": rec.get("name", ""),
            "path": str(rec.get("path", "")),
            "code": code,
            "output": out or err or "(no output)",
        })

    st.session_state[AUTO_FETCH_STATE_KEY] = True

    with st.expander("初回自動 fetch の結果", expanded=False):
        for item in fetch_logs:
            st.markdown(f"**{item['name']}** — `{item['path']}`")
            st.code(item["output"], language="bash")

    # fetch後の最新状態で再取得
    df = apps_git_dataframe(PROJECT_ROOT)

if df.empty:
    st.warning("対象フォルダが見つかりませんでした。`*_project` / `*_app` / `apps_portal` を確認してください。")
    st.stop()

st.subheader("🔎 検出結果 & ステータス（.git サイズ付き）")

# 表示名へリネーム
df_display = df.rename(columns={
    "name": "名前",
    "path": "パス",
    "kind": "種別",
    "branch": "ブランチ",
    "dirty": "変更数",
    "ahead": "↑ ahead",
    "behind": "↓ behind",
    "is_repo": "Git管理",
    "git_size_human": ".git サイズ",
    "git_size_bytes": ".git サイズ(byte)",
})

# ------------------------------------------------------------
# ✅ pandas→pyarrow 事故を避けるための表示用 型固定（おすすめ）
#   - df（元データ）は触らず df_display だけ整形
# ------------------------------------------------------------

# 1) Path → str（ここが一番事故りやすい）
if "パス" in df_display.columns:
    df_display["パス"] = df_display["パス"].astype(str)

# 2) 数値列：None/NaN混在を吸収して nullable Int に寄せる
for c in ["変更数", "↑ ahead", "↓ behind", ".git サイズ(byte)"]:
    if c in df_display.columns:
        df_display[c] = pd.to_numeric(df_display[c], errors="coerce").astype("Int64")

# 3) 文字列列：None混在でも安定する pandas StringDtype に寄せる
for c in ["名前", "種別", "ブランチ", "Git管理", ".git サイズ"]:
    if c in df_display.columns:
        df_display[c] = df_display[c].astype("string")


# 表示したい列の順序（short_status は詳細枠で出すので一覧からは外す）
cols = ["名前", "種別", "ブランチ", "変更数", "↑ ahead", "↓ behind", "Git管理", ".git サイズ", "パス"]
# 安全に存在チェックして不足列を除外
cols = [c for c in cols if c in df_display.columns]

# ------------------------------------------------------------
# 一覧テーブル表示（Git管理あり／なしで分割）
# ------------------------------------------------------------
if "Git管理" in df_display.columns:
    df_git_true = df_display[df_display["Git管理"].astype(str) == "True"]
    df_git_false = df_display[df_display["Git管理"].astype(str) == "False"]

    st.markdown("### 🟢 Git管理あり")

    st.caption(
    "変更数 = 未commit変更数（working tree の変更） / "
    "↑ ahead = 未push commit 数（ローカルだけに存在する commit） / "
    "↓ behind = 未pull commit 数（GitHub側にのみ存在する commit）"
)
    if df_git_true.empty:
        st.info("Git管理されている対象はありません。")
    else:
        st.dataframe(df_git_true[cols], width="stretch")

    st.markdown("### ⚪ Git管理なし")
    if df_git_false.empty:
        st.info("Git管理されていない対象はありません。")
    else:
        st.dataframe(df_git_false[cols], width="stretch")
else:
    st.dataframe(df_display[cols], width="stretch")

# 合計サイズのサマリ（任意）
if "git_size_bytes" in df.columns:
    total_bytes = int(df["git_size_bytes"].sum())
    # 人間可読の整形（apps側の関数に合わせた軽量版）
    def _fmt(n: int) -> str:
        size = float(n)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0 or unit == "TB":
                return (f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}")
            size /= 1024.0
        return f"{size:.2f} TB"

    st.caption(f"`.git` の合計サイズ：**{_fmt(total_bytes)}**（{total_bytes:,} bytes）")

with st.expander("各リポジトリの `git status -sb` 出力（詳細）", expanded=False):
    for _, rec in df.iterrows():
        st.markdown(f"**{rec['name']}** — `{rec['path']}`  —  `.git`: {rec.get('git_size_human', '0 B')}")
        st.code(rec["short_status"], language="bash")


# ------------------------------------------------------------
# 💬 Git ステータス記号の意味（ヘルプ折りたたみ）
# ------------------------------------------------------------
with st.expander("💬 `git status -sb` の記号の意味（クリックで開く）", expanded=False):
    st.markdown(
        """
### 🧭 Git ステータスの略号解説

| 記号 | 意味 | 説明 |
|------|------|------|
| `M` | **Modified（変更あり）** | ファイルが修正された（まだ commit していない） |
| `A` | **Added（追加）** | 新規ファイルが `git add` 済み |
| `D` | **Deleted（削除）** | ファイルが削除された（ステージ済み or 未ステージ） |
| `R` | **Renamed（リネーム）** | ファイル名が変更された |
| `C` | **Copied（コピー）** | 既存ファイルを複製した変更 |
| `??` | **Untracked（未追跡）** | Git にまだ登録されていない新規ファイル（未 `add`） |
| `!!` | **Ignored（無視対象）** | `.gitignore` により追跡しない設定のファイル |
| `UU` | **Conflict（競合）** | マージ時に競合が発生しているファイル |
"""
    )

# ------------------------------------------------------------
# 2) 操作対象の選択
# ------------------------------------------------------------
st.divider()
st.subheader("✅ 操作対象を選ぶ")

sel = []
for i, row in df.iterrows():
    c1, c2 = st.columns([1, 7])
    with c1:
        # checked = st.checkbox("", key=f"sel_{i}")

        # 修正案（ラベルは内部用、画面では非表示）
        checked = st.checkbox(
            "選択",  # 何でもよい（アクセシビリティ的には意味のある文字が望ましい）
            key=f"sel_{i}",
            label_visibility="collapsed",
)
    with c2:
        git_badge = "🟢 Git" if row["is_repo"] else "⚪️ not Git"
        st.write(
            f"**{row['name']}** — `{row['path']}` | {git_badge} | "
            f"ブランチ: `{row['branch'] or '-'}` | 変更: {row['dirty']} | "
            f"ahead: {row['ahead']} | behind: {row['behind']}"
        )
    if checked:
        sel.append(row)

if not sel:
    st.info("少なくとも1つのフォルダを選択してください。")
else:
    st.success(f"{len(sel)} 件選択中。")

if sel:
    st.markdown("### 🧩 現在選択中の対象")
    for r in sel:
        st.markdown(f"- **{r['name']}** — `{r['path']}` （Git: {r['is_repo']}）")

git_targets = [r for r in sel if r["is_repo"]]

# ------------------------------------------------------------
# 3) add / commit / push
# ------------------------------------------------------------
thick_divider("#007ACC", 4)
st.subheader("✍️ （🟢　日常）add / commit / push（選択分）（変更分のpush）")

with st.form("commit_form", clear_on_submit=False):
    add_pattern = st.text_input("add 対象", ".", key="txt_add_pattern")
    commit_msg = st.text_input("コミットメッセージ（月日-時間：（例）1026-1430）", "", key="txt_commit_msg")
    do_push = st.checkbox("コミット後に push する", value=False, key="chk_do_push")
    submitted = st.form_submit_button("実行", key="btn_commit_submit")

if submitted:
    if not git_targets:
        st.error("選択に Git リポジトリが含まれていません。")
    elif not commit_msg.strip():
        st.error("コミットメッセージが空です。")
    else:
        for rec in git_targets:
            with st.expander(f"🧾 {rec['name']} の結果", expanded=False):
                st.markdown(f"**{rec['name']}** — `{rec['path']}`")
                code, out, err = git(f"add {add_pattern}", cwd=rec["path"])
                st.code(out or err or "(no output)", language="bash")
                code, out, err = git("diff --cached --name-only", cwd=rec["path"])
                if not out.strip():
                    st.info("ステージされた変更がありません。commit をスキップ。")
                    continue
                safe_msg = shlex.quote(commit_msg)
                code, out, err = git(f"commit -m {safe_msg}", cwd=rec["path"])
                st.code(out or err or "(no output)", language="bash")
                if do_push:
                    code, out, err = git("push", cwd=rec["path"])
                    st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 4) 一括Git操作（fetch / pull / push）
# ------------------------------------------------------------
thick_divider("#007ACC", 4)
st.subheader("🛠️ 一括 Git 操作")

with st.expander("🧩 一括 Git 操作の説明（fetch / pull / push）", expanded=False):
    st.markdown(
    """
    ### 🛠️ 一括 Git 操作の概要

    このセクションでは、選択された複数のリポジトリに対して  
    **共通の Git コマンドを一括実行** します。  
    各ボタンはそれぞれ以下のような動作を行います。

    ---

    #### 🌿 `fetch --all --prune（選択分）`
    - すべてのリモートリポジトリ（例：GitHub上の origin）の参照情報を更新します。  
      例：`git fetch --all`
    - さらに `--prune` により、削除済みリモートブランチの追跡情報をローカルからも削除します。
    - リモート追跡ブランチ一覧を最新化する処理です。  
      コードやファイルの内容には影響しません。

    ---

    #### ⬇️ `pull（選択分）`
    - リモートから最新の変更を取得し、ローカルブランチへ統合します。  
      実際には `git pull`（＝`fetch + merge`）を実行しています。
    - 競合が発生する場合はエラー表示されるため、  
      状況に応じて手動解決または `stash` などが必要になります。
    - コマンド出力（またはエラー内容）はコンソール風に表示されます。

    ---

    #### ⬆️ `push（選択分）`
    - ローカルでの最新コミットをリモートブランチへ反映します。  
      実際には `git push` を実行します。
    - すでに上流ブランチが設定済み（`-u`不要）の場合に使います。
    - 成功するとリモートリポジトリ（GitHub 等）へコードが反映されます。

    ---

    #### ⚙️ 共通仕様
    - どの操作も「選択された Git リポジトリ（`git_targets`）」が対象です。  
      何も選択されていない場合は警告を表示して実行しません。
    - 各リポジトリごとに結果（標準出力 or エラー）を `st.code()` で整形して表示します。
    - `thick_divider("#007ACC", 4)` により、セクションを視覚的に区切っています。

    ---
    **💡ヒント：**
    - `fetch` は安全な更新（リモート同期のみ）  
    - `pull` はローカルへ反映  
    - `push` はリモートへ送信  
    という方向の違いを意識すると運用が分かりやすくなります。
    """
    )


col = st.columns(3)

# 🌿 fetch
with col[0]:
    if st.button("🌿 fetch --all --prune（選択分）", key="btn_fetch_main", help="全リモートの参照を更新＋不要な追跡ブランチを削除"):
        if not git_targets:
            st.warning("⚠️ Git リポジトリが選択されていません。")
        else:
            for rec in git_targets:
                st.markdown(f"**{rec['name']}**")
                code, out, err = git("fetch --all --prune", cwd=rec["path"])
                st.code(out or err or "(no output)", language="bash")

# ⬇️ pull
with col[1]:
    if st.button("⬇️ pull（選択分）", key="btn_pull_main"):
        if not git_targets:
            st.warning("⚠️ Git リポジトリが選択されていません。")
        else:
            for rec in git_targets:
                st.markdown(f"**{rec['name']}**")
                code, out, err = git("pull", cwd=rec["path"])
                st.code(out or err or "(no output)", language="bash")

# ⬆️ push
with col[2]:
    if st.button("⬆️ push（選択分）", key="btn_push_main"):
        if not git_targets:
            st.warning("⚠️ Git リポジトリが選択されていません。")
        else:
            for rec in git_targets:
                st.markdown(f"**{rec['name']}**")
                code, out, err = git("push", cwd=rec["path"])
                st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 5) ステータス再読み込み
# ------------------------------------------------------------
# thick_divider("#007ACC", 4)
# st.caption("Gitの変更を反映させます．いつでも実行できます．")
# if st.button("🔁 Git ステータスを更新", key="btn_reload_status"):
#     st.rerun()

# ------------------------------------------------------------
# 6) 🧲 git clone（新規取得：選択対象“の中身”に clone）
# ------------------------------------------------------------
thick_divider("#007ACC", 4)
st.subheader("🧲 （🟢　最初のclone）git clone（新規取得：選択対象フォルダの**中に** `.` で clone）")

with st.form("clone_into_selected_form", clear_on_submit=False):
    st.caption("※ 保存先は **選択済みの1件** の `_app` ディレクトリです。フォルダ名は常に「.」で、**中身に** clone します。")
    clone_url2 = st.text_input("リポジトリURL", placeholder="https://github.com/user/repo.git", key="txt_clone_url2")
    shallow2 = st.checkbox("--depth 1（浅い履歴）", value=False, key="chk_clone_depth2")
    submodules2 = st.checkbox("--recurse-submodules", value=False, key="chk_clone_sub2")
    run_clone2 = st.form_submit_button("🧲 選択先に clone（フォルダ名は「.」）")

if run_clone2:
    if len(sel) != 1:
        st.error("clone は操作対象を **ちょうど1件** 選択して実行してください。")
    elif not clone_url2.strip():
        st.error("リポジトリURLを入力してください。")
    else:
        rec = sel[0]
        dest_dir = Path(rec["path"])  # 例: <project_root>/<app>_project/<app>_app
        git_dir = dest_dir / ".git"

        # 既に Git 管理なら clone しない
        if git_dir.exists():
            st.error(f"既に Git リポジトリです: {dest_dir}")
        else:
            # 中身が実質空かチェック
            if not _dir_is_effectively_empty(dest_dir):
                st.error(
                    f"フォルダが空ではありません: {dest_dir}\n"
                    "→ ファイルを退避/削除するか、『新規リポジトリ初期化』機能をご利用ください。"
                )
            else:
                extra = []
                if shallow2:
                    extra += ["--depth", "1", "--no-single-branch"]
                if submodules2:
                    extra += ["--recurse-submodules"]

                cmd = " ".join(["clone"] + extra + [shlex.quote(clone_url2), "."])
                code, out, err = git(cmd, cwd=dest_dir)
                st.code(out or err or "(no output)", language="bash")
                if code == 0:
                    st.success(f"✅ clone 完了: {clone_url2} → {dest_dir}（フォルダ名は『.』）")
                    # 念のためサブモジュールを最新化
                    git("submodule update --init --recursive", cwd=dest_dir)
                else:
                    st.error("❌ clone に失敗しました。ログを確認してください。")

# ------------------------------------------------------------
# 7) 新規リポジトリ初期化
# ------------------------------------------------------------
thick_divider("#007ACC", 4)
st.subheader("🆕 （🟢　最初のgit init）新規 Git リポジトリ初期化 ➜ 初回push")

with st.expander("🧩 処理の内容を表示", expanded=False):
    st.markdown(
    """
    ### 🧩 処理の内容

    #### 🆕 ⑦ 新規 Git リポジトリ初期化
    1. **選択されたフォルダを確認**  
       - Git 管理されていないフォルダだけを抽出します。  
       - フォルダが未選択・既に Git 管理済み・実行許可チェック未ON の場合は実行しません。

    2. **Git 初期化 (`git init`) の実行**  
       - 各フォルダで `git init` を実行して `.git` ディレクトリを作成します。  
       - 実行結果を画面に表示します。

    3. **`.gitignore` の自動作成**  
       - `.gitignore` が存在しない場合は自動生成します。  
         ```
         .venv/
         __pycache__/
         .DS_Store
         ```

    4. **リモートリポジトリの設定（任意）**  
       - 入力された URL があれば  
         `git remote add origin <URL>` を実行します。

    5. **初回コミットの実行（任意）**  
       - 「初回 commit も行う」にチェックがある場合、  
         `git add .` → `git commit -m 'Initial commit'` を自動実行します。

    6. **完了メッセージの表示**  
       - 各処理完了後に結果を表示し、必要に応じて push を促します。

    ---

    #### 🚀 ⑧ 初回 push（上流ブランチを設定）

    1. **対象リポジトリを確認**  
       - `git_targets` に選択された Git 管理済みフォルダを取得します。  
       - 未選択の場合はエラーを表示します。

    2. **上流ブランチの確認**  
       - 各リポジトリで `git rev-parse --abbrev-ref --symbolic-full-name @{u}` を実行。  
       - すでに上流ブランチ（upstream）が設定済みなら `git push` は不要と判断してスキップ。

    3. **上流未設定の場合の push 処理**  
       - `push -u` または `push --set-upstream` オプション付きで初回 push を実行します。  
       - `-u` により「現在のブランチ」とリモートブランチの対応関係を登録します。  
         次回以降は `git push` だけで送信可能になります。

    4. **ブランチ指定ロジック**  
       - 「現在のブランチ（HEAD）にpush」チェックがオンなら  
         `git push -u origin HEAD`  
       - チェックがオフなら、現在のブランチ名（例：`main`）を明示して  
         `git push -u origin main` を実行。

    5. **結果出力**  
       - コマンド出力またはエラー内容を `st.code()` で表示します。  
       - 正常に完了すると、今後は通常の `git push` で同期できます。
    """
    )



st.markdown("#### 🆕 新規 Git リポジトリ初期化（選択分）")

col_init = st.columns([1, 2, 2])
with col_init[0]:
    confirm_init = st.checkbox("実行を許可する", value=False, key="chk_confirm_init")
with col_init[1]:
    remote_url = st.text_input(
        "（任意）初期リモートURL",
        placeholder="例：https://github.com/user/repo.git",
        key="txt_remote_url"
    )
with col_init[2]:
    auto_commit = st.checkbox("初回 commit も行う", value=False, key="chk_auto_commit")

if st.button("🚀 git init を実行（選択分）", key="btn_git_init", help="まだ Git 管理でないフォルダを初期化します", kwargs={"use_container_width": False}):
    init_targets = [r for r in sel if not r["is_repo"]]
    if not sel:
        st.error("対象フォルダが選択されていません。")
    elif not init_targets:
        st.warning("選択の中に Git 未初期化フォルダがありません。")
    elif not confirm_init:
        st.error("実行を許可するチェックをオンにしてください。")
    else:
        for rec in init_targets:
            repo_path = Path(rec["path"])
            st.markdown(f"**{rec['name']}** — `{repo_path}`")
            code, out, err = git("init", cwd=repo_path)
            st.code(out or err or "(no output)", language="bash")

            # .gitignore 自動作成
            gi = repo_path / ".gitignore"
            if not gi.exists():
                gi.write_text(".venv/\n__pycache__/\n.DS_Store\n")
                st.info(".gitignore を自動作成しました。")

            if remote_url.strip():
                git(f"remote add origin {shlex.quote(remote_url)}", cwd=repo_path)
            if auto_commit:
                git("add .", cwd=repo_path)
                git("commit -m 'Initial commit'", cwd=repo_path)
            st.success("✅ git init 完了")

        st.info("必要に応じてリモート設定や push を行ってください。")

# ------------------------------------------------------------
# 8) 初回 push（upstream 設定）
# ------------------------------------------------------------
st.divider()
st.markdown("#### 🚀 初回 push（上流ブランチを設定）")

col_up = st.columns([2, 2, 3])
with col_up[0]:
    remote_name = st.text_input("リモート名", "origin", key="txt_remote_name")
with col_up[1]:
    use_head = st.checkbox("現在のブランチ（HEAD）にpush", value=True, key="chk_use_head")
with col_up[2]:
    st.caption("※ 初回のみ `-u/--set-upstream` を付けて上流設定します")

if st.button("初回 push を実行（選択分）", key="btn_first_push"):
    if not git_targets:
        st.error("Git リポジトリが選択されていません。")
    else:
        for rec in git_targets:
            st.markdown(f"**{rec['name']}** — `{rec['path']}`")
            code, _, _ = git("rev-parse --abbrev-ref --symbolic-full-name @{u}", cwd=rec["path"])
            if code == 0:
                st.info("すでに上流ブランチが設定されています。通常の push を利用してください。")
                continue
            else:
                st.caption("上流ブランチが未設定 → push -u を実行します。")

            if use_head:
                cmd = f"push -u {shlex.quote(remote_name)} HEAD"
            else:
                current_branch = rec["branch"] or "main"
                cmd = f"push -u {shlex.quote(remote_name)} {shlex.quote(current_branch)}"
            code, out, err = git(cmd, cwd=rec["path"])
            st.code(out or err or "(no output)", language="bash")





# ------------------------------------------------------------
# 9) 💣 強制リセット（選択分）
# ------------------------------------------------------------
thick_divider("#ff4d4f", 3)
st.subheader("💣 （🟢　remoteとprec macのファイル更新）強制リセット（選択分）")

with st.expander("💣 強制リセット（何が起きる？安全確認ポイント）", expanded=False):
    st.markdown(
    """
    ### 💣 強制リセットとは？
    選択した各リポジトリの **現在ブランチ** を、リモート（`origin/<branch>`）の最新状態に
    **完全一致（hard reset）** させます。  
    その結果、以下が起こります。

    - ✅ **リモートの最新状態に完全同期**（ファイル内容・履歴位置が一致）
    - ❌ **未コミットの変更（ワーキングツリー/ステージング）は消えます**
    - ❌ **ローカルだけにあるコミット（push していないコミット）は履歴から外れます**
      - ※ ただし *多くの場合* `git reflog` から一定期間は復旧可能です（上級者向け）

    > 🔴 **注意**：`git reset --hard` は “追跡ファイル” をリモートの状態に上書きします。  
    > 未追跡ファイル（untracked）は原則残りますが、確実ではありません。  
    > 未追跡まで掃除するのは `git clean -fd`（本UIでは実行しません）。

    ---

    ### 実行前チェック
    1. 本当にローカルの未コミット変更や未pushコミットを捨てて良いか？
    2. 重要な変更がある場合は **stash** または **一時ブランチ/タグ** で退避を
       - 例）`git stash -u` / `git branch backup/<日付>` / `git tag pre-reset-YYYYMMDD`
    3. `origin` が設定されているか（無ければ本処理はスキップされます）

    ---

    ### このボタンが内部で実行するコマンド
    1. `git fetch origin`  
       リモートの最新状態を取得（ファイルは変えない）
    2. `git reset --hard origin/<branch>`  
       取得したリモートの状態に **強制的に一致** させる  
       - `<branch>` は **現在のブランチ**（無ければ `main` を自動使用）

    ---

    ### 失敗/スキップ条件
    - `origin` が未設定 → **エラー表示**してスキップ（`git remote add origin ...` が必要）
    - fetch 失敗／reset 失敗 → **ログ出力**し、結果に応じて成功/失敗を表示

    ---

    ### 実行後
    - テーブルの状態更新には、**サイドバーの『🔁 ステータスを更新』** を使ってください
    - 誤って消したコミットは、可能なら `git reflog` から復旧を試みてください（高度）
    """
    )


st.caption(
    "各リポジトリを **リモートの最新状態に完全一致** させます。"
    " ローカルの未コミット変更や push していないコミットは失われます。"
    " 実行前に本当に問題ないか、必ず確認してください。"
)

col_reset = st.columns([2, 2, 3])
with col_reset[0]:
    really = st.checkbox("実行内容を理解した", key="chk_really_reset")
with col_reset[1]:
    confirm_text = st.text_input("確認のため `RESET` と入力", "", key="txt_reset_confirm")
with col_reset[2]:
    st.write("手順: `git fetch origin` → `git reset --hard origin/<branch>`")
    st.caption("※ ブランチは各リポジトリの現在ブランチ（なければ main）を自動使用")

if st.button("💥 強制リセットを実行（選択分）", key="btn_force_reset"):
    if not git_targets:
        st.warning("⚠️ Git リポジトリが選択されていません。")
    elif not really or confirm_text.strip().upper() != "RESET":
        st.error("確認が未完了です。『実行内容を理解した』にチェックし、`RESET` と入力してください。")
    else:
        for rec in git_targets:
            repo_path = rec["path"]
            repo_name = rec["name"]
            st.markdown(f"**{repo_name}** — `{repo_path}`")

            # origin 設定確認
            code_r, out_r, err_r = git("remote", cwd=repo_path)
            if code_r != 0 or "origin" not in (out_r or ""):
                st.error("origin が設定されていないためスキップ（`git remote add origin ...` が必要）")
                continue

            # fetch → reset --hard
            code1, out1, err1 = git("fetch origin", cwd=repo_path)
            st.code(out1 or err1 or "(no output)", language="bash")

            branch = (rec.get("branch") or "main")
            remote_ref = shlex.quote(f"origin/{branch}")
            code2, out2, err2 = git(f"reset --hard {remote_ref}", cwd=repo_path)
            st.code(out2 or err2 or "(no output)", language="bash")

            if code1 == 0 and code2 == 0:
                st.success(f"✅ {repo_name}: origin/{branch} に強制同期しました。")
            else:
                st.error(f"❌ {repo_name}: リセットに失敗しました。ログを確認してください。")

        st.info("🔁 必要なら『ステータス再読み込み』ボタンで最新状態を反映してください。")

# ------------------------------------------------------------
# 10) 🧨 完全再初期化（履歴全消去・現スナップショットのみ）
# ------------------------------------------------------------
import shutil  # ← 追加

thick_divider("#faad14", 3)
st.subheader("🧨 完全再初期化（履歴全消去・現スナップショットのみ）")

with st.expander("🧨 これは何をする？（安全確認ポイント）", expanded=False):
    st.markdown(
    """
    ### 🧨 完全再初期化とは？
    選択した各リポジトリの **`.git` ディレクトリを削除**し、`git init` からやり直します。  
    つまり **過去の履歴はすべて消え**、**今の作業ツリーだけ**を最初の1コミットとして新規作成します。

    - ✅ 現在のファイル状態だけを初期コミット化
    - ❌ すべての過去履歴・タグ・ブランチは消えます（新しい履歴になります）
    - 🔁 既存の `origin` があれば再設定して **--force** で上書き push 可能（GitHubも再初期化されます）

    > 🔴 **注意**：共有リポジトリを上書きする場合は **チーム周知必須**。  
    > 協力者は基本 **re-clone** が必要です。  
    > GitHub のブランチ保護がある場合、いったん解除してください。

    ---

    ### 💡 clone し直す方法（リモートを完全に再取得したい場合）

    #### 同じフォルダ内でやり直す（`.git`だけ削除）
    ```bash
    rm -rf .git
    git init
    git remote add origin https://github.com/ユーザー名/リポジトリ名.git
    git fetch origin
    git checkout main
    ```
    - フォルダやファイルを残したまま、Git管理だけを再初期化。
    - 作業中のファイルを保ちたい場合はこちらが安全。

    #### 💣 最も確実な方法（フォルダごと削除して再clone）
    ```bash
    cd ..
    rm -rf リポジトリ名
    git clone https://github.com/ユーザー名/リポジトリ名.git
    ```
    - フォルダ全体を削除し、リモートの最新状態を完全に再取得。
    - `.git`, `.gitattributes`, `.gitignore` なども全てリセットされます。
    - Force push や履歴リセット後は **この方法が最も確実でクリーン**。
    """
    )


col_reinit = st.columns([2, 2, 3, 3])
with col_reinit[0]:
    really_reinit = st.checkbox("実行内容を理解した（履歴は全消去）", key="chk_really_reinit")
with col_reinit[1]:
    confirm_reinit = st.text_input("確認のため `REINIT` と入力", "", key="txt_reinit_confirm")
with col_reinit[2]:
    remote_url_input = st.text_input("（任意）リモートURL（未指定なら既存originを再利用）", "", key="txt_reinit_remote")
with col_reinit[3]:
    branch_name = st.text_input("ブランチ名", "main", key="txt_reinit_branch")

col_opts = st.columns([2, 2, 3])
with col_opts[0]:
    do_force_push = st.checkbox("終了後に --force で push する", value=False, key="chk_reinit_force_push")
with col_opts[1]:
    keep_tags = st.checkbox("タグは再作成しない（推奨）", value=True, key="chk_reinit_keep_tags")
with col_opts[2]:
    st.caption("※ `.gitattributes`/`.gitignore` は作業ツリーにあればそのまま残ります。")

if st.button("🧨 再初期化を実行（選択分）", key="btn_git_reinit"):
    if not git_targets:
        st.warning("⚠️ Git リポジトリが選択されていません。")
    elif not really_reinit or confirm_reinit.strip().upper() != "REINIT":
        st.error("確認が未完了です。『実行内容を理解した』にチェックし、`REINIT` と入力してください。")
    else:
        for rec in git_targets:
            repo_path = Path(rec["path"])
            repo_name = rec["name"]
            st.markdown(f"**{repo_name}** — `{repo_path}`")

            # 事前に既存の origin を記録（入力が空なら再利用）
            code_remote, out_remote, _ = git("remote get-url origin", cwd=repo_path)
            existing_origin = out_remote.strip() if code_remote == 0 and out_remote else ""
            use_remote = remote_url_input.strip() or existing_origin

            # 1) .git を削除（完全に作り直す）
            try:
                shutil.rmtree(repo_path / ".git", ignore_errors=True)
                st.info("`.git` を削除しました。")
            except Exception as e:
                st.error(f".git の削除に失敗: {e}")
                continue

            # 2) git init → add → commit（現スナップショットを初期コミット化）
            code1, out1, err1 = git("init", cwd=repo_path)
            st.code(out1 or err1 or "(no output)", language="bash")

            code2, out2, err2 = git("add -A", cwd=repo_path)
            st.code(out2 or err2 or "(no output)", language="bash")

            code3, out3, err3 = git('commit -m "Fresh start: current snapshot only"', cwd=repo_path)
            st.code(out3 or err3 or "(no output)", language="bash")

            # 3) ブランチ名を設定（main など）
            code4, out4, err4 = git(f"branch -M {shlex.quote(branch_name)}", cwd=repo_path)
            st.code(out4 or err4 or "(no output)", language="bash")

            # 4) リモート設定（入力 > 既存origin の優先で）
            if use_remote:
                code5, out5, err5 = git(f"remote add origin {shlex.quote(use_remote)}", cwd=repo_path)
                st.code(out5 or err5 or "(no output)", language="bash")
            else:
                st.warning("リモートURLが未指定で既存originも見つかりません。pushはスキップします。")

            # 5) 必要なら --force で push
            if do_force_push and use_remote:
                code6, out6, err6 = git(f"push -u --force origin {shlex.quote(branch_name)}", cwd=repo_path)
                st.code(out6 or err6 or "(no output)", language="bash")
                if code6 == 0:
                    st.success("✅ 強制 push 完了（リモートを新履歴で上書き）")
                else:
                    st.error("❌ 強制 push に失敗しました。ログを確認してください。")

            # 6) 仕上げメッセージ
            st.success(f"🧨 {repo_name}: 再初期化が完了しました。")
            if not do_force_push:
                st.info("必要であれば『リモートURLを設定 → --force で push』を実行してください。")

        st.info("🔁 必要なら『ステータス再読み込み』ボタンで最新状態を反映してください。")
