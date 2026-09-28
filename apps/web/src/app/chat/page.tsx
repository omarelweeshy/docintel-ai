"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, MessagesSquare, Plus, Sparkles, Trash2 } from "lucide-react";
import { useWorkspace } from "@/components/providers";
import { Empty, ErrorState, PageHeader } from "@/components/ui";
import { Citations } from "@/components/citations";
import {
  api,
  Conversation,
  ConversationDetail,
  DocumentRecord,
  PublicConfig,
} from "@/lib/api";

export default function ChatPage() {
  const { workspaceId } = useWorkspace();
  return <Chat key={workspaceId} workspaceId={workspaceId} />;
}
function Chat({ workspaceId }: { workspaceId: string }) {
  const client = useQueryClient();
  const [conversationId, setConversationId] = useState("");
  const [question, setQuestion] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [pendingQuestion, setPendingQuestion] = useState("");
  const config = useQuery({
    queryKey: ["config"],
    queryFn: () => api<PublicConfig>("/config"),
  });
  const conversations = useQuery({
    queryKey: ["conversations", workspaceId],
    queryFn: () =>
      api<Conversation[]>(`/conversations?workspace_id=${workspaceId}`),
    enabled: !!workspaceId,
  });
  const history = useQuery({
    queryKey: ["conversation", workspaceId, conversationId],
    queryFn: () =>
      api<ConversationDetail>(
        `/conversations/${conversationId}?workspace_id=${workspaceId}`,
      ),
    enabled: !!conversationId,
  });
  const documents = useQuery({
    queryKey: ["documents", workspaceId, "chat"],
    queryFn: () =>
      api<DocumentRecord[]>(`/documents?workspace_id=${workspaceId}&limit=100`),
    enabled: !!workspaceId,
  });
  const send = useMutation({
    mutationFn: async (text: string) => {
      let id = conversationId;
      if (!id) {
        const conversation = await api<Conversation>("/conversations", {
          method: "POST",
          body: JSON.stringify({
            workspace_id: workspaceId,
            title: text.slice(0, 80),
          }),
        });
        id = conversation.id;
        setConversationId(id);
        void client.invalidateQueries({
          queryKey: ["conversations", workspaceId],
        });
      }
      await api("/chat", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspaceId,
          conversation_id: id,
          question: text,
          document_ids: documentId ? [documentId] : null,
        }),
      });
      return id;
    },
    onSuccess: async (id) => {
      await client.invalidateQueries({
        queryKey: ["conversation", workspaceId, id],
      });
      setQuestion("");
      setPendingQuestion("");
    },
    onError: () => setPendingQuestion(""),
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      api(`/conversations/${id}?workspace_id=${workspaceId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      setConversationId("");
      void client.invalidateQueries({
        queryKey: ["conversations", workspaceId],
      });
    },
  });
  function newConversation() {
    setConversationId("");
    setQuestion("");
    send.reset();
  }
  return (
    <>
      <PageHeader
        eyebrow="ANSWERS WITH EVIDENCE"
        title="Ask your documents"
        description="Explore your workspace, one grounded question at a time."
      />
      {!workspaceId ? (
        <section className="panel">
          <Empty
            title="Create a workspace first"
            text="Add documents to a workspace, then ask questions about them."
          />
        </section>
      ) : (
        <div className="chat-layout">
          <aside className="conversation-panel">
            <button
              className="button secondary w-full"
              disabled={send.isPending}
              onClick={newConversation}
            >
              <Plus size={16} /> New conversation
            </button>
            <p className="nav-label mt-6">CONVERSATIONS</p>
            <ErrorState error={conversations.error || remove.error} />
            {conversations.isPending ? (
              <p className="loading">Loading...</p>
            ) : !conversations.data?.length ? (
              <p className="conversation-empty">
                Your conversations will appear here.
              </p>
            ) : (
              conversations.data.map((c) => (
                <div
                  className={`conversation-item ${c.id === conversationId ? "selected" : ""}`}
                  key={c.id}
                >
                  <button
                    disabled={send.isPending}
                    onClick={() => {
                      setConversationId(c.id);
                      send.reset();
                      setQuestion("");
                    }}
                  >
                    <MessagesSquare size={15} />
                    <span>{c.title}</span>
                  </button>
                  <button
                    className="conversation-delete"
                    aria-label={`Delete conversation ${c.title}`}
                    disabled={send.isPending || remove.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          "Delete this conversation and its saved source snapshots?",
                        )
                      )
                        remove.mutate(c.id);
                    }}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))
            )}
          </aside>
          <section className="chat-panel">
            <div className="chat-toolbar">
              <span>
                <span className="status-dot" /> Workspace knowledge
              </span>
              <select
                aria-label="Limit answers to a document"
                value={documentId}
                disabled={send.isPending}
                onChange={(e) => setDocumentId(e.target.value)}
              >
                <option value="">All ready documents</option>
                {documents.data
                  ?.filter((d) => d.status === "ready")
                  .map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.filename}
                    </option>
                  ))}
              </select>
            </div>
            <ErrorState error={documents.error} />
            <div className="messages" aria-live="polite">
              <ErrorState error={history.error} />
              {conversationId && history.isPending ? (
                <p className="loading">Loading conversation...</p>
              ) : !history.data?.messages.length && !pendingQuestion ? (
                <div className="chat-welcome">
                  <span className="chat-emblem">
                    <Sparkles size={26} />
                  </span>
                  <h2>What would you like to understand?</h2>
                  <p>
                    Ask a specific question about your documents.
                    <br />
                    Every supported answer includes inspectable sources.
                  </p>
                  <div className="question-suggestions">
                    {[
                      "What are the key requirements?",
                      "Who is responsible for implementation?",
                      "What deadlines are mentioned?",
                    ].map((text) => (
                      <button key={text} onClick={() => setQuestion(text)}>
                        {text}
                        <ArrowUp size={14} />
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                history.data?.messages.map((message) => (
                  <article
                    key={message.id}
                    className={`message ${message.role}`}
                  >
                    <div className="message-author">
                      {message.role === "user" ? "YOU" : "DOCINTEL AI"}
                    </div>
                    <p>{message.content}</p>
                    <Citations
                      citations={message.citations}
                      workspaceId={workspaceId}
                    />
                  </article>
                ))
              )}
              {pendingQuestion && (
                <>
                  <article className="message user">
                    <div className="message-author">YOU</div>
                    <p>{pendingQuestion}</p>
                  </article>
                  <div className="answer-loading" role="status">
                    <span className="pulse-dot" /> Finding evidence and
                    composing an answer...
                  </div>
                </>
              )}
            </div>
            <div className="composer-area">
              <ErrorState error={send.error} />
              <form
                className="composer"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (question.trim() && !send.isPending) {
                    setPendingQuestion(question.trim());
                    send.mutate(question.trim());
                  }
                }}
              >
                <textarea
                  aria-label="Ask a question"
                  placeholder="Ask about your documents..."
                  value={question}
                  maxLength={config.data?.max_question_chars || 2000}
                  rows={2}
                  disabled={send.isPending}
                  onChange={(e) => setQuestion(e.target.value)}
                />
                <button
                  className="send-button"
                  aria-label="Send question"
                  disabled={!question.trim() || send.isPending}
                >
                  <ArrowUp size={20} />
                </button>
              </form>
              <p>
                Answers use retrieved passages. Ask standalone questions;
                earlier turns are saved but not used as context.
              </p>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
