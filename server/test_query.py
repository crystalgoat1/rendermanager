import asyncio
from supabase import create_client

# I will use the python environment's os and import server_supabase to get the auth
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from server.server_supabase import get_supabase
sb = get_supabase()
result = sb.table("agents").select("agent_id, name, status, user_id, last_seen").execute()

with open("output.txt", "w") as f:
    for r in result.data:
        f.write(str(r) + "\n")
