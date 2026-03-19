import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AdapterResponse } from "../contracts/adapter";
import type { SuvaRequest, SuvaResponse } from "../contracts/suva";
import type {
  SuvaClient,
  SuvaClientResult
} from "../lambda/adapter/suva-client";
import {
  ContractValidationError,
  InvalidRequestError,
  buildEscalateResponse,
  createHandler,
  extractSuvaRequestContext
} from "../lambda/adapter/handler";

function createValidRequest(overrides: Partial<SuvaRequest> = {}): SuvaRequest {
  return {
    sessionId: "session-123",
    callerId: "+15551234567",
    language: "en-US",
    utterance: "Check my open findings",
    metadata: {
      awsContactId: "contact-123",
      source: "amazon-connect-lex"
    },
    ...overrides
  };
}

function createValidResponse(
  overrides: Partial<SuvaResponse> = {}
): SuvaResponse {
  return {
    status: "ANSWER",
    replyText: "Here is your answer.",
    voiceText: "Here is your answer.",
    confidence: 0.9,
    handoff: false,
    ...overrides
  };
}

function createSuvaClientMock(result: SuvaClientResult): {
  client: SuvaClient;
  queryVoice: ReturnType<typeof vi.fn>;
} {
  const queryVoice = vi.fn().mockResolvedValue(result);

  return {
    client: {
      queryVoice
    },
    queryVoice
  };
}

function createExpectedAdapterResponse(
  request: SuvaRequest,
  response: SuvaResponse
): AdapterResponse {
  return {
    awsContactId: request.metadata.awsContactId,
    ...response
  };
}

