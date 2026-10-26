# BigQuery Warehouse Explorer

**Live app:** https://bigquery-warehouse-explorer.streamlit.app

A Streamlit web app on top of two BigQuery warehouses (raw → cleaned → business, built with dbt).
Every chart is a live, parameterised BigQuery query driven by the sidebar filters.

| Page | Business question |
|---|---|
| 🚕 NYC Taxi – Fleet & Revenue Planner | Where and when should a taxi fleet place drivers? Demand heatmap, top zones, routes, tips, recommendation |
| 🛒 Olist – Marketplace & Seller Monitor | Which states, categories and sellers hurt customer reviews? Late vs on-time insight, at-risk seller list (CSV) |
| ⚙️ Pipeline – Warehouse Status | Tables, row counts and build times per layer, and data-quality results |

Warehouse code:
[nyc-taxi-bigquery-dwh](https://github.com/ShakeelOsama/nyc-taxi-bigquery-dwh) ·
[olist-ecommerce-bigquery-dwh](https://github.com/ShakeelOsama/olist-ecommerce-bigquery-dwh)

## Run (Google Cloud Shell)

You need read access to the BigQuery project that holds the data.

```bash
git clone https://github.com/ShakeelOsama/bigquery-warehouse-explorer.git ~/explorer
bash ~/explorer/start_app.sh bq-portfolio-demo
```

Then **Web Preview → Change port → 8501**.
