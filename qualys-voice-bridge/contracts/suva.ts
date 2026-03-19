/**
 * This file is auto-generated from the SUVA JSON Schemas.
 * Do not edit by hand. Run `npm run generate:contracts` after changing the schema files.
 */

/**
 * SUVA request payload forwarded by the Lambda adapter.
 */
export interface SuvaRequest {
  sessionId: string;
  callerId: string;
  language: string;
  utterance: string;
  metadata: {
    awsContactId: string;
    source: string;
  };
}

/**
 * SUVA response payload returned to the Lambda adapter.
 */
export interface SuvaResponse {
  status: "ANSWER" | "ESCALATE" | "RETRY";
  replyText: string;
  voiceText: string;
  confidence: number;
  handoff: boolean;
  caseId?: string;
  reason?: string;
}
