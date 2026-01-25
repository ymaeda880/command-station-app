# -*- coding: utf-8 -*-
"""
170_ログイン集計.py

管理者向け：
- 現在の同時ログイン数（ユーザー / セッション）
- app別の同時ログイン状況
- 時系列（1分粒度）
- 時間帯別・曜日別の利用傾向
- ユーザー別・app別の日次利用量

前提：
- 正本DB: resolve_sessions_db_path(PROJECTS_ROOT) が返すパス（storages.mode に従う）
- 共通ロジック : common_lib.sessions
- 時刻 : JST 固定
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime
import pandas as pd
import streamlit as st
import io

_THIS = Path(__file__).resolve()
PROJECTS_ROOT = _THIS.parents[3]
import sys
if str(PROJECTS_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECTS_ROOT))


from common_lib.sessions.time_utils import now_jst, date_str_jst


# ============================================================
# ページ設定
# ============================================================
st.set_page_config(
    page_title="📊 ログイン集計（管理）",
    page_icon="📊",
    layout="wide",
)

st.title("📊 ログイン集計（管理）")
st.caption("同時ログイン数・時間帯別/曜日別傾向・ユーザー別利用状況")

# ============================================================
# sys.path 調整（common_lib を import 可能に）
# ============================================================
_THIS = Path(__file__).resolve()
PROJECTS_ROOT = _THIS.parents[3]  # pages → command_station_app → command_station_project → projects
import sys
if str(PROJECTS_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECTS_ROOT))

# ============================================================
# 共通ライブラリ
# ============================================================
from common_lib.sessions import (
    SessionConfig,
    get_active_counts,
)
from common_lib.sessions.db import ensure_db
from common_lib.sessions.paths import resolve_sessions_db_path


# ============================================================
# DB パス解決（確定事項）
# ============================================================
SESSIONS_DB = resolve_sessions_db_path(PROJECTS_ROOT)
cfg = SessionConfig()

# ============================================================
# DB 接続
# ============================================================
con = ensure_db(SESSIONS_DB)

# ============================================================
# ① 現在の同時ログイン数（全app合計）
# ============================================================
st.subheader("🟢 現在の同時ログイン状況")

current = get_active_counts(
    db_path=SESSIONS_DB,
    cfg=cfg,
)

c1, c2 = st.columns(2)
with c1:
    st.metric("同時ログイン人数", current["active_users"])
with c2:
    st.metric("同時セッション数", current["active_sessions"])

# ============================================================
# ② app別 同時ログイン数
# ============================================================
st.divider()
st.subheader("📦 app別 同時ログイン人数（現在）")

df_apps = pd.read_sql(
    """
    SELECT
      app_name,
      COUNT(DISTINCT user_sub) AS active_users,
      COUNT(*) AS active_sessions
    FROM session_state
    WHERE logout_at IS NULL
      AND last_seen >= datetime('now', 'localtime', printf('-%d seconds', ?))
    GROUP BY app_name
    ORDER BY active_users DESC
    """,
    con,
    params=(cfg.ttl_sec,),
)

if df_apps.empty:
    st.info("現在アクティブなログインはありません。")
else:
    st.dataframe(df_apps, width="stretch", hide_index=True)

# ============================================================
# ②-b page別 同時ログイン数（現在）
# ============================================================
#st.divider()
st.subheader("📄 page別 同時ログイン人数（現在）")

df_pages = pd.read_sql(
    """
    SELECT
      app_name,
      page_name,
      COUNT(DISTINCT user_sub)   AS active_users,
      COUNT(DISTINCT session_id) AS active_sessions
    FROM session_state
    WHERE logout_at IS NULL
      AND last_seen >= datetime('now', 'localtime', printf('-%d seconds', ?))
    GROUP BY app_name, page_name
    ORDER BY app_name, active_users DESC
    """,
    con,
    params=(cfg.ttl_sec,),
)

if df_pages.empty:
    st.info("現在アクティブなページはありません。")
else:
    st.dataframe(df_pages, width="stretch", hide_index=True)


# ============================================================
# ③ 直近24時間：app別（縦に並べる）＋最後に総数
#   - 利用がない app（active_users>0 が一度もない）は出さない
# ============================================================

with st.expander("📊 同時ログイン数の推移（直近24時間）", expanded=False):

    st.divider()
    st.subheader("📊 同時ログイン数の推移（直近24時間・棒グラフ）")

    df_ts = pd.read_sql(
        """
        SELECT
          bucket_ts,
          app_name,
          active_users,
          peak_users
        FROM active_samples
        WHERE bucket_ts >= datetime('now', 'localtime', '-24 hours')
        ORDER BY bucket_ts ASC
        """,
        con,
        parse_dates=["bucket_ts"],
    )

    # --------------------------
    # DEBUG: df_ts の中身確認
    # --------------------------
    with st.expander("🔧 DEBUG: 直近24h df_ts の状態", expanded=False):
        st.write("rows:", len(df_ts))
        if not df_ts.empty:
            st.write("columns:", list(df_ts.columns))
            st.write("dtypes:", df_ts.dtypes.astype(str).to_dict())

            st.write(
                "unique app_name count:",
                int(df_ts["app_name"].nunique(dropna=False)),
            )
            st.write(
                "app_name sample (first 30):",
                df_ts["app_name"].head(30).tolist(),
            )

            pos = (
                df_ts.assign(is_pos=(df_ts["active_users"] > 0))
                    .groupby("app_name")["is_pos"]
                    .sum()
                    .sort_values(ascending=False)
            )
            st.write("count(active_users>0) by app (top 30):")
            st.dataframe(
                pos.head(30).reset_index(),
                width="stretch",
                hide_index=True,
            )

            st.write(
                "active_users unique sample (up to 30):",
                df_ts["active_users"].dropna().unique()[:30].tolist(),
            )

    if df_ts.empty:
        st.info("時系列データがまだありません。")
    else:
        # ------------------------------------------------------------
        # 表示範囲（現在時刻基準で24時間）
        # ------------------------------------------------------------
        now_local = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None)
        x_min = now_local - pd.Timedelta(hours=24)
        x_max = now_local

        import altair as alt

        # 利用があった app のみ
        df_used = df_ts[df_ts["active_users"] > 0].copy()

        if df_used.empty:
            st.info("直近24時間に利用がないため、推移グラフは表示しません。")
        else:
            order_apps = (
                df_used.groupby("app_name")["bucket_ts"].max()
                .sort_values(ascending=False)
                .index
                .tolist()
            )

            for app in order_apps:
                df_plot = df_ts[df_ts["app_name"] == app].copy()
                if df_plot.empty:
                    continue
                if not (df_plot["active_users"] > 0).any():
                    continue

                st.caption(f"📦 {app}")

                chart = (
                    alt.Chart(df_plot[df_plot["active_users"] > 0])
                    .mark_bar(size=8)
                    .encode(
                        x=alt.X(
                            "bucket_ts:T",
                            title=None,
                            axis=alt.Axis(format="%H:%M"),
                        ),
                        y=alt.Y(
                            "active_users:Q",
                            title="人数",
                            axis=alt.Axis(tickMinStep=1),
                            scale=alt.Scale(domainMin=0),
                        ),
                        tooltip=[
                            alt.Tooltip("bucket_ts:T", title="時刻"),
                            alt.Tooltip("active_users:Q", title="同時ログイン人数"),
                        ],
                    )
                    .properties(height=140)
                )

                st.altair_chart(chart)

            # ------------------------------------------------------------
            # 全アプリ合計
            # ------------------------------------------------------------
            st.caption("📌 全アプリ合計")

            df_total = (
                df_ts.groupby("bucket_ts", as_index=False)
                .agg(
                    active_users=("active_users", "sum"),
                    peak_users=("peak_users", "max"),
                )
            )

            chart_total = (
                alt.Chart(df_total)
                .mark_bar()
                .encode(
                    x=alt.X(
                        "bucket_ts:T",
                        title="時刻",
                        axis=alt.Axis(format="%H:%M"),
                        scale=alt.Scale(domain=[x_min, x_max]),
                    ),
                    y=alt.Y(
                        "active_users:Q",
                        title="同時ログイン人数（合計）",
                        scale=alt.Scale(domainMin=0),
                    ),
                    tooltip=[
                        alt.Tooltip("bucket_ts:T", title="時刻"),
                        alt.Tooltip(
                            "active_users:Q",
                            title="同時ログイン人数（合計）",
                        ),
                        alt.Tooltip("peak_users:Q", title="ピーク（参考）"),
                    ],
                )
                .properties(height=300, width="container")
            )

            st.altair_chart(chart_total)



# ============================================================
# ④ 時間帯別（平均・ピーク） - 今月 / 先月（expander）
#    ※ 位置：③（直近24h推移 expander）の直後
# ============================================================
with st.expander("⏰ 時間帯別 同時ログイン人数（今月 / 先月）", expanded=False):
    st.subheader("⏰ 時間帯別 同時ログイン人数（今月 / 先月）")

    # JST基準で「今月の初日 00:00」「先月の初日 00:00」を作る
    now_local = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None)
    this_month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_start = (this_month_start - pd.DateOffset(months=1)).to_pydatetime()
    this_month_start = this_month_start.to_pydatetime()

    # ----------------------------
    # 今月
    # ----------------------------
    st.caption(f"🟢 今月（{this_month_start:%Y-%m}）")

    df_hour_this = pd.read_sql(
        """
        SELECT
          CAST(strftime('%H', bucket_ts) AS INTEGER) AS hour,
          app_name,
          AVG(active_users) AS avg_users,
          MAX(peak_users) AS peak_users
        FROM active_samples
        WHERE bucket_ts >= :start
        GROUP BY hour, app_name
        ORDER BY hour, app_name
        """,
        con,
        params={"start": this_month_start.strftime("%Y-%m-%d %H:%M:%S")},
    )

    if df_hour_this.empty:
        st.info("今月の時間帯別データがありません。")
    else:
        st.dataframe(df_hour_this, width="stretch", hide_index=True)

    # ----------------------------
    # 先月
    # ----------------------------
    st.divider()
    st.caption(f"🟡 先月（{last_month_start:%Y-%m}）")

    df_hour_last = pd.read_sql(
        """
        SELECT
          CAST(strftime('%H', bucket_ts) AS INTEGER) AS hour,
          app_name,
          AVG(active_users) AS avg_users,
          MAX(peak_users) AS peak_users
        FROM active_samples
        WHERE bucket_ts >= :start
          AND bucket_ts <  :end
        GROUP BY hour, app_name
        ORDER BY hour, app_name
        """,
        con,
        params={
            "start": last_month_start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": this_month_start.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )

    if df_hour_last.empty:
        st.info("先月の時間帯別データがありません。")
    else:
        st.dataframe(df_hour_last, width="stretch", hide_index=True)


# ============================================================
# ⑤ 曜日別（平均・ピーク） - 今月 / 先月（expander）
#    ※ 位置：③（直近24h推移 expander）の直後
# ============================================================
with st.expander("📅 曜日別 同時ログイン人数（今月 / 先月）", expanded=False):
    st.subheader("📅 曜日別 同時ログイン人数（今月 / 先月）")

    weekday_map = {0: "日", 1: "月", 2: "火", 3: "水", 4: "木", 5: "金", 6: "土"}

    # JST基準で「今月の初日 00:00」「先月の初日 00:00」を作る
    now_local = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None)
    this_month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_start = (this_month_start - pd.DateOffset(months=1)).to_pydatetime()
    this_month_start = this_month_start.to_pydatetime()

    # ----------------------------
    # 今月
    # ----------------------------
    st.caption(f"🟢 今月（{this_month_start:%Y-%m}）")

    df_weekday_this = pd.read_sql(
        """
        SELECT
          CAST(strftime('%w', bucket_ts) AS INTEGER) AS weekday,
          app_name,
          AVG(active_users) AS avg_users,
          MAX(peak_users) AS peak_users
        FROM active_samples
        WHERE bucket_ts >= :start
        GROUP BY weekday, app_name
        ORDER BY weekday, app_name
        """,
        con,
        params={"start": this_month_start.strftime("%Y-%m-%d %H:%M:%S")},
    )

    if df_weekday_this.empty:
        st.info("今月の曜日別データがありません。")
    else:
        df_weekday_this["weekday"] = df_weekday_this["weekday"].map(weekday_map)
        st.dataframe(df_weekday_this, width="stretch", hide_index=True)

    # ----------------------------
    # 先月
    # ----------------------------
    st.divider()
    st.caption(f"🟡 先月（{last_month_start:%Y-%m}）")

    df_weekday_last = pd.read_sql(
        """
        SELECT
          CAST(strftime('%w', bucket_ts) AS INTEGER) AS weekday,
          app_name,
          AVG(active_users) AS avg_users,
          MAX(peak_users) AS peak_users
        FROM active_samples
        WHERE bucket_ts >= :start
          AND bucket_ts <  :end
        GROUP BY weekday, app_name
        ORDER BY weekday, app_name
        """,
        con,
        params={
            "start": last_month_start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": this_month_start.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )

    if df_weekday_last.empty:
        st.info("先月の曜日別データがありません。")
    else:
        df_weekday_last["weekday"] = df_weekday_last["weekday"].map(weekday_map)
        st.dataframe(df_weekday_last, width="stretch", hide_index=True)


# ============================================================
# session_state 本日分＋昨日分（last_seen基準）
# ============================================================
from common_lib.sessions.time_utils import now_jst, date_str_jst
from datetime import timedelta

today_jst = date_str_jst(now_jst())
yesterday_jst = date_str_jst(now_jst() - timedelta(days=1))

st.divider()
st.subheader("📋 session_state（本日分＋昨日分）")
st.write("session_stateの書き込み確認用")
st.caption("２分間操作がないとsessionが切れる．")

df_today_session = pd.read_sql(
    """
    SELECT
      user_sub,
      app_name,
      page_name,
      login_at,
      last_seen,
      logout_at,
      session_id
    FROM session_state
    WHERE last_seen IS NOT NULL
      AND date(last_seen) IN (:today, :yesterday)
    ORDER BY last_seen DESC
    """,
    con,
    params={
        "today": today_jst,
        "yesterday": yesterday_jst,
    },
    parse_dates=["login_at", "last_seen", "logout_at"],
)

if df_today_session.empty:
    st.info("本日・昨日分の session_state はありません。")
else:
    st.dataframe(df_today_session, width="stretch", hide_index=True)


# ============================================================
# user_app_daily 本日分＋昨日分（日次集計）
# ============================================================
from common_lib.sessions.time_utils import now_jst, date_str_jst
from datetime import timedelta

today_jst = date_str_jst(now_jst())
yesterday_jst = date_str_jst(now_jst() - timedelta(days=1))

st.divider()
st.subheader("👤 ユーザー別 × app別 利用量（本日＋昨日）")

df_user_today = pd.read_sql(
    """
    SELECT
      date,
      user_sub,
      app_name,
      active_minutes,
      peak_users_day,
      peak_sessions_day
    FROM user_app_daily
    WHERE date IN (:today, :yesterday)
    ORDER BY date DESC, active_minutes DESC
    """,
    con,
    params={
        "today": today_jst,
        "yesterday": yesterday_jst,
    },
)

if df_user_today.empty:
    st.info("本日・昨日分の user_app_daily はありません。")
else:
    st.dataframe(df_user_today, width="stretch", hide_index=True)


# ============================================================
# ⑥-b 本日・昨日：active_minutes 合計（ユーザー別 / app別）
# ============================================================
st.divider()
st.subheader("📌 active_minutes 合計（本日 / 昨日）")

from datetime import timedelta
from common_lib.sessions.time_utils import now_jst, date_str_jst

today_jst = date_str_jst(now_jst())
yesterday_jst = date_str_jst(now_jst() - timedelta(days=1))

# ------------------------------------------------------------
# 本日
# ------------------------------------------------------------
st.caption(f"🟢 本日（{today_jst}）")

df_user_today_sum = pd.read_sql(
    """
    SELECT
      user_sub,
      SUM(active_minutes) AS active_minutes_sum
    FROM user_app_daily
    WHERE date = :today
    GROUP BY user_sub
    ORDER BY active_minutes_sum DESC
    """,
    con,
    params={"today": today_jst},
)

df_app_today_sum = pd.read_sql(
    """
    SELECT
      app_name,
      SUM(active_minutes) AS active_minutes_sum
    FROM user_app_daily
    WHERE date = :today
    GROUP BY app_name
    ORDER BY active_minutes_sum DESC
    """,
    con,
    params={"today": today_jst},
)

c1, c2 = st.columns(2)
with c1:
    st.caption("👤 ユーザー別（本日）")
    if df_user_today_sum.empty:
        st.info("本日の user 別集計はありません。")
    else:
        st.dataframe(df_user_today_sum, width="stretch", hide_index=True)

with c2:
    st.caption("📦 app別（本日）")
    if df_app_today_sum.empty:
        st.info("本日の app 別集計はありません。")
    else:
        st.dataframe(df_app_today_sum, width="stretch", hide_index=True)

# ------------------------------------------------------------
# 昨日
# ------------------------------------------------------------
st.divider()
st.caption(f"🟡 昨日（{yesterday_jst}）")

df_user_yesterday_sum = pd.read_sql(
    """
    SELECT
      user_sub,
      SUM(active_minutes) AS active_minutes_sum
    FROM user_app_daily
    WHERE date = :yesterday
    GROUP BY user_sub
    ORDER BY active_minutes_sum DESC
    """,
    con,
    params={"yesterday": yesterday_jst},
)

df_app_yesterday_sum = pd.read_sql(
    """
    SELECT
      app_name,
      SUM(active_minutes) AS active_minutes_sum
    FROM user_app_daily
    WHERE date = :yesterday
    GROUP BY app_name
    ORDER BY active_minutes_sum DESC
    """,
    con,
    params={"yesterday": yesterday_jst},
)

c3, c4 = st.columns(2)
with c3:
    st.caption("👤 ユーザー別（昨日）")
    if df_user_yesterday_sum.empty:
        st.info("昨日の user 別集計はありません。")
    else:
        st.dataframe(df_user_yesterday_sum, width="stretch", hide_index=True)

with c4:
    st.caption("📦 app別（昨日）")
    if df_app_yesterday_sum.empty:
        st.info("昨日の app 別集計はありません。")
    else:
        st.dataframe(df_app_yesterday_sum, width="stretch", hide_index=True)









# ============================================================
# ⑥ ユーザー別 × app別 日次利用量
# ============================================================
st.divider()
st.subheader("👤 ユーザー別 × app別 利用量（日次）（過去全ログ）")

df_user = pd.read_sql(
    """
    SELECT
      date,
      user_sub,
      app_name,
      active_minutes
    FROM user_app_daily
    ORDER BY date DESC, active_minutes DESC
    LIMIT 500
    """,
    con,
)

if df_user.empty:
    st.info("ユーザー別集計データがまだありません。")
else:
    st.dataframe(df_user, width="stretch", hide_index=True)


# ================================
# 集計結果を Excel でダウンロード
# ================================
st.divider()
st.subheader("⬇️ 集計結果を Excel でダウンロード")

# 期間表示（任意：ファイル名に入れると便利）
ts_min = None
ts_max = None
if not df_ts.empty:
    ts_min = df_ts["bucket_ts"].min()
    ts_max = df_ts["bucket_ts"].max()

fname_range = ""
if ts_min is not None and ts_max is not None:
    try:
        fname_range = f"_{ts_min:%Y%m%d_%H%M}-{ts_max:%Y%m%d_%H%M}"
    except Exception:
        fname_range = ""

excel_name = f"login_summary{fname_range}.xlsx"

buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as writer:
    # ① 現在値（メトリクス相当）
    pd.DataFrame([current]).to_excel(writer, sheet_name="current_total", index=False)

    # ② app別（現在）
    if not df_apps.empty:
        df_apps.to_excel(writer, sheet_name="current_by_app", index=False)

    # ③ 時系列（直近24hの生データ）
    if not df_ts.empty:
        df_ts.to_excel(writer, sheet_name="ts_raw", index=False)

        # pivot した「チャート用」も保存（重複があっても落ちないよう pivot_table）
        df_ts_pivot = (
            df_ts.pivot_table(
                index="bucket_ts",
                columns="app_name",
                values="active_users",
                aggfunc="max",
            )
            .sort_index()
        )
        df_ts_pivot.to_excel(writer, sheet_name="ts_pivot_active_users")

    # ④ 時間帯別（今月 / 先月）
    if "df_hour_this" in globals() and not df_hour_this.empty:
        df_hour_this.to_excel(writer, sheet_name="by_hour_this_month", index=False)
    if "df_hour_last" in globals() and not df_hour_last.empty:
        df_hour_last.to_excel(writer, sheet_name="by_hour_last_month", index=False)

    # ⑤ 曜日別（今月 / 先月）
    if "df_weekday_this" in globals() and not df_weekday_this.empty:
        df_weekday_this.to_excel(writer, sheet_name="by_weekday_this_month", index=False)
    if "df_weekday_last" in globals() and not df_weekday_last.empty:
        df_weekday_last.to_excel(writer, sheet_name="by_weekday_last_month", index=False)

    # ⑥ ユーザー別×app別（日次）
    if not df_user.empty:
        df_user.to_excel(writer, sheet_name="user_app_daily", index=False)

buf.seek(0)

st.download_button(
    label="📥 Excelをダウンロード",
    data=buf.getvalue(),
    file_name=excel_name,
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
st.caption("※ 各表はシートに分けて保存しています（current/ts/by_hour/by_weekday/user_app_daily など）。")

# ============================================================
# クローズ
# ============================================================
con.close()

st.caption("※ 時刻はすべて JST。active_minutes は 1分粒度のサンプルに基づく値です。")
