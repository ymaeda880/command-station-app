# command_station_app/pages/160_ディスク状態.py
from __future__ import annotations

import html
import platform
import socket
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = Path(__file__).resolve().parents[3]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from lib.server_disk_usage import (  # noqa: E402
    aggregate_children, breakdown, collect_disks, disk_usage, excel_bytes,
    exclusive_parts, human_size, now_jst, read_monitor_routes, read_targets, run_command,
    scan_folder, scan_overview, target_error,
)

COLORS = {"projects": "#8b5cf6", "Storages": "#2563eb", "InBoxStorages": "#14b8a6",
          "Archive": "#db2777", "Databases": "#059669", "その他の使用量": "#f59e0b", "使用済み": "#f59e0b", "空き": "#e2e8f0"}
STATE_KEY = "disk_status_v2"


@st.cache_data(ttl=30, show_spinner=False)
def load_disks(host: str, routes: tuple) -> dict:
    return collect_disks(routes)


def render_bar(segments: list[dict], total: int) -> None:
    blocks, legends = [], []
    for segment in segments:
        amount = max(0, segment["bytes"])
        percent = amount / total * 100 if total else 0
        if not amount:
            continue
        label = html.escape(segment["label"])
        color = COLORS.get(segment.get("color_key", segment["label"]), "#64748b")
        tooltip = html.escape(f"{segment['label']}：{human_size(amount)}（{percent:.1f}%）", quote=True)
        foreground = "#0f172a" if segment["label"] in ("空き", "使用済み", "その他の使用量") else "#ffffff"
        short = f"{percent:.0f}%" if percent >= 6 else ""
        blocks.append(f'<div title="{tooltip}" style="width:{percent:.6f}%;background:{color};color:{foreground};'
                      f'display:flex;align-items:center;justify-content:center;overflow:hidden;font-weight:650">{short}</div>')
        legends.append(f'<span style="display:inline-flex;align-items:center;gap:6px;margin:5px 18px 0 0">'
                       f'<span style="background:{color};width:11px;height:11px;border-radius:3px;display:inline-block"></span>'
                       f'{label} <strong>{human_size(amount)}</strong> <span>({percent:.1f}%)</span></span>')
    st.markdown('<div role="img" aria-label="ディスク容量の内訳" style="display:flex;height:34px;width:100%;'
                'border-radius:8px;overflow:hidden;background:#e2e8f0">' + "".join(blocks) + '</div>'
                '<div style="font-size:0.86rem;line-height:1.7;margin-top:5px">' + "".join(legends) + '</div>',
                unsafe_allow_html=True)


def capacity_table(rows: list[dict], name_column: str) -> None:
    if not rows:
        st.info("表示する内訳がありません。")
        return
    data = []
    total = sum(row["bytes"] for row in rows)
    for row in rows:
        record = {name_column: row.get("category", row.get("user", "")),
                  "容量": human_size(row["bytes"]), "容量（GiB）": row["bytes"] / 1024**3,
                  "構成比": f"{row['bytes'] / total * 100:.1f}%" if total else "0.0%"}
        if "kind" in row:
            record["区分"] = row["kind"]
        data.append(record)
    st.dataframe(pd.DataFrame(data), hide_index=True, width="stretch",
                 column_config={"容量（GiB）": st.column_config.ProgressColumn(
                     "容量（GiB）", min_value=0, max_value=max(0.001, max(row["bytes"] for row in rows) / 1024**3), format="%.2f")})


st.set_page_config(page_title="ディスク状態", page_icon="💽", layout="wide")
location, targets = read_targets(PROJECTS_ROOT)
routes = read_monitor_routes(PROJECTS_ROOT, location, targets)
route_key = tuple((row["name"], row["path"]) for row in routes if row["path"])
host = socket.gethostname()
fingerprint = (str(PROJECTS_ROOT), host, location, tuple((r["name"], r["path"], r["mode"]) for r in targets))
if STATE_KEY not in st.session_state or st.session_state[STATE_KEY]["fingerprint"] != fingerprint:
    st.session_state[STATE_KEY] = {"fingerprint": fingerprint, "overview": {}, "details": {}, "raw_log": None}
state = st.session_state[STATE_KEY]

st.title("💽 PAISサーバーのディスク状態")
st.caption(f"接続先：{location} ｜ サーバー：{host} ｜ {platform.system()}　•　この画面を動かしているサーバーの容量です。")
st.caption("対象：本体SSDと、現在のPAIS設定で指定されている保存先・バックアップ・同期先のディスク。")
toolbar = st.columns([3, 1])
with toolbar[0]:
    st.write("**空き容量と使用率**を確認し、必要なときにフォルダーの内訳を計測できます。")
