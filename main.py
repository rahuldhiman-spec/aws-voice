import dataclasses
import json
import logging
import os
import re
import secrets
import ssl
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logging.getLogger("realtime_voice").warning(
            "Invalid integer for %s=%r; using default %s.",
            name,
            raw,
            default,
        )
        return default


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logging.getLogger("realtime_voice").warning(
            "Invalid float for %s=%r; using default %s.",
            name,
            raw,
            default,
        )
        return default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return list(default)
    if raw.startswith("["):
        try:
            values = json.loads(raw)
        except json.JSONDecodeError:
            return list(default)
        if isinstance(values, list):
            cleaned = [str(item).strip() for item in values if str(item).strip()]
            return cleaned or list(default)
        return list(default)
    cleaned = [item.strip() for item in raw.split("|") if item.strip()]
    return cleaned or list(default)


_JSON_DUMPS_KWARGS: dict[str, Any] = {"separators": (",", ":"), "ensure_ascii": False}


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, **_JSON_DUMPS_KWARGS)


def _safe_preview(value: Any, limit: int = 220) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


LOG_LEVEL = (os.getenv("LOG_LEVEL") or "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("realtime_voice")
APP_FLOW_VERSION = "2026-04-10-webrtc-server-auth"

PORT = _env_int("PORT", 3300)
PUBLIC_URL = (os.getenv("PUBLIC_URL") or "").strip() or None

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip() or None
OPENAI_MODEL = (os.getenv("OPENAI_MODEL") or "gpt-realtime").strip()
OPENAI_API_BASE = (os.getenv("OPENAI_API_BASE") or "https://api.openai.com/v1").strip().rstrip("/")

ASSISTANT_NAME = (os.getenv("ASSISTANT_NAME") or "Aira").strip()
SUPPORT_PRODUCT = (os.getenv("SUPPORT_PRODUCT") or "Qualys").strip()
VOICE = (os.getenv("VOICE") or "shimmer").strip()
AI_SPEAKS_FIRST = _env_bool("AI_SPEAKS_FIRST", False)

TRANSCRIPTION_MODEL = (os.getenv("TRANSCRIPTION_MODEL") or "gpt-4o-mini-transcribe").strip()
TRANSCRIPTION_LANGUAGE = (os.getenv("TRANSCRIPTION_LANGUAGE") or "en").strip()
TRANSCRIPTION_NOISE_REDUCTION = (os.getenv("TRANSCRIPTION_NOISE_REDUCTION") or "near_field").strip()
SERVER_VAD_THRESHOLD = _env_float("SERVER_VAD_THRESHOLD", 0.62)
SERVER_VAD_PREFIX_PADDING_MS = _env_int("SERVER_VAD_PREFIX_PADDING_MS", 300)
SERVER_VAD_SILENCE_DURATION_MS = _env_int("SERVER_VAD_SILENCE_DURATION_MS", 450)

CUSTOM_SYSTEM_MESSAGE = (os.getenv("SYSTEM_MESSAGE") or "").strip()

KNOWLEDGE_BACKEND_URL = (os.getenv("KNOWLEDGE_BACKEND_URL") or "").strip()
KNOWLEDGE_BACKEND_NAME = (os.getenv("KNOWLEDGE_BACKEND_NAME") or "support knowledge backend").strip()
KNOWLEDGE_BACKEND_API_KEY = (os.getenv("KNOWLEDGE_BACKEND_API_KEY") or "").strip()
KNOWLEDGE_BACKEND_AUTH_HEADER = (os.getenv("KNOWLEDGE_BACKEND_AUTH_HEADER") or "Authorization").strip()
KNOWLEDGE_BACKEND_AUTH_SCHEME = (os.getenv("KNOWLEDGE_BACKEND_AUTH_SCHEME") or "Bearer").strip()
KNOWLEDGE_BACKEND_TIMEOUT_S = _env_float("KNOWLEDGE_BACKEND_TIMEOUT_S", 8.0)
KNOWLEDGE_RESULT_LIMIT = _env_int("KNOWLEDGE_RESULT_LIMIT", 5)
KNOWLEDGE_BACKEND_KIND = (os.getenv("KNOWLEDGE_BACKEND_KIND") or "").strip().lower()
KNOWLEDGE_BACKEND_SSL_CERT_FILE = (os.getenv("KNOWLEDGE_BACKEND_SSL_CERT_FILE") or "").strip()
KNOWLEDGE_BACKEND_SSL_INSECURE = _env_bool("KNOWLEDGE_BACKEND_SSL_INSECURE", False)
KNOWLEDGE_CACHE_TTL_S = _env_int("KNOWLEDGE_CACHE_TTL_S", 180)

SEARCHUNIFY_UID = (os.getenv("SEARCHUNIFY_UID") or "").strip()
SEARCHUNIFY_ACCESS_TOKEN = (os.getenv("SEARCHUNIFY_ACCESS_TOKEN") or "").strip()
SEARCHUNIFY_SID = (os.getenv("SEARCHUNIFY_SID") or "").strip()
SEARCHUNIFY_SEARCH_UID = (os.getenv("SEARCHUNIFY_SEARCH_UID") or "").strip()
SEARCHUNIFY_COOKIE = (os.getenv("SEARCHUNIFY_COOKIE") or "").strip()
SEARCHUNIFY_ORIGIN = (os.getenv("SEARCHUNIFY_ORIGIN") or "").strip()
SEARCHUNIFY_REFERER = (os.getenv("SEARCHUNIFY_REFERER") or "").strip()
SEARCHUNIFY_RESULTS_PER_PAGE = _env_int("SEARCHUNIFY_RESULTS_PER_PAGE", KNOWLEDGE_RESULT_LIMIT)
SEARCHUNIFY_LANGUAGE = (os.getenv("SEARCHUNIFY_LANGUAGE") or "en").strip()
SEARCHUNIFY_SORTBY = (os.getenv("SEARCHUNIFY_SORTBY") or "_score").strip()
SEARCHUNIFY_ORDER_BY = (os.getenv("SEARCHUNIFY_ORDER_BY") or "desc").strip()

SESSION_STATE_TTL_S = _env_int("SESSION_STATE_TTL_S", 7200)
DEMO_LOOKUP_QUERY = (os.getenv("DEMO_LOOKUP_QUERY") or "qualys vulnerability findings are not updating").strip()
DEMO_LOOKUP_PRODUCT_AREA = (os.getenv("DEMO_LOOKUP_PRODUCT_AREA") or "vulnerability management detection response").strip()

SUPPORTED_REALTIME_VOICES = ("alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse")
SEARCHUNIFY_HIGHLIGHT_START = "___su-highlight-start___"
SEARCHUNIFY_HIGHLIGHT_END = "___su-highlight-end___"

DEFAULT_DYNAMIC_OPENERS = [
    "Is VMDR, patching, or remediation not behaving the way you expect?",
    "Are asset inventory or compliance results not lining up correctly?",
    "Is a web app, endpoint, or cloud security workflow failing in Qualys?",
    "Is a vendor risk, file integrity, or custom remediation flow giving you trouble?",
]
QUALYS_DYNAMIC_OPENERS = _env_list("QUALYS_DYNAMIC_OPENERS", DEFAULT_DYNAMIC_OPENERS)

# Product families are intentionally compact and domain-specific.
# Keep these aligned to the top-level Qualys product areas used for routing.

ISSUE_FAMILY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "vulnerability_management_detection_response": (
        "vmdr",
        "vulnerability management",
        "vulnerability detection",
        "detection and response",
        "risk prioritization",
        "continuous monitoring",
        "vulnerability finding",
        "exposure management",
        "threat protection",
    ),
    "patch_management": (
        "patch management",
        "patch deployment",
        "patching",
        "missing patch",
        "patch schedule",
        "patch job",
        "patch rollout",
        "third-party patch",
        "operating system patch",
    ),
    "cybersecurity_asset_management": (
        "csam",
        "cybersecurity asset management",
        "asset inventory",
        "asset discovery",
        "asset visibility",
        "asset lifecycle",
        "unknown asset",
        "hardware inventory",
        "software inventory",
        "cmdb sync",
    ),
    "policy_compliance": (
        "policy compliance",
        "configuration compliance",
        "security compliance",
        "compliance posture",
        "compliance assessment",
        "benchmark compliance",
        "cis benchmark",
        "regulatory compliance",
        "policy audit",
    ),
    "web_application_scanning": (
        "was",
        "web application scanning",
        "web app scan",
        "web application security",
        "dynamic application security",
        "owasp",
        "authenticated scan",
        "web vulnerability",
        "api security testing",
    ),
    "totalcloud": (
        "totalcloud",
        "cloud security posture",
        "cloud workload protection",
        "cloud detection and response",
        "container security",
        "kubernetes security",
        "iac security",
        "cloud misconfiguration",
        "saas security posture",
        "cnapp",
    ),
    "multi_vector_edr": (
        "edr",
        "multi-vector edr",
        "endpoint detection and response",
        "endpoint threat detection",
        "behavioral detection",
        "endpoint telemetry",
        "threat hunting",
        "host isolation",
        "endpoint incident",
    ),
    "file_integrity_monitoring": (
        "fim",
        "file integrity monitoring",
        "file change monitoring",
        "configuration change monitoring",
        "unauthorized change",
        "baseline drift",
        "registry monitoring",
        "integrity alert",
    ),
    "security_assessment_questionnaire": (
        "saq",
        "security assessment questionnaire",
        "third-party risk",
        "vendor risk",
        "supplier risk",
        "security questionnaire",
        "vendor assessment",
        "supply chain risk",
    ),
    "custom_assessment_and_remediation": (
        "car",
        "custom assessment and remediation",
        "custom assessment",
        "custom remediation",
        "custom detection",
        "custom script",
        "remediation script",
        "automated remediation",
    ),
}

