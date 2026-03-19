export type VoiceFormatter = (text: string) => string;

export const MAX_VOICE_TEXT_LENGTH = 160;

function normalizeWhitespace(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function stripVoiceUnsafeMarkup(text: string): string {
  return text
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/https?:\/\/\S+/gi, "")
    .replace(/[`*_#~]/g, "")
    .replace(/\s+([,.;!?])/g, "$1");
}

function truncateToSentence(text: string): string | null {
  const sentenceMatch = text.match(/^.+?[.!?](?=\s|$)/);

  if (!sentenceMatch) {
    return null;
  }

  const sentence = sentenceMatch[0].trim();

  return sentence.length <= MAX_VOICE_TEXT_LENGTH ? sentence : null;
}

function truncateToLength(text: string): string {
  if (text.length <= MAX_VOICE_TEXT_LENGTH) {
    return text;
  }

  const truncated = text.slice(0, MAX_VOICE_TEXT_LENGTH).trim();
  const shortened = truncated.replace(/\s+\S*$/, "").trim();

  return `${shortened.length > 0 ? shortened : truncated}...`;
}

export function formatVoiceText(text: string): string {
  const normalized = normalizeWhitespace(text);

  if (normalized.length === 0) {
    return normalized;
  }

  const cleaned = normalizeWhitespace(stripVoiceUnsafeMarkup(normalized));
  const formatted = cleaned.length > 0 ? cleaned : normalized;

  return truncateToSentence(formatted) ?? truncateToLength(formatted);
}