with toolbar[1]:
    if st.button("ディスク情報を更新", width="stretch", key="disk_refresh"):
        state.pop("excel", None)
        load_disks.clear()
snapshot = load_disks(host, route_key)
disks = snapshot["disks"]
target_problems = [f"{t['name']}：{t['error']}" for t in targets if t["error"]]
disk_issues = [d for d in disks if d["level"] in ("warning", "error")]
unknown = snapshot["enumeration_error"] or any(d["error"] for d in disks)
if disk_issues:
    message = " ／ ".join(f"{d['name']}：{d['percent']:.1f}% 使用・空き {human_size(d['free'])}" for d in disk_issues)
    (st.error if any(d["level"] == "error" for d in disk_issues) else st.warning)(message)
elif unknown or target_problems:
    st.warning("一部のディスク・保存先を確認できません。確認できたディスクは下に表示しています。")
else:
    st.success("接続中のPAIS関連ディスクに、使用率80％以上のものはありません。")
st.caption(f"ディスク情報：{snapshot['measured_at']}（日本時間） ｜ 80％以上：注意 ／ 90％以上：要対応")

# 計測後の切断や設定変更があれば、その結果を現在のバーには使用しない。
active_results = {}
for target in targets:
    result = state["overview"].get(target["name"])
    if result and result.get("ok") and not target["error"]:
        try:
            if Path(target["path"]).resolve() == Path(result["path"]) and Path(target["path"]).stat().st_dev == result["device"]:
                active_results[target["name"]] = result
        except OSError:
            pass
parts, part_error = exclusive_parts(active_results)

for disk in disks:
    with st.container(border=True):
        columns = st.columns([2.1, 1, 1, 1])
        with columns[0]:
            st.subheader(("🖥️ " if disk["is_main"] else "💾 ") + disk["name"])
            st.caption(" / ".join(disk["mounts"]))
            if disk.get("purposes"):
                st.caption("用途：" + "・".join(disk["purposes"]))
        if disk["error"]:
            st.warning(f"容量を取得できません：{disk['error']}")
            continue
        columns[1].metric("使用率", f"{disk['percent']:.1f}%")
        columns[2].metric("空き容量", human_size(disk["free"]))
        columns[3].metric("総容量", human_size(disk["total"]))
        matching = [p for p in parts if p["device"] in disk["device_ids"]]
        measured_total = sum(p["bytes"] for p in matching)
        if matching and measured_total <= disk["used"]:
            segments = [{"label": p["label"], "bytes": p["bytes"], "color_key": p["names"][0]} for p in matching]
            segments.append({"label": "その他の使用量", "bytes": disk["used"] - measured_total})
        else:
            segments = [{"label": "使用済み", "bytes": disk["used"]}]
        segments.append({"label": "空き", "bytes": disk["free"]})
        render_bar(segments, disk["total"])
        if matching and measured_total > disk["used"]:
            st.caption("フォルダー集計が使用済み容量を超えるため、使用済み／空きだけを表示しています。共有ファイルや計測時刻の差が影響する場合があります。")
        elif matching:
            times = [active_results[n]["measured_at"] for p in matching for n in p["names"]]
            st.caption(f"フォルダー内訳：{min(times)}〜{max(times)} の計測値。空き容量は上記のディスク情報更新時点です。")
        else:
            st.caption("「全体の内訳を計測」を押すと、このディスク内のPAIS主要フォルダーを色分けします。バックアップ・同期先はディスク全体の使用率を表示します。")
if part_error:
    st.info(part_error)
if unknown:
    st.warning("取得できなかったディスクがあるため、総合判定は未完了です。「詳細・診断」で確認できます。")

auxiliary = [row for row in routes if row["kind"] != "main"]
if auxiliary:
    with st.expander("PAIS設定のバックアップ・同期先（接続状況）"):
        st.caption("storage.toml の現在の環境の設定です。未接続の装置はここに表示し、容量の判定には含めません。")
        st.dataframe(pd.DataFrame([{"用途": r["name"], "保存先": r["path"] or "未設定",
                                   "接続状況": r["error"] or "接続中"} for r in auxiliary]),
                     hide_index=True, width="stretch")

st.subheader("フォルダーの使用量")
st.caption("projects 全体には、内部保存の Storages・InBoxStorages なども含まれます。上の横棒では重複分を差し引いています。")
settings_left, settings_right = st.columns([3, 1])
with settings_right:
    with st.expander("計測設定"):
        timeout = st.number_input("1回の計測の制限時間（秒）", min_value=30, max_value=3600, value=900, step=30, key="disk_timeout")
        st.caption("合計容量・ユーザー別・アプリ別のすべての計測に適用します。")
        if st.button("計測結果をクリア", key="disk_clear_measurements"):
            state["overview"] = {}
            state["details"] = {}
            state.pop("excel", None)
            st.rerun()