describe("adapter handler", () => {
  beforeEach(() => {
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("prefers voiceText and always formats spoken output on the success path", async () => {
    const request = createValidRequest();
    const response = createValidResponse({
      replyText: "Here is the full written answer.",
      voiceText: "Speak this answer."
    });
    const { client, queryVoice } = createSuvaClientMock({
      ok: true,
      data: response
    });
    const voiceFormatter = vi.fn((text: string) => `formatted:${text}`);
    const handler = createHandler({
      suvaClient: client,
      voiceFormatter
    });

    expect(extractSuvaRequestContext(request)).toEqual({
      sessionId: "session-123",
      callerId: "+15551234567",
      metadata: {
        awsContactId: "contact-123",
        source: "amazon-connect-lex"
      }
    });

    await expect(handler(request)).resolves.toEqual({
      ...createExpectedAdapterResponse(request, response),
      voiceText: "formatted:Speak this answer."
    });
    expect(queryVoice).toHaveBeenCalledWith(request);
    expect(voiceFormatter).toHaveBeenCalledWith("Speak this answer.");
  });

  it("falls back to replyText when voiceText is blank", async () => {
    const request = createValidRequest();
    const response = createValidResponse({
      replyText: "Use this written answer.",
      voiceText: "   "
    });
    const { client } = createSuvaClientMock({
      ok: true,
      data: response
    });
    const voiceFormatter = vi.fn((text: string) => `formatted:${text}`);
    const handler = createHandler({
      suvaClient: client,
      voiceFormatter
    });

    await expect(handler(request)).resolves.toEqual({
      ...createExpectedAdapterResponse(request, response),
      voiceText: "formatted:Use this written answer."
    });
    expect(voiceFormatter).toHaveBeenCalledWith("Use this written answer.");
  });

  it("falls back to replyText when voiceText is missing", async () => {
    const request = createValidRequest();
    const response = {
      status: "ANSWER",
      replyText: "Use this fallback answer.",
      confidence: 0.9,
      handoff: false
    } as unknown as SuvaResponse;
    const { client } = createSuvaClientMock({
      ok: true,
      data: response
    });
    const voiceFormatter = vi.fn((text: string) => `formatted:${text}`);
    const handler = createHandler({
      suvaClient: client,
      voiceFormatter
    });

    await expect(handler(request)).resolves.toEqual({
      awsContactId: request.metadata.awsContactId,
      ...response,
      voiceText: "formatted:Use this fallback answer."
    });
    expect(voiceFormatter).toHaveBeenCalledWith("Use this fallback answer.");
  });

  it("falls back to the built-in formatter when the injected voice formatter fails", async () => {
    const request = createValidRequest();
    const response = createValidResponse({
      voiceText:
        "Review [Qualys](https://example.com) now. This extra sentence should not be spoken."
    });
    const { client } = createSuvaClientMock({
      ok: true,
      data: response
    });
    const voiceFormatter = vi.fn(() => {
      throw new Error("formatter failed");
    });
    const handler = createHandler({
      suvaClient: client,
      voiceFormatter
    });

    await expect(handler(request)).resolves.toEqual({
      ...createExpectedAdapterResponse(request, response),
      voiceText: "Review Qualys now."
    });
    expect(voiceFormatter).toHaveBeenCalledWith(
      "Review [Qualys](https://example.com) now. This extra sentence should not be spoken."
    );
  });

  it("returns ESCALATE on low confidence", async () => {
    const request = createValidRequest();
    const { client } = createSuvaClientMock({
      ok: true,
      data: createValidResponse({
        confidence: 0.49
      })
    });
    const handler = createHandler({
      suvaClient: client
    });

    await expect(handler(request)).resolves.toEqual(
      buildEscalateResponse("LOW_CONFIDENCE", request.metadata.awsContactId)
    );
  });

  it("returns ESCALATE on timeout", async () => {
    const request = createValidRequest();
    const { client } = createSuvaClientMock({
      ok: false,
      error: {
        code: "TIMEOUT",
        message: "SUVA request timed out after 2500ms.",
        retryable: true
      }
    });
    const voiceFormatter = vi.fn((text: string) => `formatted:${text}`);
    const handler = createHandler({
      suvaClient: client,
      voiceFormatter
    });

    await expect(handler(request)).resolves.toEqual({
      ...buildEscalateResponse("TIMEOUT", request.metadata.awsContactId),
      voiceText: "formatted:Let me connect you to a human agent."
    });
    expect(voiceFormatter).toHaveBeenCalledWith(
      "Let me connect you to a human agent."
    );
  });

  it("returns ESCALATE when the SUVA response is missing required fields", async () => {
    const request = createValidRequest();
    const { client } = createSuvaClientMock({
      ok: true,
      data: {
        status: "ANSWER",
        voiceText: "Here is your answer.",
        confidence: 0.9,
        handoff: false
      } as unknown as SuvaResponse
    });
    const handler = createHandler({
      suvaClient: client
    });

    await expect(handler(request)).resolves.toEqual(
      buildEscalateResponse("MISSING_FIELDS", request.metadata.awsContactId)
    );
  });

  it("returns ESCALATE on invalid response errors from the SUVA client", async () => {
    const request = createValidRequest();
    const { client } = createSuvaClientMock({
      ok: false,
      error: {
        code: "INVALID_RESPONSE",
        message:
          'SUVA response validation failed: / missing required property "replyText"',
        retryable: false,
        status: 200
      }
    });
    const handler = createHandler({
      suvaClient: client
    });

    await expect(handler(request)).resolves.toEqual(
      buildEscalateResponse("INVALID_RESPONSE", request.metadata.awsContactId)
    );
  });

  it("emits a JSON success log with safe request metadata", async () => {
    const request = createValidRequest();
    const response = createValidResponse();
    const { client } = createSuvaClientMock({
      ok: true,
      data: response
    });
    const logger = {
      info: vi.fn(),
      error: vi.fn()
    };
    const now = vi
      .fn<() => number>()
      .mockReturnValueOnce(1_710_000_000_000)
      .mockReturnValueOnce(1_710_000_000_050)
      .mockReturnValueOnce(1_710_000_000_135);
    const handler = createHandler({
      suvaClient: client,
      logger,
      now
    });

    await expect(handler(request)).resolves.toEqual(
      createExpectedAdapterResponse(request, response)
    );

    expect(logger.error).not.toHaveBeenCalled();
    expect(logger.info).toHaveBeenCalledTimes(1);

    const serializedLog: unknown = logger.info.mock.calls[0]?.[0];

    expect(typeof serializedLog).toBe("string");

    if (typeof serializedLog !== "string") {
      throw new TypeError("Expected logger.info to receive a JSON string.");
    }

    const log: Record<string, unknown> = JSON.parse(serializedLog) as Record<
      string,
      unknown
    >;

    expect(log).toEqual({
      event: "suva_adapter_result",
      sessionId: "session-123",
      awsContactId: "contact-123",
      requestTimestamp: "2024-03-09T16:00:00.000Z",
      suvaResponseTimeMs: 85,
      status: "ANSWER"
    });
    expect(log).not.toHaveProperty("callerId");
    expect(serializedLog).not.toContain(request.callerId);
    expect(serializedLog).not.toContain(request.utterance);
  });

  it("emits a JSON error log with status and reason on unexpected failure", async () => {
    const request = createValidRequest();
    const queryVoice = vi.fn().mockRejectedValue(new Error("downstream boom"));
    const logger = {
      info: vi.fn(),
      error: vi.fn()
    };
    const now = vi
      .fn<() => number>()
      .mockReturnValueOnce(1_710_000_100_000)
      .mockReturnValueOnce(1_710_000_100_020)
      .mockReturnValueOnce(1_710_000_100_170);
    const handler = createHandler({
      suvaClient: {
        queryVoice
      },
      logger,
      now
    });

    await expect(handler(request)).resolves.toEqual(
      buildEscalateResponse("SUVA_FAILURE", request.metadata.awsContactId)
    );

    expect(logger.info).not.toHaveBeenCalled();
    expect(logger.error).toHaveBeenCalledTimes(1);

    const serializedLog: unknown = logger.error.mock.calls[0]?.[0];

    expect(typeof serializedLog).toBe("string");

    if (typeof serializedLog !== "string") {
      throw new TypeError("Expected logger.error to receive a JSON string.");
    }

    const log: Record<string, unknown> = JSON.parse(serializedLog) as Record<
      string,
      unknown
    >;

    expect(log).toEqual({
      event: "suva_adapter_result",
      sessionId: "session-123",
      awsContactId: "contact-123",
      requestTimestamp: "2024-03-09T16:01:40.000Z",
      suvaResponseTimeMs: 150,
      status: "ESCALATE",
      errorReason: "SUVA_FAILURE"
    });
    expect(log).not.toHaveProperty("callerId");
    expect(serializedLog).not.toContain(request.callerId);
    expect(serializedLog).not.toContain(request.utterance);
  });

  it("does not fail the handler when logging throws", async () => {
    const request = createValidRequest();
    const response = createValidResponse();
    const { client } = createSuvaClientMock({
      ok: true,
      data: response
    });
    const handler = createHandler({
      suvaClient: client,
      logger: {
        info: vi.fn(() => {
          throw new Error("log sink unavailable");
        }),
        error: vi.fn()
      }
    });

    await expect(handler(request)).resolves.toEqual(
      createExpectedAdapterResponse(request, response)
    );
  });

  it("returns ESCALATE when the default SUVA client is unavailable", async () => {
    const request = createValidRequest();
    const originalBaseUrl = process.env["SUVA_BASE_URL"];
    const originalEndpoint = process.env["SUVA_ENDPOINT"];

    process.env["SUVA_BASE_URL"] = "";
    process.env["SUVA_ENDPOINT"] = "";

    try {
      await expect(createHandler()(request)).resolves.toEqual(
        buildEscalateResponse("SUVA_UNAVAILABLE", request.metadata.awsContactId)
      );
    } finally {
      if (originalBaseUrl === undefined) {
        delete process.env["SUVA_BASE_URL"];
      } else {
        process.env["SUVA_BASE_URL"] = originalBaseUrl;
      }

      if (originalEndpoint === undefined) {
        delete process.env["SUVA_ENDPOINT"];
      } else {
        process.env["SUVA_ENDPOINT"] = originalEndpoint;
      }
    }
  });

  it("rejects empty utterance", async () => {
    const request = createValidRequest({
      utterance: "   "
    });
    const handler = createHandler();

    await expect(handler(request)).rejects.toThrowError(InvalidRequestError);
    await expect(handler(request)).rejects.toThrowError(/utterance/i);
  });

  it("rejects blank awsContactId", async () => {
    const request = createValidRequest({
      metadata: {
        awsContactId: "   ",
        source: "amazon-connect-lex"
      }
    });
    const handler = createHandler();

    await expect(handler(request)).rejects.toThrowError(InvalidRequestError);
    await expect(handler(request)).rejects.toThrowError(/awsContactId/i);
  });

  it("rejects missing utterance", async () => {
    const request = {
      sessionId: "session-123",
      callerId: "+15551234567",
      language: "en-US",
      metadata: {
        awsContactId: "contact-123",
        source: "amazon-connect-lex"
      }
    };
    const handler = createHandler();

    await expect(handler(request)).rejects.toThrowError(
      ContractValidationError
    );
    await expect(handler(request)).rejects.toThrowError(/utterance/i);
  });
});
