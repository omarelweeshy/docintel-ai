"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Layers3,
  LayoutDashboard,
  Files,
  UploadCloud,
  MessagesSquare,
  Plus,
  ArrowUpRight,
} from "lucide-react";
import { useWorkspace } from "./providers";
import { api, Workspace } from "@/lib/api";

const links = [
  { href: "/", name: "Overview", icon: LayoutDashboard },
  { href: "/documents", name: "Documents", icon: Files },
  { href: "/upload", name: "Upload", icon: UploadCloud },
  { href: "/chat", name: "Ask your documents", icon: MessagesSquare },
];
export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { workspaceId, selectWorkspace, workspaces, error } = useWorkspace();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: () =>
      api<Workspace>("/workspaces", {
        method: "POST",
        body: JSON.stringify({ name }),
      }),
    onSuccess: async (workspace) => {
      await queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      selectWorkspace(workspace.id);
      setCreating(false);
      setName("");
    },
  });
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" href="/">
          <span className="brand-icon">
            <Layers3 size={23} />
          </span>
          <span>
            docintel<span className="brand-ai">AI</span>
          </span>
        </Link>
        <div className="workspace-picker">
          <label htmlFor="workspace">WORKSPACE</label>
          <div className="flex gap-2">
            <select
              id="workspace"
              value={workspaceId}
              onChange={(e) => selectWorkspace(e.target.value)}
              disabled={!workspaces.length}
            >
              {!workspaces.length && (
                <option value="">Create a workspace</option>
              )}
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
            <button
              className="icon-button"
              aria-label="Create workspace"
              onClick={() => setCreating(!creating)}
            >
              <Plus size={17} />
            </button>
          </div>
          {creating && (
            <form
              className="workspace-form"
              onSubmit={(e) => {
                e.preventDefault();
                create.mutate();
              }}
            >
              <label htmlFor="workspace-name" className="sr-only">
                Workspace name
              </label>
              <input
                id="workspace-name"
                autoFocus
                placeholder="Workspace name"
                maxLength={100}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <button
                className="button primary"
                disabled={!name.trim() || create.isPending}
              >
                {create.isPending ? "Creating..." : "Create"}
              </button>
              {create.error && (
                <p role="alert" className="error-text">
                  {create.error.message}
                </p>
              )}
            </form>
          )}
        </div>
        <p className="nav-label">KNOWLEDGE</p>
        <nav>
          {links.map(({ href, name, icon: Icon }) => (
            <Link
              className={path === href ? "nav-link active" : "nav-link"}
              key={href}
              href={href}
            >
              <Icon size={18} />
              {name}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="edition">PHASE 01</span>
          <h3>Evidence comes first.</h3>
          <p>Answers connected to the passages that support them.</p>
          <Link href="/chat">
            Explore your knowledge <ArrowUpRight size={15} />
          </Link>
        </div>
        <div className="local-notice">
          <span className="status-dot" /> Local development{" "}
          <span className="text-slate-500">v0.1</span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            Workspace <span className="text-slate-300 mx-3">/</span>
            <strong>
              {workspaces.find((w) => w.id === workspaceId)?.name ||
                "Getting started"}
            </strong>
          </span>
          <span className="topbar-note">Document intelligence platform</span>
        </header>
        <main>
          {error && (
            <div className="alert" role="alert">
              Cannot connect to the API. Start the backend and database, then
              refresh. {error.message}
            </div>
          )}
          {children}
        </main>
      </div>
    </div>
  );
}
