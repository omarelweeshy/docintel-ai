"use client";
import { Fragment, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { AnswerSentence, Citation } from "@/lib/api";

/**
 * Answer text with a citation marker after each sentence. Selecting a marker shows the exact
 * passage span the sentence relies on. Sentences that failed the support check are flagged rather
 * than hidden, so the reader can judge them.
 */
export function SentenceAnswer({
  sentences,
  citations,
}: {
  sentences: AnswerSentence[];
  citations: Citation[];
}) {
  const [open, setOpen] = useState<{
    sentence: number;
    citation: number;
  } | null>(null);
  const unsupported = sentences.filter((s) => !s.supported).length;
  const span =
    open !== null
      ? sentences[open.sentence]?.spans.find(
          (s) => s.citation === open.citation,
        )
      : undefined;
  const snippet = open !== null ? citations[open.citation]?.snippet : undefined;
  return (
    <div className="sentence-answer">
      <p>
        {sentences.map((sentence, i) => (
          <Fragment key={i}>
            <span
              className={
                sentence.supported ? undefined : "sentence-unsupported"
              }
            >
              {sentence.text}
            </span>
            {sentence.citations.map((c) => (
              <button
                key={c}
                type="button"
                className={`sentence-marker ${
                  open?.sentence === i && open.citation === c ? "active" : ""
                }`}
                aria-label={`Show source ${c + 1} for this sentence`}
                aria-expanded={open?.sentence === i && open.citation === c}
                onClick={() =>
                  setOpen(
                    open?.sentence === i && open.citation === c
                      ? null
                      : { sentence: i, citation: c },
                  )
                }
              >
                {c + 1}
              </button>
            ))}
            {!sentence.supported && (
              <span
                className="sentence-flag"
                title={
                  sentence.missing_numbers.length
                    ? `Not found in the cited passage: ${sentence.missing_numbers.join(", ")}`
                    : "Not clearly supported by the cited passage"
                }
              >
                <AlertTriangle size={13} aria-hidden="true" />
                <span className="sr-only">
                  Check this sentence against its source
                </span>
              </span>
            )}{" "}
          </Fragment>
        ))}
      </p>
      {unsupported > 0 && (
        <p className="sentence-warning">
          {unsupported === 1 ? "1 sentence" : `${unsupported} sentences`} could
          not be matched to the cited passage. Check before relying on{" "}
          {unsupported === 1 ? "it" : "them"}.
        </p>
      )}
      {snippet !== undefined && span && open !== null && (
        <blockquote className="sentence-source" aria-live="polite">
          <strong>
            Source {open.citation + 1}: {citations[open.citation].filename}
            {citations[open.citation].page_number !== null &&
              `, page ${citations[open.citation].page_number}`}
          </strong>
          <span>
            {snippet.slice(0, span.start)}
            <mark>{snippet.slice(span.start, span.end)}</mark>
            {snippet.slice(span.end)}
          </span>
        </blockquote>
      )}
    </div>
  );
}