with settings_left:
    run_overview = st.button("全体の内訳を計測", type="primary", key="disk_scan_overview")
if run_overview:
    state.pop("excel", None)
    meter = st.progress(0, text="容量を計測しています…")
    def progress(index, count, name):
        meter.progress(index / count, text=f"{name} を計測しています（{index + 1}/{count}）")
    with st.spinner("フォルダーの容量を計測中…"):
        state["overview"] = scan_overview(targets, int(timeout), progress)
    load_disks.clear()
    st.rerun()

folder_rows = []
for target in targets:
    result = state["overview"].get(target["name"])
    error = target["error"] or (result.get("error", "") if result else "")
    valid = result is not None and result.get("ok") and not error
    folder_rows.append({"対象": target["name"], "容量": human_size(result["total"] if valid else None),
                        "状態": "確認が必要" if error else ("計測済み" if valid else "未計測"),
                        "保存先": target["path"] or "未設定", "計測日時": result["measured_at"] if result else "—"})
st.dataframe(pd.DataFrame(folder_rows), hide_index=True, width="stretch")
for target in targets:
    result = state["overview"].get(target["name"], {})
    error = target["error"] or result.get("error", "")
    if error:
        st.warning(f"{target['name']}：{error}")
st.caption("容量はディスク上の使用領域を集計しています。別ディスクや子シンボリックリンクの先は含めません。GiB＝1,024³バイト、TiB＝1,024⁴バイトです。")

st.divider()
st.subheader("ユーザー別・アプリ別の内訳")
st.caption("Storages はユーザー → アプリ、InBoxStorages はユーザー → ファイル種別で集計します。ボタンを押したときだけ計測します。")
if st.button("ユーザー・アプリ別を計測", key="disk_scan_details"):
    state.pop("excel", None)
    details = {}
    for target in targets:
        if target["name"] not in ("Storages", "InBoxStorages"):
            continue
        problem = target_error(target)
        if problem:
            details[target["name"]] = {"ok": False, "error": problem, "rows": {}, "total": None,
                                       "path": target["path"], "measured_at": now_jst()}
        else:
            with st.spinner(f"{target['name']} のユーザー・分類別の容量を計測しています…"):
                details[target["name"]] = scan_folder(Path(target["path"]), 2, int(timeout))
    state["details"] = details
    st.rerun()

detail_results = state["details"]
stor_users, stor_children = breakdown(detail_results.get("Storages", {}))
inbox_users, inbox_children = breakdown(detail_results.get("InBoxStorages", {}))
app_totals = aggregate_children(stor_children)
type_totals = aggregate_children(inbox_children)
user_rows = []
users = sorted({row["user"] for row in stor_users + inbox_users})
stor_lookup = {r["user"]: r for r in stor_users}
inbox_lookup = {r["user"]: r for r in inbox_users}
for user in users:
    a, b = stor_lookup.get(user), inbox_lookup.get(user)
    stor_ok = detail_results.get("Storages", {}).get("ok", False)
    inbox_ok = detail_results.get("InBoxStorages", {}).get("ok", False)
    stor_bytes = (a["bytes"] if a else 0) if stor_ok else None
    inbox_bytes = (b["bytes"] if b else 0) if inbox_ok else None
    total = (stor_bytes or 0) + (inbox_bytes or 0)
    user_rows.append({"ユーザー／フォルダー": user, "区分": (a or b)["kind"],
                      "Storages": human_size(stor_bytes), "InBoxStorages": human_size(inbox_bytes),
                      "合計（取得分）": human_size(total), "合計（GiB）": total / 1024**3})
user_rows.sort(key=lambda row: -row["合計（GiB）"])

if not detail_results:
    st.info("「ユーザー・アプリ別を計測」で表示します。")
