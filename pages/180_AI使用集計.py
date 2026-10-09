# -*- coding: utf-8 -*-
# command_station_app/pages/180_AI使用集計.py
# ============================================================
# 🤖 AI使用集計（管理者向け）
#
# 目的：
# - ai_runs.db に保存されている全AI実行ログを参照専用で集計する
# - PAIS内でAIを使用している app / page / user / model を把握する
# - run_id 単位でAI実行の詳細を確認する
#
# 方針：
# - ai_runs.db は参照のみとし，INSERT / UPDATE / DELETE は行わない
# - 既存の common_lib/busy および 172_busy集計.py は変更しない
# - 時刻は ai_runs.db に保存されている JST ISO文字列を使用する
# ============================================================

from __future__ import annotations

# ============================================================
# imports
# ============================================================

from datetime import date, timedelta
from pathlib import Path
import io
import json
import sys

import pandas as pd
import streamlit as st


# ============================================================
# sys.path 調整
# ============================================================

_THIS = Path(__file__).resolve()
PROJECTS_ROOT = _THIS.parents[3]

if str(PROJECTS_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECTS_ROOT))


# ============================================================
# common_lib
# ============================================================

from common_lib.sessions.time_utils import now_jst
from common_lib.busy.paths import resolve_ai_runs_db_path
from common_lib.busy.db import ensure_db, connect


# ============================================================
# UI表示用
# ============================================================

try:
    from common_lib.ui.time_format import format_jst_iso_ja  # type: ignore
except Exception:
    format_jst_iso_ja = None  # type: ignore


# ============================================================
# helper
# ============================================================

def _fmt_ts(ts: str | None) -> str:
    if not ts:
        return "—"

    if format_jst_iso_ja is not None:
        try:
            return str(format_jst_iso_ja(ts))
        except Exception:
            return str(ts)

    return str(ts)


def _safe_int(value) -> int:
    if pd.isna(value):
        return 0

    try:
        return int(value)
    except Exception:
        return 0


def _safe_float(value) -> float:
    if pd.isna(value):
        return 0.0

    try:
        return float(value)
    except Exception:
        return 0.0


def _format_meta_json(value: str | None) -> str:
    if not value:
        return ""

    try:
        obj = json.loads(value)
        return json.dumps(
            obj,
            ensure_ascii=False,
            indent=2,
        )
    except Exception:
        return str(value)


# ============================================================
# page
# ============================================================

st.set_page_config(
    page_title="Command Station / AI使用集計",
    page_icon="🤖",
    layout="wide",
)

st.title("🤖 AI使用集計")

st.caption(
    "PAIS全体のAI実行ログ（ai_runs.db）を参照し，"
    "利用者・アプリ・ページ・モデル・token・費用等を集計します。"
)

st.info(
    "このページは参照専用です。"
    "ai_runs.db の INSERT / UPDATE / DELETE は行いません。"
)


# ============================================================
# DB
# ============================================================

AI_DB = resolve_ai_runs_db_path(PROJECTS_ROOT)
ensure_db(AI_DB)

con = connect(AI_DB)


# ============================================================
# 全ログ読込
# ============================================================

df_all = pd.read_sql(
    """
    SELECT
        run_id,
        parent_run_id,
        user_sub,
        app_name,
        page_name,
        task_type,
        provider,
        model,
        status,
        started_at,
        finished_at,
        elapsed_ms,
        input_tokens,
        output_tokens,
        total_tokens,
        cost_usd,
        usd_jpy,
        cost_jpy,
        error_type,
        error_message,
        meta_json
    FROM ai_runs
    ORDER BY started_at DESC
    """,
    con,
)


# ============================================================
# データなし
# ============================================================

if df_all.empty:
    st.warning("ai_runs.db にAI実行ログがありません。")
    con.close()
    st.stop()


# ============================================================
# 日付列
# ============================================================

df_all["run_date"] = df_all["started_at"].astype(str).str[:10]
df_all["run_month"] = df_all["started_at"].astype(str).str[:7]

available_dates = [
    str(v)
    for v in df_all["run_date"].dropna().unique().tolist()
    if str(v).strip()
]

available_dates = sorted(available_dates)

today_jst = now_jst().date()

if available_dates:
    try:
        first_log_date = date.fromisoformat(available_dates[0])
    except Exception:
        first_log_date = today_jst
else:
    first_log_date = today_jst


