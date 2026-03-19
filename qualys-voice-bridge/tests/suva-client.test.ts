import { afterEach, describe, expect, it, vi } from "vitest";

import type { SuvaRequest, SuvaResponse } from "../contracts/suva";
import {
  DEFAULT_SUVA_TIMEOUT_MS,
  createSuvaClient
} from "../lambda/adapter/suva-client";

function createRequest(overrides: Partial<SuvaRequest> = {}): SuvaRequest {
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

function createResponse(overrides: Partial<SuvaResponse> = {}): SuvaResponse {
  return {
    status: "ANSWER",
    replyText: "This is a test response.",
    voiceText: "This is a test response.",
    confidence: 1,
    handoff: false,
    ...overrides
  };
}

function createFetchMock() {
  return vi.fn<(input: string, init?: RequestInit) => Promise<Response>>();
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("createSuvaClient", () => {
  it("posts to /voice/query and returns parsed JSON on success", async () => {
    const fetchMock = createFetchMock();
    const timeoutSpy = vi.spyOn(AbortSignal, "timeout");
    const request = createRequest();
    const response = createResponse();

    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: {
          "content-type": "application/json"
        }
      })
    );

    const client = createSuvaClient({
      baseUrl: "https://suva.example.com",
      fetchFn: fetchMock as typeof fetch
    });
    const result = await client.queryVoice(request);

    expect(result).toEqual({
      ok: true,
      data: response
    });
    expect(timeoutSpy).toHaveBeenCalledWith(DEFAULT_SUVA_TIMEOUT_MS);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const firstCall = fetchMock.mock.calls[0];

    expect(firstCall).toBeDefined();

    if (!firstCall) {
      throw new Error("Expected fetch to be called once.");
    }

    const url = firstCall[0];
    const init = firstCall[1];

    expect(url).toBe("https://suva.example.com/voice/query");
    expect(init).toMatchObject({
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify(request)
    });
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("returns a structured timeout error", async () => {
    const fetchMock = createFetchMock();
    const request = createRequest();

    fetchMock.mockRejectedValue(new DOMException("Timed out", "AbortError"));

    const client = createSuvaClient({
      baseUrl: "https://suva.example.com",
      fetchFn: fetchMock as typeof fetch
    });
    const result = await client.queryVoice(request);

    expect(result).toEqual({
      ok: false,
      error: {
        code: "TIMEOUT",
        message: "SUVA request timed out after 2500ms.",
        retryable: true
      }
    });
  });

  it("treats TimeoutError rejections as structured timeout errors", async () => {
    const fetchMock = createFetchMock();
    const request = createRequest();

    fetchMock.mockRejectedValue(new DOMException("Timed out", "TimeoutError"));

    const client = createSuvaClient({
      baseUrl: "https://suva.example.com",
      fetchFn: fetchMock as typeof fetch
    });
    const result = await client.queryVoice(request);

    expect(result).toEqual({
      ok: false,
      error: {
        code: "TIMEOUT",
        message: "SUVA request timed out after 2500ms.",
        retryable: true
      }
    });
  });

  it("returns a structured network error", async () => {
    const fetchMock = createFetchMock();
    const request = createRequest();

    fetchMock.mockRejectedValue(new Error("socket hang up"));

    const client = createSuvaClient({
      baseUrl: "https://suva.example.com",
      fetchFn: fetchMock as typeof fetch
    });
    const result = await client.queryVoice(request);

    expect(result).toEqual({
      ok: false,
      error: {
        code: "NETWORK_ERROR",
        message: "SUVA request failed to reach the API.",
        retryable: true
      }
    });
  });

  it("returns a structured HTTP error for 500 responses", async () => {
    const fetchMock = createFetchMock();
    const request = createRequest();

    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ error: "boom" }), {
        status: 500,
        headers: {
          "content-type": "application/json"
        }
      })
    );

    const client = createSuvaClient({
      baseUrl: "https://suva.example.com",
      fetchFn: fetchMock as typeof fetch
    });
    const result = await client.queryVoice(request);

    expect(result).toEqual({
      ok: false,
      error: {
        code: "HTTP_ERROR",
        message: "SUVA API returned HTTP 500.",
        retryable: true,
        status: 500
      }
    });
  });

  it("marks 4xx HTTP errors as non-retryable", async () => {
    const fetchMock = createFetchMock();
    const request = createRequest();

    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ error: "bad request" }), {
        status: 400,
        headers: {
          "content-type": "application/json"
        }
      })
    );

    const client = createSuvaClient({
      baseUrl: "https://suva.example.com",
      fetchFn: fetchMock as typeof fetch
    });
    const result = await client.queryVoice(request);

    expect(result).toEqual({
      ok: false,
      error: {
        code: "HTTP_ERROR",
        message: "SUVA API returned HTTP 400.",
        retryable: false,
        status: 400
      }
    });
  });

  it("returns a structured invalid JSON error", async () => {
    const fetchMock = createFetchMock();
    const request = createRequest();

    fetchMock.mockResolvedValue(
      new Response("not-json", {
        status: 200,
        headers: {
          "content-type": "application/json"
        }
      })
    );

    const client = createSuvaClient({
      baseUrl: "https://suva.example.com",
      fetchFn: fetchMock as typeof fetch
    });
    const result = await client.queryVoice(request);

    expect(result).toEqual({
      ok: false,
      error: {
        code: "INVALID_JSON",
        message: "SUVA API returned a response body that is not valid JSON.",
        retryable: false,
        status: 200
      }
    });
  });

  it("returns a structured invalid response error for malformed payloads", async () => {
    const fetchMock = createFetchMock();
    const request = createRequest();

    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "ANSWER",
          voiceText: "This is a test response.",
          confidence: 1,
          handoff: false
        }),
        {
          status: 200,
          headers: {
            "content-type": "application/json"
          }
        }
      )
    );

    const client = createSuvaClient({
      baseUrl: "https://suva.example.com",
      fetchFn: fetchMock as typeof fetch
    });
    const result = await client.queryVoice(request);

    expect(result).toEqual({
      ok: false,
      error: {
        code: "INVALID_RESPONSE",
        message:
          'SUVA response validation failed: / missing required property "replyText"',
        retryable: false,
        status: 200
      }
    });
  });

  it("rejects invalid timeout configuration at client creation", () => {
    const fetchMock = createFetchMock();

    expect(() =>
      createSuvaClient({
        baseUrl: "https://suva.example.com",
        timeoutMs: Number.NaN,
        fetchFn: fetchMock as typeof fetch
      })
    ).toThrowError(TypeError);
    expect(() =>
      createSuvaClient({
        baseUrl: "https://suva.example.com",
        timeoutMs: Number.NaN,
        fetchFn: fetchMock as typeof fetch
      })
    ).toThrowError(/timeout/i);
  });
});
