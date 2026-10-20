import { demoDownloadUrl, demoRequest, demoUpload } from "@/demo/server";

export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
// Public demo build: requests are answered in the browser (see src/demo). Set at build time.
export const DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === "1";
export type Workspace = { id: string; name: string; created_at: string };
export type DocumentRecord = {
  id: string;
  workspace_id: string;
  filename: string;
  content_type: string;
  file_size: number;
  status: "processing" | "ready" | "failed";
  chunk_count: number;
  page_count: number | null;
  created_at: string;
  processed_at: string | null;
  error_message: string | null;
};
export type IngestJob = {
  id: string;
  document_id: string;
  kind: "ingest" | "reindex";
  status: "queued" | "running" | "succeeded" | "failed";
  stage: string;
  progress: number;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
};
export type Citation = {
  document_id: string;
  filename: string;
  page_number: number | null;
  chunk_id: string;
  snippet: string;
};
export type SentenceSpan = { citation: number; start: number; end: number };
export type AnswerSentence = {
  text: string;
  citations: number[];
  spans: SentenceSpan[];
  supported: boolean;
  missing_numbers: string[];
};
export type Message = {
  id: string;
  role: string;
  content: string;
  citations: Citation[];
  sentences?: AnswerSentence[];
  created_at: string;
};
export type Conversation = {
  id: string;
  title: string;
  workspace_id: string;
  created_at: string;
};
export type ConversationDetail = Conversation & { messages: Message[] };
export type Stats = {
  documents: number;
  ready: number;
  processing: number;
  failed: number;
  chunks: number;
};
export type PublicConfig = {
  max_upload_bytes: number;
  max_question_chars: number;
  ai_provider: "ollama" | "openai";
  ai_configured: boolean;
  uses_history?: boolean;
  demo?: boolean;
};
export type ChatAnswer = {
  answer: string;
  citations: Citation[];
  insufficient_context: boolean;
  sentences?: AnswerSentence[];
};
export type StreamHandlers = {
  onStage?: (stage: string) => void;
  onDelta?: (text: string) => void;
};

/** Parse one Server-Sent Events block ("event: x" and "data: {...}" lines). */
export function parseSseBlock(
  block: string,
): { event: string; data: unknown } | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) };
  } catch {
    return null;
  }
}

/**
 * POST /chat/stream and dispatch events. Resolves with the validated final answer. Delta text is
 * provisional and must be replaced by the final answer, never stored as one.
 */
export async function streamChat(
  body: Record<string, unknown>,
  handlers: StreamHandlers,
): Promise<ChatAnswer> {
  const response = await fetch(API + "/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const parsed: unknown = await response.json().catch(() => null);
    throw new Error(
      errorMessage(parsed, `Request failed (${response.status}).`),
    );
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    // SSE events end with a blank line; normalise CRLF so proxies cannot split them differently.
    const blocks = buffer.replace(/\r\n/g, "\n").split("\n\n");
    buffer = done ? "" : (blocks.pop() ?? "");
    for (const block of blocks) {
      const item = parseSseBlock(block);
      if (!item) continue;
      const data = item.data as Record<string, unknown>;
      if (item.event === "stage" && typeof data.stage === "string")
        handlers.onStage?.(data.stage);
      else if (item.event === "delta" && typeof data.text === "string")
        handlers.onDelta?.(data.text);
      else if (item.event === "final") return item.data as ChatAnswer;
      else if (item.event === "error")
        throw new Error(
          typeof data.message === "string" ? data.message : "Answering failed.",
        );
    }
    if (done) break;
  }
  throw new Error("The answer stream ended unexpectedly.");
}

export function errorMessage(body: unknown, fallback: string): string {
  if (typeof body === "object" && body !== null && "error" in body) {
    const error = body.error;
    if (
      typeof error === "object" &&
      error !== null &&
      "message" in error &&
      typeof error.message === "string"
    )
      return error.message;
  }
  return fallback;
}
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  if (DEMO) return demoRequest<T>(path, init);
  const response = await fetch(API + path, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new Error(errorMessage(body, `Request failed (${response.status}).`));
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export function validateFile(
  file: Pick<File, "name" | "size">,
  maxBytes: number,
): string | null {
  if (!/\.(pdf|docx|txt)$/i.test(file.name))
    return "Choose a PDF, DOCX, or UTF-8 TXT file.";
  if (file.size === 0) return "This file is empty.";
  if (file.size > maxBytes)
    return `File exceeds the ${Math.round(maxBytes / 1024 / 1024)} MB limit.`;
  return null;
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Poll a queued document's ingestion job until it finishes, then return the document. */
export async function waitForIngestion(
  workspaceId: string,
  documentId: string,
  onJob?: (job: IngestJob) => void,
  intervalMs = 1500,
): Promise<DocumentRecord> {
  for (;;) {
    const job = await api<IngestJob>(
      `/documents/${documentId}/job?workspace_id=${workspaceId}`,
    );
    onJob?.(job);
    if (job.status === "succeeded" || job.status === "failed")
      return api<DocumentRecord>(
        `/documents/${documentId}?workspace_id=${workspaceId}`,
      );
    await sleep(intervalMs);
  }
}

/**
 * Upload a file. With inline ingestion the server answers 201 with the processed document. With
 * queued ingestion it answers 202 with the document and its job, and this waits for the job.
 */
export async function uploadDocument(
  workspaceId: string,
  file: File,
  progress: (value: number) => void,
  onJob?: (job: IngestJob) => void,
): Promise<DocumentRecord> {
  if (DEMO) return demoUpload(workspaceId, file, progress);
  const result = await sendUpload(workspaceId, file, progress);
  if ("job" in result) {
    onJob?.(result.job);
    return waitForIngestion(workspaceId, result.document.id, onJob);
  }
  return result;
}

function sendUpload(
  workspaceId: string,
  file: File,
  progress: (value: number) => void,
): Promise<DocumentRecord | { document: DocumentRecord; job: IngestJob }> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", API + "/documents");
    request.timeout = 600000;
    request.upload.onprogress = (event) => {
      if (event.lengthComputable)
        progress(Math.round((event.loaded / event.total) * 100));
    };
    request.onerror = () =>
      reject(new Error("Connection lost. Check Documents before retrying."));
    request.ontimeout = () =>
      reject(
        new Error(
          "Processing timed out. Check Documents for its current state.",
        ),
      );
    request.onload = () => {
      try {
        const result = JSON.parse(request.responseText);
        if (request.status >= 200 && request.status < 300) resolve(result);
        else reject(new Error(errorMessage(result, "Upload failed.")));
      } catch {
        reject(new Error("Server returned an unreadable response."));
      }
    };
    const form = new FormData();
    form.append("workspace_id", workspaceId);
    form.append("file", file);
    request.send(form);
  });
}
export const downloadUrl = (documentId: string, workspaceId: string) =>
  DEMO
    ? demoDownloadUrl(documentId)
    : `${API}/documents/${documentId}/download?workspace_id=${workspaceId}`;
export const formatBytes = (bytes: number) =>
  bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
