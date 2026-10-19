// In-browser stand-in for the FastAPI routes the UI calls, used only by the public demo build.
// State lives in this browser's localStorage; nothing is sent anywhere.
import type {
  Citation,
  Conversation,
  ConversationDetail,
  DocumentRecord,
  Message,
  PublicConfig,
  Stats,
  Workspace,
} from "@/lib/api";
import corpus from "./corpus.json";
import {
  answerQuestion,
  chunkPages,
  INSUFFICIENT,
  type Chunk,
  type Page,
} from "./retrieval";

type StoredDocument = DocumentRecord & {
  sha256: string;
  sample: boolean;
  pages: Page[];
};
type StoredMessage = Message & { conversation_id: string };
type State = {
  version: 1;
  workspaces: Workspace[];
  documents: StoredDocument[];
  conversations: Conversation[];
  messages: StoredMessage[];
};

const KEY = "docintel.demo.v1";
const SAMPLE_SIZES: Record<string, number> = {
  "northstar-incident-response-handbook.pdf": 7219,
  "asteron-vendor-access-standard.docx": 38989,
  "meridian-data-export-policy.txt": 2081,
};
export const DEMO_MAX_UPLOAD = 1024 * 1024;

class DemoError extends Error {
  constructor(
    message: string,
    public status = 400,
  ) {
    super(message);
  }
}

const now = () => new Date().toISOString();
const id = () => crypto.randomUUID();

function seed(): State {
  const workspace: Workspace = {
    id: id(),
    name: "Sample policies",
    created_at: now(),
  };
  const documents = corpus.map((doc, i): StoredDocument => {
    const docId = id();
    const created = new Date(
      Date.now() - (corpus.length - i) * 60000,
    ).toISOString();
    return {
      id: docId,
      workspace_id: workspace.id,
      filename: doc.filename,
      content_type: doc.content_type,
      file_size: SAMPLE_SIZES[doc.filename] ?? 0,
      status: "ready",
      chunk_count: chunkPages(docId, doc.filename, doc.pages).length,
      page_count: doc.pages[0]?.number === null ? null : doc.pages.length,
      created_at: created,
      processed_at: created,
      error_message: null,
      sha256: `sample:${doc.filename}`,
      sample: true,
      pages: doc.pages,
    };
  });
  return {
    version: 1,
    workspaces: [workspace],
    documents,
    conversations: [],
    messages: [],
  };
}

let memory: State | null = null;
function load(): State {
  if (memory) return memory;
  try {
    const saved = JSON.parse(
      localStorage.getItem(KEY) || "null",
    ) as State | null;
    memory = saved?.version === 1 ? saved : seed();
  } catch {
    memory = seed();
  }
  return memory;
}
function save(state: State) {
  memory = state;
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Storage full or blocked: keep working in memory for this tab.
  }
}
export function resetDemo() {
  memory = null;
  try {
    localStorage.removeItem(KEY);
    localStorage.removeItem("docintel.workspace");
  } catch {}
}

const publicDocument = (doc: StoredDocument): DocumentRecord => ({
  id: doc.id,
  workspace_id: doc.workspace_id,
  filename: doc.filename,
  content_type: doc.content_type,
  file_size: doc.file_size,
  status: doc.status,
  chunk_count: doc.chunk_count,
  page_count: doc.page_count,
  created_at: doc.created_at,
  processed_at: doc.processed_at,
  error_message: doc.error_message,
});

function requireWorkspace(state: State, workspaceId: string | null) {
  if (!workspaceId || !state.workspaces.some((w) => w.id === workspaceId))
    throw new DemoError("Workspace not found.", 404);
  return workspaceId;
}

function chunksFor(
  state: State,
  workspaceId: string,
  documentIds: string[] | null,
) {
  const pageText = new Map<string, string>();
  const chunks: Chunk[] = state.documents
    .filter((d) => d.workspace_id === workspaceId && d.status === "ready")
    .filter((d) => !documentIds?.length || documentIds.includes(d.id))
    .flatMap((d) => {
      d.pages.forEach((p) => pageText.set(`${d.id}:${p.number}`, p.text));
      return chunkPages(d.id, d.filename, d.pages);
    });
  return {
    chunks,
    pageText: (c: Chunk) =>
      pageText.get(`${c.documentId}:${c.pageNumber}`) || "",
  };
}

