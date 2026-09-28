export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
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
export type Citation = {
  document_id: string;
  filename: string;
  page_number: number | null;
  chunk_id: string;
  snippet: string;
};
export type Message = {
  id: string;
  role: string;
  content: string;
  citations: Citation[];
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
  ai_configured: boolean;
};

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
export function uploadDocument(
  workspaceId: string,
  file: File,
  progress: (value: number) => void,
): Promise<DocumentRecord> {
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
        if (request.status >= 200 && request.status < 300)
          resolve(result as DocumentRecord);
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
export const formatBytes = (bytes: number) =>
  bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
