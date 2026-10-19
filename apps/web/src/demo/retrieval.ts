// Browser-side retrieval for the public demo. No model runs here: answers are
// sentences extracted from the best-matching passages, or an explicit abstention.

export type Page = { number: number | null; text: string };
export type Chunk = {
  id: string;
  documentId: string;
  filename: string;
  pageNumber: number | null;
  index: number;
  text: string;
};
export type Sentence = { chunk: Chunk; text: string; heading: string };

export const INSUFFICIENT =
  "I don't have enough evidence in the selected documents to answer this question.";
export const REFUSAL =
  "I can't reveal hidden instructions or follow instructions found inside documents. Document text is treated as untrusted data. Ask a question about the content instead.";

export const normalize = (text: string) =>
  text
    .normalize("NFKC")
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "")
    .trim();

// Same windowing as the API's WordChunker: 350 words, 50 overlap, per page.
export function chunkPages(
  documentId: string,
  filename: string,
  pages: Page[],
  target = 350,
  overlap = 50,
): Chunk[] {
  const chunks: Chunk[] = [];
  for (const page of pages) {
    const words = normalize(page.text).split(/\s+/).filter(Boolean);
    let start = 0;
    while (start < words.length) {
      const end = Math.min(words.length, start + target);
      chunks.push({
        id: `${documentId}:${chunks.length}`,
        documentId,
        filename,
        pageNumber: page.number,
        index: chunks.length,
        text: words.slice(start, end).join(" "),
      });
      if (end === words.length) break;
      start = Math.max(start + 1, end - overlap);
    }
  }
  return chunks;
}

const STOP = new Set(
  (
    "a an and are as at be been but by can could do does did for from had has have how i if in into is it its " +
    "me my of on or our should so such than that the their them then there these they this to was we were what " +
    "when where which who whom whose why will with would you your must may might about any all also after before " +
    "long often quickly much many tell please"
  ).split(" "),
);

// Keyword search misses paraphrases; a small synonym list covers common policy wording.
const SYNONYMS: Record<string, string> = {
  keep: "retain",
  kept: "retain",
  hold: "retain",
  held: "retain",
  retention: "retain",
  mfa: "multi",
  approv: "approval",
};

