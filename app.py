"""
BigQuery Warehouse Explorer – a Streamlit web app on top of the business layer.

Every chart is a live, parameterised BigQuery query driven by the filters in the sidebar.
Pages:
  1. NYC Taxi – Fleet & Revenue Planner   (where and when should drivers be?)
  2. Olist – Marketplace & Seller Monitor  (which sellers / states hurt customer reviews?)
  3. Pipeline – Warehouse Status           (raw -> cleaned -> business, row counts, data quality)

Run:  streamlit run app.py --server.port 8501
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess

import pandas as pd
import plotly.express as px
import streamlit as st
from google.cloud import bigquery

st.set_page_config(page_title="BigQuery Warehouse Explorer", page_icon="📊", layout="wide")

def _secret_sa() -> dict | None:
    """Service-account credentials from Streamlit secrets (used on Streamlit Community Cloud)."""
    try:
        return dict(st.secrets["gcp_service_account"])
    except Exception:
        return None


def _gcloud_project() -> str:
    try:
        return subprocess.run(["gcloud", "config", "get-value", "project"],
                              capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


SA_INFO = _secret_sa()
PROJECT = (os.environ.get("GCP_PROJECT")
           or (SA_INFO or {}).get("project_id")
           or _gcloud_project())
USER = os.environ.get("USER", "me")
DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]          # BigQuery dayofweek 1 = Sunday
BLUE, GREEN, AMBER, RED = "#2563eb", "#16a34a", "#d97706", "#dc2626"


@st.cache_resource
def client() -> bigquery.Client:
    if SA_INFO:                                  # deployed: read-only service account from secrets
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(SA_INFO)
        return bigquery.Client(project=PROJECT, credentials=creds)
    return bigquery.Client(project=PROJECT)      # Cloud Shell / local: the signed-in user


def _param(name, value):
    if isinstance(value, (list, tuple)):
        return bigquery.ArrayQueryParameter(name, "STRING", list(value))
    if isinstance(value, bool):
        return bigquery.ScalarQueryParameter(name, "BOOL", value)
    if isinstance(value, dt.date):
        return bigquery.ScalarQueryParameter(name, "DATE", value)
    if isinstance(value, int):
        return bigquery.ScalarQueryParameter(name, "INT64", value)
    return bigquery.ScalarQueryParameter(name, "STRING", value)


@st.cache_data(ttl=600, show_spinner=False)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run a parameterised query. params = ((name, value), ...) so results can be cached."""
    cfg = bigquery.QueryJobConfig(query_parameters=[_param(n, v) for n, v in params])
    return client().query(sql, job_config=cfg).to_dataframe()


def show_sql(sql: str) -> None:
    with st.expander("SQL behind this chart"):
        st.code(sql.strip(), language="sql")


def as_date(v) -> dt.date:
    return pd.Timestamp(v).date()


def money(v, prefix="$"):
    if v is None or pd.isna(v):
        return "–"
    return f"{prefix}{v/1e6:,.2f}M" if abs(v) >= 1e6 else f"{prefix}{v:,.0f}"


@st.cache_data(ttl=3600, show_spinner=False)
def default_nyc_dataset() -> str:
    """The NYC business dataset is named after whoever ran dbt (dev_<user>_business).
    Find it, so the app works for any viewer of the project without configuration."""
    if os.environ.get("NYC_DATASET"):
        return os.environ["NYC_DATASET"]
    try:
        if st.secrets.get("NYC_DATASET"):
            return str(st.secrets["NYC_DATASET"])
    except Exception:
        pass
    try:
        names = q(f"""select table_schema s from `{PROJECT}`.`region-us`.INFORMATION_SCHEMA.TABLES
                      where table_name = 'mart_daily_revenue' and table_schema like 'dev_%_business'
                      order by 1""").s.tolist()
        if names:
            return names[0]
    except Exception:
        pass
    return f"dev_{USER}_business"


