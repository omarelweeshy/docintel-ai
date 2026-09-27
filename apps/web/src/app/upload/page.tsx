"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileText, UploadCloud, ArrowRight } from "lucide-react";
import { useWorkspace } from "@/components/providers";
import { Empty, PageHeader } from "@/components/ui";
import { api, formatBytes, PublicConfig, uploadDocument, validateFile } from "@/lib/api";

export default function UploadPage() {
  const { workspaceId } = useWorkspace();
  const client = useQueryClient();
  const config = useQuery({ queryKey: ["config"], queryFn: () => api<PublicConfig>("/config") });
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState("");
  const maxBytes = config.data?.max_upload_bytes ?? 20 * 1024 * 1024;
  function choose(candidate?: File) {
    if (busy || !candidate) return;
    setError(""); setSuccess(""); setProgress(0);
    const validation = validateFile(candidate, maxBytes);
    if (validation) { setError(validation); setFile(null); return; }
    setFile(candidate);
  }
  async function submit() {
    if (!file || !workspaceId || busy) return;
    const targetWorkspace = workspaceId;
    setBusy(true); setError(""); setSuccess("");
    try {
      const result = await uploadDocument(targetWorkspace, file, setProgress);
      if (result.status === "failed") setError(result.error_message || "Processing failed. See Documents for details.");
      else setSuccess(`${result.filename} is ready. ${result.chunk_count} passages indexed.`);
      setFile(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Upload failed."); }
    finally {
      setBusy(false);
      void client.invalidateQueries({ queryKey: ["documents", targetWorkspace] });
      void client.invalidateQueries({ queryKey: ["stats", targetWorkspace] });
    }
  }
  return <>
    <PageHeader eyebrow="BUILD YOUR KNOWLEDGE BASE" title="Upload documents" description="Bring your source material into a workspace. We will take care of the indexing."/>
    {config.data && !config.data.ai_configured && <div className="notice">AI processing is not configured. Set OPENAI_API_KEY on the API server before uploading; otherwise documents will be marked failed.</div>}
    {!workspaceId ? <section className="panel"><Empty title="Create a workspace first" text="Use the + button in the sidebar, then upload your first document."/></section> : <div className="upload-layout"><section className="panel upload-panel">
      <div className="section-heading"><div><h2>Add a document</h2><p>One file at a time. Your original is kept for reference.</p></div></div>
      <div className={`dropzone ${dragging ? "dragging" : ""}`} onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files.length > 1) setError("Please upload one file at a time."); else choose(e.dataTransfer.files[0]); }}>
        <span className="upload-icon"><UploadCloud size={34}/></span><h3>Drop your document here</h3><p>or choose a file from your computer</p><button className="button secondary" disabled={busy} onClick={() => input.current?.click()}>Browse files</button><small>PDF, DOCX, TXT · Up to {Math.round(maxBytes / 1024 / 1024)} MB</small>
        <input ref={input} className="sr-only" type="file" aria-label="Choose document" accept=".pdf,.docx,.txt" disabled={busy} onChange={e => { choose(e.target.files?.[0]); e.target.value = ""; }}/>
      </div>
      {file && <div className="selected-file"><FileText size={24}/><div><strong>{file.name}</strong><small>{formatBytes(file.size)}</small></div><button className="button primary" disabled={busy} onClick={() => void submit()}>{busy ? "Working..." : "Upload & index"}</button></div>}
      {busy && <div className="upload-progress" role="status"><div><span>{progress < 100 ? "Uploading file" : "Parsing, chunking, and indexing"}</span><span>{progress < 100 ? `${progress}%` : "Processing..."}</span></div><progress max={100} value={progress}/><p>You can inspect its status on the Documents page.</p></div>}
      {error && <div className="alert m-6" role="alert">{error} <Link href="/documents" className="underline">View documents</Link></div>}
      {success && <div className="success-notice" role="status"><CheckCircle2 size={20}/><div>{success}<Link href="/chat">Ask a question <ArrowRight size={15}/></Link></div></div>}
    </section><aside className="upload-guide"><p className="eyebrow">FROM FILE TO EVIDENCE</p><h2>What happens next</h2>{[
      ["01", "Validate & store", "File type, size, and duplicates are checked before indexing."],
      ["02", "Parse & organize", "Text becomes overlapping passages. PDF page numbers stay attached."],
      ["03", "Index & explore", "Embeddings make passages searchable in this workspace."],
    ].map(([n, title, text]) => <div className="guide-step" key={n}><span>{n}</span><div><h3>{title}</h3><p>{text}</p></div></div>)}<div className="guide-note"><strong>A note on scanned files</strong><p>V1 needs selectable PDF text. OCR is not enabled. DOCX and TXT do not have stable page numbers.</p></div></aside></div>}
  </>;
}