ISSUE_FAMILY_LABELS = {
    "vulnerability_management_detection_response": "a Qualys Vulnerability Management, Detection & Response issue",
    "patch_management": "a Qualys Patch Management issue",
    "cybersecurity_asset_management": "a Qualys Cybersecurity Asset Management issue",
    "policy_compliance": "a Qualys Policy Compliance issue",
    "web_application_scanning": "a Qualys Web Application Scanning issue",
    "totalcloud": "a Qualys TotalCloud issue",
    "multi_vector_edr": "a Qualys Multi-Vector EDR issue",
    "file_integrity_monitoring": "a Qualys File Integrity Monitoring issue",
    "security_assessment_questionnaire": "a Qualys Security Assessment Questionnaire issue",
    "custom_assessment_and_remediation": "a Qualys Custom Assessment and Remediation issue",
    "general": "a Qualys support issue",
}
INTEGRATION_TARGETS = ("servicenow", "jira", "splunk", "sumo logic", "qradar", "siem", "snowflake", "slack")
FRUSTRATION_PATTERNS = {
    "high": ("not working", "still not working", "nothing works", "fed up", "frustrated", "urgent", "asap"),
    "medium": ("issue", "problem", "stuck", "again", "same error", "failing", "broken"),
}
QUALYS_DOMAIN_HINTS = (
    "qualys",
    "cloud agent",
    "vmdr",
    "vulnerability",
    "patch management",
    "patching",
    "csam",
    "asset inventory",
    "policy compliance",
    "compliance",
    "was",
    "web application",
    "totalcloud",
    "cloud posture",
    "container security",
    "edr",
    "endpoint detection",
    "fim",
    "file integrity",
    "saq",
    "security questionnaire",
    "third-party risk",
    "car",
    "custom assessment",
    "servicenow",
    "jira",
    "splunk",
    "siem",
    "api",
    "connector",
    "integration",
)
OFF_TOPIC_PATTERNS = (
    "weather",
    "news",
    "headline",
    "sports",
    "movie",
    "music",
    "recipe",
    "travel",
    "politics",
    "president",
    "celebrity",
    "horoscope",
    "joke",
    "funny",
    "story",
    "poem",
)
SEARCH_FIRST_PATTERNS = (
    "exact troubleshooting",
    "exact steps",
    "step by step",
    "troubleshooting steps",
    "what are the steps",
    "what should i check",
    "what do i check",
    "error code",
    "what does this error",
    "what does the error",
    "api",
    "endpoint",
    "payload",
    "request body",
    "response body",
    "header",
    "connector",
    "integration",
    "servicenow",
    "jira",
    "splunk",
    "product fact",
    "supported",
    "limit",
    "version",
)
SEARCH_COMPONENT_HINTS: dict[str, tuple[str, ...]] = {
    "vulnerability_management_detection_response": ("vulnerability finding", "risk prioritization", "continuous monitoring", "threat protection"),
    "patch_management": ("patch deployment", "patch schedule", "missing patch", "patch rollout"),
    "cybersecurity_asset_management": ("asset inventory", "asset discovery", "asset visibility", "cmdb sync"),
    "policy_compliance": ("compliance posture", "benchmark compliance", "policy audit", "regulatory compliance"),
    "web_application_scanning": ("web application security", "authenticated scan", "api security testing", "owasp"),
    "totalcloud": ("cloud security posture", "cloud workload protection", "container security", "iac security"),
    "multi_vector_edr": ("endpoint telemetry", "endpoint threat detection", "threat hunting", "host isolation"),
    "file_integrity_monitoring": ("file change monitoring", "registry monitoring", "baseline drift", "integrity alert"),
    "security_assessment_questionnaire": ("third-party risk", "vendor risk", "security questionnaire", "vendor assessment"),
    "custom_assessment_and_remediation": ("custom assessment", "custom remediation", "custom detection", "automated remediation"),
}
SEARCH_SYMPTOM_PATTERNS = (
    "not checking in",
    "not reporting",
    "not syncing",
    "not showing",
    "missing",
    "failed",
    "failing",
    "timeout",
    "timed out",
    "connection refused",
    "unauthorized",
    "forbidden",
    "invalid token",
    "access denied",
    "error",
)

try:
    import certifi  # type: ignore
except Exception:  # noqa: BLE001
    certifi = None


def _append_unique(values: list[str], value: str, limit: int = 6) -> None:
    cleaned = value.strip()
    if not cleaned:
        return
    normalized = " ".join(cleaned.lower().split())
    for existing in values:
        if " ".join(existing.lower().split()) == normalized:
            return
    values.append(cleaned)
    if len(values) > limit:
        del values[:-limit]


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_+-]{3,}", text.lower())}


def _resolve_realtime_voice(value: str) -> str:
    candidate = value.strip().lower()
    if candidate in SUPPORTED_REALTIME_VOICES:
        return candidate
    logger.warning("Unsupported realtime voice `%s`; falling back to `shimmer`.", value)
    return "shimmer"


VOICE = _resolve_realtime_voice(VOICE)
STATIC_DIR = Path(__file__).with_name("static")
KNOWLEDGE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
SESSION_STATE: dict[str, tuple[float, "CallState"]] = {}


