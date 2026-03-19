import type { SuvaRequest, SuvaResponse } from "../../contracts/suva";
import {
  ContractValidationError,
  parseSuvaResponse
} from "../../contracts/suva-validation";

export const DEFAULT_SUVA_TIMEOUT_MS = 2_500;
const VOICE_QUERY_PATH = "/voice/query";

export type SuvaClientErrorCode =
  | "TIMEOUT"
  | "NETWORK_ERROR"
  | "HTTP_ERROR"
  | "INVALID_JSON"
  | "INVALID_RESPONSE";

export interface SuvaClientError {
  code: SuvaClientErrorCode;
  message: string;
  retryable: boolean;
  status?: number;
}

export type SuvaClientResult =
  | {
      ok: true;
      data: SuvaResponse;
    }
  | {
      ok: false;
      error: SuvaClientError;
    };

export interface SuvaClientOptions {
  baseUrl: string;
  timeoutMs?: number;
  fetchFn?: typeof fetch;
}

export interface SuvaClient {
  queryVoice(request: SuvaRequest): Promise<SuvaClientResult>;
}

function buildError(
  code: SuvaClientErrorCode,
  message: string,
  options: {
    retryable: boolean;
    status?: number;
  }
): SuvaClientResult {
  const error: SuvaClientError = {
    code,
    message,
    retryable: options.retryable
  };

  if (options.status !== undefined) {
    error.status = options.status;
  }

  return {
    ok: false,
    error
  };
}

function isTimeoutError(error: unknown): boolean {
  return (
    error instanceof Error &&
    (error.name === "AbortError" || error.name === "TimeoutError")
  );
}

function resolveVoiceQueryUrl(baseUrl: string): string {
  return new URL(VOICE_QUERY_PATH, baseUrl.trim()).toString();
}

function resolveFetchFn(fetchFn: typeof fetch | undefined): typeof fetch {
  if (typeof fetchFn === "function") {
    return fetchFn;
  }

  throw new TypeError(
    "A fetch implementation is required to create the SUVA client."
  );
}

function validateTimeoutMs(timeoutMs: number): number {
  if (Number.isFinite(timeoutMs) && timeoutMs >= 0) {
    return timeoutMs;
  }

  throw new TypeError("SUVA timeoutMs must be a finite non-negative number.");
}

export function createSuvaClient(options: SuvaClientOptions): SuvaClient {
  const fetchFn = resolveFetchFn(options.fetchFn ?? globalThis.fetch);
  const timeoutMs = validateTimeoutMs(
    options.timeoutMs ?? DEFAULT_SUVA_TIMEOUT_MS
  );
  const url = resolveVoiceQueryUrl(options.baseUrl);

  return {
    async queryVoice(request: SuvaRequest): Promise<SuvaClientResult> {
      let response: Response;

      try {
        response = await fetchFn(url, {
          method: "POST",
          headers: {
            "content-type": "application/json"
          },
          body: JSON.stringify(request),
          signal: AbortSignal.timeout(timeoutMs)
        });
      } catch (error) {
        if (isTimeoutError(error)) {
          return buildError(
            "TIMEOUT",
            `SUVA request timed out after ${timeoutMs}ms.`,
            {
              retryable: true
            }
          );
        }

        return buildError(
          "NETWORK_ERROR",
          "SUVA request failed to reach the API.",
          {
            retryable: true
          }
        );
      }

      if (!response.ok) {
        return buildError(
          "HTTP_ERROR",
          `SUVA API returned HTTP ${response.status}.`,
          {
            retryable: response.status >= 500,
            status: response.status
          }
        );
      }

      let payload: unknown;

      try {
        payload = await response.json();
      } catch {
        return buildError(
          "INVALID_JSON",
          "SUVA API returned a response body that is not valid JSON.",
          {
            retryable: false,
            status: response.status
          }
        );
      }

      try {
        return {
          ok: true,
          data: parseSuvaResponse(payload)
        };
      } catch (error) {
        if (error instanceof ContractValidationError) {
          return buildError("INVALID_RESPONSE", error.message, {
            retryable: false,
            status: response.status
          });
        }

        return buildError(
          "INVALID_RESPONSE",
          "SUVA API returned an invalid response.",
          {
            retryable: false,
            status: response.status
          }
        );
      }
    }
  };
}