# ------------------------------------------------------------------ sidebar
st.sidebar.title("📊 Warehouse Explorer")
page = st.sidebar.radio("Use case", [
    "🚕 NYC Taxi – Fleet & Revenue Planner",
    "🛒 Olist – Marketplace & Seller Monitor",
    "⚙️ Pipeline – Warehouse Status",
])
with st.sidebar.expander("Connection"):
    st.write(f"Project: `{PROJECT}`")
    nyc_ds = st.text_input("NYC business dataset", default_nyc_dataset())
    olist_ds = st.text_input("Olist business dataset", "dev_olist_business")
NYC = f"`{PROJECT}.{nyc_ds}`"
OL = f"`{PROJECT}.{olist_ds}`"


# ================================================================== NYC page
def nyc_page():
    st.title("🚕 NYC Taxi – Fleet & Revenue Planner")
    st.caption("Question: where and when should a taxi fleet place its drivers to earn the most? "
               "Live queries on `fct_trips` (~8.9M trips) in BigQuery.")

    bounds = q(f"select min(pickup_date) lo, max(pickup_date) hi from {NYC}.mart_daily_revenue")
    lo, hi = as_date(bounds.lo[0]), as_date(bounds.hi[0])
    boroughs = q(f"select distinct borough b from {NYC}.dim_zones where borough is not null order by 1").b.tolist()
    pays = q(f"select payment_type p from {NYC}.fct_trips where pickup_date = @d group by 1 order by count(*) desc",
             (("d", hi),)).p.dropna().tolist()

    st.sidebar.markdown("### Filters")
    rng = st.sidebar.date_input("Pickup dates", (lo, hi), min_value=lo, max_value=hi)
    d1, d2 = (rng if isinstance(rng, (list, tuple)) and len(rng) == 2 else (lo, hi))
    sel_b = st.sidebar.multiselect("Pickup borough", boroughs, default=[])
    sel_p = st.sidebar.multiselect("Payment type", pays, default=[])
    airport = st.sidebar.checkbox("Airport trips only")

    where = """pickup_date between @d1 and @d2
      and (coalesce(array_length(@b), 0) = 0 or pu_borough in unnest(@b))
      and (coalesce(array_length(@p), 0) = 0 or payment_type in unnest(@p))
      and (not @airport or is_airport_trip)"""
    P = (("d1", d1), ("d2", d2), ("b", tuple(sel_b)), ("p", tuple(sel_p)), ("airport", airport))

    with st.spinner("Querying BigQuery..."):
        k = q(f"""select count(*) trips, sum(total_amount) revenue, avg(total_amount) ticket,
                  avg(duration_min) minutes, avg(trip_distance) miles,
                  safe_divide(countif(payment_type_code = 1), count(*)) card
                  from {NYC}.fct_trips where {where}""", P).iloc[0]
    if not k.trips:
        st.warning("No trips match these filters.")
        return
    c = st.columns(6)
    c[0].metric("Trips", f"{k.trips:,.0f}")
    c[1].metric("Revenue", money(k.revenue))
    c[2].metric("Avg fare", f"${k.ticket:,.2f}")
    c[3].metric("Avg trip", f"{k.minutes:,.1f} min")
    c[4].metric("Avg distance", f"{k.miles:,.1f} mi")
    c[5].metric("Paid by card", f"{k.card:.0%}")

    # demand heatmap -> recommendation
    heat_sql = f"""select pickup_day_of_week dow, pickup_hour hour, count(*) trips,
                   safe_divide(sum(total_amount), sum(duration_min) / 60) rev_per_hour
                   from {NYC}.fct_trips where {where} group by 1, 2"""
    heat = q(heat_sql, P)
    heat["day"] = heat.dow.map(lambda d: DAYS[int(d) - 1])
    best = heat.sort_values("trips", ascending=False).iloc[0]
    st.success(f"**Recommendation:** peak demand for this selection is **{best.day} at {int(best.hour):02d}:00** "
               f"({best.trips:,.0f} trips in the period). Schedule the most drivers in that window.")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("When is demand highest?")
        pivot = heat.pivot_table(index="day", columns="hour", values="trips", fill_value=0).reindex(DAYS)
        fig = px.imshow(pivot, aspect="auto", color_continuous_scale="Blues",
                        labels=dict(x="Hour of day", y="", color="Trips"))
        fig.update_layout(height=330, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)
        show_sql(heat_sql)
    with right:
        st.subheader("Where should drivers wait?")
        zones_sql = f"""select pu_zone zone, count(*) trips, avg(total_amount) avg_fare
                        from {NYC}.fct_trips where {where} and pu_zone is not null
                        group by 1 order by trips desc limit 12"""
        zones = q(zones_sql, P)
        fig = px.bar(zones.sort_values("trips"), x="trips", y="zone", orientation="h",
                     hover_data={"avg_fare": ":.2f"}, color_discrete_sequence=[BLUE])
        fig.update_layout(height=330, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="", xaxis_title="Trips")
        st.plotly_chart(fig, use_container_width=True)
        show_sql(zones_sql)

    st.subheader("Daily trips and revenue")
    daily_sql = f"""select pickup_date, count(*) trips, sum(total_amount) revenue
                    from {NYC}.fct_trips where {where} group by 1 order by 1"""
    daily = q(daily_sql, P)
    fig = px.line(daily, x="pickup_date", y=["trips"], color_discrete_sequence=[BLUE])
    fig.add_scatter(x=daily.pickup_date, y=daily.revenue, name="revenue ($)", yaxis="y2", line=dict(color=GREEN))
    fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="", yaxis_title="Trips",
                      yaxis2=dict(title="Revenue ($)", overlaying="y", side="right", showgrid=False),
                      legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, use_container_width=True)
    show_sql(daily_sql)

    a, b = st.columns(2)
    with a:
        st.subheader("Most common routes")
        routes = q(f"""select concat(pu_zone, ' → ', do_zone) route, count(*) trips, avg(total_amount) avg_fare,
                       avg(duration_min) avg_minutes
                       from {NYC}.fct_trips where {where} and pu_zone is not null and do_zone is not null
                       group by 1 order by trips desc limit 10""", P)
        st.dataframe(routes.style.format({"trips": "{:,.0f}", "avg_fare": "${:,.2f}", "avg_minutes": "{:,.1f}"}),
                     use_container_width=True, hide_index=True)
    with b:
        st.subheader("Tipping by time of day (card trips)")
        tips = q(f"""select time_band, count(*) trips, approx_quantiles(tip_pct_of_fare, 100)[offset(50)] median_tip,
                     safe_divide(countif(tip_amount = 0), count(*)) no_tip
                     from {NYC}.fct_trips where {where} and tip_is_recorded and fare_amount > 0
                     group by 1""", P)
        order = ["am_peak", "midday", "pm_peak", "evening", "overnight"]
        tips["o"] = tips.time_band.map(order.index)
        fig = px.bar(tips.sort_values("o"), x="time_band", y="median_tip", color_discrete_sequence=[GREEN],
                     hover_data={"trips": ":,", "no_tip": ":.1%", "o": False})
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), yaxis_tickformat=".0%",
                          xaxis_title="", yaxis_title="Median tip % of fare")
        st.plotly_chart(fig, use_container_width=True)