@dataclass
class CallState:
    assistant_name: str
    support_product: str
    routed_issue_family: str = "general"
    routed_issue_label: str = ISSUE_FAMILY_LABELS["general"]
    routing_reason: str = ""
    product_area: str = ""
    issue_summary: str = ""
    user_goal: str = ""
    caller_name: str = ""
    company: str = ""
    environment: str = ""
    error_text: str = ""
    frustration_level: str = "low"
    off_topic_detected: bool = False
    off_topic_reason: str = ""
    off_topic_turns: int = 0
    last_user_transcript: str = ""
    last_assistant_transcript: str = ""
    user_turns: int = 0
    assistant_turns: int = 0
    confirmed_facts: list[str] = field(default_factory=list)
    tried_steps: list[str] = field(default_factory=list)
    integration_targets: list[str] = field(default_factory=list)
    grounding_notes: list[str] = field(default_factory=list)
    summary_history: list[str] = field(default_factory=list)
    last_context_hint_signature: str = ""

    def apply_user_transcript(self, transcript: str) -> bool:
        self.last_user_transcript = transcript.strip()
        if not self.last_user_transcript:
            return False
        self.user_turns += 1
        _append_unique(self.summary_history, self.last_user_transcript, limit=4)

        routed_family, routed_label = _route_issue_family(self.last_user_transcript)
        route_changed = False
        if routed_family != "general" and routed_family != self.routed_issue_family:
            self.routed_issue_family = routed_family
            self.routed_issue_label = routed_label
            self.routing_reason = "keyword routing from caller transcript"
            if not self.product_area:
                self.product_area = routed_family
            route_changed = True

        for target in _extract_integration_targets(self.last_user_transcript):
            _append_unique(self.integration_targets, target)

        frustration = _detect_frustration(self.last_user_transcript)
        if frustration == "high" or (frustration == "medium" and self.frustration_level == "low"):
            self.frustration_level = frustration

        off_topic_detected, off_topic_reason = _detect_off_topic(
            self.last_user_transcript,
            self.routed_issue_family,
            self.integration_targets,
        )
        self.off_topic_detected = off_topic_detected
        self.off_topic_reason = off_topic_reason
        if off_topic_detected:
            self.off_topic_turns += 1

        if not self.issue_summary:
            self.issue_summary = self.last_user_transcript
        return route_changed

    def remember_context(self, payload: dict[str, Any]) -> None:
        mappings = {
            "caller_name": "caller_name",
            "company": "company",
            "product_area": "product_area",
            "issue_summary": "issue_summary",
            "user_goal": "user_goal",
            "environment": "environment",
            "error_text": "error_text",
            "frustration_level": "frustration_level",
        }
        for key, attr in mappings.items():
            value = str(payload.get(key) or "").strip()
            if value:
                setattr(self, attr, value)

        issue_family = str(payload.get("issue_family") or "").strip().lower()
        if issue_family in ISSUE_FAMILY_LABELS:
            self.routed_issue_family = issue_family
            self.routed_issue_label = ISSUE_FAMILY_LABELS[issue_family]
            self.routing_reason = "assistant tool classification"

        for field_name, target_list in (
            ("integration_target", self.integration_targets),
            ("confirmed_fact", self.confirmed_facts),
            ("tried_step", self.tried_steps),
            ("grounding_note", self.grounding_notes),
        ):
            value = str(payload.get(field_name) or "").strip()
            if value:
                _append_unique(target_list, value)

        step_result = str(payload.get("step_result") or "").strip()
        if step_result and self.tried_steps:
            _append_unique(self.confirmed_facts, f"Step result: {step_result}")

    def as_tool_payload(self) -> dict[str, Any]:
        return {
            "assistant_name": self.assistant_name,
            "support_product": self.support_product,
            "routed_issue_family": self.routed_issue_family,
            "routed_issue_label": self.routed_issue_label,
            "routing_reason": self.routing_reason,
            "product_area": self.product_area,
            "issue_summary": self.issue_summary,
            "user_goal": self.user_goal,
            "caller_name": self.caller_name,
            "company": self.company,
            "environment": self.environment,
            "error_text": self.error_text,
            "frustration_level": self.frustration_level,
            "off_topic_detected": self.off_topic_detected,
            "off_topic_reason": self.off_topic_reason,
            "off_topic_turns": self.off_topic_turns,
            "integration_targets": list(self.integration_targets),
            "confirmed_facts": list(self.confirmed_facts),
            "tried_steps": list(self.tried_steps),
            "user_turns": self.user_turns,
            "assistant_turns": self.assistant_turns,
            "last_user_transcript": self.last_user_transcript,
            "last_assistant_transcript": self.last_assistant_transcript,
        }

    def summary_text(self) -> str:
        details = [
            f"Current routed issue: {self.routed_issue_label}.",
        ]
        if self.issue_summary:
            details.append(f"Working summary: {self.issue_summary}")
        if self.user_goal:
            details.append(f"User goal: {self.user_goal}")
        if self.integration_targets:
            details.append(f"Integrations mentioned: {', '.join(self.integration_targets)}")
        if self.confirmed_facts:
            details.append(f"Confirmed facts: {'; '.join(self.confirmed_facts[-3:])}")
        if self.tried_steps:
            details.append(f"Tried steps: {'; '.join(self.tried_steps[-3:])}")
        if self.off_topic_detected and self.off_topic_reason:
            details.append(f"Guardrail note: {self.off_topic_reason}")
        details.append(f"Frustration level: {self.frustration_level}")
        return " ".join(details)


class SessionRequest(BaseModel):
    session_id: str = Field(min_length=1)


class TranscriptRequest(BaseModel):
    session_id: str = Field(min_length=1)
    transcript: str = Field(min_length=1)


class ContextPayloadRequest(BaseModel):
    session_id: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    session_id: str = Field(min_length=1)
    query: str = ""
    product_area: str | None = None


class RealtimeCallRequest(BaseModel):
    sdp: str = Field(min_length=1)


def _build_system_message() -> str:
    sections = [
        f"You are {ASSISTANT_NAME}, the support assistant for {SUPPORT_PRODUCT}.",
        (
            "Sound like a deeply technical Qualys expert who talks in a casual, calm, natural way with a warm, soft, sweet feminine tone. "
            "Do not sound corporate, polished, scripted, or overly professional. "
            "Sound clear, sharp, relaxed, gentle, and easy to talk to."
        ),
        (
            "On the first greeting, be clear that you are the support assistant for Qualys. "
            "After that, talk like a real troubleshooting expert. Use short spoken sentences, normal support language, "
            "and natural phrases like 'okay, that helps', 'let's check that next', or 'that points more toward the connector side'."
        ),
        (
            "Always begin each meaningful troubleshooting reply with a short summary of what you understood. "
            "Then translate the issue into the right Qualys product area in plain language, for example "
            "'This sounds like a VMDR detection issue' or 'This sounds more like a ServiceNow connector issue'."
        ),
        (
            "You help with Qualys support topics such as VMDR, Patch Management, CSAM, Policy Compliance, WAS, TotalCloud, "
            "Multi-Vector EDR, FIM, SAQ, CAR, and directly related APIs, connectors, and integrations. "
            "If the caller describes something informally, rephrase it into proper Qualys terminology before troubleshooting."
        ),
        (
            "Stay strictly inside Qualys support and directly related Qualys integrations. "
            "Do not answer general knowledge, news, weather, sports, entertainment, unrelated coding, personal questions, roleplay, or open-world chat."
        ),
        (
            "Be friendly, sweet, and casual, but not silly. Do not flirt, do not sound seductive, do not use sexual language, and do not get distracted by banter. "
            "Keep the conversation focused on solving the Qualys issue."
        ),
        (
            "If the caller asks something off-topic, refuse briefly in a natural way and pull the conversation back to Qualys support, "
            "for example: 'I can only help with Qualys issues. If something in Qualys is failing, tell me what's happening.'"
        ),
        (
            "Default style: technical expert first, casual tone second. Explain hard things simply without sounding textbook or formal. "
            "Give a brief explanation, then one concrete next step."
        ),
        (
            "Use adaptive support flow. Start simple and practical. If needed, become more technical. "
            "Guide one action at a time, confirm what changed, and update your hypothesis when a step fails."
        ),
        (
            "Collect context naturally while talking: caller name, company, product area, environment, integration target, "
            "error text, what was already tried, and the user's goal. Reuse those details later in the same call."
        ),
        (
            "Use confirmation loops naturally. Check what the caller already tried, suggest the next likely step, "
            "and if that does not work, explain the updated theory in simple words."
        ),
        (
            "If the caller sounds frustrated, acknowledge that first in a human way, then reduce the load by giving only one short next step."
        ),
        (
            "For unclear audio, background noise, crosstalk, or mixed phrasing, do not panic. "
            "Say what you think you heard, ask for a short confirmation, and recover practically instead of over-apologizing."
        ),
        (
            "Support English first, but handle common Indian support phrasing and simple Hinglish naturally when the caller uses it. "
            "Reply mostly in clear English."
        ),
        (
            "When the likely answer is already clear from the live conversation, answer directly without searching first. "
            "Those direct answers should sound natural and expert: a quick explanation plus one next step."
        ),
        (
            "If SearchUnify or another support knowledge source is available, use it only when needed: when you are uncertain, when the issue is ambiguous, "
            "or when the caller wants exact troubleshooting steps, error-code meaning, API details, integration details, or product-specific facts."
        ),
        (
            "Before checking the knowledge base, say one short casual transition so there is no dead pause, such as "
            "'Okay, this sounds like the connector side, let me quickly check the exact path.'"
        ),
        (
            "If you find guidance in the knowledge base, say that briefly and then explain it naturally in plain human language. "
            "If the guidance is weak, empty, or conflicting, give one safe preliminary check first and then ask one targeted clarifying question. "
            "If the guidance is strong but long, give only the first one or two steps and then pause for confirmation. "
            "Trust grounded knowledge-base guidance over your earlier assumption when they conflict."
        ),
        (
            "If the caller interrupts you, briefly acknowledge it, answer the caller's new words first, and continue the previous point only if it is still relevant."
        ),
        (
            "If a tool is unavailable, stay within Qualys support scope. Do not switch into general knowledge mode."
        ),
        (
            "Use the call memory tools throughout the conversation. Record important caller facts, tried steps, and your current Qualys issue framing "
            "with `remember_call_context`. If you need a refresh before suggesting the next step, use `get_call_context`."
        ),
    ]
    if CUSTOM_SYSTEM_MESSAGE:
        sections.append(f"Additional business instructions: {CUSTOM_SYSTEM_MESSAGE}")
    return "\n\n".join(sections)


