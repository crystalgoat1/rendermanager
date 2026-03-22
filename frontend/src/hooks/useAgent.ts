import { useEffect, useState } from "preact/hooks";
import { supabase } from "../supabaseClient";
import type { Agent } from "../types";

const AGENT_COLUMNS = "agent_id, name, status, last_seen, blend_files, blend_files_updated_at, blend_files_info, system_info, created_at";

async function fetchAgents(): Promise<Agent[]> {
  const { data } = await supabase
    .from("agents")
    .select(AGENT_COLUMNS)
    .order("last_seen", { ascending: false });
  return (data as Agent[]) ?? [];
}

export function useAgents() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAgents().then((data) => {
      setAgents(data);
      setLoading(false);
    });

    // Unique channel name per hook instance — prevents channel collisions when
    // multiple components (e.g. AppLayout + DashboardPage) both call useAgents().
    const channelId = Math.random().toString(36).substring(7);
    const channel = supabase
      .channel(`agents-realtime-${channelId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "agents" },
        (payload) => {
          if (payload.eventType === "UPDATE") {
            const incoming = payload.new as Agent;
            setAgents((prev) =>
              prev.map((a) => {
                if (a.agent_id !== incoming.agent_id) return a;
                // Merge instead of replace: realtime payloads from heartbeat
                // updates may omit or null-out large JSONB columns like
                // blend_files_info. Preserve existing values when the incoming
                // payload has them as null/undefined.
                return {
                  ...a,
                  ...incoming,
                  blend_files: incoming.blend_files ?? a.blend_files,
                  blend_files_info: incoming.blend_files_info ?? a.blend_files_info,
                };
              })
            );
          } else if (payload.eventType === "INSERT") {
            setAgents((prev) => [payload.new as Agent, ...prev]);
          } else if (payload.eventType === "DELETE") {
            setAgents((prev) =>
              prev.filter((a) => a.agent_id !== (payload.old as Agent).agent_id)
            );
          }
        }
      )
      .subscribe();

    // Polling fallback — catch missed Realtime events (agent online/offline)
    // Pauses when the tab is hidden to save egress.
    let poll: ReturnType<typeof setInterval> | null = setInterval(() => {
      fetchAgents().then(setAgents);
    }, 15_000);

    function onVisibilityChange() {
      if (document.visibilityState === "visible") {
        if (!poll) {
          fetchAgents().then(setAgents); // immediate catch-up
          poll = setInterval(() => fetchAgents().then(setAgents), 15_000);
        }
      } else {
        if (poll) {
          clearInterval(poll);
          poll = null;
        }
      }
    }
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      supabase.removeChannel(channel);
      if (poll) clearInterval(poll);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []);

  return { agents, loading };
}
