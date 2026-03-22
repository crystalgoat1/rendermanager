from server.server_supabase import get_supabase

def test():
    sb = get_supabase()
    try:
        res = sb.table("preview_requests").select("pass_name").limit(1).execute()
        print("preview_requests.pass_name exists!")
    except Exception as e:
        print("Error on preview_requests.pass_name:", e)
        
    try:
        res = sb.table("jobs").select("available_passes").limit(1).execute()
        print("jobs.available_passes exists!")
    except Exception as e:
        print("Error on jobs.available_passes:", e)

if __name__ == "__main__":
    test()