# ================================================================== Olist page
def olist_page():
    st.title("🛒 Olist – Marketplace & Seller Monitor")
    st.caption("Question: which states, categories and sellers are hurting customer satisfaction? "
               "Live queries on `fct_order_items` and `mart_seller_scorecard` in BigQuery.")

    bounds = q(f"select min(purchase_date) lo, max(purchase_date) hi from {OL}.fct_order_items")
    lo, hi = as_date(bounds.lo[0]), as_date(bounds.hi[0])
    states = q(f"select distinct customer_state s from {OL}.fct_order_items where customer_state is not null order by 1").s.tolist()
    cats = q(f"""select category_name c from {OL}.fct_order_items group by 1 order by sum(line_value) desc""").c.dropna().tolist()

    st.sidebar.markdown("### Filters")
    rng = st.sidebar.date_input("Purchase dates", (lo, hi), min_value=lo, max_value=hi)
    d1, d2 = (rng if isinstance(rng, (list, tuple)) and len(rng) == 2 else (lo, hi))
    sel_s = st.sidebar.multiselect("Customer state", states, default=[])
    sel_c = st.sidebar.multiselect("Product category", cats, default=[])

    where = """purchase_date between @d1 and @d2
      and (coalesce(array_length(@s), 0) = 0 or customer_state in unnest(@s))
      and (coalesce(array_length(@c), 0) = 0 or category_name in unnest(@c))"""
    P = (("d1", d1), ("d2", d2), ("s", tuple(sel_s)), ("c", tuple(sel_c)))

    with st.spinner("Querying BigQuery..."):
        k = q(f"""with f as (select * from {OL}.fct_order_items where {where}),
                  o as (select order_id, any_value(review_score) review, any_value(is_late_delivery) late from f group by 1)
                  select (select count(*) from o) orders, (select sum(line_value) from f) revenue,
                         (select count(distinct seller_id) from f) sellers,
                         (select avg(review) from o) review,
                         (select safe_divide(countif(late), countif(late is not null)) from o) late_rate""", P).iloc[0]
    if not k.orders:
        st.warning("No orders match these filters.")
        return
    c = st.columns(5)
    c[0].metric("Orders", f"{k.orders:,.0f}")
    c[1].metric("Revenue", money(k.revenue, "R$"))
    c[2].metric("Active sellers", f"{k.sellers:,.0f}")
    c[3].metric("Avg review", f"{k.review:.2f} / 5")
    c[4].metric("Late deliveries", f"{k.late_rate:.1%}")

    late_sql = f"""with o as (select order_id, any_value(review_score) review, any_value(is_late_delivery) late
                              from {OL}.fct_order_items where {where} group by 1)
                   select if(late, 'Late', 'On time') delivery, count(*) orders, avg(review) avg_review
                   from o where late is not null group by 1"""
    late = q(late_sql, P)
    if len(late) == 2:
        gap = late.set_index("delivery").avg_review
        st.error(f"**Insight:** late orders average **{gap['Late']:.2f}★** vs **{gap['On time']:.2f}★** on time, "
                 f"a drop of **{gap['On time'] - gap['Late']:.2f} stars**. Fixing late delivery protects reviews.")

    left, right = st.columns(2)
    with left:
        st.subheader("Monthly orders and revenue")
        m = q(f"""select date_trunc(purchase_date, month) month, count(distinct order_id) orders, sum(line_value) revenue
                  from {OL}.fct_order_items where {where} group by 1 order by 1""", P)
        fig = px.bar(m, x="month", y="orders", color_discrete_sequence=[BLUE])
        fig.add_scatter(x=m.month, y=m.revenue, name="revenue (R$)", yaxis="y2", line=dict(color=GREEN))
        fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="",
                          yaxis2=dict(title="Revenue (R$)", overlaying="y", side="right", showgrid=False),
                          showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Review score: late vs on time")
        fig = px.bar(late, x="delivery", y="avg_review", color="delivery",
                     color_discrete_map={"Late": RED, "On time": GREEN}, hover_data={"orders": ":,"})
        fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
                          yaxis_range=[1, 5], xaxis_title="", yaxis_title="Average review (1-5)")
        st.plotly_chart(fig, use_container_width=True)
        show_sql(late_sql)

    a, b = st.columns(2)
    with a:
        st.subheader("Late-delivery rate by state")
        sts = q(f"""with o as (select order_id, any_value(customer_state) state, any_value(is_late_delivery) late
                               from {OL}.fct_order_items where {where} group by 1)
                    select state, count(*) orders, safe_divide(countif(late), countif(late is not null)) late_rate
                    from o group by 1 having orders >= 50 order by late_rate desc limit 15""", P)
        fig = px.bar(sts, x="state", y="late_rate", color_discrete_sequence=[AMBER], hover_data={"orders": ":,"})
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), yaxis_tickformat=".0%",
                          xaxis_title="", yaxis_title="% late")
        st.plotly_chart(fig, use_container_width=True)
    with b:
        st.subheader("Top categories by revenue")
        cat = q(f"""select category_name category, sum(line_value) revenue, avg(review_score) avg_review
                    from {OL}.fct_order_items where {where} group by 1 order by revenue desc limit 10""", P)
        fig = px.bar(cat.sort_values("revenue"), x="revenue", y="category", orientation="h",
                     color="avg_review", color_continuous_scale="RdYlGn", range_color=[3, 4.6])
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="", xaxis_title="Revenue (R$)")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("⚠️ At-risk sellers to contact")
    st.caption("Sellers active in this selection whose scorecard tier is `at_risk` "
               "(low reviews, late hand-over to carrier or high cancellations).")
    risk_sql = f"""select s.seller_id, s.seller_state, s.orders, round(s.revenue, 2) revenue,
                   round(s.avg_review_score, 2) avg_review, round(s.late_handover_rate, 3) late_handover_rate,
                   round(s.late_delivery_rate, 3) late_delivery_rate, round(s.cancellation_rate, 3) cancellation_rate
                   from {OL}.mart_seller_scorecard s
                   where s.risk_tier = 'at_risk'
                     and s.seller_id in (select seller_id from {OL}.fct_order_items where {where})
                   order by s.revenue desc limit 100"""
    risk = q(risk_sql, P)
    st.dataframe(risk, use_container_width=True, hide_index=True)
    st.download_button("Download at-risk sellers (CSV)", risk.to_csv(index=False), "at_risk_sellers.csv", "text/csv")
    show_sql(risk_sql)


