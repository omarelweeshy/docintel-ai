"use client";
import { FileText, ChevronDown, Download } from "lucide-react";
import { API, Citation } from "@/lib/api";
export function Citations({ citations, workspaceId }: { citations: Citation[]; workspaceId: string }) {
  if (!citations.length) return null;
  return <div className="citations"><p>SUPPORTING SOURCES <span>{citations.length}</span></p>{citations.map((citation, index) =>
    <details key={citation.chunk_id} className="citation-card"><summary><span className="citation-number">{index + 1}</span><FileText size={15}/><strong>{citation.filename}</strong><span className="citation-page">{citation.page_number !== null ? `Page ${citation.page_number}` : "Passage"}</span><ChevronDown size={15}/></summary>
      <div className="citation-content"><blockquote>{citation.snippet}</blockquote><a href={`${API}/documents/${citation.document_id}/download?workspace_id=${workspaceId}`}><Download size={14}/>Download source document</a><small>Snapshot from answer time. Deleted documents are no longer downloadable.</small></div>
    </details>
  )}</div>;
}