else:
    for name, result in detail_results.items():
        st.caption(f"{name}：{result['measured_at']}（日本時間）の計測結果")
        if not result.get("ok"):
            st.warning(f"{name} の内訳を取得できません：{result.get('error', '')}　失敗した対象は合計に含めていません。")
    user_tab, app_tab, type_tab = st.tabs(["ユーザー別", "Storages：アプリ別", "InBoxStorages：ファイル種別"])
    with user_tab:
        if user_rows:
            st.dataframe(pd.DataFrame(user_rows), hide_index=True, width="stretch",
                         column_config={"合計（GiB）": st.column_config.ProgressColumn(
                             "合計（GiB）", min_value=0, max_value=max(0.001, max(r["合計（GiB）"] for r in user_rows)), format="%.2f")})
            st.caption("「_」「.」で始まるフォルダーと logs、直下ファイルは共通・管理として表示します。")
            selected = st.selectbox("ユーザー／フォルダーを選んで詳しく見る", users, key="disk_detail_user")
            detail_cols = st.columns(2)
            with detail_cols[0]:
                st.write("**Storages の内訳**")
                capacity_table(aggregate_children(stor_children, selected), "アプリ／分類")
            with detail_cols[1]:
                st.write("**InBoxStorages の内訳**")
                capacity_table(aggregate_children(inbox_children, selected), "ファイル種別")
        else:
            st.info("表示できるユーザー別の計測結果がありません。")
    with app_tab:
        st.caption("全ユーザー・共通管理フォルダーを横断し、同じアプリ／分類名を合計しています。")
        capacity_table(app_totals, "アプリ／分類")
    with type_tab:
        capacity_table(type_totals, "ファイル種別")

with st.expander("projects 直下の内訳"):
    result = state["overview"].get("projects", {})
    if result.get("ok"):
        root = Path(result["path"])
        children = [{"category": Path(path).name, "bytes": size} for path, size in result["rows"].items() if Path(path).parent == root]
        extra = max(0, result["total"] - sum(row["bytes"] for row in children))
        if extra:
            children.append({"category": "（直下ファイル等）", "bytes": extra})
        capacity_table(sorted(children, key=lambda row: -row["bytes"]), "フォルダー")
    else:
        st.info("「全体の内訳を計測」で表示します。")

with st.expander("Excelに保存"):
    if st.button("現在の表示内容からExcelを作成", key="disk_make_excel"):
        disk_rows = [{"ディスク": d["name"], "保存先": " / ".join(d["mounts"]),
                      "総容量（バイト）": d.get("total"), "使用済み（バイト）": d.get("used"),
                      "空き（バイト）": d.get("free"), "使用率（％）": d.get("percent"),
                      "状態": d["status"], "計測日時": snapshot["measured_at"]} for d in disks]
        sheets = {"ディスク": disk_rows, "フォルダー": folder_rows, "ユーザー別": user_rows,
                  "Storagesアプリ別": [{"アプリ／分類": r["category"], "容量（バイト）": r["bytes"], "容量（GiB）": r["bytes"] / 1024**3} for r in app_totals],
                  "InBox種別": [{"ファイル種別": r["category"], "容量（バイト）": r["bytes"], "容量（GiB）": r["bytes"] / 1024**3} for r in type_totals],
                  "計測情報": [{"対象": name, "計測日時": row["measured_at"], "エラー": row.get("error", "")}
                              for name, row in {**state["overview"], **{f"{k} 内訳": v for k, v in detail_results.items()}}.items()]}
        try:
            state["excel"] = (excel_bytes(sheets), f"disk_usage_{now_jst().replace('-', '').replace(':', '').replace(' ', '_')}.xlsx")
        except Exception as exc:
            state.pop("excel", None)
            st.error(f"Excelを作成できません：{exc}")
    if state.get("excel"):
        st.download_button("作成したExcelをダウンロード", data=state["excel"][0], file_name=state["excel"][1],
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with st.expander("任意の保存先を確認"):
    target_path = st.text_input("対象パス", value=str(PROJECTS_ROOT), key="disk_custom_path")
    if st.button("この保存先のディスク容量を確認", key="disk_custom_check"):
        try:
            usage = disk_usage(Path(target_path).expanduser())
            st.write(f"使用率 {usage['percent']:.1f}% ／ 空き {human_size(usage['free'])} ／ 総容量 {human_size(usage['total'])}")
        except (OSError, ValueError) as exc:
            st.error(f"取得できません：{exc}")

with st.expander("詳細・診断"):
    st.caption("同じAPFSコンテナのボリュームは、情報を取得できた場合にまとめて表示します。複数ディスクの容量は合算していません。")
    for message in snapshot["errors"]:
        st.code(message)
    st.code(snapshot["df_raw"] or "df の結果なし", language="text")
    if platform.system() == "Darwin" and st.button("PAISのディスク詳細を取得", key="disk_raw_log"):
        logs = []
        for disk in disks:
            code, output, error = run_command(["diskutil", "info", disk["sample_path"]], 15)
            logs.append(disk["name"] + "\n" + (output.decode("utf-8", "replace") if code == 0 else error))
        state["raw_log"] = "\n\n".join(logs)
    if state.get("raw_log"):
        st.code(state["raw_log"], language="text")
