import { describe, expect, it } from "vitest";

import {
  MAX_VOICE_TEXT_LENGTH,
  formatVoiceText
} from "../lambda/adapter/voice-formatter";

describe("voice formatter", () => {
  it("cleans markup, links, and extra whitespace", () => {
    expect(
      formatVoiceText(
        "  Check [Qualys](https://example.com) now.\n\n*Review* the dashboard after that.  "
      )
    ).toBe("Check Qualys now.");
  });

  it("keeps spoken output short when the text is too long", () => {
    const longText =
      "This response is intentionally long so the voice formatter has to trim it down without waiting for punctuation and without leaving the caller with an overly verbose spoken response that rambles on and on";
    const formatted = formatVoiceText(longText);

    expect(formatted.length).toBeLessThanOrEqual(MAX_VOICE_TEXT_LENGTH + 3);
    expect(formatted.endsWith("...")).toBe(true);
  });
});