# ================================================================== Pipeline page
def pipeline_page():
    st.title("⚙️ Pipeline – Warehouse Status")
    st.caption("Raw → cleaned → business layers in BigQuery, built and tested by dbt, orchestrated by Airflow.")
    st.markdown("**Source data → `raw` → `cleaned` (validated, deduplicated) → `business` (facts, dims, marts) → this app**")

    cleaned_nyc = nyc_ds.replace("_business", "_cleaned")
    cleaned_ol = olist_ds.replace("_business", "_cleaned")
    parts = []
    for layer, ds in [("raw", "raw"), ("cleaned (NYC)", cleaned_nyc), ("business (NYC)", nyc_ds),
                      ("cleaned (Olist)", cleaned_ol), ("business (Olist)", olist_ds)]:
        try:
            parts.append(q(f"""select '{layer}' layer, table_id table_name, row_count,
                               round(size_bytes / 1e6, 1) size_mb, timestamp_millis(last_modified_time) last_built
                               from `{PROJECT}.{ds}.__TABLES__`"""))
        except Exception as e:                      # dataset missing -> show and continue
            st.warning(f"Dataset `{ds}` not found ({type(e).__name__}).")
    if parts:
        tables = pd.concat(parts, ignore_index=True)
        summary = tables.groupby("layer", sort=False).agg(tables=("table_name", "count"), rows=("row_count", "sum"),
                                                          size_mb=("size_mb", "sum"), last_built=("last_built", "max"))
        c = st.columns(len(summary))
        for col, (layer, r) in zip(c, summary.iterrows()):
            col.metric(layer, f"{r.rows:,.0f} rows", f"{r.tables} tables", delta_color="off")
        st.dataframe(tables.sort_values(["layer", "row_count"], ascending=[True, False]),
                     use_container_width=True, hide_index=True,
                     column_config={"row_count": st.column_config.NumberColumn(format="%d")})

    st.subheader("Data quality: what happened to every raw NYC trip")
    try:
        dq = q(f"select outcome, sum(row_count) n from {NYC}.mart_data_quality_monthly group by 1 order by 2 desc")
        dq["kind"] = dq.outcome.map(lambda o: "accepted" if o == "accepted" else "rejected")
        fig = px.bar(dq, x="n", y="outcome", orientation="h", log_x=True, color="kind",
                     color_discrete_map={"accepted": GREEN, "rejected": AMBER})
        fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
                          yaxis_title="", xaxis_title="Rows (log scale)")
        st.plotly_chart(fig, use_container_width=True)
        acc = dq.loc[dq.outcome == "accepted", "n"].sum()
        st.info(f"{acc:,.0f} of {dq.n.sum():,.0f} raw trips accepted ({acc / dq.n.sum():.1%}). "
                "Rejected trips are kept in `stg_yellow_trips__rejected` with the rule they broke.")
    except Exception as e:
        st.warning(f"Data-quality mart not available ({type(e).__name__}).")


{"🚕": nyc_page, "🛒": olist_page, "⚙️": pipeline_page}[page.split(" ")[0]]()
st.sidebar.caption("Data: NYC TLC trip records and Olist public dataset. Built with BigQuery, dbt, Airflow and Streamlit.")
