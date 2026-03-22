import { useEffect, useState } from "preact/hooks";
import { supabase } from "../supabaseClient";
import type { Job } from "../types";
import { useSession } from "./useSession";

export function useJobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const { session } = useSession();

  useEffect(() => {
    if (!session) {
      setJobs([]);
      setLoading(false);
      return;
    }

    async function fetchJobs() {
      try {
        const { data, error } = await supabase
          .from("jobs")
          .select("*")
          .order("created_at", { ascending: false })
          .limit(100);

        if (!error && data) {
          setJobs(data as Job[]);
        }
      } catch (err) {
        console.error("fetchJobs error:", err);
      } finally {
        setLoading(false);
      }
    }

    // Initial load
    fetchJobs();

    // Unique channel name per hook instance
    const channelId = Math.random().toString(36).substring(7);
    const channel = supabase
      .channel(`jobs-realtime-${channelId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "jobs" },
        (payload) => {
          if (payload.eventType === "INSERT") {
            setJobs((prev) => [payload.new as Job, ...prev]);
          } else if (payload.eventType === "UPDATE") {
            setJobs((prev) =>
              prev.map((j) =>
                j.job_id === (payload.new as Job).job_id ? (payload.new as Job) : j
              )
            );
          } else if (payload.eventType === "DELETE") {
            setJobs((prev) =>
              prev.filter((j) => j.job_id !== (payload.old as Job).job_id)
            );
          }
        }
      )
      .subscribe();

    // Polling fallback — catch missed Realtime events (cancel stuck, status changes)
    // Pauses when the tab is hidden to save egress.
    let poll: ReturnType<typeof setInterval> | null = setInterval(() => {
      fetchJobs();
    }, 15_000);

    function onVisibilityChange() {
      if (document.visibilityState === "visible") {
        if (!poll) {
          fetchJobs(); // immediate catch-up
          poll = setInterval(() => fetchJobs(), 15_000);
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
  }, [!!session]);

  return { jobs, loading };
}
