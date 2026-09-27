"use client";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState } from "react";
import { api, Workspace } from "@/lib/api";

type WorkspaceContextValue = {
  workspaceId: string; selectWorkspace: (id: string) => void;
  workspaces: Workspace[]; loading: boolean; error: Error | null;
};
const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);
export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("Workspace provider missing");
  return value;
}
function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const client = useQueryClient();
  const [selected, setSelected] = useState("");
  const query = useQuery({ queryKey: ["workspaces"], queryFn: () => api<Workspace[]>("/workspaces") });
  useEffect(() => { setSelected(localStorage.getItem("docintel.workspace") || ""); }, []);
  const workspaces = query.data || [];
  const workspaceId = workspaces.some(w => w.id === selected) ? selected : workspaces[0]?.id || "";
  function selectWorkspace(id: string) {
    setSelected(id);
    localStorage.setItem("docintel.workspace", id);
    void client.invalidateQueries({ queryKey: ["stats", id] });
  }
  return <WorkspaceContext.Provider value={{ workspaceId, selectWorkspace, workspaces, loading: query.isPending, error: query.error }}>
    {children}
  </WorkspaceContext.Provider>;
}
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: {
    queries: { staleTime: 10000, retry: 1, refetchOnWindowFocus: true },
    mutations: { retry: false },
  } }));
  return <QueryClientProvider client={client}><WorkspaceProvider>{children}</WorkspaceProvider></QueryClientProvider>;
}