// Simulates network latency so loading states are visible, as they are against the real API.
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function demoRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  await wait(120);
  const url = new URL(path, "https://demo.local");
  const method = (init?.method || "GET").toUpperCase();
  const body = init?.body ? JSON.parse(String(init.body)) : {};
  const workspaceId = url.searchParams.get("workspace_id");
  const state = load();
  const parts = url.pathname.split("/").filter(Boolean);
  const result = (value: unknown) => value as T;

  if (url.pathname === "/config" && method === "GET")
    return result({
      max_upload_bytes: DEMO_MAX_UPLOAD,
      max_question_chars: 2000,
      ai_provider: "ollama",
      ai_configured: true,
      demo: true,
    } satisfies PublicConfig);

  if (parts[0] === "workspaces") {
    if (parts.length === 1 && method === "GET") return result(state.workspaces);
    if (parts.length === 1 && method === "POST") {
      const name = String(body.name || "")
        .trim()
        .slice(0, 120);
      if (!name) throw new DemoError("Workspace name is required.");
      const workspace = { id: id(), name, created_at: now() };
      save({ ...state, workspaces: [...state.workspaces, workspace] });
      return result(workspace);
    }
    if (parts[2] === "stats" && method === "GET") {
      const docs = state.documents.filter(
        (d) => d.workspace_id === requireWorkspace(state, parts[1]),
      );
      return result({
        documents: docs.length,
        ready: docs.filter((d) => d.status === "ready").length,
        processing: docs.filter((d) => d.status === "processing").length,
        failed: docs.filter((d) => d.status === "failed").length,
        chunks: docs.reduce((n, d) => n + d.chunk_count, 0),
      } satisfies Stats);
    }
  }

  if (parts[0] === "documents") {
    const ws = requireWorkspace(state, workspaceId);
    if (parts.length === 1 && method === "GET") {
      const limit = Number(url.searchParams.get("limit") || 25);
      const offset = Number(url.searchParams.get("offset") || 0);
      return result(
        state.documents
          .filter((d) => d.workspace_id === ws)
          .sort((a, b) => b.created_at.localeCompare(a.created_at))
          .slice(offset, offset + limit)
          .map(publicDocument),
      );
    }
    if (parts.length === 2 && method === "DELETE") {
      if (
        !state.documents.some((d) => d.id === parts[1] && d.workspace_id === ws)
      )
        throw new DemoError("Document not found.", 404);
      save({
        ...state,
        documents: state.documents.filter((d) => d.id !== parts[1]),
      });
      return result(undefined);
    }
  }

  if (parts[0] === "conversations") {
    if (parts.length === 1 && method === "GET") {
      const ws = requireWorkspace(state, workspaceId);
      return result(
        state.conversations
          .filter((c) => c.workspace_id === ws)
          .sort((a, b) => b.created_at.localeCompare(a.created_at)),
      );
    }
    if (parts.length === 1 && method === "POST") {
      const ws = requireWorkspace(state, body.workspace_id);
      const conversation = {
        id: id(),
        workspace_id: ws,
        title: String(body.title || "New conversation").slice(0, 80),
        created_at: now(),
      };
      save({ ...state, conversations: [...state.conversations, conversation] });
      return result(conversation);
    }
    const conversation = state.conversations.find(
      (c) => c.id === parts[1] && c.workspace_id === workspaceId,
    );
    if (!conversation) throw new DemoError("Conversation not found.", 404);
    if (method === "GET")
      return result({
        ...conversation,
        messages: state.messages
          .filter((m) => m.conversation_id === conversation.id)
          .map((m): Message => ({
            id: m.id,
            role: m.role,
            content: m.content,
            citations: m.citations,
            created_at: m.created_at,
          })),
      } satisfies ConversationDetail);
    if (method === "DELETE") {
      save({
        ...state,
        conversations: state.conversations.filter(
          (c) => c.id !== conversation.id,
        ),
        messages: state.messages.filter(
          (m) => m.conversation_id !== conversation.id,
        ),
      });
      return result(undefined);
    }
  }

  if (url.pathname === "/chat" && method === "POST") {
    const ws = requireWorkspace(state, body.workspace_id);
    const conversation = state.conversations.find(
      (c) => c.id === body.conversation_id && c.workspace_id === ws,
    );
    if (!conversation) throw new DemoError("Conversation not found.", 404);
    const question = String(body.question || "")
      .trim()
      .slice(0, 2000);
    if (!question) throw new DemoError("Ask a question.");
    await wait(500);
    const { chunks, pageText } = chunksFor(state, ws, body.document_ids);
    const answer = chunks.length
      ? answerQuestion(question, chunks, pageText)
      : { answer: INSUFFICIENT, chunks: [], insufficient: true };
    const citations: Citation[] = answer.chunks.map((c) => ({
      document_id: c.documentId,
      filename: c.filename,
      page_number: c.pageNumber,
      chunk_id: c.id,
      snippet: c.text,
    }));
    const user: StoredMessage = {
      id: id(),
      conversation_id: conversation.id,
      role: "user",
      content: question,
      citations: [],
      created_at: now(),
    };
    const assistant: StoredMessage = {
      id: id(),
      conversation_id: conversation.id,
      role: "assistant",
      content: answer.answer,
      citations,
      created_at: now(),
    };
    save({ ...state, messages: [...state.messages, user, assistant] });
    return result({
      answer: answer.answer,
      citations,
      insufficient_context: answer.insufficient,
    });
  }

  throw new DemoError(
    `The public demo does not support ${method} ${url.pathname}.`,
    404,
  );
}

