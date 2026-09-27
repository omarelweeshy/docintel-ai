"use client";
import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Search, Trash2, Upload } from "lucide-react";
import { useWorkspace } from "@/components/providers";
import { Empty, ErrorState, FileLabel, PageHeader, Status } from "@/components/ui";
import { API, api, DocumentRecord } from "@/lib/api";

export default function DocumentsPage() {
  const { workspaceId } = useWorkspace();
  return <Documents key={workspaceId} workspaceId={workspaceId}/>;
}
function Documents({ workspaceId }: { workspaceId: string }) {
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [deleting, setDeleting] = useState<DocumentRecord | null>(null);
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["documents", workspaceId, offset], queryFn: () => api<DocumentRecord[]>(`/documents?workspace_id=${workspaceId}&limit=25&offset=${offset}`), enabled: !!workspaceId, refetchInterval: 5000 });
  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/documents/${id}?workspace_id=${workspaceId}`, { method: "DELETE" }),
    onSuccess: () => { setDeleting(null); void client.invalidateQueries({ queryKey: ["documents", workspaceId] }); void client.invalidateQueries({ queryKey: ["stats", workspaceId] }); },
  });
  const documents = query.data?.filter(d => d.filename.toLowerCase().includes(search.toLowerCase())) || [];
  return <>
    <PageHeader eyebrow="KNOWLEDGE LIBRARY" title="Documents" description="Manage the source material behind every answer." action={<Link className="button primary" href="/upload"><Upload size={16}/> Upload documents</Link>}/>
    <ErrorState error={query.error}/>
    <section className="panel">
      <div className="section-heading"><h2>Workspace library</h2><div className="search-input"><Search size={17}/><input aria-label="Filter filenames on this page" placeholder="Filter this page..." value={search} onChange={e => setSearch(e.target.value)}/></div></div>
      {!workspaceId ? <Empty title="Select a workspace" text="Create a workspace from the sidebar to organize your documents."/> : query.isPending ? <p className="loading">Loading documents...</p> : !documents.length ? <Empty title={search ? "No matching filenames" : "Your library starts here"} text={search ? "Try another filename or another page." : "Upload PDF, DOCX, and TXT files to build your knowledge library."} href="/upload" label="Add documents"/> : <div className="table-scroll"><table><thead><tr><th>Document</th><th>Status</th><th>Passages</th><th>Uploaded</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>
        {documents.map(doc => <tr key={doc.id}><td><FileLabel document={doc}/>{doc.error_message && <p className="document-error">{doc.error_message}</p>}</td><td><Status status={doc.status}/></td><td>{doc.chunk_count}</td><td className="date-cell">{new Date(doc.created_at).toLocaleDateString()}</td><td><div className="flex gap-1"><a className="icon-button" title="Download original" aria-label={`Download ${doc.filename}`} href={`${API}/documents/${doc.id}/download?workspace_id=${workspaceId}`}><Download size={17}/></a><button className="icon-button danger" aria-label={`Delete ${doc.filename}`} onClick={() => { remove.reset(); setDeleting(doc); }}><Trash2 size={17}/></button></div></td></tr>)}
      </tbody></table></div>}
      {!!workspaceId && <div className="pagination"><span>Page {Math.floor(offset / 25) + 1}</span><div className="flex gap-2"><button className="button secondary" disabled={!offset} onClick={() => setOffset(offset - 25)}>Previous</button><button className="button secondary" disabled={(query.data?.length || 0) < 25} onClick={() => setOffset(offset + 25)}>Next</button></div></div>}
    </section>
    {deleting && <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="delete-title"><h2 id="delete-title">Delete this document?</h2><p><strong>{deleting.filename}</strong> and its indexed passages will be removed. Existing conversation answers and citation snapshots are retained; delete those conversations separately if needed.</p><ErrorState error={remove.error}/><div className="flex justify-end gap-2"><button className="button secondary" disabled={remove.isPending} onClick={() => setDeleting(null)}>Cancel</button><button autoFocus className="button destructive" disabled={remove.isPending} onClick={() => remove.mutate(deleting.id)}>{remove.isPending ? "Deleting..." : "Delete document"}</button></div></section></div>}
  </>;
}