SYSTEM_MESSAGE = _build_system_message()


def _build_transcription_prompt() -> str:
    return (
        "Desktop voice support session about Qualys. Expect terms like Qualys, VMDR, Patch Management, CSAM, "
        "Policy Compliance, WAS, TotalCloud, EDR, FIM, SAQ, CAR, ServiceNow, Jira, Splunk, SIEM, API, connector, "
        "vulnerability, patching, compliance, cloud posture, asset inventory, and common Indian English support phrasing."
    )


def _build_initial_greeting_line() -> str:
    opener = secrets.choice(QUALYS_DYNAMIC_OPENERS)
    return (
        f"Hi, I'm {ASSISTANT_NAME} from {SUPPORT_PRODUCT} support. "
        f"What can I help you with in {SUPPORT_PRODUCT} today? {opener}"
    )


def _build_realtime_tools() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "name": "remember_call_context",
            "description": (
                "Store important call details so the assistant can remember the caller's issue, product area, tried steps, "
                "and Qualys terminology across the rest of the conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_family": {"type": "string"},
                    "product_area": {"type": "string"},
                    "issue_summary": {"type": "string"},
                    "user_goal": {"type": "string"},
                    "caller_name": {"type": "string"},
                    "company": {"type": "string"},
                    "environment": {"type": "string"},
                    "error_text": {"type": "string"},
                    "integration_target": {"type": "string"},
                    "frustration_level": {"type": "string"},
                    "confirmed_fact": {"type": "string"},
                    "tried_step": {"type": "string"},
                    "step_result": {"type": "string"},
                    "grounding_note": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "get_call_context",
            "description": "Retrieve the latest remembered call context before proposing the next troubleshooting step or summary.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    ]
    if _knowledge_backend_enabled():
        tools.append(
            {
                "type": "function",
                "name": "search_qualys_support_knowledge",
                "description": (
                    "Search SearchUnify or another configured support knowledge source for Qualys-specific troubleshooting steps, "
                    "terminology, error explanations, APIs, connector guidance, or integration help. Use this when you need exact grounded guidance, "
                    "when the caller wants product-specific facts or exact steps, or when you are uncertain and need to verify the correct path."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The user's issue in natural language, rewritten with the important Qualys terms preserved.",
                        },
                        "product_area": {
                            "type": "string",
                            "description": "Optional Qualys area such as VMDR, Patch Management, CSAM, Policy Compliance, WAS, TotalCloud, EDR, FIM, SAQ, or CAR.",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            }
        )
    return tools


def _build_browser_session_config() -> dict[str, Any]:
    session = {
        "type": "realtime",
        "model": OPENAI_MODEL,
        "instructions": SYSTEM_MESSAGE,
        "output_modalities": ["audio"],
        "max_output_tokens": 900,
        "audio": {
            "input": {
                "transcription": {
                    "model": TRANSCRIPTION_MODEL,
                    "language": TRANSCRIPTION_LANGUAGE,
                    "prompt": _build_transcription_prompt(),
                },
                "noise_reduction": {"type": TRANSCRIPTION_NOISE_REDUCTION},
                "turn_detection": {
                    "type": "server_vad",
                    "create_response": True,
                    "interrupt_response": True,
                    "threshold": SERVER_VAD_THRESHOLD,
                    "prefix_padding_ms": SERVER_VAD_PREFIX_PADDING_MS,
                    "silence_duration_ms": SERVER_VAD_SILENCE_DURATION_MS,
                },
            },
            "output": {"voice": VOICE},
        },
        "tools": _build_realtime_tools(),
        "tool_choice": "auto",
    }
    return session


def _encode_multipart_form_data(fields: dict[str, str]) -> tuple[str, bytes]:
    boundary = f"----QualysRealtimeBoundary{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


def _create_realtime_call_sdp(offer_sdp: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    content_type, request_body = _encode_multipart_form_data(
        {
            "sdp": offer_sdp,
            "session": _json_dumps(_build_browser_session_config()),
        }
    )
    request = urllib_request.Request(
        f"{OPENAI_API_BASE}/realtime/calls",
        data=request_body,
        method="POST",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": content_type,
            "Accept": "application/json, application/sdp, text/plain, */*",
        },
    )

    try:
        with urllib_request.urlopen(request, timeout=30) as response:
            response_body = response.read()
            response_content_type = response.headers.get("Content-Type", "")
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore").strip()
        raise RuntimeError(detail or f"OpenAI create call failed with {exc.code}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"OpenAI create call failed: {exc.reason}") from exc

    if "application/json" in response_content_type:
        try:
            payload = json.loads(response_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenAI returned invalid JSON while creating the realtime call.") from exc
        answer = payload.get("answer")
        sdp = payload.get("sdp") or (answer.get("sdp") if isinstance(answer, dict) else answer) or ""
    else:
        sdp = response_body.decode("utf-8", "ignore")

    if not sdp.strip():
        raise RuntimeError("OpenAI returned an empty SDP answer.")
    return sdp


def _route_issue_family(text: str) -> tuple[str, str]:
    lowered = text.lower()
    best_family = "general"
    best_score = 0
    for family, keywords in ISSUE_FAMILY_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in lowered)
        if score > best_score:
            best_family = family
            best_score = score
    return best_family, ISSUE_FAMILY_LABELS[best_family]


def _extract_integration_targets(text: str) -> list[str]:
    lowered = text.lower()
    return [target.title() for target in INTEGRATION_TARGETS if target in lowered]


def _detect_frustration(text: str) -> str:
    lowered = text.lower()
    for level in ("high", "medium"):
        if any(phrase in lowered for phrase in FRUSTRATION_PATTERNS[level]):
            return level
    return "low"


def _detect_off_topic(text: str, routed_family: str, integration_targets: list[str]) -> tuple[bool, str]:
    lowered = text.lower().strip()
    if not lowered:
        return False, ""
    if routed_family != "general" or integration_targets:
        return False, ""
    if any(hint in lowered for hint in QUALYS_DOMAIN_HINTS):
        return False, ""
    matched = [pattern for pattern in OFF_TOPIC_PATTERNS if pattern in lowered]
    if matched:
        return True, f"Detected non-Qualys topic: {matched[0]}"
    return False, ""


def _build_call_context_hint(call_state: CallState) -> str:
    if call_state.off_topic_detected:
        return (
            "Guardrail reminder: the caller's latest request is off-topic. "
            "Do not answer it. Refuse briefly, say you only handle Qualys issues and integrations, and ask the caller to describe the Qualys problem instead."
        )
    segments = [
        f"Live call context update: the caller currently sounds like they have {call_state.routed_issue_label}.",
    ]
    if call_state.last_user_transcript:
        segments.append(f"Latest caller wording: {call_state.last_user_transcript}")
    if call_state.integration_targets:
        segments.append(f"Integration targets mentioned: {', '.join(call_state.integration_targets)}.")
    if call_state.frustration_level == "high":
        segments.append("Caller sounds frustrated. Acknowledge that first, then offer one short next step.")
    segments.append("On your next response, summarize first and then state the Qualys terminology clearly.")
    return " ".join(segments)


def _context_hint_for_state(call_state: CallState) -> str:
    signature = "|".join(
        [
            call_state.routed_issue_family,
            call_state.frustration_level,
            "off-topic" if call_state.off_topic_detected else "in-scope",
            call_state.off_topic_reason,
            ",".join(call_state.integration_targets),
            call_state.last_user_transcript[:120],
        ]
    )
    if signature == call_state.last_context_hint_signature:
        return ""
    if (
        call_state.routed_issue_family == "general"
        and call_state.frustration_level == "low"
        and not call_state.off_topic_detected
    ):
        return ""
    call_state.last_context_hint_signature = signature
    return _build_call_context_hint(call_state)


def _best_product_area_hint(call_state: CallState) -> str | None:
    product_area = (call_state.product_area or "").strip()
    if product_area:
        return product_area.replace("_", " ")
    if call_state.routed_issue_family != "general":
        return call_state.routed_issue_family.replace("_", " ")
    return None


def _knowledge_backend_enabled() -> bool:
    return bool(KNOWLEDGE_BACKEND_URL)


def _clean_searchunify_highlight(value: str) -> str:
    return value.replace(SEARCHUNIFY_HIGHLIGHT_START, "").replace(SEARCHUNIFY_HIGHLIGHT_END, "")


def _knowledge_backend_kind() -> str:
    if KNOWLEDGE_BACKEND_KIND:
        return KNOWLEDGE_BACKEND_KIND
    if "searchunify.ai/search/searchResultByPost" in KNOWLEDGE_BACKEND_URL:
        return "searchunify_post"
    return "generic_get"


def _cache_get(key: str) -> dict[str, Any] | None:
    cached = KNOWLEDGE_CACHE.get(key)
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at < time.time():
        KNOWLEDGE_CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: str, payload: dict[str, Any]) -> None:
    KNOWLEDGE_CACHE[key] = (time.time() + max(KNOWLEDGE_CACHE_TTL_S, 1), payload)


def _freshness_bonus(indexed_date: str) -> float:
    if not indexed_date:
        return 0.0
    try:
        indexed_dt = datetime.fromisoformat(indexed_date.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    age_days = max((datetime.now(timezone.utc) - indexed_dt).days, 0)
    if age_days <= 30:
        return 1.5
    if age_days <= 180:
        return 0.75
    if age_days <= 365:
        return 0.25
    return 0.0


def _build_ssl_context(cafile: str, insecure: bool) -> ssl.SSLContext:
    if insecure:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    if cafile:
        return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


def _knowledge_ssl_context() -> ssl.SSLContext | None:
    if not KNOWLEDGE_BACKEND_URL.lower().startswith("https://"):
        return None
    cafile = KNOWLEDGE_BACKEND_SSL_CERT_FILE or (certifi.where() if certifi is not None else "")
    return _build_ssl_context(cafile, KNOWLEDGE_BACKEND_SSL_INSECURE)


def _extract_error_tokens(text: str) -> list[str]:
    matches = re.findall(r"\b(?:[A-Z]{2,}[A-Z0-9_-]*|\d{3,})\b", text)
    return _dedupe_preserve_order(matches, limit=4)


def _extract_search_symptoms(text: str) -> list[str]:
    lowered = text.lower()
    return [pattern for pattern in SEARCH_SYMPTOM_PATTERNS if pattern in lowered]


def _extract_search_components(text: str, routed_family: str, product_area: str | None = None) -> list[str]:
    lowered = text.lower()
    component_family = routed_family
    product_area_key = (product_area or "").strip().lower().replace(" ", "_")
    if product_area_key in SEARCH_COMPONENT_HINTS:
        component_family = product_area_key
    candidates = list(SEARCH_COMPONENT_HINTS.get(component_family, ()))
    if "scanner" in lowered:
        candidates.append("scanner appliance")
    if "connector" in lowered:
        candidates.append("connector")
    if any(target in lowered for target in INTEGRATION_TARGETS):
        candidates.append("integration")
    return [
        value
        for value in _dedupe_preserve_order(candidates, limit=4)
        if value in lowered or value in SEARCH_COMPONENT_HINTS.get(component_family, ())
    ]


def _rewrite_support_query(query: str, product_area: str | None) -> str:
    base_query = " ".join(query.strip().split())
    if not base_query:
        return base_query
    routed_family, _ = _route_issue_family(f"{base_query} {product_area or ''}")
    product_area_value = (product_area or "").strip().replace("_", " ")
    if not product_area_value and routed_family != "general":
        product_area_value = routed_family.replace("_", " ")

    keyword_segments: list[str] = [SUPPORT_PRODUCT]
    if product_area_value:
        keyword_segments.append(product_area_value)
    keyword_segments.extend(_extract_error_tokens(base_query))
    keyword_segments.extend(_extract_search_components(base_query, routed_family, product_area_value))
    keyword_segments.extend(_extract_search_symptoms(base_query))
    keyword_segments.append(base_query)
    return " ".join(_dedupe_preserve_order([segment for segment in keyword_segments if segment], limit=8))


def _build_searchunify_payload(query: str) -> dict[str, Any]:
    search_uid = SEARCHUNIFY_SEARCH_UID or str(uuid.uuid4())
    return {
        "storeContext": True,
        "langAttr": "",
        "react": 1,
        "isRecommendationsWidget": False,
        "searchString": query,
        "from": 0,
        "sortby": SEARCHUNIFY_SORTBY,
        "orderBy": SEARCHUNIFY_ORDER_BY,
        "pageNo": "1",
        "aggregations": [],
        "clonedAggregations": [],
        "uid": SEARCHUNIFY_UID,
        "resultsPerPage": SEARCHUNIFY_RESULTS_PER_PAGE,
        "exactPhrase": "",
        "withOneOrMore": "",
        "withoutTheWords": "",
        "pageSize": str(SEARCHUNIFY_RESULTS_PER_PAGE),
        "sid": SEARCHUNIFY_SID,
        "language": SEARCHUNIFY_LANGUAGE,
        "mergeSources": False,
        "versionResults": True,
        "suCaseCreate": False,
        "visitedtitle": "",
        "paginationClicked": False,
        "email": "",
        "searchUid": search_uid,
        "accessToken": SEARCHUNIFY_ACCESS_TOKEN,
        "getAutoTunedResult": True,
        "getSimilarSearches": True,
        "smartFacets": True,
    }


def _build_searchunify_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": "SearchUnifyQualysWebRTCDemo/1.0",
    }
    if SEARCHUNIFY_ORIGIN:
        headers["Origin"] = SEARCHUNIFY_ORIGIN
    if SEARCHUNIFY_REFERER:
        headers["Referer"] = SEARCHUNIFY_REFERER
    if SEARCHUNIFY_COOKIE:
        headers["Cookie"] = SEARCHUNIFY_COOKIE
    return headers


def _searchunify_missing_settings() -> list[str]:
    missing: list[str] = []
    if not SEARCHUNIFY_UID:
        missing.append("SEARCHUNIFY_UID")
    if not SEARCHUNIFY_ACCESS_TOKEN:
        missing.append("SEARCHUNIFY_ACCESS_TOKEN")
    if not SEARCHUNIFY_SID:
        missing.append("SEARCHUNIFY_SID")
    return missing


def _flatten_searchunify_highlights(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        cleaned = _clean_searchunify_highlight(value).strip()
        if cleaned:
            values.append(cleaned)
        return values
    if isinstance(value, list):
        for item in value:
            values.extend(_flatten_searchunify_highlights(item))
        return values
    if isinstance(value, dict):
        for item in value.values():
            values.extend(_flatten_searchunify_highlights(item))
    return values


def _dedupe_preserve_order(values: list[str], limit: int = 3) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(value.strip())
        if len(deduped) >= limit:
            break
    return deduped


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "solved"}


def _extract_searchunify_snippet(hit: dict[str, Any]) -> str:
    highlight_parts = _dedupe_preserve_order(_flatten_searchunify_highlights(hit.get("highlight")), limit=2)
    if highlight_parts:
        return " … ".join(highlight_parts)[:1200]
    for key in ("snippet", "summary", "description", "text", "body"):
        value = hit.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:1200]
    return ""


def _score_result(
    title: str,
    snippet: str,
    source_name: str,
    query_tokens: set[str],
    product_area_tokens: set[str],
    base_score: float = 0.0,
    indexed_date: str = "",
    solved: bool = False,
) -> tuple[float, list[str]]:
    match_text = " ".join(part for part in (title, snippet, source_name) if part)
    doc_tokens = _tokenize(match_text)
    overlap = len(query_tokens & doc_tokens)
    area_overlap = len(product_area_tokens & doc_tokens)
    freshness = _freshness_bonus(indexed_date)
    score = base_score + (overlap * 0.9) + (area_overlap * 1.1) + freshness
    signals: list[str] = []
    if base_score:
        signals.append(f"backend score {base_score:.2f}")
    if overlap:
        signals.append(f"query overlap {overlap}")
    if area_overlap:
        signals.append(f"product-area overlap {area_overlap}")
    if freshness:
        signals.append("fresh content boost")
    if solved:
        score += 0.5
        signals.append("marked solved")
    return score, signals


def _extract_backend_results(payload: Any) -> list[dict[str, str]]:
    items: list[Any]
    if isinstance(payload, dict):
        for key in ("results", "items", "hits", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                items = value
                break
        else:
            items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        return [{"title": "Raw backend response", "snippet": str(payload), "url": ""}]

    extracted: list[dict[str, str]] = []
    for item in items[:KNOWLEDGE_RESULT_LIMIT]:
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("name") or item.get("heading") or "Support result")
            url = str(item.get("url") or item.get("link") or item.get("source") or "")
            snippet = str(
                item.get("snippet")
                or item.get("summary")
                or item.get("content")
                or item.get("text")
                or item.get("description")
                or ""
            )
            extracted.append({"title": title, "url": url, "snippet": snippet[:1200]})
        else:
            extracted.append({"title": "Support result", "url": "", "snippet": str(item)[:1200]})
    return extracted


def _normalize_generic_results(payload: Any, query: str, product_area: str | None) -> list[dict[str, Any]]:
    query_tokens = _tokenize(query)
    product_area_tokens = _tokenize(product_area or "")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(_extract_backend_results(payload)):
        title = str(item.get("title") or "Support result").strip()
        snippet = str(item.get("snippet") or "").strip()
        url = str(item.get("url") or "").strip()
        score, signals = _score_result(
            title=title,
            snippet=snippet,
            source_name=KNOWLEDGE_BACKEND_NAME,
            query_tokens=query_tokens,
            product_area_tokens=product_area_tokens,
            base_score=max(KNOWLEDGE_RESULT_LIMIT - index, 0) * 0.2,
        )
        normalized.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet[:1200],
                "source_type": "generic",
                "source_name": KNOWLEDGE_BACKEND_NAME,
                "confidence": round(min(0.99, 0.2 + (score / 12)), 2),
                "score": round(score, 2),
                "match_signals": signals,
            }
        )
    normalized.sort(key=lambda item: item.get("score", 0), reverse=True)
    return normalized[:KNOWLEDGE_RESULT_LIMIT]


