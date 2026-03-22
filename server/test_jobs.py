from dotenv import load_dotenv
import os
from supabase import create_client, Client

load_dotenv()
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_KEY")
sb: Client = create_client(url, key)

res = sb.table("jobs").select("job_id, blend_relpath, output_format, available_passes").order("created_at", desc=True).limit(5).execute()
for j in res.data:
    print(j)
