"""Print a service-account key file as the TOML block Streamlit Community Cloud expects.

    python3 make_streamlit_secrets.py ~/sa-key.json

Paste the output into: Streamlit Cloud -> your app -> Settings -> Secrets.
Never commit the key file or this output to Git.
"""
import json
import sys

key = json.load(open(sys.argv[1]))
print("[gcp_service_account]")
for k, v in key.items():
    print(f"{k} = {json.dumps(v)}")