def _normalize_searchunify_results(payload: dict[str, Any], query: str, product_area: str | None) -> list[dict[str, Any]]:
    hits = payload.get("result", {}).get("hits") or []
    if not isinstance(hits, list):
        return []
    query_tokens = _tokenize(query)
    product_area_tokens = _tokenize(product_area or "")
    normalized: list[dict[str, Any]] = []
    for hit in hits[: max(SEARCHUNIFY_RESULTS_PER_PAGE, KNOWLEDGE_RESULT_LIMIT)]:
        if not isinstance(hit, dict):
            continue
        title = str(hit.get("objName") or hit.get("title") or "SearchUnify result").strip()
        snippet = _extract_searchunify_snippet(hit)
        url = str(hit.get("href") or hit.get("clientHref") or "").strip()
        source_name = str(hit.get("sourceLabel") or hit.get("sourceName") or "SearchUnify").strip()
        indexed_date = str(hit.get("indexedDate") or "").strip()
        solved = _coerce_bool(hit.get("solved"))
        try:
            backend_score = float(hit.get("_score") or 0.0)
        except (TypeError, ValueError):
            backend_score = 0.0
        score, signals = _score_result(
            title=title,
            snippet=snippet,
            source_name=source_name,
            query_tokens=query_tokens,
            product_area_tokens=product_area_tokens,
            base_score=backend_score,
            indexed_date=indexed_date,
            solved=solved,
        )
        normalized.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "source_type": "searchunify",
                "source_name": source_name,
                "source_label": str(hit.get("sourceLabel") or "").strip(),
                "client_url": str(hit.get("clientHref") or "").strip(),
                "content_tag": str(hit.get("contentTag") or "").strip(),
                "indexed_date": indexed_date,
                "solved": solved,
                "confidence": round(min(0.99, 0.2 + (score / 18)), 2),
                "score": round(score, 2),
                "match_signals": signals,
            }
        )
    normalized.sort(key=lambda item: item.get("score", 0), reverse=True)
    return normalized[:KNOWLEDGE_RESULT_LIMIT]


