#!/bin/bash
# Starts the BigQuery Warehouse Explorer web app in Cloud Shell on port 8501.
#   bash start_app.sh                       # uses the current gcloud project
#   bash start_app.sh bq-portfolio-demo     # or name the BigQuery project that holds the data
# First run installs Streamlit into its own virtualenv (~1-2 min).
set -e
APP_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -n "$1" ]; then
  gcloud config set project "$1" >/dev/null 2>&1
fi

if [ ! -x ~/appvenv/bin/streamlit ]; then
  echo ">>> Installing Streamlit (one time)..."
  python3 -m venv ~/appvenv
  ~/appvenv/bin/pip install -q --upgrade pip
  ~/appvenv/bin/pip install -q -r "$APP_DIR/requirements.txt"
fi

export GCP_PROJECT=$(gcloud config get-value project 2>/dev/null)
echo ">>> Using BigQuery project: $GCP_PROJECT"
echo ">>> App starting. Open Web Preview -> Change port -> 8501."
exec ~/appvenv/bin/streamlit run "$APP_DIR/app.py" \
  --server.port 8501 --server.headless true \
  --server.enableCORS false --server.enableXsrfProtection false \
  --browser.gatherUsageStats false --theme.base light
