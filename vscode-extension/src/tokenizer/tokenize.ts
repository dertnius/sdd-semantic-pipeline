/**
 * Host-side tokenization. Runs in the Node extension host (no webview CSP), and
 * sends TokenChunk[] to the webview to render.
 *
 * Encoder: o200k_base (the GPT-4o/4.1/Copilot encoding, same one ctx.py uses
 * under --exact), bundled offline. For Claude models we still show the o200k
 * segmentation for illustration but flag it: Claude's tokenizer is not public,
 * so the count is reported as an estimate.
 */
import { Tiktoken } from "js-tiktoken/lite";
import o200k_base from "js-tiktoken/ranks/o200k_base";
import type { TokenChunk, TokenizeResult } from "../panel/protocol";

let enc: Tiktoken | null = null;
function encoder(): Tiktoken {
  if (!enc) {
    enc = new Tiktoken(o200k_base);
  }
  return enc;
}

function isClaudeModel(model: string): boolean {
  return /claude|anthropic|opus|sonnet|haiku/i.test(model || "");
}

export function tokenize(text: string, model = ""): TokenizeResult {
  const chars = text.length;
  const bytes = Buffer.byteLength(text, "utf8");
  let ids: number[] = [];
  try {
    // allow + disallow empty -> special-looking substrings encode as plain text, never throws
    ids = encoder().encode(text, [], []);
  } catch {
    ids = [];
  }
  const e = encoder();
  const safeDecode = (slice: number[]): string => {
    try {
      return e.decode(slice);
    } catch {
      return "�";
    }
  };

  // Per-token decode loses data when a codepoint (e.g. an emoji) is split across
  // tokens — decode([id]) yields U+FFFD. So extend the group until it decodes
  // cleanly (capped at 4 tokens — a UTF-8 codepoint is at most 4 bytes). This
  // reconstructs the input exactly while preserving the true token count.
  const tokens: TokenChunk[] = [];
  let cursor = 0;
  let i = 0;
  while (i < ids.length) {
    let j = i + 1;
    let piece = safeDecode(ids.slice(i, j));
    while (piece.includes("�") && j < ids.length && j - i < 4) {
      j++;
      piece = safeDecode(ids.slice(i, j));
    }
    tokens.push({
      id: ids[i],
      text: piece,
      start: cursor,
      end: cursor + piece.length,
      merged: j - i,
    });
    cursor += piece.length;
    i = j;
  }

  const claude = isClaudeModel(model);
  const result: TokenizeResult = {
    tokens,
    count: ids.length,
    chars,
    bytes,
    encoder: "o200k",
    model: model || "(unspecified)",
  };
  if (claude) {
    const estimate = Math.round(chars / 4);
    result.note =
      `Claude's tokenizer is not public — this uses the o200k (GPT) encoding for illustration. ` +
      `A rough chars/4 estimate would be ~${estimate} tokens.`;
  }
  return result;
}
