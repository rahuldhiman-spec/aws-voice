export interface LexTurnContext {
  sessionId: string;
  callerId: string;
  awsContactId: string;
  language: string;
  inputTranscript: string;
  intentName: string | null;
  sessionAttributes: Record<string, string>;
  requestAttributes: Record<string, string>;
}

export interface AdapterResponse {
  awsContactId: string;
  status: "ANSWER" | "ESCALATE" | "RETRY";
  replyText: string;
  voiceText: string;
  confidence: number;
  handoff: boolean;
  caseId?: string;
  reason?: string;
}
