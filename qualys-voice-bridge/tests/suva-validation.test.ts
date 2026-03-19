import { describe, expect, it } from "vitest";

import {
  ContractValidationError,
  isSuvaRequest,
  isSuvaResponse,
  parseSuvaRequest,
  parseSuvaResponse
} from "../contracts/suva-validation";

describe("SUVA request validation", () => {
  it("accepts a valid request payload", () => {
    const payload = {
      sessionId: "session-123",
      callerId: "+15551234567",
      language: "en-US",
      utterance: "Check my findings",
      metadata: {
        awsContactId: "contact-123",
        source: "amazon-connect-lex"
      }
    };

    expect(parseSuvaRequest(payload)).toEqual(payload);
    expect(isSuvaRequest(payload)).toBe(true);
  });

  it("rejects an invalid request payload", () => {
    const payload = {
      sessionId: "session-123",
      callerId: "+15551234567",
      language: "en-US",
      utterance: "Check my findings",
      metadata: {
        awsContactId: 123,
        source: "amazon-connect-lex"
      }
    };

    expect(isSuvaRequest(payload)).toBe(false);
    expect(() => parseSuvaRequest(payload)).toThrowError(
      ContractValidationError
    );
    expect(() => parseSuvaRequest(payload)).toThrowError(/awsContactId/);
  });

  it("rejects an empty awsContactId", () => {
    const payload = {
      sessionId: "session-123",
      callerId: "+15551234567",
      language: "en-US",
      utterance: "Check my findings",
      metadata: {
        awsContactId: "",
        source: "amazon-connect-lex"
      }
    };

    expect(isSuvaRequest(payload)).toBe(false);
    expect(() => parseSuvaRequest(payload)).toThrowError(
      ContractValidationError
    );
    expect(() => parseSuvaRequest(payload)).toThrowError(/awsContactId/);
  });
});

describe("SUVA response validation", () => {
  it("accepts a valid response payload", () => {
    const payload = {
      status: "ANSWER",
      replyText: "Here is your answer.",
      voiceText: "Here is your answer.",
      confidence: 0.98,
      handoff: false,
      caseId: "case-42"
    };

    expect(parseSuvaResponse(payload)).toEqual(payload);
    expect(isSuvaResponse(payload)).toBe(true);
  });

  it("rejects an invalid response payload", () => {
    const payload = {
      status: "UNKNOWN",
      replyText: "Here is your answer.",
      voiceText: "Here is your answer.",
      confidence: "high",
      handoff: false
    };

    expect(isSuvaResponse(payload)).toBe(false);
    expect(() => parseSuvaResponse(payload)).toThrowError(
      ContractValidationError
    );
    expect(() => parseSuvaResponse(payload)).toThrowError(/status|confidence/);
  });

  it("rejects confidence values outside the 0..1 range", () => {
    const payload = {
      status: "ANSWER",
      replyText: "Here is your answer.",
      voiceText: "Here is your answer.",
      confidence: 1.5,
      handoff: false
    };

    expect(isSuvaResponse(payload)).toBe(false);
    expect(() => parseSuvaResponse(payload)).toThrowError(
      ContractValidationError
    );
    expect(() => parseSuvaResponse(payload)).toThrowError(/confidence/);
  });
});
