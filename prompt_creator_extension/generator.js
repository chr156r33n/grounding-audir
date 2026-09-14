const MIN_WORDS = 20;
const MAX_WORDS = 30;
const FALLBACK_MIN_WORDS = 12;
const STOP_WORDS = new Set([
  "about", "after", "also", "and", "are", "because", "been", "before", "being",
  "between", "both", "but", "can", "does", "for", "from", "has", "have", "into",
  "more", "most", "not", "only", "other", "over", "page", "say", "says", "than",
  "that", "the", "their", "there", "these", "they", "this", "through", "under",
  "using", "was", "were", "what", "when", "where", "which", "while", "who",
  "will", "with", "would", "you", "your",
]);
const GENERIC = new Set([
  "account", "basket", "blog", "contact", "cookie", "copyright", "explore",
  "follow", "help", "home", "learn", "login", "menu", "newsletter", "privacy",
  "read", "register", "search", "share", "shop", "signin", "signup", "social",
  "subscribe", "terms",
]);
const BOILERPLATE =
  /\b(?:accept (?:all )?cookies?|cookie (?:policy|settings?)|privacy policy|terms (?:and|&) conditions|sign (?:in|up)|log in|register|subscribe|newsletter|skip to content|read more|learn more|view all|contact us|follow us|share (?:this|on)|add to (?:cart|basket)|open menu|close menu|back to top|all rights reserved)\b/i;

export function selectQuotablePassages(evidence, limit = 15, options = {}) {
  const minWords = options.minWords ?? MIN_WORDS;
  const maxWords = options.maxWords ?? MAX_WORDS;
  const requireDistinctive = options.requireDistinctive !== false;
  const kindBonus = {
    meta_description: 35,
    h1: 30,
    h2: 22,
    h3: 14,
    p: 8,
    div: 5,
    li: 4,
  };
  const raw = [];
  for (const chunk of evidence.chunks) {
    for (const passage of quotableSegments(chunk.text, minWords, maxWords)) {
      if (isBoilerplate(passage, chunk.kind)) continue;
      const tokens = distinctiveTokens(passage);
      if (requireDistinctive && new Set(tokens).size < 3) continue;
      raw.push({
        passage,
        supportingText: chunk.text.slice(0, 600),
        kind: chunk.kind,
        score: chunk.score || 40,
        tokens,
      });
    }
  }

  const frequency = new Map();
  for (const item of raw) {
    for (const token of new Set(item.tokens)) {
      frequency.set(token, (frequency.get(token) || 0) + 1);
    }
  }
  const titleTokens = new Set(distinctiveTokens(evidence.title || ""));
  const ranked = raw
    .map((item) => {
      const tokens = new Set(item.tokens);
      const rarity = [...tokens].reduce(
        (sum, token) => sum + 1 / (frequency.get(token) || 1),
        0,
      );
      const titleOverlap = [...tokens].filter((token) => titleTokens.has(token)).length;
      const genericCount = [...tokens].filter((token) => GENERIC.has(token)).length;
      let score =
        item.score +
        (kindBonus[item.kind] || 0) +
        Math.min(rarity * 5, 35) +
        Math.min(titleOverlap * 4, 12) -
        genericCount * 5;
      if (/\d/.test(item.passage)) score += 8;
      if (specificNameCount(item.passage) >= 2) score += 8;
      return { ...item, score };
    })
    .sort((a, b) => b.score - a.score || a.passage.localeCompare(b.passage));

  const selected = [];
  const fingerprints = [];
  for (const item of ranked) {
    const fingerprint = new Set(distinctiveTokens(item.passage));
    const duplicate = fingerprints.some((prior) => {
      const overlap = [...fingerprint].filter((token) => prior.has(token)).length;
      return overlap / Math.max(1, Math.min(fingerprint.size, prior.size)) > 0.7;
    });
    if (duplicate) continue;
    selected.push(item);
    fingerprints.push(fingerprint);
    if (selected.length >= limit) break;
  }
  return selected;
}

