# command_station_app/pages/172_busy集計.py
#
# -*- coding: utf-8 -*-
"""
172_busy集計.py

管理者向け：
- ai_runs.db（Storages/_admin/ai_runs/ai_runs.db）を集計して表示
- 現在の実行中（running）
- 本日・昨日（JST）の実行数 / tokens / cost
- 直近24時間の推移（簡易）
- model/provider別の内訳
- 直近エラー一覧

前提：
- busy の正本DB: common_lib.busy.paths.resolve_ai_runs_db_path(PROJECTS_ROOT)
- 時刻：JST固定（sessions系と同じ思想）
"""

from __future__ import annotations

from pathlib import Path
from datetime import timedelta
import sys
import io

import pandas as pd
import streamlit as st


# ============================================================
# sys.path 調整（common_lib を import できるように）
# ============================================================
_THIS = Path(__file__).resolve()
PROJECTS_ROOT = _THIS.parents[3]
if str(PROJECTS_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECTS_ROOT))


# ============================================================
# 共通ライブラリ
# ============================================================
from common_lib.sessions.time_utils import now_jst, date_str_jst

from common_lib.busy.paths import resolve_ai_runs_db_path
from common_lib.busy.db import ensure_db, connect



# UI表示用（存在しない場合はフォールバック）
try:
    from common_lib.ui.time_format import format_jst_iso_ja  # type: ignore
except Exception:
    format_jst_iso_ja = None  # type: ignore


def _fmt_ts(ts: str | None) -> str:
    if not ts:
        return "—"
    if format_jst_iso_ja is not None:
        try:
            return str(format_jst_iso_ja(ts))
        except Exception:
            return ts
    return ts


# ============================================================
# ページ設定
# ============================================================
st.set_page_config(
    page_title="Command Station / busy集計",
    page_icon="🤖",
    layout="wide",
)

st.title("🤖 busy集計（ai_runs.db）")
st.caption("AI実行（busy）の永続ログを集計して表示します（正本：Storages/_admin/ai_runs/ai_runs.db）")


# ============================================================
# DB接続（ai_runs.db）
# ============================================================
AI_DB = resolve_ai_runs_db_path(PROJECTS_ROOT)
ensure_db(AI_DB)
con = connect(AI_DB)


# ============================================================
# 時刻・期間（JST）
# ============================================================
now = now_jst()
today = date_str_jst(now)
yesterday = date_str_jst(now - timedelta(days=1))
since_24h = (now - timedelta(hours=24)).isoformat(timespec="seconds")


# ============================================================
# サイドバー：🧹 running クリーンアップ（1時間超を強制終了）
# ============================================================
with st.sidebar:
    st.divider()
    st.subheader("🧹 running クリーンアップ")

    st.caption("started_at から 1時間以上経過した running を強制的に終了確定します。")

    cleanup_clicked = st.button("🧹 1時間超の running を強制終了")
    
    if cleanup_clicked:
        try:
            cur = con.cursor()

            # ============================================================
            # 1時間超の running を DB側で判定して強制終了
            # - started_at は ISO文字列（例: 2026-01-21T12:21:53+09:00）
            # - julianday() で時刻として比較する（文字列比較しない）
            # ============================================================
            cur.execute(
                """
                SELECT run_id, started_at
                FROM ai_runs
                WHERE status = 'running'
                  AND (julianday('now','localtime') - julianday(started_at)) >= (1.0/24)
                ORDER BY started_at ASC
                """
            )
            rows = cur.fetchall()
            run_ids = [r[0] for r in rows]

            if not run_ids:
                st.info("強制終了対象はありません（1時間超の running は見つかりません）。")
            else:
                # 一括更新
                # - status は error に確定（運用方針：新statusを増やさない）
                # - finished_at は DB側の now(localtime)
                cur.execute(
                    """
                    UPDATE ai_runs
                    SET
                      status = 'error',
                      finished_at = datetime('now','localtime'),
                      elapsed_ms = CAST((julianday('now','localtime') - julianday(started_at)) * 86400000 AS INTEGER),
                      error_type = 'forced_finish_over_1h',
                      error_message = 'forced finish by admin (over 1h)'
                    WHERE status = 'running'
                      AND (julianday('now','localtime') - julianday(started_at)) >= (1.0/24)
                    """
                )
                con.commit()

                st.success(f"強制終了しました: {len(run_ids)} 件")
                with st.expander("対象 run_id（確認用）", expanded=False):
                    st.write(run_ids)

        except Exception as e:
            con.rollback()
            st.error(f"強制終了に失敗しました: {e}")


# ============================================================
# ① 現在の running
# ============================================================
st.subheader("🟢 現在の busy（running）")

df_running = pd.read_sql(
    """
    SELECT
      run_id,
      user_sub,
      app_name,
      page_name,
      task_type,
      provider,
      model,
      started_at,
      elapsed_ms
    FROM ai_runs
    WHERE status = 'running'
    ORDER BY started_at DESC
    """,
    con,
)