def _detect_result_conflict(results: list[dict[str, Any]]) -> tuple[bool, str]:
    if len(results) < 2:
        return False, ""
    first, second = results[0], results[1]
    try:
        first_score = float(first.get("score") or 0.0)
        second_score = float(second.get("score") or 0.0)
    except (TypeError, ValueError):
        return False, ""
    same_target = (
        _normalize_text(str(first.get("url") or ""))
        and _normalize_text(str(first.get("url") or "")) == _normalize_text(str(second.get("url") or ""))
    )
    distinct_titles = _normalize_text(str(first.get("title") or "")) != _normalize_text(str(second.get("title") or ""))
    if same_target or not distinct_titles:
        return False, ""
    if abs(first_score - second_score) > 0.9:
        return False, ""
    summary = (
        f"Top results are similarly strong but point to different paths: "
        f"`{first.get('title', 'Result 1')}` vs `{second.get('title', 'Result 2')}`."
    )
    return True, summary


def _build_grounding_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    best_result = results[0] if results else None
    conflict, conflict_summary = _detect_result_conflict(results)
    best_confidence = float(best_result.get("confidence") or 0.0) if best_result else 0.0
    if best_confidence >= 0.75:
        response_mode = "answer_directly"
    elif best_confidence >= 0.45:
        response_mode = "answer_and_confirm"
    else:
        response_mode = "clarify_first"
    return {
        "best_result": best_result,
        "best_confidence": round(best_confidence, 2),
        "conflict": conflict,
        "conflict_summary": conflict_summary,
        "response_mode": response_mode,
    }