export function extractQuoteWindow(
  text,
  { minWords = MIN_WORDS, maxWords = MAX_WORDS } = {},
) {
  const matches = [...text.matchAll(/[A-Za-z0-9][A-Za-z0-9'’&/-]*/g)];
  if (matches.length < minWords) return null;
  if (matches.length <= maxWords) {
    const last = matches.at(-1);
    return text.slice(matches[0].index, last.index + last[0].length);
  }

  let best = null;
  for (let size = maxWords; size >= minWords; size -= 1) {
    for (let start = 0; start <= matches.length - size; start += 1) {
      let score = 0;
      for (const match of matches.slice(start, start + size)) {
        const word = match[0];
        const lower = word.toLowerCase();
        if (!STOP_WORDS.has(lower) && word.length > 3) score += 2;
        if (GENERIC.has(lower)) score -= 3;
        if (/^[A-Z]/.test(word) || /\d/.test(word)) score += 1;
      }
      const first = matches[start];
      const last = matches[start + size - 1];
      const before = text.slice(0, first.index).trimEnd();
      const after = text.slice(last.index + last[0].length).trimStart();
      if (!before || /[.!?]["')\]]?$/.test(before)) score += 12;
      if (!after || /^[.!?]["')\]]?/.test(after)) score += 12;
      if (!best || score > best.score) best = { score, start, size };
    }
  }
  const first = matches[best.start];
  const last = matches[best.start + best.size - 1];
  return text.slice(first.index, last.index + last[0].length);
}

export function buildSelectionInstruction(candidates, title, count) {
  return `Select the ${count} most meaningful, page-specific quotations below.
Prefer concrete facts, distinctive names, numbers, products, places, or claims that
are likely to identify this exact page. Reject navigation, calls to action, generic
marketing language, cookie text, and ambiguous statements. Do not rewrite any text.
Return JSON only in the form {"ids":[0,1]} ordered best first.

Page title: ${title || "Unknown"}
Candidates:
${JSON.stringify(candidates.map((item, id) => ({ id, text: item.passage })))}`;
}

export function parseSelection(value, candidateCount) {
  let text = String(value || "").trim();
  text = text.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  let ids = [];
  try {
    const parsed = JSON.parse(text);
    ids = Array.isArray(parsed) ? parsed : parsed?.ids;
  } catch {
    const match = text.match(/\[[\d,\s]+\]/);
    if (match) ids = JSON.parse(match[0]);
  }
  if (!Array.isArray(ids)) return [];
  return [...new Set(ids)]
    .map(Number)
    .filter((id) => Number.isInteger(id) && id >= 0 && id < candidateCount);
}

export async function generatePrompts(evidence, { count = 5, session, rankPassages } = {}) {
  const requested = Math.max(3, Math.min(Number(count), 8));
  const poolSize = Math.max(12, requested * 3);
  let pool = selectQuotablePassages(evidence, poolSize);
  let selectionMode = "strict";
  if (!pool.length) {
    pool = selectQuotablePassages(evidence, poolSize, {
      minWords: FALLBACK_MIN_WORDS,
      maxWords: MAX_WORDS,
      requireDistinctive: false,
    });
    selectionMode = "relaxed";
  }
  if (!pool.length) {
    pool = emergencyPassages(evidence, poolSize);
    selectionMode = "broad";
  }
  if (!pool.length) {
    throw new Error("This page did not contain enough readable text to quote.");
  }
  let selectedIds = [];
  if (session && rankPassages && selectionMode === "strict") {
    try {
      const response = await rankPassages(
        session,
        buildSelectionInstruction(pool, evidence.title, requested),
      );
      selectedIds = parseSelection(response, pool.length).slice(0, requested);
    } catch {
      selectedIds = [];
    }
  }
  const ids = [
    ...selectedIds,
    ...pool.map((_, index) => index).filter((id) => !selectedIds.includes(id)),
  ].slice(0, requested);
  const modelSelected = new Set(selectedIds);
  return ids.map((id) => ({
    prompt: `"${pool[id].passage}" please retrieve a web page with this exact text`,
    passage: pool[id].passage,
    supportingText: pool[id].supportingText,
    selectionMode,
    generationMethod: modelSelected.has(id)
      ? "chrome_ai_selection"
      : selectionMode === "strict"
        ? "heuristic_selection"
        : `heuristic_${selectionMode}_fallback`,
  }));
}

export function chatbotLinks(prompt) {
  const encoded = encodeURIComponent(prompt);
  return [
    { name: "ChatGPT", url: `https://chatgpt.com/?q=${encoded}` },
    { name: "Claude", url: `https://claude.ai/new?q=${encoded}` },
    {
      name: "Gemini",
      url: `https://gemini.google.com/app?q=${encoded}`,
    },
  ];
}

export function promptListText(prompts) {
  return prompts.map((item) => item.prompt).join("\n\n");
}

function emergencyPassages(evidence, limit) {
  const candidates = [];
  for (const chunk of evidence.chunks || []) {
    const text = clean(chunk.text);
    if (!text) continue;
    if (isBoilerplate(text, chunk.kind)) continue;
    const words = wordCount(text);
    if (words < 8) continue;
    let passage = extractQuoteWindow(text, {
      minWords: 8,
      maxWords: MAX_WORDS,
    });
    if (!passage) {
      const matches = [...text.matchAll(/[A-Za-z0-9][A-Za-z0-9'’&/-]*/g)];
      if (matches.length < 8) continue;
      const last = matches[Math.min(matches.length, MAX_WORDS) - 1];
      passage = text.slice(matches[0].index, last.index + last[0].length);
    }
    candidates.push({
      passage,
      supportingText: text.slice(0, 600),
      kind: chunk.kind,
      score: (chunk.score || 20) - 15,
      tokens: distinctiveTokens(passage),
    });
  }
  if (evidence.title && wordCount(evidence.title) >= 5) {
    candidates.push({
      passage: clean(evidence.title),
      supportingText: clean(evidence.title),
      kind: "h1",
      score: 10,
      tokens: distinctiveTokens(evidence.title),
    });
  }
  return candidates
    .sort((a, b) => b.score - a.score || b.passage.length - a.passage.length)
    .filter((item, index, list) =>
      list.findIndex((other) => other.passage === item.passage) === index,
    )
    .slice(0, limit);
}

function quotableSegments(text, minWords = MIN_WORDS, maxWords = MAX_WORDS) {
  const parts = clean(text)
    .split(/(?<=[.!?])\s+|;\s+/)
    .filter(Boolean);
  const passages = [];
  for (let start = 0; start < parts.length; start += 1) {
    let combined = "";
    for (let end = start; end < parts.length; end += 1) {
      combined = clean(`${combined} ${parts[end]}`);
      if (wordCount(combined) < minWords) continue;
      const passage = extractQuoteWindow(combined, { minWords, maxWords });
      if (passage && !passages.includes(passage)) passages.push(passage);
      break;
    }
  }
  return passages;
}

function isBoilerplate(text, kind) {
  const words = text.match(/[A-Za-z0-9][A-Za-z0-9'’/-]*/g) || [];
  const genericCount = words.filter((word) => GENERIC.has(word.toLowerCase())).length;
  if (BOILERPLATE.test(text) && words.length <= 28) return true;
  if ((text.match(/[|›»]/g) || []).length >= 3) return true;
  if (genericCount / Math.max(1, words.length) >= 0.35) return true;
  return kind === "li" && words.length <= 8;
}

function distinctiveTokens(text) {
  return [...text.matchAll(/[A-Za-z0-9][A-Za-z0-9'’/-]*/g)]
    .map((match) => match[0].toLowerCase())
    .filter((token) => token.length >= 4 && !STOP_WORDS.has(token));
}

function specificNameCount(text) {
  const names = text.match(/\b[A-Z][A-Za-z0-9'’&/-]{2,}\b/g) || [];
  return names.slice(1).filter((word) => !STOP_WORDS.has(word.toLowerCase())).length;
}

function wordCount(text) {
  return (text.match(/[A-Za-z0-9][A-Za-z0-9'’&/-]*/g) || []).length;
}

function clean(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}