# ============================================================
# ① 集計条件
# ============================================================

st.divider()
st.subheader("① 集計条件")

c1, c2 = st.columns(2)

with c1:
    start_date = st.date_input(
        "開始日",
        value=max(
            first_log_date,
            today_jst - timedelta(days=30),
        ),
        min_value=first_log_date,
        max_value=today_jst,
        key="180_ai_usage__start_date",
    )

with c2:
    end_date = st.date_input(
        "終了日",
        value=today_jst,
        min_value=first_log_date,
        max_value=today_jst,
        key="180_ai_usage__end_date",
    )

if start_date > end_date:
    st.error("開始日は終了日以前にしてください。")
    con.close()
    st.stop()


# ============================================================
# 期間で先に絞る
# ============================================================

df_period = df_all[
    (df_all["run_date"] >= start_date.isoformat())
    & (df_all["run_date"] <= end_date.isoformat())
].copy()


# ============================================================
# filter options
# ============================================================

def _options(column: str) -> list[str]:
    if df_period.empty:
        return []

    values = (
        df_period[column]
        .dropna()
        .astype(str)
        .map(str.strip)
    )

    values = [
        value
        for value in values.unique().tolist()
        if value
    ]

    return sorted(values)


user_options = _options("user_sub")
app_options = _options("app_name")
page_options = _options("page_name")
task_options = _options("task_type")
provider_options = _options("provider")
model_options = _options("model")
status_options = _options("status")


# ============================================================
# filter UI
# ============================================================

f1, f2, f3, f4 = st.columns(4)

with f1:
    selected_user = st.selectbox(
        "利用者",
        ["すべて"] + user_options,
        key="180_ai_usage__user",
    )

with f2:
    selected_app = st.selectbox(
        "アプリ",
        ["すべて"] + app_options,
        key="180_ai_usage__app",
    )

with f3:
    selected_page = st.selectbox(
        "ページ",
        ["すべて"] + page_options,
        key="180_ai_usage__page",
    )

with f4:
    selected_task = st.selectbox(
        "処理種別",
        ["すべて"] + task_options,
        key="180_ai_usage__task",
    )


f5, f6, f7 = st.columns(3)

with f5:
    selected_provider = st.selectbox(
        "Provider",
        ["すべて"] + provider_options,
        key="180_ai_usage__provider",
    )

with f6:
    selected_model = st.selectbox(
        "モデル",
        ["すべて"] + model_options,
        key="180_ai_usage__model",
    )

with f7:
    selected_status = st.selectbox(
        "状態",
        ["すべて"] + status_options,
        key="180_ai_usage__status",
    )


# ============================================================
# filter
# ============================================================

df = df_period.copy()

if selected_user != "すべて":
    df = df[df["user_sub"].astype(str) == selected_user]

if selected_app != "すべて":
    df = df[df["app_name"].astype(str) == selected_app]

if selected_page != "すべて":
    df = df[df["page_name"].astype(str) == selected_page]

if selected_task != "すべて":
    df = df[df["task_type"].astype(str) == selected_task]

if selected_provider != "すべて":
    df = df[df["provider"].astype(str) == selected_provider]

if selected_model != "すべて":
    df = df[df["model"].astype(str) == selected_model]

if selected_status != "すべて":
    df = df[df["status"].astype(str) == selected_status]


st.caption(
    f"対象期間：{start_date.isoformat()} ～ {end_date.isoformat()}　"
    f"対象AI実行：{len(df):,} 件"
)


# ============================================================
# ② 全体サマリ
# ============================================================

st.divider()
st.subheader("② 全体サマリ")

if df.empty:
    st.info("指定条件に該当するAI実行ログはありません。")
else:
    run_count = int(len(df))
    user_count = int(df["user_sub"].nunique())
    app_count = int(df["app_name"].nunique())
    page_count = int(df["page_name"].nunique())

    input_tokens = _safe_int(df["input_tokens"].sum())
    output_tokens = _safe_int(df["output_tokens"].sum())
    total_tokens = _safe_int(df["total_tokens"].sum())
    cost_jpy = _safe_float(df["cost_jpy"].sum())

    error_count = int((df["status"] == "error").sum())

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric("AI実行回数", f"{run_count:,}")

    with c2:
        st.metric("利用ユーザー数", f"{user_count:,}")

    with c3:
        st.metric("利用アプリ数", f"{app_count:,}")

    with c4:
        st.metric("利用ページ数", f"{page_count:,}")

    c5, c6, c7, c8 = st.columns(4)

    with c5:
        st.metric("入力 token", f"{input_tokens:,}")

    with c6:
        st.metric("出力 token", f"{output_tokens:,}")

    with c7:
        st.metric("総 token", f"{total_tokens:,}")

    with c8:
        st.metric("費用", f"¥{cost_jpy:,.2f}")

    st.caption(f"エラー：{error_count:,} 件")