def _knowledge_lookup_sync(query: str, product_area: str | None) -> dict[str, Any]:
    if not KNOWLEDGE_BACKEND_URL:
        return {
            "backend": KNOWLEDGE_BACKEND_NAME,
            "query": query,
            "results": [],
            "note": "Knowledge backend is not configured.",
        }
    rewritten_query = _rewrite_support_query(query, product_area)
    backend_kind = _knowledge_backend_kind()
    cache_key = f"{backend_kind}|{_normalize_text(rewritten_query)}|{_normalize_text(product_area or '')}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    ssl_context = _knowledge_ssl_context()
    if backend_kind == "searchunify_post":
        missing_settings = _searchunify_missing_settings()
        if missing_settings:
            return {
                "backend": KNOWLEDGE_BACKEND_NAME,
                "backend_kind": backend_kind,
                "query": query,
                "rewritten_query": rewritten_query,
                "product_area": product_area or "",
                "results": [],
                "note": f"Missing SearchUnify configuration: {', '.join(missing_settings)}",
                "best_result": None,
                "best_confidence": 0.0,
                "conflict": False,
                "conflict_summary": "",
                "response_mode": "clarify_first",
            }
        request_body = json.dumps(_build_searchunify_payload(rewritten_query)).encode("utf-8")
        request = urllib_request.Request(KNOWLEDGE_BACKEND_URL, data=request_body, method="POST")
        for key, value in _build_searchunify_headers().items():
            request.add_header(key, value)
    else:
        params = {"q": rewritten_query, "limit": str(KNOWLEDGE_RESULT_LIMIT)}
        if product_area:
            params["product_area"] = product_area
        request_url = f"{KNOWLEDGE_BACKEND_URL}?{urllib_parse.urlencode(params)}"
        request = urllib_request.Request(request_url)
        request.add_header("Accept", "application/json")

    if KNOWLEDGE_BACKEND_API_KEY:
        auth_value = KNOWLEDGE_BACKEND_API_KEY
        if KNOWLEDGE_BACKEND_AUTH_SCHEME:
            auth_value = f"{KNOWLEDGE_BACKEND_AUTH_SCHEME} {KNOWLEDGE_BACKEND_API_KEY}"
        request.add_header(KNOWLEDGE_BACKEND_AUTH_HEADER, auth_value)

    with urllib_request.urlopen(request, timeout=KNOWLEDGE_BACKEND_TIMEOUT_S, context=ssl_context) as response:
        body = response.read().decode("utf-8", errors="replace")
        content_type = response.headers.get("Content-Type", "")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {"results": [{"title": "Support result", "snippet": body, "url": ""}]}

    if backend_kind == "searchunify_post" and isinstance(payload, dict):
        normalized_results = _normalize_searchunify_results(payload, rewritten_query, product_area)
        note = str(payload.get("message") or "").strip()
    else:
        normalized_results = _normalize_generic_results(payload, rewritten_query, product_area)
        note = ""

    result = {
        "backend": KNOWLEDGE_BACKEND_NAME,
        "backend_kind": backend_kind,
        "query": query,
        "rewritten_query": rewritten_query,
        "product_area": product_area or "",
        "content_type": content_type,
        "results": normalized_results,
        "note": note,
        **_build_grounding_summary(normalized_results),
    }
    _cache_set(cache_key, result)
    return result