c1, c2, c3 = st.columns(3)
with c1:
    st.write("**running 件数**")
    st.write(int(len(df_running)))
with c2:
    st.write("**running users（distinct）**")
    st.write(int(df_running["user_sub"].nunique()) if not df_running.empty else 0)
with c3:
    st.write("**running apps（distinct）**")
    st.write(int(df_running["app_name"].nunique()) if not df_running.empty else 0)

if df_running.empty:
    st.info("現在 running のAI実行はありません。")
else:
    df_show = df_running.copy()
    df_show["started_at"] = df_show["started_at"].map(_fmt_ts)
    st.dataframe(df_show, width="stretch", hide_index=True)

    st.subheader("📦 running（app別）")
    df_running_app = (
        df_running.groupby(["app_name"], as_index=False)
        .agg(running=("run_id", "count"), users=("user_sub", "nunique"))
        .sort_values(["running", "users"], ascending=False)
    )
    st.dataframe(df_running_app, width="stretch", hide_index=True)

    # ------------------------------------------------------------
    # 📄 running（page別）
    # ------------------------------------------------------------
    st.subheader("📄 running（page別）")

    df_running_page = (
        df_running.groupby(["app_name", "page_name"], as_index=False)
        .agg(
            running=("run_id", "count"),
            users=("user_sub", "nunique"),
        )
        .sort_values(["running", "users"], ascending=False)
    )

    if df_running_page.empty:
        st.info("現在 running のページはありません。")
    else:
        st.dataframe(df_running_page, width="stretch", hide_index=True)


    # ------------------------------------------------------------
    # 📄 running（user別）
    # ------------------------------------------------------------
    st.subheader("👤 running（user別）")
    df_running_user = (
        df_running.groupby(["user_sub"], as_index=False)
        .agg(running=("run_id", "count"), apps=("app_name", "nunique"))
        .sort_values(["running", "apps"], ascending=False)
    )
    st.dataframe(df_running_user, width="stretch", hide_index=True)


# ============================================================
# ② 本日・昨日（JST）サマリ
# ============================================================
st.divider()
st.subheader("📅 本日・昨日（JST）の実行サマリ")

df_day = pd.read_sql(
    """
    SELECT
      run_id,
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
      cost_jpy
    FROM ai_runs
    WHERE started_at LIKE :today_prefix
       OR started_at LIKE :yesterday_prefix
    ORDER BY started_at DESC
    """,
    con,
    params={
        "today_prefix": f"{today}%",
        "yesterday_prefix": f"{yesterday}%",
    },
)

if df_day.empty:
    st.info("本日・昨日の ai_runs はありません。")
else:
    # 表示用に日時を整形
    df_day_view = df_day.copy()
    df_day_view["started_at"] = df_day_view["started_at"].map(_fmt_ts)
    df_day_view["finished_at"] = df_day_view["finished_at"].map(_fmt_ts)

    with st.expander("🧾 本日・昨日の run 一覧（raw）", expanded=False):
        st.dataframe(df_day_view, width="stretch", hide_index=True)

    # 日別サマリ（件数・tokens・cost）
    def _day_key(s: str) -> str:
        # started_at は ISOなので YYYY-MM-DD が先頭
        return (s or "")[:10] if s else "—"

    df_day2 = df_day.copy()
    df_day2["date"] = df_day2["started_at"].map(_day_key)

    df_sum_day = (
        df_day2.groupby(["date"], as_index=False)
        .agg(
            runs=("run_id", "count"),
            success=("status", lambda x: int((x == "success").sum())),
            error=("status", lambda x: int((x == "error").sum())),
            input_tokens=("input_tokens", "sum"),
            output_tokens=("output_tokens", "sum"),
            total_tokens=("total_tokens", "sum"),
            cost_usd=("cost_usd", "sum"),
            cost_jpy=("cost_jpy", "sum"),
        )
        .sort_values("date", ascending=False)
    )
    st.subheader("📌 日別サマリ（件数 / tokens / cost）")
    st.dataframe(df_sum_day, width="stretch", hide_index=True)

    df_sum_app = (
        df_day2.groupby(["date", "app_name"], as_index=False)
        .agg(
            runs=("run_id", "count"),
            total_tokens=("total_tokens", "sum"),
            cost_jpy=("cost_jpy", "sum"),
        )
        .sort_values(["date", "runs"], ascending=False)
    )
    st.subheader("📦 app別サマリ（本日・昨日）")
    st.dataframe(df_sum_app, width="stretch", hide_index=True)

    df_sum_user = (
        df_day2.groupby(["date", "user_sub"], as_index=False)
        .agg(
            runs=("run_id", "count"),
            total_tokens=("total_tokens", "sum"),
            cost_jpy=("cost_jpy", "sum"),
        )
        .sort_values(["date", "runs"], ascending=False)
    )
    st.subheader("👤 user別サマリ（本日・昨日）")
    st.dataframe(df_sum_user, width="stretch", hide_index=True)


