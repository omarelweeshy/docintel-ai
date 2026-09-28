"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Upload,
  Files,
  Layers3,
  CheckCircle2,
  Clock3,
  ArrowRight,
} from "lucide-react";
import { useWorkspace } from "@/components/providers";
import {
  Empty,
  ErrorState,
  FileLabel,
  PageHeader,
  Status,
} from "@/components/ui";
import { api, DocumentRecord, Stats } from "@/lib/api";

export default function Dashboard() {
  const { workspaceId, loading } = useWorkspace();
  const stats = useQuery({
    queryKey: ["stats", workspaceId],
    queryFn: () => api<Stats>(`/workspaces/${workspaceId}/stats`),
    enabled: !!workspaceId,
    refetchInterval: 5000,
  });
  const docs = useQuery({
    queryKey: ["documents", workspaceId, "recent"],
    queryFn: () =>
      api<DocumentRecord[]>(`/documents?workspace_id=${workspaceId}&limit=5`),
    enabled: !!workspaceId,
    refetchInterval: 5000,
  });
  return (
    <>
      <PageHeader
        eyebrow="YOUR KNOWLEDGE, CONNECTED"
        title="Workspace overview"
        description="Turn your documents into knowledge you can work with."
        action={
          <Link className="button primary" href="/upload">
            <Upload size={16} /> Upload documents
          </Link>
        }
      />
      <section className="hero-panel">
        <div>
          <span className="hero-kicker">
            <span /> GROUNDED IN YOUR DOCUMENTS
          </span>
          <h2>
            Good answers start
            <br />
            with clear evidence.
          </h2>
          <p>
            Ask a question. Find the relevant passages.
            <br />
            See exactly where your answer came from.
          </p>
          <Link href="/chat" className="button hero-button">
            Ask your documents <ArrowUpRight size={17} />
          </Link>
        </div>
        <div className="evidence-graphic" aria-hidden="true">
          <div className="graphic-document">
            <div className="graphic-top">
              <Files size={20} />
              <span>YOUR KNOWLEDGE</span>
            </div>
            <i />
            <i />
            <i className="short" />
            <div className="highlight-line" />
            <i />
            <i className="short" />
          </div>
          <div className="graphic-source">
            <CheckCircle2 size={19} />
            <div>
              <strong>Connected to the source</strong>
              <span>Document · Page · Passage</span>
            </div>
          </div>
        </div>
      </section>
      <ErrorState error={stats.error || docs.error} />
      <section className="stats-grid">
        {[
          {
            label: "Total documents",
            value: stats.data?.documents,
            icon: Files,
            note: "In this workspace",
          },
          {
            label: "Ready to explore",
            value: stats.data?.ready,
            icon: CheckCircle2,
            note: "Parsed and indexed",
          },
          {
            label: "Indexed passages",
            value: stats.data?.chunks,
            icon: Layers3,
            note: "Searchable source chunks",
          },
          {
            label: "Processing",
            value: stats.data?.processing,
            icon: Clock3,
            note: stats.data?.failed
              ? `${stats.data.failed} need attention`
              : "Ingestion activity",
          },
        ].map(({ label, value, icon: Icon, note }) => (
          <article key={label} className="stat-card">
            <div>
              {label}
              <Icon size={18} />
            </div>
            <strong>{value ?? (workspaceId ? "..." : "0")}</strong>
            <p>{note}</p>
          </article>
        ))}
      </section>
      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>Recent documents</h2>
            <p>Your latest additions to this workspace.</p>
          </div>
          <Link href="/documents">
            View all <ArrowRight size={15} />
          </Link>
        </div>
        {loading || (workspaceId && docs.isPending) ? (
          <p className="loading">Loading workspace...</p>
        ) : !workspaceId ? (
          <Empty
            title="Create your first workspace"
            text="Use the + button in the sidebar to keep a collection of documents together."
          />
        ) : !docs.data?.length ? (
          <Empty
            title="A clear starting point"
            text="Add a policy, report, or guide. Your indexed documents will appear here."
            href="/upload"
            label="Upload your first document"
          />
        ) : (
          <div className="document-rows">
            {docs.data.map((doc) => (
              <div className="document-row" key={doc.id}>
                <FileLabel document={doc} />
                <Status status={doc.status} />
                <span className="row-meta">{doc.chunk_count} passages</span>
              </div>
            ))}
          </div>
        )}
      </section>
      <p className="page-footnote">
        Built for traceable answers. Always review the supporting evidence.
      </p>
    </>
  );
}
