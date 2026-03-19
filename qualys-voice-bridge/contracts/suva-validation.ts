import Ajv, { type ErrorObject, type ValidateFunction } from "ajv";

import type { SuvaRequest, SuvaResponse } from "./suva";
import suvaRequestSchema from "./suva-request.schema.json";
import suvaResponseSchema from "./suva-response.schema.json";

export class ContractValidationError extends Error {
  readonly errors: readonly ErrorObject[];

  constructor(message: string, errors: readonly ErrorObject[] = []) {
    super(message);
    this.name = "ContractValidationError";
    this.errors = errors;
  }
}

const ajv = new Ajv({
  allErrors: true,
  strict: true
});

const validateSuvaRequest = ajv.compile<SuvaRequest>(suvaRequestSchema);
const validateSuvaResponse = ajv.compile<SuvaResponse>(suvaResponseSchema);

function formatValidationError(error: ErrorObject): string {
  if (
    error.keyword === "required" &&
    typeof error.params === "object" &&
    error.params !== null &&
    "missingProperty" in error.params
  ) {
    const params = error.params as { missingProperty: string };

    return `${error.instancePath || "/"} missing required property "${params.missingProperty}"`;
  }

  return `${error.instancePath || "/"} ${error.message ?? "is invalid"}`;
}

function buildValidationMessage(
  contractName: string,
  errors: readonly ErrorObject[] | null | undefined
): string {
  if (!errors || errors.length === 0) {
    return `${contractName} validation failed.`;
  }

  return `${contractName} validation failed: ${errors
    .map((error) => formatValidationError(error))
    .join("; ")}`;
}

function parseWithValidator<T>(
  validator: ValidateFunction<T>,
  payload: unknown,
  contractName: string
): T {
  if (validator(payload)) {
    return payload;
  }

  throw new ContractValidationError(
    buildValidationMessage(contractName, validator.errors),
    validator.errors ?? []
  );
}

export function isSuvaRequest(payload: unknown): payload is SuvaRequest {
  return validateSuvaRequest(payload);
}

export function isSuvaResponse(payload: unknown): payload is SuvaResponse {
  return validateSuvaResponse(payload);
}

export function parseSuvaRequest(payload: unknown): SuvaRequest {
  return parseWithValidator(validateSuvaRequest, payload, "SUVA request");
}

export function parseSuvaResponse(payload: unknown): SuvaResponse {
  return parseWithValidator(validateSuvaResponse, payload, "SUVA response");
}
