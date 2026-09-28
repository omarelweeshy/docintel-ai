import Link from "next/link";
import { ArrowRight, FileText } from "lucide-react";
import { DocumentRecord, formatBytes } from "@/lib/api";

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="subtitle">{description}</p>
      </div>
      {action}
    </div>
  );
}
export function Empty({
  title,
  text,
  href,
  label,
}: {
  title: string;
  text: string;
  href?: string;
  label?: string;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <FileText size={28} />
      </span>
      <h3>{title}</h3>
      <p>{text}</p>
      {href && (
        <Link className="button primary" href={href}>
          {label}
          <ArrowRight size={16} />
        </Link>
      )}
    </div>
  );
}
export function ErrorState({ error }: { error: Error | null }) {
  return error ? (
    <p className="alert" role="alert">
      {error.message}
    </p>
  ) : null;
}
export function Status({ status }: { status: DocumentRecord["status"] }) {
  return (
    <span className={`status ${status}`}>
      <span />
      {status}
    </span>
  );
}
export function FileLabel({ document }: { document: DocumentRecord }) {
  return (
    <div className="file-label">
      <span className="file-icon">
        <FileText size={20} />
      </span>
      <div>
        <strong>{document.filename}</strong>
        <small>
          {document.filename.split(".").pop()?.toUpperCase()}{" "}
          <span className="mx-1">/</span> {formatBytes(document.file_size)}
        </small>
      </div>
    </div>
  );
}