# ============================================================
# ③ AI使用ページ一覧
# ============================================================

st.divider()
st.subheader("③ AI使用ページ一覧")

st.caption(
    "現在 ai_runs.db に記録されているAI利用箇所を，"
    "app / page / task_type / provider / model 単位で集計します。"
)

if df.empty:
    st.info("表示対象はありません。")
else:
    df_page = (
        df.groupby(
            [
                "app_name",
                "page_name",
                "task_type",
                "provider",
                "model",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            runs=("run_id", "count"),
            users=("user_sub", "nunique"),
            last_used_at=("started_at", "max"),
            input_tokens=("input_tokens", "sum"),
            output_tokens=("output_tokens", "sum"),
            total_tokens=("total_tokens", "sum"),
            cost_jpy=("cost_jpy", "sum"),
        )
        .sort_values(
            ["runs", "last_used_at"],
            ascending=[False, False],
        )
    )

    df_page_view = df_page.copy()
    df_page_view["last_used_at"] = df_page_view["last_used_at"].map(_fmt_ts)

    st.dataframe(
        df_page_view,
        width="stretch",
        hide_index=True,
    )


# ============================================================
# ④ 利用者別集計
# ============================================================

st.divider()
st.subheader("④ 利用者別集計")

if df.empty:
    st.info("表示対象はありません。")
else:
    df_user = (
        df.groupby(
            ["user_sub"],
            as_index=False,
        )
        .agg(
            runs=("run_id", "count"),
            apps=("app_name", "nunique"),
            pages=("page_name", "nunique"),
            input_tokens=("input_tokens", "sum"),
            output_tokens=("output_tokens", "sum"),
            total_tokens=("total_tokens", "sum"),
            cost_jpy=("cost_jpy", "sum"),
            last_used_at=("started_at", "max"),
        )
        .sort_values(
            ["runs", "total_tokens"],
            ascending=False,
        )
    )

    df_user_view = df_user.copy()
    df_user_view["last_used_at"] = df_user_view["last_used_at"].map(_fmt_ts)

    st.dataframe(
        df_user_view,
        width="stretch",
        hide_index=True,
    )



# ============================================================
# ⑤ 利用者別月別集計
# ============================================================

st.divider()
st.subheader("⑤ 利用者別月別集計")

if df.empty:
    st.info("表示対象はありません。")
else:
    df_user_month = (
        df.groupby(
            [
                "run_month",
                "user_sub",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            runs=("run_id", "count"),
            apps=("app_name", "nunique"),
            pages=("page_name", "nunique"),
            input_tokens=("input_tokens", "sum"),
            output_tokens=("output_tokens", "sum"),
            total_tokens=("total_tokens", "sum"),
            cost_jpy=("cost_jpy", "sum"),
            last_used_at=("started_at", "max"),
        )
        .sort_values(
            [
                "run_month",
                "user_sub",
            ],
            ascending=[False, True],
        )
    )

    df_user_month_view = df_user_month.copy()

    df_user_month_view["last_used_at"] = (
        df_user_month_view["last_used_at"].map(_fmt_ts)
    )

    df_user_month_view = df_user_month_view.rename(
        columns={
            "run_month": "利用月",
            "user_sub": "利用者",
            "runs": "実行回数",
            "apps": "アプリ数",
            "pages": "ページ数",
            "input_tokens": "入力 token",
            "output_tokens": "出力 token",
            "total_tokens": "総 token",
            "cost_jpy": "費用（円）",
            "last_used_at": "最終利用日時",
        }
    )

    st.dataframe(
        df_user_month_view,
        width="stretch",
        hide_index=True,
        column_config={
            "利用月": st.column_config.TextColumn(
                "利用月",
                width="small",
            ),
            "利用者": st.column_config.TextColumn(
                "利用者",
                width="medium",
            ),
            "実行回数": st.column_config.NumberColumn(
                "実行回数",
                format="%d",
            ),
            "アプリ数": st.column_config.NumberColumn(
                "アプリ数",
                format="%d",
            ),
            "ページ数": st.column_config.NumberColumn(
                "ページ数",
                format="%d",
            ),
            "入力 token": st.column_config.NumberColumn(
                "入力 token",
                format="%d",
            ),
            "出力 token": st.column_config.NumberColumn(
                "出力 token",
                format="%d",
            ),
            "総 token": st.column_config.NumberColumn(
                "総 token",
                format="%d",
            ),
            "費用（円）": st.column_config.NumberColumn(
                "費用（円）",
                format="¥%.2f",
            ),
            "最終利用日時": st.column_config.TextColumn(
                "最終利用日時",
                width="medium",
            ),
        },
    )

# ============================================================
# ⑥ Provider / Model別集計
# ============================================================

st.divider()
st.subheader("⑥ Provider / Model別集計")

if df.empty:
    st.info("表示対象はありません。")
else:
    df_model = (
        df.groupby(
            ["provider", "model"],
            dropna=False,
            as_index=False,
        )
        .agg(
            runs=("run_id", "count"),
            users=("user_sub", "nunique"),
            apps=("app_name", "nunique"),
            pages=("page_name", "nunique"),
            input_tokens=("input_tokens", "sum"),
            output_tokens=("output_tokens", "sum"),
            total_tokens=("total_tokens", "sum"),
            cost_jpy=("cost_jpy", "sum"),
            last_used_at=("started_at", "max"),
        )
        .sort_values(
            ["runs", "total_tokens"],
            ascending=False,
        )
    )

    df_model_view = df_model.copy()
    df_model_view["last_used_at"] = df_model_view["last_used_at"].map(_fmt_ts)

    st.dataframe(
        df_model_view,
        width="stretch",
        hide_index=True,
    )


# ============================================================
# ⑥ AI実行履歴
# ============================================================

st.divider()
st.subheader("⑥ AI実行履歴")

if df.empty:
    st.info("表示対象はありません。")
else:
    df_runs = df[
        [
            "started_at",
            "user_sub",
            "app_name",
            "page_name",
            "task_type",
            "provider",
            "model",
            "status",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cost_jpy",
            "run_id",
        ]
    ].copy()

    df_runs["started_at"] = df_runs["started_at"].map(_fmt_ts)

    st.dataframe(
        df_runs,
        width="stretch",
        hide_index=True,
    )


# ============================================================
# ⑦ run_id 詳細
# ============================================================

st.divider()
st.subheader("⑦ run_id 詳細")

if df.empty:
    st.info("確認できる run_id はありません。")
else:
    run_ids = df["run_id"].dropna().astype(str).tolist()

    selected_run_id = st.selectbox(
        "確認する run_id",
        run_ids,
        key="180_ai_usage__run_id",
    )

    selected_rows = df[
        df["run_id"].astype(str) == selected_run_id
    ]

    if selected_rows.empty:
        st.warning("指定した run_id のデータが見つかりません。")
    else:
        row = selected_rows.iloc[0]

        d1, d2 = st.columns(2)

        with d1:
            st.write("**run_id**")
            st.code(str(row["run_id"]))

            st.write("**parent_run_id**")
            st.write(
                "—"
                if pd.isna(row["parent_run_id"])
                else str(row["parent_run_id"])
            )

            st.write("**利用者**")
            st.write(str(row["user_sub"]))

            st.write("**アプリ**")
            st.write(str(row["app_name"]))

            st.write("**ページ**")
            st.write(str(row["page_name"]))

            st.write("**処理種別**")
            st.write(str(row["task_type"]))

            st.write("**Provider**")
            st.write(str(row["provider"]))

            st.write("**Model**")
            st.write(str(row["model"]))

        with d2:
            st.write("**状態**")
            st.write(str(row["status"]))

            st.write("**開始日時**")
            st.write(_fmt_ts(row["started_at"]))

            st.write("**終了日時**")
            st.write(_fmt_ts(row["finished_at"]))

            st.write("**処理時間（ms）**")
            st.write(_safe_int(row["elapsed_ms"]))

            st.write("**入力 token**")
            st.write(_safe_int(row["input_tokens"]))

            st.write("**出力 token**")
            st.write(_safe_int(row["output_tokens"]))

            st.write("**総 token**")
            st.write(_safe_int(row["total_tokens"]))

            st.write("**費用（USD）**")
            st.write(_safe_float(row["cost_usd"]))

            st.write("**USD/JPY**")
            st.write(_safe_float(row["usd_jpy"]))

            st.write("**費用（JPY）**")
            st.write(_safe_float(row["cost_jpy"]))

        if (
            not pd.isna(row["error_type"])
            or not pd.isna(row["error_message"])
        ):
            with st.expander("🚨 エラー情報", expanded=False):
                st.write("**error_type**")
                st.write(
                    ""
                    if pd.isna(row["error_type"])
                    else str(row["error_type"])
                )

                st.write("**error_message**")
                st.write(
                    ""
                    if pd.isna(row["error_message"])
                    else str(row["error_message"])
                )

        with st.expander("🧾 meta_json", expanded=False):
            st.code(
                _format_meta_json(
                    None
                    if pd.isna(row["meta_json"])
                    else str(row["meta_json"])
                ),
                language="json",
            )


# ============================================================
# ⑧ Excel ダウンロード
# ============================================================

st.divider()
st.subheader("⑧ Excel ダウンロード")

st.caption(
    "現在の集計条件で絞り込まれているAI使用実績をExcelでダウンロードします。"
)

if df.empty:
    st.info("ダウンロード対象のAI実行ログはありません。")
else:
    # --------------------------------------------------------
    # Excel出力用データ
    # --------------------------------------------------------

    df_excel_runs = df[
        [
            "run_id",
            "parent_run_id",
            "user_sub",
            "app_name",
            "page_name",
            "task_type",
            "provider",
            "model",
            "status",
            "started_at",
            "finished_at",
            "elapsed_ms",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cost_usd",
            "usd_jpy",
            "cost_jpy",
            "error_type",
            "error_message",
            "meta_json",
        ]
    ].copy()

    df_excel_page = (
        df.groupby(
            [
                "app_name",
                "page_name",
                "task_type",
                "provider",
                "model",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            runs=("run_id", "count"),
            users=("user_sub", "nunique"),
            last_used_at=("started_at", "max"),
            input_tokens=("input_tokens", "sum"),
            output_tokens=("output_tokens", "sum"),
            total_tokens=("total_tokens", "sum"),
            cost_jpy=("cost_jpy", "sum"),
        )
        .sort_values(
            ["runs", "last_used_at"],
            ascending=[False, False],
        )
    )

    df_excel_user = (
        df.groupby(
            ["user_sub"],
            as_index=False,
        )
        .agg(
            runs=("run_id", "count"),
            apps=("app_name", "nunique"),
            pages=("page_name", "nunique"),
            input_tokens=("input_tokens", "sum"),
            output_tokens=("output_tokens", "sum"),
            total_tokens=("total_tokens", "sum"),
            cost_jpy=("cost_jpy", "sum"),
            last_used_at=("started_at", "max"),
        )
        .sort_values(
            ["runs", "total_tokens"],
            ascending=False,
        )
    )


    df_excel_user_month = (
        df.groupby(
            [
                "run_month",
                "user_sub",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            runs=("run_id", "count"),
            apps=("app_name", "nunique"),
            pages=("page_name", "nunique"),
            input_tokens=("input_tokens", "sum"),
            output_tokens=("output_tokens", "sum"),
            total_tokens=("total_tokens", "sum"),
            cost_jpy=("cost_jpy", "sum"),
            last_used_at=("started_at", "max"),
        )
        .sort_values(
            [
                "run_month",
                "user_sub",
            ],
            ascending=[False, True],
        )
    )

    df_excel_user_month["last_used_at"] = (
        df_excel_user_month["last_used_at"].map(_fmt_ts)
    )

    df_excel_user_month = df_excel_user_month.rename(
        columns={
            "run_month": "利用月",
            "user_sub": "利用者",
            "runs": "実行回数",
            "apps": "アプリ数",
            "pages": "ページ数",
            "input_tokens": "入力 token",
            "output_tokens": "出力 token",
            "total_tokens": "総 token",
            "cost_jpy": "費用（円）",
            "last_used_at": "最終利用日時",
        }
    )

    df_excel_model = (
        df.groupby(
            ["provider", "model"],
            dropna=False,
            as_index=False,
        )
        .agg(
            runs=("run_id", "count"),
            users=("user_sub", "nunique"),
            apps=("app_name", "nunique"),
            pages=("page_name", "nunique"),
            input_tokens=("input_tokens", "sum"),
            output_tokens=("output_tokens", "sum"),
            total_tokens=("total_tokens", "sum"),
            cost_jpy=("cost_jpy", "sum"),
            last_used_at=("started_at", "max"),
        )
        .sort_values(
            ["runs", "total_tokens"],
            ascending=False,
        )
    )

    df_excel_summary = pd.DataFrame(
        [
            {
                "開始日": start_date.isoformat(),
                "終了日": end_date.isoformat(),
                "利用者": selected_user,
                "アプリ": selected_app,
                "ページ": selected_page,
                "処理種別": selected_task,
                "Provider": selected_provider,
                "モデル": selected_model,
                "状態": selected_status,
                "AI実行回数": int(len(df)),
                "利用ユーザー数": int(df["user_sub"].nunique()),
                "利用アプリ数": int(df["app_name"].nunique()),
                "利用ページ数": int(df["page_name"].nunique()),
                "入力token": _safe_int(df["input_tokens"].sum()),
                "出力token": _safe_int(df["output_tokens"].sum()),
                "総token": _safe_int(df["total_tokens"].sum()),
                "費用JPY": _safe_float(df["cost_jpy"].sum()),
                "エラー件数": int((df["status"] == "error").sum()),
            }
        ]
    )

    # --------------------------------------------------------
    # Excel生成
    # --------------------------------------------------------

    excel_buffer = io.BytesIO()

    with pd.ExcelWriter(
        excel_buffer,
        engine="openpyxl",
    ) as writer:
        df_excel_summary.to_excel(
            writer,
            sheet_name="集計条件・概要",
            index=False,
        )

        df_excel_page.to_excel(
            writer,
            sheet_name="AI使用ページ一覧",
            index=False,
        )

        df_excel_user.to_excel(
            writer,
            sheet_name="利用者別集計",
            index=False,
        )

        df_excel_user_month.to_excel(
            writer,
            sheet_name="利用者別月別集計",
            index=False,
        )

        ws_user_month = writer.sheets["利用者別月別集計"]

        for row in range(2, ws_user_month.max_row + 1):
            ws_user_month.cell(row=row, column=3).number_format = "#,##0"
            ws_user_month.cell(row=row, column=4).number_format = "#,##0"
            ws_user_month.cell(row=row, column=5).number_format = "#,##0"
            ws_user_month.cell(row=row, column=6).number_format = "#,##0"
            ws_user_month.cell(row=row, column=7).number_format = "#,##0"
            ws_user_month.cell(row=row, column=8).number_format = "#,##0"
            ws_user_month.cell(row=row, column=9).number_format = '¥#,##0.00'

        ws_user_month.column_dimensions["A"].width = 12
        ws_user_month.column_dimensions["B"].width = 18
        ws_user_month.column_dimensions["C"].width = 12
        ws_user_month.column_dimensions["D"].width = 12
        ws_user_month.column_dimensions["E"].width = 12
        ws_user_month.column_dimensions["F"].width = 18
        ws_user_month.column_dimensions["G"].width = 18
        ws_user_month.column_dimensions["H"].width = 18
        ws_user_month.column_dimensions["I"].width = 16
        ws_user_month.column_dimensions["J"].width = 24

        df_excel_model.to_excel(
            writer,
            sheet_name="モデル別集計",
            index=False,
        )

        df_excel_runs.to_excel(
            writer,
            sheet_name="AI実行履歴",
            index=False,
        )

    excel_buffer.seek(0)

    download_timestamp = now_jst().strftime("%Y%m%d-%H%M%S")

    st.download_button(
        label="📥 AI使用集計をExcelでダウンロード",
        data=excel_buffer.getvalue(),
        file_name=f"{download_timestamp}_AI使用集計.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="180_ai_usage__excel_download",
    )


# ============================================================
# DB情報
# ============================================================

st.divider()

with st.expander("🗄️ 参照DB情報", expanded=False):
    st.write("**ai_runs.db**")
    st.code(str(AI_DB))

    st.write("**全保存件数**")
    st.write(f"{len(df_all):,} 件")

    st.write("**最古の記録日**")
    st.write(available_dates[0] if available_dates else "—")

    st.write("**最新の記録日**")
    st.write(available_dates[-1] if available_dates else "—")

    st.caption(
        "このページでは ai_runs.db の参照のみを行い，"
        "データの追加・変更・削除は行いません。"
    )


# ============================================================
# close
# ============================================================

con.close()
