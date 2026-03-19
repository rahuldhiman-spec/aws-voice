import type { AdapterResponse } from "../../contracts/adapter";
import type { SuvaRequest, SuvaResponse } from "../../contracts/suva";
import {
  ContractValidationError,
  parseSuvaRequest,
  parseSuvaResponse
} from "../../contracts/suva-validation";
import {
  createSuvaClient,
  type SuvaClient,
  type SuvaClientResult
} from "./suva-client";
import { formatVoiceText, type VoiceFormatter } from "./voice-formatter";

const EMPTY_UTTERANCE_MESSAGE = "SUVA request utterance must not be empty.";
const EMPTY_AWS_CONTACT_ID_MESSAGE =
  "SUVA request awsContactId must not be empty.";
const ESCALATE_MESSAGE = "Let me connect you to a human agent.";
const MINIMUM_CONFIDENCE = 0.5;

export class InvalidRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidRequestError";
  }
}

export interface SuvaRequestContext {
  sessionId: string;
  callerId: string;
  metadata: SuvaRequest["metadata"];
}

export interface AdapterHandlerDependencies {
  suvaClient?: SuvaClient;
  voiceFormatter?: VoiceFormatter;
  logger?: Pick<Console, "info" | "error">;
  now?: () => number;
}

export interface StructuredHandlerLog {
  event: "suva_adapter_result";
  sessionId: string;
  awsContactId: string;
  requestTimestamp: string;
  suvaResponseTimeMs: number;
  status: AdapterResponse["status"];
  errorReason?: string;
}

export function validateSuvaHandlerInput(payload: unknown): SuvaRequest {
  const request = parseSuvaRequest(payload);

  if (request.utterance.trim().length === 0) {
    throw new InvalidRequestError(EMPTY_UTTERANCE_MESSAGE);
  }

  if (request.metadata.awsContactId.trim().length === 0) {
    throw new InvalidRequestError(EMPTY_AWS_CONTACT_ID_MESSAGE);
  }

  return request;
}

export function extractSuvaRequestContext(
  request: SuvaRequest
): SuvaRequestContext {
  return {
    sessionId: request.sessionId,
    callerId: request.callerId,
    metadata: request.metadata
  };
}