# ============================================================
# ③ 直近24時間（簡易）
# ============================================================
st.divider()
with st.expander("⏱️ 直近24時間（簡易サマリ）", expanded=False):
    st.subheader("⏱️ 直近24時間（since: JST -24h）")

    df_24 = pd.read_sql(
        """
        SELECT
          run_id,
          user_sub,
          app_name,
          page_name,
          task_type,
          provider,
          model,
          status,
          started_at,
          elapsed_ms,
          total_tokens,
          cost_jpy
        FROM ai_runs
        WHERE started_at >= :since
        ORDER BY started_at DESC
        """,
        con,
        params={"since": since_24h},
    )

    if df_24.empty:
        st.info("直近24時間の ai_runs はありません。")
    else:
        st.caption(f"対象期間: {today}（含む） / since={since_24h}")

        # provider/model 別
        st.subheader("🧠 provider / model 別（直近24h）")
        df_24_model = (
            df_24.groupby(["provider", "model"], as_index=False)
            .agg(
                runs=("run_id", "count"),
                success=("status", lambda x: int((x == "success").sum())),
                error=("status", lambda x: int((x == "error").sum())),
                total_tokens=("total_tokens", "sum"),
                cost_jpy=("cost_jpy", "sum"),
            )
            .sort_values(["runs", "total_tokens"], ascending=False)
        )
        st.dataframe(df_24_model, width="stretch", hide_index=True)

        # app 別
        st.subheader("📦 app別（直近24h）")
        df_24_app = (
            df_24.groupby(["app_name"], as_index=False)
            .agg(
                runs=("run_id", "count"),
                total_tokens=("total_tokens", "sum"),
                cost_jpy=("cost_jpy", "sum"),
            )
            .sort_values(["runs", "total_tokens"], ascending=False)
        )
        st.dataframe(df_24_app, width="stretch", hide_index=True)

        # 直近エラー（24h）
        st.subheader("🚨 直近エラー（24h / 上位20）")
        df_24_err = pd.read_sql(
            """
            SELECT
              started_at,
              user_sub,
              app_name,
              page_name,
              provider,
              model,
              error_type,
              error_message,
              run_id
            FROM ai_runs
            WHERE status = 'error'
              AND started_at >= :since
            ORDER BY started_at DESC
            LIMIT 20
            """,
            con,
            params={"since": since_24h},
        )
        if df_24_err.empty:
            st.info("直近24時間のエラーはありません。")
        else:
            df_24_err_view = df_24_err.copy()
            df_24_err_view["started_at"] = df_24_err_view["started_at"].map(_fmt_ts)
            st.dataframe(df_24_err_view, width="stretch", hide_index=True)


# ============================================================
# ④ 直近エラー（全期間 / 上位）
# ============================================================
st.divider()
with st.expander("🚨 エラー一覧（最新50）", expanded=False):
    df_err = pd.read_sql(
        """
        SELECT
          started_at,
          user_sub,
          app_name,
          page_name,
          task_type,
          provider,
          model,
          error_type,
          error_message,
          run_id
        FROM ai_runs
        WHERE status = 'error'
        ORDER BY started_at DESC
        LIMIT 50
        """,
        con,
        parse_dates=None,
    )

    if df_err.empty:
        st.info("エラーはありません。")
    else:
        df_err_view = df_err.copy()
        df_err_view["started_at"] = df_err_view["started_at"].map(_fmt_ts)
        st.dataframe(df_err_view, width="stretch", hide_index=True)


# ============================================================
# ⑤ Excel ダウンロード（任意）
# ============================================================
st.divider()
with st.expander("⬇️ 集計結果を Excel でダウンロード（任意）", expanded=False):
    st.caption("※ ai_runs.db の代表的な集計表をシートに分けて保存します。")

    # 直近24h と 本日/昨日 が無い場合にも落ちないように用意
    df_24_for_xlsx = pd.read_sql(
        """
        SELECT *
        FROM ai_runs
        WHERE started_at >= :since
        ORDER BY started_at DESC
        """,
        con,
        params={"since": since_24h},
    )

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        # running
        if not df_running.empty:
            df_running.to_excel(writer, sheet_name="running", index=False)

        # today/yesterday raw
        if not df_day.empty:
            df_day.to_excel(writer, sheet_name="today_yesterday_raw", index=False)

        # day summary（あれば）
        if "df_sum_day" in globals() and not df_sum_day.empty:
            df_sum_day.to_excel(writer, sheet_name="day_summary", index=False)

        # 24h raw
        if not df_24_for_xlsx.empty:
            df_24_for_xlsx.to_excel(writer, sheet_name="last24h_raw", index=False)

        # error latest
        if "df_err" in globals() and not df_err.empty:
            df_err.to_excel(writer, sheet_name="errors_latest", index=False)

    buf.seek(0)
    st.download_button(
        label="📥 Excelをダウンロード",
        data=buf.getvalue(),
        file_name=f"busy_summary_{today}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ============================================================
# クローズ
# ============================================================
con.close()
st.caption("※ 時刻はすべて JST（ISO文字列）。ai_runs.db は永続ログです。")