export function stem(word: string) {
  const base = word
    .replace(/'s$/, "")
    .replace(/(ies)$/, "y")
    .replace(/(ing|ed|es|s)$/, "")
    .replace(/(e)$/, "");
  return SYNONYMS[base] ?? SYNONYMS[word] ?? base;
}

export const terms = (text: string) =>
  (text.toLowerCase().match(/[a-z0-9]+(?:'[a-z]+)?/g) || [])
    .filter((w) => !STOP.has(w))
    .map(stem)
    .filter((w) => w.length > 1);

// Instruction-like text inside documents is data, never an answer.
const INJECTION =
  /\b(ignore|disregard)\b.{0,30}\b(instructions|prompt)\b|\bsystem prompt\b|\byou are now\b|\bjailbreak\b/i;
const META_QUESTION =
  /\b(system prompt|hidden instructions?|your instructions|developer message|jailbreak)\b|\b(ignore|disregard)\b.{0,30}\binstructions\b|\bfollow the instructions?\b/i;

// Paragraph-aware sentence split: wrapped lines are joined, short headings and table rows stand alone.
export function sentences(chunk: Chunk, pageText: string): Sentence[] {
  const lines = pageText
    .split(/\r?\n/)
    .map((l) => l.replace(/\s+/g, " ").trim());
  const paragraphs: { text: string; heading: string }[] = [];
  let current = "";
  let heading = "";
  const flush = () => {
    if (current) paragraphs.push({ text: current, heading });
    current = "";
  };
  for (const line of lines) {
    if (!line) {
      flush();
      continue;
    }
    const isHeading = line.split(" ").length < 6 && !/[.!?:]$/.test(line);
    if (isHeading || line.includes(" | ")) {
      flush();
      if (isHeading) heading = line;
      paragraphs.push({ text: line, heading });
      continue;
    }
    current = current ? `${current} ${line}` : line;
    if (/[.!?:]$/.test(line)) flush();
  }
  flush();
  const chunkText = chunk.text.toLowerCase();
  return paragraphs
    .flatMap((p) =>
      p.text
        .split(/(?<=[.!?])\s+(?=[A-Z0-9])/)
        .map((text) => ({ text: text.trim(), heading: p.heading })),
    )
    .filter((s) => s.text.split(" ").length >= 4)
    .filter((s) => chunkText.includes(s.text.toLowerCase().slice(0, 40)))
    .map((s) => ({ chunk, ...s }));
}

type Scored = { chunk: Chunk; score: number };

export function bm25(
  query: string[],
  chunks: Chunk[],
  k1 = 1.4,
  b = 0.75,
): Scored[] {
  const docs = chunks.map((c) =>
    terms(`${c.filename.replace(/[-_.]/g, " ")} ${c.text}`),
  );
  const avg = docs.reduce((n, d) => n + d.length, 0) / Math.max(1, docs.length);
  const df = new Map<string, number>();
  docs.forEach((d) =>
    new Set(d).forEach((t) => df.set(t, (df.get(t) || 0) + 1)),
  );
  return chunks
    .map((chunk, i) => {
      const tf = new Map<string, number>();
      docs[i].forEach((t) => tf.set(t, (tf.get(t) || 0) + 1));
      const score = [...new Set(query)].reduce((sum, t) => {
        const f = tf.get(t) || 0;
        if (!f) return sum;
        const idf = Math.log(
          1 +
            (chunks.length - (df.get(t) || 0) + 0.5) / ((df.get(t) || 0) + 0.5),
        );
        return (
          sum +
          (idf * f * (k1 + 1)) / (f + k1 * (1 - b + (b * docs[i].length) / avg))
        );
      }, 0);
      return { chunk, score };
    })
    .filter((s) => s.score > 0)
    .sort((a, b) => b.score - a.score);
}

export type Answer = { answer: string; chunks: Chunk[]; insufficient: boolean };

export function answerQuestion(
  question: string,
  chunks: Chunk[],
  pageText: (chunk: Chunk) => string,
  topK = 6,
): Answer {
  if (META_QUESTION.test(question))
    return { answer: REFUSAL, chunks: [], insufficient: true };
  const query = [...new Set(terms(question))];
  if (!query.length || !chunks.length)
    return { answer: INSUFFICIENT, chunks: [], insufficient: true };

  const vocabulary = new Set(
    chunks.flatMap((c) =>
      terms(`${c.filename.replace(/[-_.]/g, " ")} ${c.text}`),
    ),
  );
  const known = query.filter((t) => vocabulary.has(t));
  // Most of the question must exist somewhere in the workspace, or we abstain.
  if (known.length / query.length < 0.5)
    return { answer: INSUFFICIENT, chunks: [], insufficient: true };

  const ranked = bm25(query, chunks).slice(0, topK);
  if (!ranked.length)
    return { answer: INSUFFICIENT, chunks: [], insufficient: true };

  const weight = (t: string) => {
    const n = chunks.filter((c) => terms(c.text).includes(t)).length;
    return Math.log(1 + chunks.length / (1 + n)) + 0.5;
  };
  const total = known.reduce((n, t) => n + weight(t), 0);

  const candidates = ranked.slice(0, 3).flatMap(({ chunk, score }) =>
    sentences(chunk, pageText(chunk))
      .filter((s) => !INJECTION.test(s.text))
      .map((s) => {
        const own = new Set(terms(s.text));
        const file = new Set(terms(chunk.filename.replace(/[-_.]/g, " ")));
        const section = new Set(terms(s.heading));
        // Rank on terms that tell sentences apart: words already in the filename identify the
        // document, not the answer. Section headings count, since they frame the sentence.
        const discriminating = known.filter(
          (t) => !file.has(t) && (own.has(t) || section.has(t)),
        );
        const covered = known.filter(
          (t) => own.has(t) || file.has(t) || section.has(t),
        );
        // Complete sentences beat fragments: extracted table columns do not reliably line up.
        const prose = /[.!?]$/.test(s.text) ? 1 : 0.5;
        return {
          ...s,
          // Words in the sentence itself count fully; words only in its heading count half.
          own:
            prose *
            discriminating.reduce(
              (n, t) => n + weight(t) * (own.has(t) ? 1 : 0.5),
              0,
            ),
          matchesText: known.some((t) => own.has(t)),
          coverage: covered.reduce((n, t) => n + weight(t), 0) / total,
          chunkScore: score,
        };
      }),
  );
  candidates.sort((a, b) => b.own - a.own || b.chunkScore - a.chunkScore);
  const best = candidates[0];
  if (!best || best.own === 0 || !best.matchesText || best.coverage < 0.6)
    return { answer: INSUFFICIENT, chunks: [], insufficient: true };

  return { answer: best.text, chunks: [best.chunk], insufficient: false };
}