async function sha256(text: string) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text),
  );
  return Array.from(new Uint8Array(digest), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}

// TXT is parsed in the browser. PDF and DOCX need the server-side parsers.
export async function demoUpload(
  workspaceId: string,
  file: File,
  progress: (value: number) => void,
): Promise<DocumentRecord> {
  const state = load();
  requireWorkspace(state, workspaceId);
  if (!/\.txt$/i.test(file.name))
    throw new DemoError(
      "The public demo indexes TXT files in your browser. PDF and DOCX parsing runs in the self-hosted edition.",
    );
  for (const step of [25, 60, 100]) {
    await wait(150);
    progress(step);
  }
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true })
      .decode(await file.arrayBuffer())
      .replace(/^﻿/, "");
  } catch {
    throw new DemoError("This file is not valid UTF-8 text.");
  }
  if (!text.trim())
    throw new DemoError("Document contains no extractable text.");
  const hash = await sha256(text);
  if (
    state.documents.some(
      (d) => d.workspace_id === workspaceId && d.sha256 === hash,
    )
  )
    throw new DemoError("This document is already in the workspace.", 409);
  await wait(400);
  const docId = id();
  const pages: Page[] = [{ number: null, text }];
  const doc: StoredDocument = {
    id: docId,
    workspace_id: workspaceId,
    filename: file.name,
    content_type: "text/plain",
    file_size: file.size,
    status: "ready",
    chunk_count: chunkPages(docId, file.name, pages).length,
    page_count: null,
    created_at: now(),
    processed_at: now(),
    error_message: null,
    sha256: hash,
    sample: false,
    pages,
  };
  save({ ...state, documents: [...state.documents, doc] });
  return publicDocument(doc);
}

// Sample originals are static files; uploaded text is rebuilt from what was stored.
export function demoDownloadUrl(documentId: string) {
  const doc = load().documents.find((d) => d.id === documentId);
  if (!doc) return "#";
  if (doc.sample) return `/demo/${doc.filename}`;
  return `data:text/plain;charset=utf-8,${encodeURIComponent(doc.pages.map((p) => p.text).join("\n"))}`;
}