function isNonEmptyText(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function hasRequiredResponseFields(
  response: Partial<SuvaResponse> | null | undefined
): boolean {
  return (
    response !== null &&
    response !== undefined &&
    typeof response.confidence === "number" &&
    typeof response.handoff === "boolean" &&
    typeof response.status === "string" &&
    isNonEmptyText(response.replyText)
  );
}

function normalizeSuvaResponse(response: Partial<SuvaResponse>): SuvaResponse {
  return parseSuvaResponse({
    ...response,
    voiceText: isNonEmptyText(response.voiceText)
      ? response.voiceText
      : response.replyText
  });
}

function formatAdapterVoiceText(
  voiceSource: string,
  voiceFormatter: VoiceFormatter
): string {
  try {
    const formatted = formatVoiceText(voiceFormatter(voiceSource));

    return formatted.length > 0 ? formatted : formatVoiceText(voiceSource);
  } catch {
    return formatVoiceText(voiceSource);
  }
}

export function mapSuvaResponseToAdapterResponse(
  response: SuvaResponse,
  awsContactId = "",
  voiceFormatter: VoiceFormatter = formatVoiceText
): AdapterResponse {
  const voiceSource = isNonEmptyText(response.voiceText)
    ? response.voiceText
    : response.replyText;

  return {
    awsContactId,
    status: response.status,
    replyText: response.replyText,
    voiceText: formatAdapterVoiceText(voiceSource, voiceFormatter),
    confidence: response.confidence,
    handoff: response.handoff,
    ...(response.caseId !== undefined ? { caseId: response.caseId } : {}),
    ...(response.reason !== undefined ? { reason: response.reason } : {})
  };
}

export function buildEscalateResponse(
  reason: string,
  awsContactId = "",
  voiceFormatter: VoiceFormatter = formatVoiceText
): AdapterResponse {
  const response = parseSuvaResponse({
    status: "ESCALATE",
    replyText: ESCALATE_MESSAGE,
    voiceText: ESCALATE_MESSAGE,
    confidence: 0,
    handoff: true,
    reason
  });

  return mapSuvaResponseToAdapterResponse(
    response,
    awsContactId,
    voiceFormatter
  );
}

export function buildStructuredHandlerLog(
  requestContext: SuvaRequestContext,
  requestTimestamp: string,
  suvaResponseTimeMs: number,
  response: AdapterResponse
): StructuredHandlerLog {
  return {
    event: "suva_adapter_result",
    sessionId: requestContext.sessionId,
    awsContactId: requestContext.metadata.awsContactId,
    requestTimestamp,
    suvaResponseTimeMs,
    status: response.status,
    ...(response.reason !== undefined ? { errorReason: response.reason } : {})
  };
}

function logStructuredHandlerResult(
  logger: Pick<Console, "info" | "error">,
  level: "info" | "error",
  log: StructuredHandlerLog
): void {
  try {
    logger[level](JSON.stringify(log));
  } catch {
    // Logging must not block the Lambda response path.
  }
}

function getCurrentTimeMs(now: () => number): number {
  const currentTimeMs = now();

  return Number.isFinite(currentTimeMs) ? currentTimeMs : Date.now();
}

function toIsoTimestamp(timestampMs: number): string {
  const timestamp = new Date(timestampMs);

  return Number.isNaN(timestamp.getTime())
    ? new Date().toISOString()
    : timestamp.toISOString();
}

function calculateDurationMs(startTimeMs: number, endTimeMs: number): number {
  return Math.max(0, endTimeMs - startTimeMs);
}

export function mapSuvaResultToAdapterResponse(
  result: SuvaClientResult,
  awsContactId = "",
  voiceFormatter: VoiceFormatter = formatVoiceText
): AdapterResponse {
  if (!result.ok) {
    return buildEscalateResponse(
      result.error.code,
      awsContactId,
      voiceFormatter
    );
  }

  if (!hasRequiredResponseFields(result.data)) {
    return buildEscalateResponse(
      "MISSING_FIELDS",
      awsContactId,
      voiceFormatter
    );
  }

  try {
    const response = normalizeSuvaResponse(result.data);

    if (response.confidence < MINIMUM_CONFIDENCE) {
      return buildEscalateResponse(
        "LOW_CONFIDENCE",
        awsContactId,
        voiceFormatter
      );
    }

    return mapSuvaResponseToAdapterResponse(
      response,
      awsContactId,
      voiceFormatter
    );
  } catch (error) {
    if (error instanceof ContractValidationError) {
      return buildEscalateResponse(
        "INVALID_RESPONSE",
        awsContactId,
        voiceFormatter
      );
    }

    throw error;
  }
}

function createDefaultSuvaClient(): SuvaClient | null {
  const baseUrl =
    process.env["SUVA_BASE_URL"] ?? process.env["SUVA_ENDPOINT"] ?? "";

  if (baseUrl.length === 0) {
    return null;
  }

  try {
    return createSuvaClient({
      baseUrl
    });
  } catch {
    return null;
  }
}

export function createHandler(
  dependencies: AdapterHandlerDependencies = {}
): (event: unknown) => Promise<AdapterResponse> {
  return async function handler(event: unknown): Promise<AdapterResponse> {
    const now = dependencies.now ?? Date.now;
    const requestStartedAtMs = getCurrentTimeMs(now);
    const request = validateSuvaHandlerInput(event);
    const requestContext = extractSuvaRequestContext(request);
    const awsContactId = request.metadata.awsContactId;
    const voiceFormatter = dependencies.voiceFormatter ?? formatVoiceText;
    const logger = dependencies.logger ?? console;
    const requestTimestamp = toIsoTimestamp(requestStartedAtMs);
    let response: AdapterResponse | undefined;
    let suvaResponseTimeMs = 0;
    let logLevel: "info" | "error" = "info";
    let suvaRequestStartedAtMs: number | null = null;

    try {
      const suvaClient = dependencies.suvaClient ?? createDefaultSuvaClient();

      if (!suvaClient) {
        response = buildEscalateResponse(
          "SUVA_UNAVAILABLE",
          awsContactId,
          voiceFormatter
        );
        return response;
      }

      suvaRequestStartedAtMs = getCurrentTimeMs(now);
      const result = await suvaClient.queryVoice(request);
      suvaResponseTimeMs = calculateDurationMs(
        suvaRequestStartedAtMs,
        getCurrentTimeMs(now)
      );

      response = mapSuvaResultToAdapterResponse(
        result,
        awsContactId,
        voiceFormatter
      );
      return response;
    } catch {
      if (suvaRequestStartedAtMs !== null) {
        suvaResponseTimeMs = calculateDurationMs(
          suvaRequestStartedAtMs,
          getCurrentTimeMs(now)
        );
      }

      logLevel = "error";
      response = buildEscalateResponse(
        "SUVA_FAILURE",
        awsContactId,
        voiceFormatter
      );
      return response;
    } finally {
      if (response) {
        logStructuredHandlerResult(
          logger,
          logLevel,
          buildStructuredHandlerLog(
            requestContext,
            requestTimestamp,
            suvaResponseTimeMs,
            response
          )
        );
      }
    }
  };
}

export const handler = createHandler();

export { ContractValidationError };