async def _knowledge_lookup(query: str, product_area: str | None) -> dict[str, Any]:
    try:
        result = await __import__("asyncio").to_thread(_knowledge_lookup_sync, query, product_area)
        best_result = result.get("best_result") or {}
        logger.info(
            "Knowledge lookup complete kind=%s best_source=%s confidence=%s conflict=%s",
            result.get("backend_kind") or _knowledge_backend_kind(),
            best_result.get("source_name") or KNOWLEDGE_BACKEND_NAME,
            result.get("best_confidence"),
            result.get("conflict"),
        )
        return result
    except urllib_error.HTTPError as exc:
        logger.warning("Knowledge lookup HTTP error: %s", exc)
        return {"backend": KNOWLEDGE_BACKEND_NAME, "query": query, "results": [], "error": f"HTTP {exc.code}"}
    except urllib_error.URLError as exc:
        logger.warning("Knowledge lookup URL error: %s", exc)
        return {"backend": KNOWLEDGE_BACKEND_NAME, "query": query, "results": [], "error": str(exc.reason)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Knowledge lookup failed")
        return {"backend": KNOWLEDGE_BACKEND_NAME, "query": query, "results": [], "error": str(exc)}


def _best_search_query_for_state(call_state: CallState, requested_query: str = "", requested_product_area: str | None = None) -> tuple[str, str | None]:
    query = requested_query.strip() or call_state.issue_summary or call_state.last_user_transcript
    product_area = (requested_product_area or "").strip() or _best_product_area_hint(call_state)
    return query, product_area


def _prune_session_state() -> None:
    now = time.time()
    expired = [session_id for session_id, (expires_at, _) in SESSION_STATE.items() if expires_at < now]
    for session_id in expired:
        SESSION_STATE.pop(session_id, None)


def _get_or_create_session_state(session_id: str) -> CallState:
    _prune_session_state()
    cached = SESSION_STATE.get(session_id)
    if cached:
        _, state = cached
        SESSION_STATE[session_id] = (time.time() + SESSION_STATE_TTL_S, state)
        return state
    state = CallState(assistant_name=ASSISTANT_NAME, support_product=SUPPORT_PRODUCT)
    SESSION_STATE[session_id] = (time.time() + SESSION_STATE_TTL_S, state)
    return state


def _reset_session_state(session_id: str) -> None:
    SESSION_STATE.pop(session_id, None)


def _demo_check(name: str, ok: bool, detail: str, severity: str = "error") -> dict[str, Any]:
    return {"name": name, "ok": ok, "severity": severity, "detail": detail}


def _build_demo_readiness_checks() -> list[dict[str, Any]]:
    checks = [
        _demo_check(
            "openai_api_key",
            bool(OPENAI_API_KEY),
            "OpenAI API key is configured." if OPENAI_API_KEY else "Set OPENAI_API_KEY in `.env`.",
        ),
        _demo_check(
            "voice",
            VOICE in SUPPORTED_REALTIME_VOICES,
            f"Realtime voice `{VOICE}` is active.",
        ),
        _demo_check(
            "static_ui",
            STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists(),
            "Static WebRTC UI assets are present.",
        ),
        _demo_check(
            "knowledge_backend",
            _knowledge_backend_enabled(),
            (
                f"Knowledge backend `{KNOWLEDGE_BACKEND_NAME}` is configured."
                if _knowledge_backend_enabled()
                else "Set KNOWLEDGE_BACKEND_URL to enable grounded support answers."
            ),
        ),
    ]
    if _knowledge_backend_enabled():
        backend_kind = _knowledge_backend_kind()
        checks.append(
            _demo_check(
                "knowledge_backend_kind",
                backend_kind in {"searchunify_post", "generic_get"},
                f"Backend kind is `{backend_kind}`.",
            )
        )
        if backend_kind == "searchunify_post":
            missing = _searchunify_missing_settings()
            checks.append(
                _demo_check(
                    "searchunify_required_config",
                    not missing,
                    "SearchUnify required settings are configured."
                    if not missing
                    else f"Missing SearchUnify settings: {', '.join(missing)}.",
                )
            )
    return checks


def _demo_ready(checks: list[dict[str, Any]]) -> bool:
    return all(check["ok"] for check in checks if check.get("severity") != "warning")


app = FastAPI(title="Qualys WebRTC Voice Demo")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def _log_startup_configuration() -> None:
    logger.info(
        "Startup config version=%s model=%s voice=%s public_url=%s knowledge_backend=%s/%s frontend=webrtc-browser-backend-signaled",
        APP_FLOW_VERSION,
        OPENAI_MODEL,
        VOICE,
        PUBLIC_URL or "<unset>",
        KNOWLEDGE_BACKEND_NAME if _knowledge_backend_enabled() else "<disabled>",
        _knowledge_backend_kind() if _knowledge_backend_enabled() else "",
    )
    logger.info(
        "Realtime browser config vad_threshold=%.2f vad_prefix_padding_ms=%s vad_silence_ms=%s ai_speaks_first=%s",
        SERVER_VAD_THRESHOLD,
        SERVER_VAD_PREFIX_PADDING_MS,
        SERVER_VAD_SILENCE_DURATION_MS,
        AI_SPEAKS_FIRST,
    )


@app.get("/", response_class=FileResponse)
async def index_page():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return JSONResponse(content={"ok": False, "error": "UI assets missing."}, status_code=500)
    return FileResponse(index_path)


@app.get("/health", response_class=JSONResponse)
async def health():
    return {
        "ok": True,
        "app_flow_version": APP_FLOW_VERSION,
        "frontend_mode": "browser-webrtc-backend-signaled",
        "public_url": PUBLIC_URL,
        "model": OPENAI_MODEL,
        "voice": VOICE,
        "assistant_name": ASSISTANT_NAME,
        "support_product": SUPPORT_PRODUCT,
        "transcription_model": TRANSCRIPTION_MODEL,
        "knowledge_backend_enabled": _knowledge_backend_enabled(),
        "knowledge_backend_name": KNOWLEDGE_BACKEND_NAME,
        "knowledge_backend_kind": _knowledge_backend_kind() if _knowledge_backend_enabled() else "",
        "knowledge_cache_ttl_s": KNOWLEDGE_CACHE_TTL_S,
        "session_state_ttl_s": SESSION_STATE_TTL_S,
        "demo_ready": _demo_ready(_build_demo_readiness_checks()),
        "openai_key_exposed_to_browser": False,
    }


@app.get("/socket/api/realtime-config", response_class=JSONResponse)
async def realtime_config():
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is missing.")
    return {
        "app_flow_version": APP_FLOW_VERSION,
        "mode": "browser-webrtc-backend-signaled",
        "public_url": PUBLIC_URL,
        "model": OPENAI_MODEL,
        "voice": VOICE,
        "assistant_name": ASSISTANT_NAME,
        "support_product": SUPPORT_PRODUCT,
        "knowledge_backend_name": KNOWLEDGE_BACKEND_NAME if _knowledge_backend_enabled() else "",
        "knowledge_backend_enabled": _knowledge_backend_enabled(),
        "ai_speaks_first": AI_SPEAKS_FIRST,
        "initial_greeting": _build_initial_greeting_line(),
        "session": _build_browser_session_config(),
        "tool_names": [tool["name"] for tool in _build_realtime_tools()],
    }


@app.post("/socket/api/realtime-call", response_class=PlainTextResponse)
async def realtime_call(request: RealtimeCallRequest):
    try:
        answer_sdp = await __import__("asyncio").to_thread(_create_realtime_call_sdp, request.sdp)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return PlainTextResponse(answer_sdp)


@app.post("/socket/api/session/reset", response_class=JSONResponse)
async def reset_session(request: SessionRequest):
    _reset_session_state(request.session_id)
    _get_or_create_session_state(request.session_id)
    return {"ok": True, "session_id": request.session_id}


@app.post("/socket/api/context/transcript", response_class=JSONResponse)
async def update_transcript(request: TranscriptRequest):
    call_state = _get_or_create_session_state(request.session_id)
    route_changed = call_state.apply_user_transcript(request.transcript)
    if route_changed:
        _append_unique(call_state.confirmed_facts, f"Routed issue family: {call_state.routed_issue_label}")
    system_hint = _context_hint_for_state(call_state)
    return {
        "ok": True,
        "route_changed": route_changed,
        "system_hint": system_hint,
        "context": call_state.as_tool_payload(),
        "summary": call_state.summary_text(),
        "search_recommended": any(pattern in request.transcript.lower() for pattern in SEARCH_FIRST_PATTERNS),
    }


@app.post("/socket/api/tool/remember-context", response_class=JSONResponse)
async def remember_context(request: ContextPayloadRequest):
    call_state = _get_or_create_session_state(request.session_id)
    call_state.remember_context(request.payload)
    return {
        "ok": True,
        "summary": call_state.summary_text(),
        "context": call_state.as_tool_payload(),
    }


@app.post("/socket/api/tool/get-context", response_class=JSONResponse)
async def get_context(request: SessionRequest):
    call_state = _get_or_create_session_state(request.session_id)
    return {
        "summary": call_state.summary_text(),
        "context": call_state.as_tool_payload(),
    }


@app.post("/socket/api/tool/search", response_class=JSONResponse)
async def search_tool(request: SearchRequest):
    call_state = _get_or_create_session_state(request.session_id)
    query, product_area = _best_search_query_for_state(call_state, request.query, request.product_area)
    result = await _knowledge_lookup(query, product_area)
    best_result = result.get("best_result") or {}
    best_title = str(best_result.get("title") or "").strip()
    if best_title:
        _append_unique(call_state.grounding_notes, f"Knowledge base match: {best_title}", limit=4)
    return result


@app.get("/demo-readiness", response_class=JSONResponse)
async def demo_readiness(probe_search: bool = False, query: str = "", product_area: str = ""):
    checks = _build_demo_readiness_checks()
    payload: dict[str, Any] = {
        "ready": _demo_ready(checks),
        "checks": checks,
        "defaults": {
            "demo_lookup_query": DEMO_LOOKUP_QUERY,
            "demo_lookup_product_area": DEMO_LOOKUP_PRODUCT_AREA,
        },
    }
    if probe_search and _knowledge_backend_enabled():
        search_query = query.strip() or DEMO_LOOKUP_QUERY
        search_product_area = product_area.strip() or DEMO_LOOKUP_PRODUCT_AREA
        probe_result = await _knowledge_lookup(search_query, search_product_area)
        payload["knowledge_probe"] = {
            "query": search_query,
            "product_area": search_product_area,
            "result_count": len(probe_result.get("results") or []),
            "best_confidence": probe_result.get("best_confidence"),
            "response_mode": probe_result.get("response_mode"),
            "conflict": probe_result.get("conflict"),
            "best_result": probe_result.get("best_result"),
            "error": probe_result.get("error"),
            "note": probe_result.get("note"),
        }
    return payload


@app.get("/demo-search", response_class=JSONResponse)
async def demo_search(query: str = "", product_area: str = ""):
    search_query = query.strip() or DEMO_LOOKUP_QUERY
    search_product_area = product_area.strip() or DEMO_LOOKUP_PRODUCT_AREA
    return await _knowledge_lookup(search_query, search_product_area)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT, proxy_headers=True, forwarded_allow_ips="*")
