import asyncio
import base64
import dataclasses
import inspect
import json
import logging
import os
import re
import secrets
import ssl
import time
import uuid
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import Connect, VoiceResponse

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


_JSON_DUMPS_KWARGS: dict[str, Any] = {"separators": (",", ":"), "ensure_ascii": False}


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, **_JSON_DUMPS_KWARGS)


def _safe_preview(value: Any, limit: int = 220) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("realtime_voice")
APP_FLOW_VERSION = "2026-04-08-kb-flow-v3"

PORT = int(os.getenv("PORT", "5050"))
PUBLIC_URL = (os.getenv("PUBLIC_URL") or "").strip() or None

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip() or None
OPENAI_PROJECT = (os.getenv("OPENAI_PROJECT") or "").strip() or None
OPENAI_ORGANIZATION = (os.getenv("OPENAI_ORGANIZATION") or "").strip() or None
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-realtime")
OPENAI_WS_URL = os.getenv("OPENAI_WS_URL", f"wss://api.openai.com/v1/realtime?model={OPENAI_MODEL}")
OPENAI_BETA_HEADER = (os.getenv("OPENAI_BETA_HEADER", "") or "").strip()
OPENAI_CONNECT_RETRIES = int(os.getenv("OPENAI_CONNECT_RETRIES", "3"))
OPENAI_CONNECT_TIMEOUT_S = float(os.getenv("OPENAI_CONNECT_TIMEOUT_S", "10"))
OPENAI_SSL_CERT_FILE = os.getenv("OPENAI_SSL_CERT_FILE", "").strip()
OPENAI_SSL_INSECURE = _env_bool("OPENAI_SSL_INSECURE", False)

LEGACY_DEFAULT_SYSTEM_MESSAGE = "You are a helpful human female assistant who answers any questions I ask."
CUSTOM_SYSTEM_MESSAGE = (os.getenv("SYSTEM_MESSAGE") or "").strip()
if CUSTOM_SYSTEM_MESSAGE == LEGACY_DEFAULT_SYSTEM_MESSAGE:
    CUSTOM_SYSTEM_MESSAGE = ""

ASSISTANT_NAME = (os.getenv("ASSISTANT_NAME") or "SearchUnify assistant").strip()
SUPPORT_PRODUCT = (os.getenv("SUPPORT_PRODUCT") or "Qualys").strip()
VOICE = os.getenv("VOICE", "verse").strip()
AI_SPEAKS_FIRST = _env_bool("AI_SPEAKS_FIRST", True)
INTERRUPT_DEBOUNCE_MS = int(os.getenv("INTERRUPT_DEBOUNCE_MS", "180"))
INTERRUPT_MIN_SPEECH_MS = max(int(os.getenv("INTERRUPT_MIN_SPEECH_MS", "260")), INTERRUPT_DEBOUNCE_MS)
INTERRUPT_RESPONSE_COOLDOWN_MS = int(os.getenv("INTERRUPT_RESPONSE_COOLDOWN_MS", "250"))
SERVER_VAD_THRESHOLD = float(os.getenv("SERVER_VAD_THRESHOLD", "0.62"))
SERVER_VAD_PREFIX_PADDING_MS = int(os.getenv("SERVER_VAD_PREFIX_PADDING_MS", "300"))
SERVER_VAD_SILENCE_DURATION_MS = int(os.getenv("SERVER_VAD_SILENCE_DURATION_MS", "450"))
KNOWLEDGE_BACKEND_URL = (os.getenv("KNOWLEDGE_BACKEND_URL") or "").strip()
KNOWLEDGE_BACKEND_NAME = (os.getenv("KNOWLEDGE_BACKEND_NAME") or "support knowledge backend").strip()
KNOWLEDGE_BACKEND_API_KEY = (os.getenv("KNOWLEDGE_BACKEND_API_KEY") or "").strip()
KNOWLEDGE_BACKEND_AUTH_HEADER = (os.getenv("KNOWLEDGE_BACKEND_AUTH_HEADER") or "Authorization").strip()
KNOWLEDGE_BACKEND_AUTH_SCHEME = (os.getenv("KNOWLEDGE_BACKEND_AUTH_SCHEME") or "Bearer").strip()
KNOWLEDGE_BACKEND_TIMEOUT_S = float(os.getenv("KNOWLEDGE_BACKEND_TIMEOUT_S", "8"))
KNOWLEDGE_RESULT_LIMIT = int(os.getenv("KNOWLEDGE_RESULT_LIMIT", "5"))
KNOWLEDGE_BACKEND_KIND = (os.getenv("KNOWLEDGE_BACKEND_KIND") or "").strip().lower()
KNOWLEDGE_BACKEND_SSL_CERT_FILE = (os.getenv("KNOWLEDGE_BACKEND_SSL_CERT_FILE") or "").strip()
KNOWLEDGE_BACKEND_SSL_INSECURE = _env_bool("KNOWLEDGE_BACKEND_SSL_INSECURE", False)
KNOWLEDGE_CACHE_TTL_S = int(os.getenv("KNOWLEDGE_CACHE_TTL_S", "180"))
SEARCHUNIFY_UID = (os.getenv("SEARCHUNIFY_UID") or "").strip()
SEARCHUNIFY_ACCESS_TOKEN = (os.getenv("SEARCHUNIFY_ACCESS_TOKEN") or "").strip()
SEARCHUNIFY_SID = (os.getenv("SEARCHUNIFY_SID") or "").strip()
SEARCHUNIFY_SEARCH_UID = (os.getenv("SEARCHUNIFY_SEARCH_UID") or "").strip()
SEARCHUNIFY_COOKIE = (os.getenv("SEARCHUNIFY_COOKIE") or "").strip()
SEARCHUNIFY_ORIGIN = (os.getenv("SEARCHUNIFY_ORIGIN") or "").strip()
SEARCHUNIFY_REFERER = (os.getenv("SEARCHUNIFY_REFERER") or "").strip()
SEARCHUNIFY_RESULTS_PER_PAGE = int(os.getenv("SEARCHUNIFY_RESULTS_PER_PAGE", str(KNOWLEDGE_RESULT_LIMIT)))
SEARCHUNIFY_LANGUAGE = (os.getenv("SEARCHUNIFY_LANGUAGE") or "en").strip()
SEARCHUNIFY_SORTBY = (os.getenv("SEARCHUNIFY_SORTBY") or "_score").strip()
SEARCHUNIFY_ORDER_BY = (os.getenv("SEARCHUNIFY_ORDER_BY") or "desc").strip()
TRANSCRIPTION_MODEL = (os.getenv("TRANSCRIPTION_MODEL") or "gpt-4o-mini-transcribe").strip()
TRANSCRIPTION_LANGUAGE = (os.getenv("TRANSCRIPTION_LANGUAGE") or "en").strip()
TRANSCRIPTION_NOISE_REDUCTION = (os.getenv("TRANSCRIPTION_NOISE_REDUCTION") or "near_field").strip()
COMMUNICATION_STYLE = (os.getenv("COMMUNICATION_STYLE") or "warm_regional").strip().lower()

LOG_OPENAI_EVENTS = _env_bool("LOG_OPENAI_EVENTS", False)
SHOW_TIMING_MATH = _env_bool("SHOW_TIMING_MATH", False)
LOG_CALL_TRANSCRIPTS = _env_bool("LOG_CALL_TRANSCRIPTS", False)
LOG_TOOL_PAYLOADS = _env_bool("LOG_TOOL_PAYLOADS", False)
LOG_TWILIO_MEDIA_EVENTS = _env_bool("LOG_TWILIO_MEDIA_EVENTS", False)
LOG_KNOWLEDGE_DETAILS = _env_bool("LOG_KNOWLEDGE_DETAILS", False)
DEMO_LOOKUP_QUERY = (os.getenv("DEMO_LOOKUP_QUERY") or "cloud agent not checking in").strip()
DEMO_LOOKUP_PRODUCT_AREA = (os.getenv("DEMO_LOOKUP_PRODUCT_AREA") or "cloud agent").strip()
LOG_EVENT_TYPES = {
    "response.content.done",
    "rate_limits.updated",
    "response.done",
    "input_audio_buffer.committed",
    "input_audio_buffer.speech_stopped",
    "input_audio_buffer.speech_started",
    "response.create",
    "session.created",
    "session.updated",
}

SUPPORTED_REALTIME_VOICES = ("aira", "marin", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse")
SUPPORTED_COMMUNICATION_STYLES = ("warm_regional", "neutral_support", "concise_technical")
SEARCHUNIFY_HIGHLIGHT_START = "___su-highlight-start___"
SEARCHUNIFY_HIGHLIGHT_END = "___su-highlight-end___"
KNOWLEDGE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
QUALYS_DOMAIN_TERMS = (
    "Qualys",
    "VMDR",
    "Cloud Agent",
    "Asset Inventory",
    "Authentication Record",
    "Auth Record",
    "Scanner Appliance",
    "ServiceNow",
    "Jira",
    "Splunk",
    "SIEM",
    "Connector",
    "API",
    "XML API",
    "QID",
    "WAS",
    "Scan Profile",
    "Option Profile",
    "QID",
    "BUNDLE",
    "PATCH",
    "vulnerability",
)

app = FastAPI()


@app.on_event("startup")
async def _log_startup_configuration() -> None:
    logger.info(
        "Startup config version=%s model=%s voice=%s communication_style=%s public_url=%s knowledge_backend=%s/%s",
        APP_FLOW_VERSION,
        OPENAI_MODEL,
        VOICE,
        COMMUNICATION_STYLE,
        PUBLIC_URL or "<unset>",
        KNOWLEDGE_BACKEND_NAME if _knowledge_backend_enabled() else "<disabled>",
        _knowledge_backend_kind() if _knowledge_backend_enabled() else "",
    )
    if any((LOG_OPENAI_EVENTS, SHOW_TIMING_MATH, LOG_CALL_TRANSCRIPTS, LOG_TOOL_PAYLOADS, LOG_TWILIO_MEDIA_EVENTS, LOG_KNOWLEDGE_DETAILS)):
        logger.info(
            "Debug flags openai_events=%s timing_math=%s call_transcripts=%s tool_payloads=%s twilio_media_events=%s knowledge_details=%s",
            LOG_OPENAI_EVENTS,
            SHOW_TIMING_MATH,
            LOG_CALL_TRANSCRIPTS,
            LOG_TOOL_PAYLOADS,
            LOG_TWILIO_MEDIA_EVENTS,
            LOG_KNOWLEDGE_DETAILS,
        )
    logger.info(
        "Interruption config min_speech_ms=%s cooldown_ms=%s vad_threshold=%.2f vad_silence_ms=%s",
        INTERRUPT_MIN_SPEECH_MS,
        INTERRUPT_RESPONSE_COOLDOWN_MS,
        SERVER_VAD_THRESHOLD,
        SERVER_VAD_SILENCE_DURATION_MS,
    )

try:
    import certifi  # type: ignore
except Exception:  # noqa: BLE001
    certifi = None


def _ws_connect_kwargs(headers: dict[str, str]) -> dict[str, Any]:
    param = "additional_headers" if "additional_headers" in inspect.signature(websockets.connect).parameters else "extra_headers"
    kwargs: dict[str, Any] = {
        param: headers,
        "open_timeout": OPENAI_CONNECT_TIMEOUT_S,
        "ping_interval": 20,
        "ping_timeout": 20,
        "close_timeout": 5,
        "max_size": None,
    }
    ssl_ctx = _openai_ssl_context()
    if ssl_ctx is not None:
        kwargs["ssl"] = ssl_ctx
    return kwargs


def _openai_ssl_context() -> ssl.SSLContext | None:
    # Only build a custom context for wss:// URLs; allow default behavior otherwise.
    if not OPENAI_WS_URL.lower().startswith("wss://"):
        return None

    if OPENAI_SSL_INSECURE:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        logger.warning("OPENAI_SSL_INSECURE=true: TLS verification disabled (unsafe).")
        return ctx

    cafile = OPENAI_SSL_CERT_FILE or (certifi.where() if certifi is not None else "")
    if cafile:
        return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


def _redact_secret(secret: str | None) -> str:
    if not secret:
        return "<missing>"
    if len(secret) <= 12:
        return secret[:4] + "..."
    return f"{secret[:8]}...{secret[-4:]}"


def _append_unique(values: list[str], value: str, limit: int = 8) -> None:
    cleaned = value.strip()
    if not cleaned:
        return
    lower_cleaned = cleaned.lower()
    if any(existing.lower() == lower_cleaned for existing in values):
        return
    values.append(cleaned)
    if len(values) > limit:
        del values[:-limit]


def _resolve_realtime_voice(value: str) -> str:
    voice = value.strip().lower()
    if voice in SUPPORTED_REALTIME_VOICES:
        return voice
    logger.warning("Unsupported realtime voice `%s`; falling back to `coral`.", value)
    return "coral"


def _resolve_communication_style(value: str) -> str:
    style = value.strip().lower()
    if style in SUPPORTED_COMMUNICATION_STYLES:
        return style
    logger.warning("Unsupported communication style `%s`; falling back to `warm_regional`.", value)
    return "warm_regional"


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_+-]{3,}", text.lower())}


def _clean_searchunify_highlight(value: str) -> str:
    return value.replace(SEARCHUNIFY_HIGHLIGHT_START, "").replace(SEARCHUNIFY_HIGHLIGHT_END, "")


def _knowledge_backend_kind() -> str:
    if KNOWLEDGE_BACKEND_KIND:
        return KNOWLEDGE_BACKEND_KIND
    if "searchunify.ai/search/searchResultByPost" in KNOWLEDGE_BACKEND_URL:
        return "searchunify_post"
    return "generic_get"


def _cache_get(key: str) -> dict[str, Any] | None:
    item = KNOWLEDGE_CACHE.get(key)
    if not item:
        return None
    expires_at, payload = item
    if expires_at < time.time():
        KNOWLEDGE_CACHE.pop(key, None)
        return None
    if LOG_KNOWLEDGE_DETAILS:
        logger.debug("Knowledge cache hit for key=%s", _safe_preview(key, limit=120))
    return payload


def _cache_set(key: str, payload: dict[str, Any]) -> None:
    KNOWLEDGE_CACHE[key] = (time.time() + max(KNOWLEDGE_CACHE_TTL_S, 1), payload)
    if LOG_KNOWLEDGE_DETAILS:
        logger.debug(
            "Knowledge cache set for key=%s ttl=%ss results=%s",
            _safe_preview(key, limit=120),
            KNOWLEDGE_CACHE_TTL_S,
            len(payload.get("results") or []),
        )


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
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
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


def _extract_preserved_domain_terms(text: str) -> list[str]:
    matches: list[tuple[int, str]] = []
    for phrase in QUALYS_DOMAIN_TERMS:
        for match in re.finditer(re.escape(phrase), text, flags=re.IGNORECASE):
            matches.append((match.start(), match.group(0).strip()))
    matches.sort(key=lambda item: item[0])
    return _dedupe_preserve_order([value for _, value in matches], limit=7)


def _clean_human_transcript(text: str) -> str:
    collapsed = " ".join(text.strip().split())
    if not collapsed:
        return ""

    cleaned = re.sub(
        r"\b(?:uh+|um+|umm+|hmm+|ah+|oh+|okay+|ok+|acha|actually|basically|literally|please|plz|just|kind of|sort of|you know|i mean)\b",
        " ",
        collapsed,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(?:hi|hello|hey|thanks|thank you|can you help|could you help|i need help|need help)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[^\w\s/-]", " ", cleaned)
    cleaned = re.sub(r"\b(\w+)(?:\s+\1\b)+", r"\1", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def _rewrite_support_query(query: str, product_area: str | None) -> str:
    cleaned = _clean_human_transcript(query)
    source_text = cleaned or " ".join(query.strip().split())
    if not source_text:
        return ""

    preserved_terms = _extract_preserved_domain_terms(source_text)
    error_tokens = _extract_error_tokens(query)
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "be",
        "for",
        "from",
        "get",
        "got",
        "have",
        "having",
        "help",
        "i",
        "im",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "our",
        "please",
        "the",
        "this",
        "to",
        "we",
        "with",
        "you",
        "your",
    }
    preserved_term_tokens = {
        token.lower()
        for term in preserved_terms
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_/-]*", term)
    }
    raw_tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_/-]*", source_text)
    keywords = [
        token
        for token in raw_tokens
        if (
            len(token) > 1
            and token.lower() not in stopwords
            and token.lower() not in SUPPORT_PRODUCT.lower().split()
            and token.lower() not in preserved_term_tokens
        )
    ]

    segments: list[str] = []
    if product_area:
        segments.append(product_area.strip().replace("_", " "))
    segments.extend(preserved_terms)
    segments.extend(error_tokens)
    segments.extend(keywords)
    compact = _dedupe_preserve_order([segment for segment in segments if segment], limit=7)
    if compact:
        return " ".join(compact)
    fallback_tokens = _dedupe_preserve_order(raw_tokens, limit=7)
    return " ".join(fallback_tokens)


def _build_knowledge_cache_key(query: str, product_area: str | None, backend_kind: str | None = None) -> tuple[str, str]:
    actual_backend_kind = backend_kind or _knowledge_backend_kind()
    rewritten_query = _rewrite_support_query(query, product_area)
    cache_key = f"{actual_backend_kind}|{_normalize_text(rewritten_query)}|{_normalize_text(product_area or '')}"
    return cache_key, rewritten_query


def _build_searchunify_payload(query: str) -> dict[str, Any]:
    search_uid = SEARCHUNIFY_SEARCH_UID or str(uuid.uuid4())
    return {
        "storeContext": False,
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
        "User-Agent": "SearchUnifyQualysVoice/1.0",
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
    highlight = hit.get("highlight")
    highlight_parts = _dedupe_preserve_order(_flatten_searchunify_highlights(highlight), limit=2)
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


def _normalize_generic_results(
    payload: Any,
    query: str,
    product_area: str | None,
) -> list[dict[str, Any]]:
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
                "gpt_context": str(item.get("gptContext") or item.get("gpt_context") or "").strip(),
                "confidence": round(min(0.99, 0.2 + (score / 12)), 2),
                "score": round(score, 2),
                "match_signals": signals,
            }
        )
    normalized.sort(key=lambda item: item.get("score", 0), reverse=True)
    return normalized[:KNOWLEDGE_RESULT_LIMIT]


def _normalize_searchunify_results(
    payload: dict[str, Any],
    query: str,
    product_area: str | None,
) -> list[dict[str, Any]]:
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
                "gpt_context": str(hit.get("gptContext") or hit.get("gpt_context") or "").strip(),
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


def _build_transcription_prompt() -> str:
    return (
        "Phone support call about Qualys. Expect terms like Qualys, VMDR, Cloud Agent, Asset Inventory, "
        "scanner appliance, authentication record, tags, detections, QID, ServiceNow, Jira, Splunk, SIEM, API, "
        "connector, remediation, and common Indian English support phrasing."
    )


COMMUNICATION_STYLE = _resolve_communication_style(COMMUNICATION_STYLE)
VOICE = _resolve_realtime_voice(VOICE)


@dataclass
class CallState:
    assistant_name: str
    support_product: str
    product_area: str = ""
    issue_summary: str = ""
    user_goal: str = ""
    caller_name: str = ""
    company: str = ""
    environment: str = ""
    error_text: str = ""
    last_user_transcript: str = ""
    last_assistant_transcript: str = ""
    user_turns: int = 0
    assistant_turns: int = 0
    confirmed_facts: list[str] = field(default_factory=list)
    tried_steps: list[str] = field(default_factory=list)

    def apply_user_transcript(self, transcript: str) -> None:
        self.last_user_transcript = transcript.strip()
        if not self.last_user_transcript:
            return

        self.user_turns += 1
        cleaned_summary = _clean_human_transcript(self.last_user_transcript)
        if cleaned_summary:
            self.issue_summary = cleaned_summary
        elif not self.issue_summary:
            self.issue_summary = self.last_user_transcript

    def remember_context(self, payload: dict[str, Any]) -> None:
        logger.info("CallState.remember_context - Remembering context from payload: %s", 
                   {k: _safe_preview(str(v), limit=50) for k, v in payload.items() if v})
        mappings = {
            "caller_name": "caller_name",
            "company": "company",
            "product_area": "product_area",
            "issue_summary": "issue_summary",
            "user_goal": "user_goal",
            "environment": "environment",
            "error_text": "error_text",
        }
        for key, attr in mappings.items():
            value = str(payload.get(key) or "").strip()
            if value:
                logger.debug("CallState.remember_context - Setting %s to '%s'", attr, _safe_preview(value, limit=100))
                setattr(self, attr, value)

        for field_name, target_list in (
            ("confirmed_fact", self.confirmed_facts),
            ("tried_step", self.tried_steps),
        ):
            value = str(payload.get(field_name) or "").strip()
            if value:
                logger.debug("CallState.remember_context - Adding to %s: '%s'", field_name, _safe_preview(value, limit=100))
                _append_unique(target_list, value)

        step_result = str(payload.get("step_result") or "").strip()
        if step_result and self.tried_steps:
            logger.debug("CallState.remember_context - Adding step result: '%s'", _safe_preview(step_result, limit=100))
            _append_unique(self.confirmed_facts, f"Step result: {step_result}")

    def as_tool_payload(self) -> dict[str, Any]:
        return {
            "assistant_name": self.assistant_name,
            "support_product": self.support_product,
            "product_area": self.product_area,
            "issue_summary": self.issue_summary,
            "user_goal": self.user_goal,
            "caller_name": self.caller_name,
            "company": self.company,
            "environment": self.environment,
            "error_text": self.error_text,
            "confirmed_facts": list(self.confirmed_facts),
            "tried_steps": list(self.tried_steps),
            "user_turns": self.user_turns,
            "assistant_turns": self.assistant_turns,
            "last_user_transcript": self.last_user_transcript,
            "last_assistant_transcript": self.last_assistant_transcript,
        }

    def summary_text(self) -> str:
        details = [f"Caller is speaking with {self.assistant_name} about {self.support_product}."]
        if self.product_area:
            details.append(f"Product area: {self.product_area}")
        if self.issue_summary:
            details.append(f"Working summary: {self.issue_summary}")
        if self.user_goal:
            details.append(f"User goal: {self.user_goal}")
        if self.confirmed_facts:
            details.append(f"Confirmed facts: {'; '.join(self.confirmed_facts[-3:])}")
        if self.tried_steps:
            details.append(f"Tried steps: {'; '.join(self.tried_steps[-3:])}")
        if self.error_text:
            details.append(f"Error text: {self.error_text}")
        return " ".join(details)


def _knowledge_backend_enabled() -> bool:
    return bool(KNOWLEDGE_BACKEND_URL)


def _demo_check(name: str, ok: bool, detail: str, severity: str = "error") -> dict[str, Any]:
    return {"name": name, "ok": ok, "severity": severity, "detail": detail}


def _build_demo_readiness_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    checks.append(
        _demo_check(
            "openai_api_key",
            bool(OPENAI_API_KEY),
            "OpenAI API key is configured." if OPENAI_API_KEY else "Set OPENAI_API_KEY in `.env`.",
        )
    )
    checks.append(
        _demo_check(
            "public_url",
            bool(PUBLIC_URL and PUBLIC_URL.startswith("https://")),
            f"Using PUBLIC_URL `{PUBLIC_URL}`." if PUBLIC_URL else "Set PUBLIC_URL to your reachable HTTPS URL.",
        )
    )
    checks.append(
        _demo_check(
            "voice",
            VOICE in SUPPORTED_REALTIME_VOICES,
            f"Realtime voice `{VOICE}` is active.",
        )
    )
    checks.append(
        _demo_check(
            "knowledge_backend",
            _knowledge_backend_enabled(),
            (
                f"Knowledge backend `{KNOWLEDGE_BACKEND_NAME}` is configured."
                if _knowledge_backend_enabled()
                else "Set KNOWLEDGE_BACKEND_URL to enable grounded support answers."
            ),
        )
    )

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
            checks.append(
                _demo_check(
                    "searchunify_origin",
                    bool(SEARCHUNIFY_ORIGIN),
                    "SearchUnify origin is configured."
                    if SEARCHUNIFY_ORIGIN
                    else "Set SEARCHUNIFY_ORIGIN for browser-like request parity.",
                    severity="warning",
                )
            )
            checks.append(
                _demo_check(
                    "searchunify_referer",
                    bool(SEARCHUNIFY_REFERER),
                    "SearchUnify referer is configured."
                    if SEARCHUNIFY_REFERER
                    else "Set SEARCHUNIFY_REFERER if your SearchUnify instance expects it.",
                    severity="warning",
                )
            )
            checks.append(
                _demo_check(
                    "searchunify_tls",
                    not KNOWLEDGE_BACKEND_SSL_INSECURE,
                    "Knowledge backend TLS verification is enabled."
                    if not KNOWLEDGE_BACKEND_SSL_INSECURE
                    else "KNOWLEDGE_BACKEND_SSL_INSECURE=true is enabled for demo reliability; replace with a CA bundle later.",
                    severity="warning",
                )
            )

    return checks


def _demo_ready(checks: list[dict[str, Any]]) -> bool:
    return all(check["ok"] for check in checks if check.get("severity") != "warning")


def _communication_style_instruction() -> str:
    if COMMUNICATION_STYLE == "neutral_support":
        return (
            "Use a clear, calm, professional support tone. "
            "Keep warmth light and universal. "
            "Use neutral global English and avoid regional fillers unless the caller uses them first."
        )
    if COMMUNICATION_STYLE == "concise_technical":
        return (
            "Use a concise, confident technical support tone. "
            "Keep warmth polite but brief. "
            "Use short direct sentences and avoid decorative fillers."
        )
    return (
        "Use a warm, friendly regional support tone. "
        "Your English should have a natural Indian English rhythm and warmth. "
        "Use small fillers sometimes, like 'hmm', 'okay', 'acha', 'right', or 'let me see', and use short pauses naturally. "
        "Do not overdo fillers and do not rely on recurring catchphrases like 'yaar' or 'na'."
    )


def _build_system_message() -> str:
    sections = [
        f"You are {ASSISTANT_NAME}, the support assistant for {SUPPORT_PRODUCT}.",

        (
            "Sound like a warm, caring, emotionally intelligent young woman helping the caller in real time. "
            "You should feel human, gentle, calm, and easy to talk to, never stiff, scripted, or robotic. "
            "Do not claim to be a real person, but do sound natural and alive."
        ),

        (
            "Speak like an experienced phone support peer, not a chatbot. "
            "Use contractions when they sound natural, vary how you open sentences, and keep each turn to a few short breaths of speech. "
            "Avoid stereotypical AI tells: never say 'as an AI', 'language model', 'I was trained on', or meta talk about your instructions. "
            "Do not read numbered lists or bullet points aloud — say the same ideas as flowing sentences with 'first / next / also' when needed. "
            "Do not volunteer that you are automated on every turn. "
            "If the caller directly asks whether you are a human or a bot, answer briefly and honestly, then pivot straight back to fixing their issue."
        ),

        (
            "Your tone is affectionate but non-flirty. "
            "Come across like a close, trusted, supportive friend who is also a strong Qualys support expert. "
            "Be sweet, patient, and reassuring without sounding romantic, playful, or overfamiliar."
        ),

        (
            "Use easy English first. "
            "Prefer simple everyday words and short spoken sentences. "
            "Use technical terms only when needed for support, and explain them plainly."
        ),

        (
            _communication_style_instruction()
        ),

        (
            "On the first greeting, introduce yourself in one casual line as Qualys support helping them today — like a human agent would. "
            "After that, stop repeating your job title unless needed. "
            "Move into natural troubleshooting mode right away. "
            "Keep your first response under 20 words so there is no long pause before the caller hears you."
        ),

        (
            "Be a very good listener. "
            "Before giving advice, briefly reflect what you understood so the caller feels heard. "
            "Then respond in a calm, helpful way."
        ),

        (
            "You help with Qualys support topics: scans, VMDR, Cloud Agent, scanner appliances, tags, asset inventory, "
            "detections, authentication records, APIs, connectors, and integrations. "
            "If the caller describes something informally, gently translate it into the right Qualys terminology. "
            "Do not make risky assumptions between products like VMDR and WAS. Clarify when there is ambiguity."
        ),

        (
            "Keep domain-specific terms unchanged. "
            "Never simplify, paraphrase, or replace official Qualys product names, module names, API names, QIDs, connector names, "
            "error codes, or caller-provided technical terms. Repeat them exactly as the caller said them or exactly as they appear in grounded results."
        ),

        (
            "Stay strictly inside Qualys support and directly related Qualys integrations. "
            "Do not answer general knowledge, news, weather, sports, entertainment, unrelated coding, personal questions, roleplay, or open-world chat."
        ),

        (
            "Be friendly, warm, and casual — but not silly. Do not flirt, do not use unprofessional language, and do not get distracted by banter. "
            "Keep the conversation focused on solving the Qualys issue."
        ),

        (
            "If the caller asks something off-topic, refuse briefly and naturally, then bring it back — "
            "for example: 'I can help with Qualys support. Tell me what is happening on your side.'"
        ),

        (
            "Explain hard things simply — no textbook language and no stiff formality. "
            "Give a brief explanation, then the next step. "
            "Usually give one step at a time, but it is fine to ask two closely related questions together when that helps move faster."
        ),

        (
            "Use adaptive support flow. Start simple and practical. Go more technical if needed. "
            "Guide one action at a time, confirm what changed, and update your hypothesis when a step fails — "
            "like 'okay so that did not work... which means it is probably not the scanner side. Let us look at the connector config now'."
        ),

        (
            "Collect context naturally while talking: caller name, company, product area, environment, integration target, "
            "error text, what was already tried, and the caller's goal. Reuse those details naturally later in the call."
        ),

        (
            "Use confirmation loops naturally. Check what the caller already tried, suggest the next likely step, "
            "and if that does not work, explain the updated theory simply. "
            "Keep it conversational, warm, and clear."
        ),

        (
            "If the caller sounds frustrated, upset, or confused, comfort and validate them first in a brief human way — "
            "for example, 'I understand... this is frustrating. We will go step by step.' — "
            "then give only one short next action."
        ),

        (
            "For unclear audio, background noise, or mixed phrasing, stay calm. "
            "Say what you think you heard, ask for a quick confirmation, and recover naturally — "
            "like 'Sorry... I think I missed that. You said the scan is failing on the authentication side, correct?'"
        ),

        (
            "Handle common Indian support phrasing smoothly. "
            "Reply mostly in clear English with natural Indian English rhythm, warmth, and melody."
        ),

        (
            "When you answer, never narrate your internal search or verification steps. "
            "Just answer naturally, like you already understand the issue."
        ),

        (
            "If SearchUnify or another support knowledge source is available, use it silently in the background on every real support turn. "
            "Do not tell the caller you are searching or checking a source."
        ),

        (
            "Convert noisy caller wording into a clean issue summary in your head. "
            "Reduce filler words, hesitation, and repeated words before reasoning about the issue."
        ),

        (
            "Use grounded support guidance silently. "
            "Answer directly in plain human language. "
            "If the guidance is weak or conflicting, give one safe first check and ask one short clarifying question. "
            "If the guidance is strong but long, give only the first one or two steps and pause for confirmation."
        ),

        (
            "If the caller interrupts, stop immediately and respond to the new words right away. "
            "Do not finish your previous sentence. "
            "Do not over-acknowledge the interruption. "
            "Only return to the earlier point later if it is still helpful. "
            "On interruption, drop the old line of thought and move with the new information. "
            "Give zero indication you are using a knowledge base. Do not mention SearchUnify or any other tool by name."
        ),

        (
            "If a tool is unavailable, stay within Qualys support scope. Do not switch into general knowledge mode."
        ),

        (
            "Use the call memory tools throughout the conversation. Record important caller facts, tried steps, and your current Qualys issue framing "
            "with remember_call_context. If you need a refresh before suggesting the next step, use get_call_context."
        ),
    ]

    if CUSTOM_SYSTEM_MESSAGE:
        sections.append(f"Additional business instructions: {CUSTOM_SYSTEM_MESSAGE}")

    return "\n\n".join(sections)

SYSTEM_MESSAGE = _build_system_message()


def _build_twilio_stream_url(request: Request) -> str:
    base = (PUBLIC_URL or "").strip()
    if base:
        base = base.rstrip("/")
    else:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
        prefix = (request.headers.get("x-forwarded-prefix") or "").strip()
        prefix = f"/{prefix.strip('/')}" if prefix.strip("/") else ""
        base = f"{proto}://{host}{prefix}".rstrip("/")

    if base.startswith("https://"):
        ws_base = "wss://" + base.removeprefix("https://")
    elif base.startswith("http://"):
        ws_base = "ws://" + base.removeprefix("http://")
    elif base.startswith(("wss://", "ws://")):
        ws_base = base
    else:
        ws_base = "wss://" + base

    return f"{ws_base.rstrip('/')}/media-stream"


def _build_initial_greeting_line() -> str:
    return (
        f"Hi, I am {ASSISTANT_NAME} from {SUPPORT_PRODUCT} support. "
        "Tell me what is happening, and I will help you."
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
                    "product_area": {"type": "string"},
                    "issue_summary": {"type": "string"},
                    "user_goal": {"type": "string"},
                    "caller_name": {"type": "string"},
                    "company": {"type": "string"},
                    "environment": {"type": "string"},
                    "error_text": {"type": "string"},
                    "confirmed_fact": {"type": "string"},
                    "tried_step": {"type": "string"},
                    "step_result": {"type": "string"},
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
    if not _knowledge_backend_enabled():
        return tools
    tools.append(
        {
            "type": "function",
            "name": "search_qualys_support_knowledge",
            "description": (
                "Search SearchUnify or another configured support knowledge source for Qualys-specific troubleshooting steps, "
                "terminology, error explanations, APIs, connector guidance, or integration help. "
                "Use a compact cleaned keyword query and rely on the result silently in the background."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A compact cleaned support query, ideally 6 to 7 keywords, with the important Qualys terms preserved.",
                    },
                    "product_area": {
                        "type": "string",
                        "description": "Optional Qualys area such as VMDR, Cloud Agent, scanners, API, tags, auth records, or integrations.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        }
    )
    return tools


def _estimate_pcmu_audio_ms(base64_payload: str) -> int:
    try:
        audio_bytes = base64.b64decode(base64_payload)
    except Exception:  # noqa: BLE001
        return 0
    return int(round((len(audio_bytes) / 8000) * 1000))


def _best_product_area_hint(call_state: CallState) -> str | None:
    product_area = (call_state.product_area or "").strip()
    if product_area:
        return product_area.replace("_", " ")
    return None


def _build_direct_response_hint(call_state: CallState) -> str:
    product_area = _best_product_area_hint(call_state) or "Qualys support"
    issue_text = call_state.issue_summary or call_state.last_user_transcript or "the caller's issue"
    return (
        "For your next response, answer directly in simple human English. "
        f"Keep the answer grounded in {product_area}. "
        f"Caller issue: {issue_text}. "
        "Do not describe your internal process. "
        "Keep Qualys product names, API names, QIDs, error text, and other technical terms exactly as given. "
        "Give a short explanation and the best next step."
    )


def _build_safe_preliminary_check(call_state: CallState) -> str:
    return "ask them to confirm the exact error text or the last screen where the workflow fails"


def _build_knowledge_grounding_hint(result: dict[str, Any], call_state: CallState) -> str:
    backend = str(result.get("backend") or KNOWLEDGE_BACKEND_NAME).strip()
    query = str(result.get("rewritten_query") or result.get("query") or "").strip()
    response_mode = str(result.get("response_mode") or "clarify_first").strip()
    error = str(result.get("error") or "").strip()
    note = str(result.get("note") or "").strip()
    results = result.get("results") or []
    safe_check = _build_safe_preliminary_check(call_state)

    if error:
        return (
            f"Knowledge grounding update: live lookup to {backend} failed with `{error}`. "
            "Do not mention the lookup or any source. "
            f"Answer directly in simple English. If you are not sure, give one safe preliminary check first: {safe_check}. "
            "Then ask one short clarifying question. Do not invent product-specific steps."
        )

    if not results:
        reason = note or "No matching support results were returned."
        return (
            f"Knowledge grounding update: {backend} returned no strong results for `{query}`. {reason} "
            "Do not mention the lookup or any source. "
            f"Answer directly in simple English. Give one safe preliminary check first: {safe_check}. "
            "Then ask one short clarifying question before giving more detailed troubleshooting steps."
        )

    best_result = result.get("best_result") or {}
    title = str(best_result.get("title") or "Support result").strip()
    source_name = str(best_result.get("source_name") or backend).strip()
    snippet = str(best_result.get("snippet") or "").strip()
    url = str(best_result.get("url") or best_result.get("client_url") or "").strip()
    snippet = snippet[:700]

    guidance = [
        f"Knowledge grounding update from {backend} for your next answer.",
        "Use the retrieved guidance silently in the background.",
        "Do not say you searched, checked a source, found an article, or used the knowledge base.",
        "Answer directly in simple human language first.",
        "Keep Qualys product names, API names, QIDs, connector names, and error text exactly as written.",
        "Do not mention the article title or source name out loud unless the caller explicitly asks.",
        f"Use the retrieved results as the source of truth for product-specific facts and next steps. Query used: `{query}`.",
    ]
    if response_mode == "answer_directly":
        guidance.append("The retrieval confidence is strong. Give only the first one or two steps, then pause for confirmation.")
    elif response_mode == "answer_and_confirm":
        guidance.append("Give a brief explanation, then only the first one or two steps, then confirm one key detail with the caller.")
    else:
        guidance.append(f"Give one safe preliminary check first: {safe_check}. Then ask one targeted clarifying question before giving detailed steps.")

    if result.get("conflict"):
        conflict_summary = str(result.get("conflict_summary") or "").strip()
        if conflict_summary:
            guidance.append(f"{conflict_summary} Do not pick a path until you clarify which scenario fits.")

    guidance.append(f"Top result title: {title}.")
    guidance.append(f"Top result source: {source_name}.")
    if snippet:
        guidance.append(f"Top result evidence: {snippet}")
    if url:
        guidance.append(f"Top result URL: {url}")
    return " ".join(guidance)


def _extract_event_item_id(event: dict[str, Any]) -> str:
    item_id = event.get("item_id")
    if isinstance(item_id, str) and item_id.strip():
        return item_id.strip()

    item = event.get("item")
    if isinstance(item, dict):
        nested_id = item.get("id")
        if isinstance(nested_id, str) and nested_id.strip():
            return nested_id.strip()
    return ""


def _extract_transcript_text(event: dict[str, Any]) -> str:
    for key in ("transcript", "text"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    item = event.get("item")
    if isinstance(item, dict):
        for content in item.get("content") or []:
            if isinstance(content, dict):
                for key in ("transcript", "text"):
                    value = content.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
    return ""


def _extract_function_calls_from_event(event: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    item = event.get("item")
    if isinstance(item, dict) and item.get("type") == "function_call":
        candidates.append(item)
    response = event.get("response")
    if isinstance(response, dict):
        for output_item in response.get("output") or []:
            if isinstance(output_item, dict) and output_item.get("type") == "function_call":
                candidates.append(output_item)
    return candidates


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
        return [{"title": "Raw backend response", "snippet": str(payload)}]

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


def _knowledge_lookup_sync(query: str, product_area: str | None) -> dict[str, Any]:
    logger.info("_knowledge_lookup_sync - Starting knowledge lookup: query='%s', product_area='%s'", 
               _safe_preview(query, limit=100), product_area or "none")
    if not KNOWLEDGE_BACKEND_URL:
        logger.info("_knowledge_lookup_sync - Knowledge backend not configured")
        return {
            "backend": KNOWLEDGE_BACKEND_NAME,
            "query": query,
            "results": [],
            "note": "Knowledge backend is not configured.",
        }

    backend_kind = _knowledge_backend_kind()
    cache_key, rewritten_query = _build_knowledge_cache_key(query, product_area, backend_kind)
    logger.info("_knowledge_lookup_sync - Query rewritten: '%s' -> '%s', backend_kind='%s'", 
               _safe_preview(query, limit=100), _safe_preview(rewritten_query, limit=100), backend_kind)
    if LOG_KNOWLEDGE_DETAILS:
        logger.debug(
            "Knowledge lookup start backend=%s kind=%s query=%s rewritten=%s product_area=%s",
            KNOWLEDGE_BACKEND_NAME,
            backend_kind,
            _safe_preview(query),
            _safe_preview(rewritten_query),
            product_area or "",
        )
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("_knowledge_lookup_sync - Cache hit for key='%s'", _safe_preview(cache_key, limit=150))
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
    if LOG_KNOWLEDGE_DETAILS:
        logger.debug(
            "Knowledge backend response content_type=%s body_preview=%s",
            content_type,
            _safe_preview(body, limit=300),
        )
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

    grounding = _build_grounding_summary(normalized_results)
    result = {
        "backend": KNOWLEDGE_BACKEND_NAME,
        "backend_kind": backend_kind,
        "query": query,
        "rewritten_query": rewritten_query,
        "product_area": product_area or "",
        "content_type": content_type,
        "results": normalized_results,
        "note": note,
        **grounding,
    }
    top_gpt_contexts = [
        _safe_preview(str(item.get("gpt_context") or item.get("gptContext") or ""), limit=100)
        for item in normalized_results[:3]
    ]
    logger.info(
        "_knowledge_lookup_sync - Knowledge results prepared: count=%s best_confidence=%s response_mode=%s conflict=%s top_titles=%s top_gpt_contexts=%s",
        len(normalized_results),
        result.get("best_confidence"),
        result.get("response_mode"),
        result.get("conflict"),
        [
            _safe_preview(str(item.get("title") or ""), limit=80)
            for item in normalized_results[:3]
        ],
        top_gpt_contexts,
    )
    if LOG_KNOWLEDGE_DETAILS:
        logger.debug(
            "Knowledge lookup normalized results=%s best_confidence=%s response_mode=%s conflict=%s best_title=%s results=%s top_gpt_contexts=%s",
            len(normalized_results),
            result.get("best_confidence"),
            result.get("response_mode"),
            result.get("conflict"),
            _safe_preview((result.get("best_result") or {}).get("title") or ""),
            _safe_preview(normalized_results, limit=700),
            top_gpt_contexts,
        )
    _cache_set(cache_key, result)
    return result


async def _knowledge_lookup(query: str, product_area: str | None, call_logger: logging.Logger) -> dict[str, Any]:
    logger.info("_knowledge_lookup - Starting async knowledge lookup: query='%s', product_area='%s'", 
               _safe_preview(query, limit=100), product_area or "none")
    try:
        result = await asyncio.to_thread(_knowledge_lookup_sync, query, product_area)
        best_result = result.get("best_result") or {}
        logger.info("_knowledge_lookup - Lookup completed: backend='%s', result_count=%s, best_confidence=%s, response_mode='%s', conflict=%s", 
                   result.get("backend"), len(result.get("results") or []), result.get("best_confidence"), result.get("response_mode"), result.get("conflict"))
        call_logger.info(
            "Knowledge lookup complete kind=%s best_source=%s confidence=%s conflict=%s",
            result.get("backend_kind") or _knowledge_backend_kind(),
            best_result.get("source_name") or KNOWLEDGE_BACKEND_NAME,
            result.get("best_confidence"),
            result.get("conflict"),
        )
        return result
    except urllib_error.HTTPError as exc:
        logger.warning("_knowledge_lookup - HTTP error during lookup: %s", exc)
        call_logger.warning("Knowledge lookup HTTP error: %s", exc)
        return {"backend": KNOWLEDGE_BACKEND_NAME, "query": query, "results": [], "error": f"HTTP {exc.code}"}
    except urllib_error.URLError as exc:
        logger.warning("_knowledge_lookup - URL error during lookup: %s", exc)
        call_logger.warning("Knowledge lookup URL error: %s", exc)
        return {"backend": KNOWLEDGE_BACKEND_NAME, "query": query, "results": [], "error": str(exc.reason)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("_knowledge_lookup - Unexpected error during lookup")
        call_logger.exception("Knowledge lookup failed")
        return {"backend": KNOWLEDGE_BACKEND_NAME, "query": query, "results": [], "error": str(exc)}


async def _openai_connect():
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY. Put it in `.env` (see README).")

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    if OPENAI_PROJECT:
        headers["OpenAI-Project"] = OPENAI_PROJECT
    if OPENAI_ORGANIZATION:
        headers["OpenAI-Organization"] = OPENAI_ORGANIZATION
    if OPENAI_BETA_HEADER:
        headers["OpenAI-Beta"] = OPENAI_BETA_HEADER
    connect_kwargs = _ws_connect_kwargs(headers)
    logger.debug(
        "Opening OpenAI realtime connection url=%s model=%s project=%s organization=%s ssl_custom=%s",
        OPENAI_WS_URL,
        OPENAI_MODEL,
        bool(OPENAI_PROJECT),
        bool(OPENAI_ORGANIZATION),
        "ssl" in connect_kwargs,
    )

    last_exc: Exception | None = None
    ssl_hint_logged = False
    for attempt in range(OPENAI_CONNECT_RETRIES + 1):
        try:
            return await websockets.connect(OPENAI_WS_URL, **connect_kwargs)
        except Exception as exc:
            last_exc = exc
            if isinstance(exc, ssl.SSLCertVerificationError) and not ssl_hint_logged:
                ssl_hint_logged = True
                logger.error(
                    "TLS verification failed. If you're on macOS with python.org Python, run the bundled "
                    "`Install Certificates.command`, or set `OPENAI_SSL_CERT_FILE` to your CA bundle "
                    "(certifi is supported)."
                )
            if "invalid_api_key" in str(exc):
                logger.error(
                    "OpenAI rejected the API key %s. If this is a project-scoped key, verify it is active in "
                    "the OpenAI dashboard and that any required `OPENAI_PROJECT` / `OPENAI_ORGANIZATION` env vars "
                    "match the owning project/org.",
                    _redact_secret(OPENAI_API_KEY),
                )
            if attempt >= OPENAI_CONNECT_RETRIES:
                break
            backoff_s = min(0.5 * (2**attempt), 5.0)
            logger.warning(
                "OpenAI WS connect failed (attempt %s/%s): %s; retrying in %.1fs",
                attempt + 1,
                OPENAI_CONNECT_RETRIES + 1,
                exc,
                backoff_s,
            )
            await asyncio.sleep(backoff_s)
    raise last_exc or RuntimeError("OpenAI WS connect failed")


async def _send_session_update(openai_ws) -> None:
    tools = _build_realtime_tools()
    session_update = {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "instructions": SYSTEM_MESSAGE,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcmu"},
                    "transcription": {
                        "model": TRANSCRIPTION_MODEL,
                        "language": TRANSCRIPTION_LANGUAGE,
                        "prompt": _build_transcription_prompt(),
                    },
                    "noise_reduction": {"type": TRANSCRIPTION_NOISE_REDUCTION},
                    "turn_detection": {
                        "type": "server_vad",
                        "create_response": False,
                        "interrupt_response": True,
                        "threshold": SERVER_VAD_THRESHOLD,
                        "prefix_padding_ms": SERVER_VAD_PREFIX_PADDING_MS,
                        "silence_duration_ms": SERVER_VAD_SILENCE_DURATION_MS,
                    },
                },
                "output": {
                    "format": {"type": "audio/pcmu"},
                    "voice": VOICE,
                },
            },
        },
    }
    if tools:
        session_update["session"]["tools"] = tools
        session_update["session"]["tool_choice"] = "auto"
    logger.debug("Sending session.update")
    if LOG_TOOL_PAYLOADS:
        logger.debug(
            "Session config voice=%s transcription_model=%s noise_reduction=%s tools=%s",
            VOICE,
            TRANSCRIPTION_MODEL,
            TRANSCRIPTION_NOISE_REDUCTION,
            [tool.get("name") for tool in tools],
        )
    try:
        await openai_ws.send(_json_dumps(session_update))
    except websockets.exceptions.ConnectionClosed as exc:
        msg = str(exc)
        if "invalid_api_key" in msg:
            raise RuntimeError(
                "OpenAI rejected `OPENAI_API_KEY` (invalid_api_key). Check that the key is active, copied fully, "
                "and, if needed, that `OPENAI_PROJECT` / `OPENAI_ORGANIZATION` are set correctly."
            ) from exc
        raise


async def _send_initial_greeting(openai_ws) -> None:
    greeting_line = _build_initial_greeting_line()
    if LOG_CALL_TRANSCRIPTS:
        logger.debug("Initial greeting line=%s", _safe_preview(greeting_line))
    initial_conversation_item = {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "Please greet the caller exactly once at the start of the call. "
                        f"Say: '{greeting_line}' "
                        "Then pause and listen for the caller instead of continuing with a long monologue."
                    ),
                }
            ],
        },
    }
    await openai_ws.send(_json_dumps(initial_conversation_item))
    await openai_ws.send(_json_dumps({"type": "response.create"}))


@app.get("/", response_class=JSONResponse)
async def index_page():
    logger.info("GET / - Index page requested")
    response = JSONResponse(content={"message": "Hello! This is the AI Phone Agent with OpenAI Realtime API. Please set up your Twilio webhook to point to /incoming-call and start a call to see it in action."})
    logger.info("GET / - Response sent: %s", response.body.decode() if hasattr(response, 'body') else "JSON response")
    return response



@app.get("/health", response_class=JSONResponse)
async def health():
    logger.info("GET /health - Health check requested")
    response_data = {
        "ok": True,
        "model": OPENAI_MODEL,
        "voice": VOICE,
        "communication_style": COMMUNICATION_STYLE,
        "assistant_name": ASSISTANT_NAME,
        "support_product": SUPPORT_PRODUCT,
        "transcription_model": TRANSCRIPTION_MODEL,
        "knowledge_backend_enabled": _knowledge_backend_enabled(),
        "knowledge_backend_name": KNOWLEDGE_BACKEND_NAME,
        "knowledge_backend_kind": _knowledge_backend_kind() if _knowledge_backend_enabled() else "",
        "knowledge_cache_ttl_s": KNOWLEDGE_CACHE_TTL_S,
        "demo_ready": _demo_ready(_build_demo_readiness_checks()),
        "debug_flags": {
            "log_openai_events": LOG_OPENAI_EVENTS,
            "show_timing_math": SHOW_TIMING_MATH,
            "log_call_transcripts": LOG_CALL_TRANSCRIPTS,
            "log_tool_payloads": LOG_TOOL_PAYLOADS,
            "log_twilio_media_events": LOG_TWILIO_MEDIA_EVENTS,
            "log_knowledge_details": LOG_KNOWLEDGE_DETAILS,
        },
    }
    logger.info("GET /health - Response: ok=%s, model=%s, voice=%s, knowledge_enabled=%s", 
                response_data["ok"], response_data["model"], response_data["voice"], response_data["knowledge_backend_enabled"])
    return response_data


@app.get("/demo-readiness", response_class=JSONResponse)
async def demo_readiness(probe_search: bool = False, query: str = "", product_area: str = ""):
    logger.info("GET /demo-readiness - Demo readiness check requested with probe_search=%s, query='%s', product_area='%s'", 
                probe_search, query, product_area)
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
        logger.info("GET /demo-readiness - Performing knowledge probe with query='%s', product_area='%s'", 
                    search_query, search_product_area)
        probe_result = await _knowledge_lookup(search_query, search_product_area, logger.getChild("demo_probe"))
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
        logger.info("GET /demo-readiness - Knowledge probe completed: result_count=%s, best_confidence=%s, response_mode=%s, conflict=%s", 
                    payload["knowledge_probe"]["result_count"], 
                    payload["knowledge_probe"]["best_confidence"], 
                    payload["knowledge_probe"]["response_mode"], 
                    payload["knowledge_probe"]["conflict"])
    logger.info("GET /demo-readiness - Response: ready=%s, checks_count=%s, has_probe=%s", 
                payload["ready"], len(payload["checks"]), "knowledge_probe" in payload)
    return payload


@app.get("/demo-search", response_class=JSONResponse)
async def demo_search(query: str = "", product_area: str = ""):
    search_query = query.strip() or DEMO_LOOKUP_QUERY
    search_product_area = product_area.strip() or DEMO_LOOKUP_PRODUCT_AREA
    logger.info("GET /demo-search - Demo search requested with query='%s', product_area='%s'", 
                search_query, search_product_area)
    result = await _knowledge_lookup(search_query, search_product_area, logger.getChild("demo_search"))
    logger.info("GET /demo-search - Search completed: result_count=%s, best_confidence=%s, response_mode=%s, conflict=%s, error=%s", 
                len(result.get("results") or []), 
                result.get("best_confidence"), 
                result.get("response_mode"), 
                result.get("conflict"), 
                result.get("error"))
    return result


@app.api_route("/incoming-call", methods=["GET", "POST"])
@app.api_route("/invoke/incoming-call", methods=["GET", "POST"])
@app.api_route("/socket/invoke/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Return TwiML instructing Twilio to start a Media Stream to `/media-stream`."""
    logger.info("Incoming call webhook - Method: %s, URL: %s, Headers: %s", 
                request.method, str(request.url), dict(request.headers))
    stream_url = _build_twilio_stream_url(request)
    logger.info("Incoming call webhook - Streaming to %s", stream_url)
    if stream_url.startswith("ws://"):
        logger.warning("Twilio Media Streams typically requires `wss://` (TLS). Check `PUBLIC_URL` / proxy config.")
    if "localhost" in stream_url or "127.0.0.1" in stream_url:
        logger.warning("Twilio cannot reach localhost. Set `PUBLIC_URL` to your ngrok/production HTTPS URL.")

    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=stream_url)
    response.append(connect)
    twiml_content = str(response)
    logger.info("Incoming call webhook - TwiML response generated: %s", twiml_content)
    return HTMLResponse(content=twiml_content, media_type="application/xml")


@app.websocket("/media-stream")
@app.websocket("/invoke/media-stream")
@app.websocket("/socket/invoke/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Bridge Twilio Media Streams <-> OpenAI Realtime API."""
    logger.info("WebSocket connection attempt to /media-stream from %s", websocket.client.host if websocket.client else "unknown")
    await websocket.accept()
    call_logger = logger.getChild(secrets.token_hex(4))
    call_logger.info("Twilio WS connected - Call ID: %s", call_logger.name)
    if LOG_TWILIO_MEDIA_EVENTS or LOG_TOOL_PAYLOADS or LOG_CALL_TRANSCRIPTS:
        call_logger.debug(
            "Call debug flags transcripts=%s tools=%s twilio_media=%s openai_events=%s knowledge=%s",
            LOG_CALL_TRANSCRIPTS,
            LOG_TOOL_PAYLOADS,
            LOG_TWILIO_MEDIA_EVENTS,
            LOG_OPENAI_EVENTS,
            LOG_KNOWLEDGE_DETAILS,
        )

    openai_ws = None
    try:
        openai_ws = await _openai_connect()
        call_logger.info("OpenAI WS connected (%s) - Session update and initial greeting will be sent", OPENAI_MODEL)
        await _send_session_update(openai_ws)
        call_logger.info("Session update sent to OpenAI - Tools configured: %s, Voice: %s, Model: %s", 
                        len(_build_realtime_tools()), VOICE, OPENAI_MODEL)

        stream_sid: str | None = None
        latest_media_timestamp_ms = 0
        last_assistant_item_id: str | None = None
        response_start_timestamp_twilio_ms: int | None = None
        assistant_audio_sent_ms = 0
        mark_queue: deque[str] = deque()
        twilio_started = asyncio.Event()
        pending_interrupt_task: asyncio.Task[None] | None = None
        handled_call_ids: set[str] = set()
        last_user_input_signature = ""
        last_user_input_signature_at = 0.0
        pending_user_turn_task: asyncio.Task[None] | None = None
        knowledge_flow_active = False
        knowledge_prefetch_query = ""
        knowledge_prefetch_product_area = ""
        knowledge_prefetch_cache_key = ""
        knowledge_prefetch_task: asyncio.Task[dict[str, Any]] | None = None
        knowledge_prefetch_result: dict[str, Any] | None = None
        active_response_id: str | None = None
        interruption_pending_ack = False
        response_resume_not_before = 0.0
        response_done_event = asyncio.Event()
        response_done_event.set()
        call_state = CallState(assistant_name=ASSISTANT_NAME, support_product=SUPPORT_PRODUCT)

        async def send_mark() -> None:
            if not stream_sid:
                return
            await websocket.send_text(
                f'{{"event":"mark","streamSid":"{stream_sid}","mark":{{"name":"responsePart"}}}}'
            )
            mark_queue.append("responsePart")

        async def handle_speech_started_event() -> None:
            nonlocal assistant_audio_sent_ms, response_start_timestamp_twilio_ms, last_assistant_item_id, interruption_pending_ack, response_resume_not_before
            if not (mark_queue and response_start_timestamp_twilio_ms is not None and last_assistant_item_id):
                return

            interruption_pending_ack = True
            response_resume_not_before = max(
                response_resume_not_before,
                time.monotonic() + (max(INTERRUPT_RESPONSE_COOLDOWN_MS, 0) / 1000),
            )
            cancel_knowledge_prefetch()
            if active_response_id:
                await openai_ws.send(
                    _json_dumps(
                        {
                            "type": "response.cancel",
                            "response_id": active_response_id,
                        }
                    )
                )

            elapsed_ms = max(0, latest_media_timestamp_ms - response_start_timestamp_twilio_ms)
            truncate_at_ms = min(elapsed_ms, max(assistant_audio_sent_ms, 0))
            if truncate_at_ms <= 0:
                return
            if SHOW_TIMING_MATH:
                call_logger.debug(
                    "Truncation math: %sms - %sms = %sms; clamped to %sms of assistant audio",
                    latest_media_timestamp_ms,
                    response_start_timestamp_twilio_ms,
                    elapsed_ms,
                    truncate_at_ms,
                )

            truncate_event = {
                "type": "conversation.item.truncate",
                "item_id": last_assistant_item_id,
                "content_index": 0,
                "audio_end_ms": truncate_at_ms,
            }
            await openai_ws.send(_json_dumps(truncate_event))

            await websocket.send_text(f'{{"event":"clear","streamSid":"{stream_sid}"}}')
            mark_queue.clear()
            assistant_audio_sent_ms = 0
            last_assistant_item_id = None
            response_start_timestamp_twilio_ms = None

        def cancel_pending_interrupt() -> None:
            nonlocal pending_interrupt_task
            if pending_interrupt_task is not None and not pending_interrupt_task.done():
                pending_interrupt_task.cancel()
            pending_interrupt_task = None

        def cancel_pending_user_turn() -> None:
            nonlocal pending_user_turn_task
            if pending_user_turn_task is not None and not pending_user_turn_task.done():
                pending_user_turn_task.cancel()
            pending_user_turn_task = None

        def cancel_knowledge_prefetch() -> None:
            nonlocal knowledge_prefetch_task, knowledge_prefetch_result, knowledge_prefetch_query, knowledge_prefetch_product_area, knowledge_prefetch_cache_key, knowledge_flow_active
            if knowledge_prefetch_task is not None and not knowledge_prefetch_task.done():
                knowledge_prefetch_task.cancel()
            knowledge_prefetch_task = None
            knowledge_prefetch_result = None
            knowledge_prefetch_query = ""
            knowledge_prefetch_product_area = ""
            knowledge_prefetch_cache_key = ""
            knowledge_flow_active = False

        async def schedule_interrupt() -> None:
            nonlocal pending_interrupt_task
            cancel_pending_interrupt()

            async def _delayed_interrupt() -> None:
                nonlocal pending_interrupt_task
                try:
                    await asyncio.sleep(max(INTERRUPT_MIN_SPEECH_MS, 0) / 1000)
                    await handle_speech_started_event()
                except asyncio.CancelledError:
                    return
                finally:
                    if pending_interrupt_task is asyncio.current_task():
                        pending_interrupt_task = None

            pending_interrupt_task = asyncio.create_task(_delayed_interrupt(), name="interrupt-debounce")

        async def send_system_message(text: str, label: str) -> None:
            logger.info("send_system_message - Sending system message: label='%s', text_length=%s", label, len(text))
            if LOG_TOOL_PAYLOADS or (label == "knowledge grounding" and LOG_KNOWLEDGE_DETAILS):
                logger.debug("send_system_message - Content: %s", _safe_preview(text, limit=700))
                call_logger.debug("Sending %s=%s", label, _safe_preview(text, limit=700))
            await openai_ws.send(
                _json_dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "system",
                            "content": [{"type": "input_text", "text": text}],
                        },
                    }
                )
            )
            logger.debug("send_system_message - System message sent to OpenAI")

        async def maybe_send_interruption_ack_hint() -> None:
            nonlocal interruption_pending_ack
            if not interruption_pending_ack:
                return

            interrupted_point = _safe_preview(call_state.last_assistant_transcript, limit=240)
            hint = (
                "The caller interrupted your previous answer. Stop your old line of thought and respond to the caller's newest words first. "
                "Do not finish your previous sentence. Return to your earlier point later only if it still helps."
            )
            if interrupted_point:
                hint += f" Your interrupted point was: {interrupted_point}."
            await send_system_message(hint, "interruption hint")
            interruption_pending_ack = False

        async def request_assistant_response(reason: str, wait_for_previous: bool = True) -> None:
            nonlocal active_response_id
            logger.info("request_assistant_response - Requesting assistant response: reason='%s', wait_for_previous=%s, active_response_id='%s'", 
                       reason, wait_for_previous, active_response_id or "none")
            if wait_for_previous:
                wait_timeout_s = 3.0 if time.monotonic() < response_resume_not_before else 8.0
                logger.debug("request_assistant_response - Waiting for previous response completion (timeout=%ss)", wait_timeout_s)
                try:
                    await asyncio.wait_for(response_done_event.wait(), timeout=wait_timeout_s)
                except TimeoutError:
                    if active_response_id:
                        logger.warning("request_assistant_response - Timed out waiting for active response=%s before phase=%s; cancelling and retrying wait", 
                                      active_response_id, reason)
                        call_logger.warning(
                            "Timed out waiting for active response=%s before phase=%s; cancelling and retrying wait",
                            active_response_id,
                            reason,
                        )
                        await openai_ws.send(
                            _json_dumps(
                                {
                                    "type": "response.cancel",
                                    "response_id": active_response_id,
                                }
                            )
                        )
                        await asyncio.wait_for(response_done_event.wait(), timeout=2.0)
                    else:
                        raise
            remaining_cooldown_s = response_resume_not_before - time.monotonic()
            if remaining_cooldown_s > 0:
                logger.debug("request_assistant_response - Waiting for interruption cooldown: %ss", remaining_cooldown_s)
                await asyncio.sleep(remaining_cooldown_s)
            response_done_event.clear()
            if reason in {"knowledge-bridge", "knowledge-answer", "direct-answer"}:
                logger.info("request_assistant_response - Starting new response phase: %s", reason)
                call_logger.info("Assistant response started phase=%s", reason)
            if LOG_TOOL_PAYLOADS:
                call_logger.debug("Creating assistant response reason=%s", reason)
            try:
                logger.debug("request_assistant_response - Sending response.create to OpenAI")
                await openai_ws.send(_json_dumps({"type": "response.create"}))
                logger.info("request_assistant_response - Response.create sent successfully")
            except Exception:
                logger.exception("request_assistant_response - Failed to send response.create")
                response_done_event.set()
                raise

        async def get_server_managed_knowledge_result(query: str, product_area: str | None) -> dict[str, Any]:
            nonlocal knowledge_prefetch_result
            search_cache_key, _ = _build_knowledge_cache_key(query, product_area)
            if (
                knowledge_prefetch_result is not None
                and search_cache_key == knowledge_prefetch_cache_key
            ):
                return knowledge_prefetch_result

            if (
                knowledge_prefetch_task is not None
                and search_cache_key == knowledge_prefetch_cache_key
            ):
                try:
                    knowledge_prefetch_result = await knowledge_prefetch_task
                except asyncio.CancelledError:
                    raise
                except Exception:
                    call_logger.exception("Server-managed knowledge prefetch failed")
                    knowledge_prefetch_result = {
                        "backend": KNOWLEDGE_BACKEND_NAME,
                        "query": query,
                        "results": [],
                        "error": "server-managed prefetch failed",
                    }
                return knowledge_prefetch_result

            cached_result = _cache_get(search_cache_key)
            if cached_result is not None:
                logger.info("get_server_managed_knowledge_result - Reusing cached knowledge result for key=%s", _safe_preview(search_cache_key, limit=150))
                return cached_result

            return await _knowledge_lookup(query, product_area, call_logger)

        async def run_grounded_response() -> None:
            nonlocal knowledge_flow_active, knowledge_prefetch_task, knowledge_prefetch_result, knowledge_prefetch_query, knowledge_prefetch_product_area, knowledge_prefetch_cache_key
            query = (call_state.last_user_transcript or call_state.issue_summary).strip()
            if not query:
                await send_system_message(_build_direct_response_hint(call_state), "direct answer")
                await request_assistant_response("direct-answer")
                return

            product_area = _best_product_area_hint(call_state)
            search_cache_key, rewritten_query = _build_knowledge_cache_key(query, product_area)
            knowledge_flow_active = True
            knowledge_prefetch_query = query
            knowledge_prefetch_product_area = product_area or ""
            knowledge_prefetch_cache_key = search_cache_key
            knowledge_prefetch_result = _cache_get(search_cache_key)
            knowledge_prefetch_task = None
            if knowledge_prefetch_result is not None:
                call_logger.info(
                    "Reusing cached knowledge result product_area=%s query=%s rewritten_query=%s",
                    product_area or "",
                    _safe_preview(query, limit=220),
                    _safe_preview(rewritten_query, limit=120),
                )
            else:
                call_logger.info(
                    "Knowledge lookup starting product_area=%s query=%s rewritten_query=%s",
                    product_area or "",
                    _safe_preview(query, limit=220),
                    _safe_preview(rewritten_query, limit=120),
                )
                knowledge_prefetch_task = asyncio.create_task(
                    _knowledge_lookup(query, product_area, call_logger),
                    name="knowledge-prefetch",
                )
            try:
                grounding = await get_server_managed_knowledge_result(query, product_area)
                knowledge_prefetch_result = grounding
                best_result = grounding.get("best_result") or {}
                best_title = str(best_result.get("title") or "").strip()
                call_logger.info(
                    "Knowledge answer starting best_title=%s confidence=%s response_mode=%s",
                    _safe_preview(best_title, limit=160),
                    grounding.get("best_confidence"),
                    grounding.get("response_mode"),
                )
                await send_system_message(_build_knowledge_grounding_hint(grounding, call_state), "knowledge grounding")
                await request_assistant_response("knowledge-answer")
            finally:
                knowledge_flow_active = False
                if knowledge_prefetch_task is not None and knowledge_prefetch_task.done():
                    knowledge_prefetch_task = None

        async def handle_transcribed_user_turn(transcript: str) -> None:
            try:
                logger.info("handle_transcribed_user_turn - Processing user transcript: '%s'", _safe_preview(transcript, limit=200))
                call_state.apply_user_transcript(transcript)
                call_logger.info("Caller transcript received summary=%s", _safe_preview(call_state.issue_summary, limit=220))
                if LOG_CALL_TRANSCRIPTS:
                    call_logger.debug(
                        "Caller transcript=%s context=%s",
                        _safe_preview(transcript, limit=400),
                        _safe_preview(call_state.summary_text(), limit=500),
                    )

                await maybe_send_interruption_ack_hint()
                if _knowledge_backend_enabled():
                    logger.info("handle_transcribed_user_turn - Starting grounded response flow")
                    await run_grounded_response()
                    return

                logger.info("handle_transcribed_user_turn - Direct answer flow, sending hint to OpenAI")
                await send_system_message(_build_direct_response_hint(call_state), "direct answer")
                await request_assistant_response("direct-answer")
            except asyncio.CancelledError:
                logger.debug("handle_transcribed_user_turn - Task cancelled")
                if LOG_CALL_TRANSCRIPTS:
                    call_logger.debug("Cancelled pending user turn handling")
                raise
            except Exception:
                logger.exception("handle_transcribed_user_turn - Unexpected error in user turn handler")
                call_logger.exception("User turn handler failed")

        def schedule_transcribed_user_turn(event: dict[str, Any], transcript: str) -> None:
            nonlocal last_user_input_signature, last_user_input_signature_at, pending_user_turn_task
            item_id = _extract_event_item_id(event)
            normalized_transcript = _normalize_text(transcript)
            signature = item_id or normalized_transcript
            now = time.monotonic()
            if signature and signature == last_user_input_signature and (now - last_user_input_signature_at) < 1.5:
                if LOG_CALL_TRANSCRIPTS:
                    call_logger.debug("Skipping duplicate caller transcript signature=%s", signature)
                return

            last_user_input_signature = signature
            last_user_input_signature_at = now
            cancel_pending_user_turn()
            cancel_knowledge_prefetch()
            pending_user_turn_task = asyncio.create_task(
                handle_transcribed_user_turn(transcript),
                name="handle-user-turn",
            )

        async def handle_tool_call(item: dict[str, Any]) -> None:
            call_id = item.get("call_id")
            tool_name = item.get("name")
            if not call_id or call_id in handled_call_ids:
                call_logger.debug("handle_tool_call - Skipping tool call: call_id='%s', name='%s' (already handled or missing id)", call_id, tool_name)
                return
            handled_call_ids.add(call_id)

            logger.info("handle_tool_call - Processing tool call: id='%s', name='%s'", call_id, tool_name)
            raw_arguments = item.get("arguments") or "{}"
            if isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    arguments = {"raw_arguments": raw_arguments}
            elif isinstance(raw_arguments, dict):
                arguments = raw_arguments
            else:
                arguments = {}

            call_logger.info("Handling tool call `%s`", tool_name)
            if LOG_TOOL_PAYLOADS:
                call_logger.debug("Tool `%s` arguments=%s", tool_name, _safe_preview(arguments, limit=500))
            if tool_name == "remember_call_context":
                logger.info("handle_tool_call - Executing remember_call_context with arguments: %s", 
                           {k: _safe_preview(str(v), limit=50) for k, v in arguments.items()})
                call_state.remember_context(arguments)
                tool_output = {
                    "ok": True,
                    "summary": call_state.summary_text(),
                    "context": call_state.as_tool_payload(),
                }
                logger.info("handle_tool_call - remember_call_context completed: confirmed_facts=%s, tried_steps=%s", 
                           len(call_state.confirmed_facts), len(call_state.tried_steps))
            elif tool_name == "get_call_context":
                logger.info("handle_tool_call - Executing get_call_context")
                tool_output = {
                    "summary": call_state.summary_text(),
                    "context": call_state.as_tool_payload(),
                }
                logger.info("handle_tool_call - get_call_context completed: user_turns=%s, assistant_turns=%s", 
                           call_state.user_turns, call_state.assistant_turns)
            elif tool_name == "search_qualys_support_knowledge":
                query = str(arguments.get("query") or "").strip()
                product_area = str(arguments.get("product_area") or "").strip() or None
                if not query:
                    query = call_state.issue_summary or call_state.last_user_transcript
                logger.info("handle_tool_call - Executing search_qualys_support_knowledge: query='%s', product_area='%s'", 
                           _safe_preview(query, limit=100), product_area or "none")
                if knowledge_flow_active:
                    call_logger.info("Reusing server-managed knowledge flow for tool call query=%s", _safe_preview(query, limit=220))
                    tool_output = await get_server_managed_knowledge_result(query, product_area)
                else:
                    tool_output = await _knowledge_lookup(query, product_area, call_logger)
                results = tool_output.get("results") or []
                top_titles = [
                    _safe_preview(str(item.get("title") or ""), limit=80)
                    for item in results[:3]
                ]
                top_snippets = [
                    _safe_preview(str(item.get("snippet") or ""), limit=120)
                    for item in results[:3]
                ]
                top_gpt_contexts = [
                    _safe_preview(str(item.get("gpt_context") or item.get("gptContext") or ""), limit=100)
                    for item in results[:3]
                ]
                logger.info(
                    "handle_tool_call - search_qualys_support_knowledge completed: result_count=%s best_confidence=%s top_titles=%s top_snippets=%s top_gpt_contexts=%s",
                    len(results),
                    tool_output.get("best_confidence"),
                    top_titles,
                    top_snippets,
                    top_gpt_contexts,
                )
            else:
                logger.warning("handle_tool_call - Unknown tool name: '%s'", tool_name)
                tool_output = {"error": f"Unsupported tool: {tool_name}"}

            if LOG_TOOL_PAYLOADS:
                call_logger.debug("Tool `%s` output=%s", tool_name, _safe_preview(tool_output, limit=700))

            logger.info("handle_tool_call - Sending tool output back to OpenAI: tool='%s', output_keys=%s", 
                       tool_name, list(tool_output.keys()))
            await openai_ws.send(
                _json_dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": _json_dumps(tool_output),
                        },
                    }
                )
            )
            if tool_name == "search_qualys_support_knowledge":
                best_result = tool_output.get("best_result") or {}
                best_title = str(best_result.get("title") or "").strip()
                if knowledge_flow_active:
                    call_logger.info("Skipping duplicate response.create for server-managed knowledge tool call")
                    return
                logger.info("handle_tool_call - Sending knowledge grounding hint to OpenAI")
                await send_system_message(_build_knowledge_grounding_hint(tool_output, call_state), "knowledge grounding")
            logger.info("handle_tool_call - Creating new assistant response for tool result")
            await request_assistant_response(f"tool:{tool_name}", wait_for_previous=False)

        async def receive_from_twilio() -> None:
            nonlocal assistant_audio_sent_ms, stream_sid, latest_media_timestamp_ms, last_assistant_item_id, response_start_timestamp_twilio_ms, last_user_input_signature, last_user_input_signature_at, interruption_pending_ack, response_resume_not_before, active_response_id
            try:
                async for message in websocket.iter_text():
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        call_logger.warning("Twilio sent non-JSON frame; ignoring")
                        continue

                    event_type = data.get("event")
                    if event_type == "start":
                        stream_sid = data.get("start", {}).get("streamSid")
                        if LOG_TWILIO_MEDIA_EVENTS:
                            call_logger.debug("Twilio start payload=%s", _safe_preview(data, limit=500))
                        twilio_started.set()
                        latest_media_timestamp_ms = 0
                        assistant_audio_sent_ms = 0
                        response_start_timestamp_twilio_ms = None
                        last_assistant_item_id = None
                        call_state.__dict__.update(dataclasses.asdict(CallState(assistant_name=ASSISTANT_NAME, support_product=SUPPORT_PRODUCT)))
                        handled_call_ids.clear()
                        last_user_input_signature = ""
                        last_user_input_signature_at = 0.0
                        interruption_pending_ack = False
                        response_resume_not_before = 0.0
                        active_response_id = None
                        cancel_pending_user_turn()
                        cancel_knowledge_prefetch()
                        response_done_event.set()
                        cancel_pending_interrupt()
                        mark_queue.clear()
                        call_logger.info("Twilio stream started: %s", stream_sid)
                        if AI_SPEAKS_FIRST:
                            call_logger.info("AI speaks first enabled - Sending initial greeting")
                            response_done_event.clear()
                            await _send_initial_greeting(openai_ws)
                            call_logger.info("Initial greeting sent to OpenAI")
                        continue

                    if event_type == "media":
                        if not twilio_started.is_set():
                            continue
                        payload = data.get("media", {}).get("payload")
                        ts = data.get("media", {}).get("timestamp")
                        if payload is None or ts is None:
                            continue
                        latest_media_timestamp_ms = int(ts)
                        logger.debug("Twilio media received - timestamp=%s, payload_length=%s", ts, len(payload) if payload else 0)
                        if LOG_TWILIO_MEDIA_EVENTS:
                            call_logger.debug(
                                "Twilio media ts=%s payload_chars=%s",
                                ts,
                                len(payload),
                            )
                        await openai_ws.send(f'{{"type":"input_audio_buffer.append","audio":"{payload}"}}')
                        continue

                    if event_type == "mark":
                        if LOG_TWILIO_MEDIA_EVENTS:
                            call_logger.debug("Twilio mark payload=%s queue_before=%s", _safe_preview(data, limit=300), len(mark_queue))
                        if mark_queue:
                            mark_queue.popleft()
                        if not mark_queue:
                            assistant_audio_sent_ms = 0
                            response_start_timestamp_twilio_ms = None
                            last_assistant_item_id = None
                        continue

                    if event_type == "stop":
                        logger.info("Twilio stop event received - Closing WebSocket connections")
                        call_logger.info("Twilio sent stop; closing")
                        if LOG_TWILIO_MEDIA_EVENTS:
                            call_logger.debug("Twilio stop payload=%s", _safe_preview(data, limit=300))
                        cancel_pending_user_turn()
                        cancel_knowledge_prefetch()
                        cancel_pending_interrupt()
                        await openai_ws.close()
                        return

            except WebSocketDisconnect:
                call_logger.info("Twilio WS disconnected")
            finally:
                cancel_pending_user_turn()
                cancel_knowledge_prefetch()
                cancel_pending_interrupt()
                with suppress(Exception):
                    await openai_ws.close()

        async def send_to_twilio() -> None:
            nonlocal assistant_audio_sent_ms, last_assistant_item_id, response_start_timestamp_twilio_ms, active_response_id
            try:
                await asyncio.wait_for(twilio_started.wait(), timeout=10)
            except TimeoutError:
                call_logger.warning("Timed out waiting for Twilio start event; closing")
                return

            try:
                async for openai_message in openai_ws:
                    if not isinstance(openai_message, str):
                        continue
                    try:
                        event = json.loads(openai_message)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type")
                    if LOG_OPENAI_EVENTS or (event_type in LOG_EVENT_TYPES):
                        call_logger.debug("OpenAI event: %s", event_type)

                    if event_type == "response.created":
                        response = event.get("response") or {}
                        response_id = response.get("id")
                        if isinstance(response_id, str) and response_id.strip():
                            active_response_id = response_id.strip()
                            logger.info("OpenAI response created - Response ID: %s", active_response_id)
                        continue

                    if event_type == "error":
                        error = event.get("error") or event
                        response_done_event.set()
                        if isinstance(error, dict) and error.get("code") == "unknown_parameter":
                            call_logger.error(
                                "OpenAI rejected a session parameter: %s (%s)",
                                error.get("param"),
                                error.get("message"),
                            )
                        else:
                            call_logger.error("OpenAI error: %s", error)
                        return

                    if event_type == "response.done":
                        logger.info("OpenAI response completed - Response ID: %s", active_response_id or "unknown")
                        active_response_id = None
                        response_done_event.set()
                        tool_calls = _extract_function_calls_from_event(event)
                        if tool_calls:
                            logger.info("OpenAI response.done - Processing %s tool calls", len(tool_calls))
                        for item in tool_calls:
                            await handle_tool_call(item)
                        continue

                    if event_type in {
                        "response.function_call_arguments.done",
                        "response.output_item.done",
                        "conversation.item.created",
                    }:
                        for item in _extract_function_calls_from_event(event):
                            await handle_tool_call(item)
                        continue

                    if event_type in {
                        "conversation.item.input_audio_transcription.completed",
                        "conversation.item.input_audio_transcription.done",
                        "input_audio_transcription.completed",
                    }:
                        transcript = _extract_transcript_text(event)
                        if transcript:
                            logger.info("OpenAI transcription completed - User transcript: '%s'", _safe_preview(transcript, limit=150))
                            schedule_transcribed_user_turn(event, transcript)
                        continue

                    if event_type in {
                        "response.audio_transcript.done",
                        "response.output_audio_transcript.done",
                    }:
                        transcript = _extract_transcript_text(event)
                        if transcript:
                            call_state.last_assistant_transcript = transcript
                            call_state.assistant_turns += 1
                            logger.info("OpenAI assistant transcript completed - Assistant transcript: '%s'", _safe_preview(transcript, limit=150))
                            if LOG_CALL_TRANSCRIPTS:
                                call_logger.debug("Assistant transcript=%s", _safe_preview(transcript, limit=400))
                        continue

                    if event_type in {"response.audio.delta", "response.output_audio.delta"}:
                        delta = event.get("delta")
                        if not delta or not stream_sid:
                            continue

                        item_id = event.get("item_id")
                        if item_id and item_id != last_assistant_item_id:
                            logger.info("OpenAI audio started - New item ID: %s", item_id)
                            assistant_audio_sent_ms = 0
                            response_start_timestamp_twilio_ms = latest_media_timestamp_ms if latest_media_timestamp_ms > 0 else None
                            last_assistant_item_id = item_id

                        if response_start_timestamp_twilio_ms is None:
                            assistant_audio_sent_ms = 0
                        logger.debug("OpenAI audio delta - Sending to Twilio: payload_length=%s, total_audio_ms=%s", 
                                   len(delta), assistant_audio_sent_ms + _estimate_pcmu_audio_ms(delta))
                        await websocket.send_text(
                            f'{{"event":"media","streamSid":"{stream_sid}","media":{{"payload":"{delta}"}}}}'
                        )
                        assistant_audio_sent_ms += _estimate_pcmu_audio_ms(delta)
                        if LOG_TWILIO_MEDIA_EVENTS:
                            call_logger.debug(
                                "OpenAI audio delta item_id=%s payload_chars=%s total_assistant_audio_ms=%s",
                                event.get("item_id"),
                                len(delta),
                                assistant_audio_sent_ms,
                            )

                        if response_start_timestamp_twilio_ms is None and latest_media_timestamp_ms > 0:
                            response_start_timestamp_twilio_ms = latest_media_timestamp_ms

                        await send_mark()
                        continue

                    if event_type == "input_audio_buffer.speech_started":
                        logger.info("OpenAI speech started detected - Interrupting assistant if active")
                        if last_assistant_item_id:
                            await schedule_interrupt()
                        continue

                    if event_type == "input_audio_buffer.speech_stopped":
                        logger.debug("OpenAI speech stopped detected - Cancelling pending interrupt")
                        cancel_pending_interrupt()
                        continue

            except Exception:
                call_logger.exception("Error forwarding OpenAI -> Twilio")
            finally:
                cancel_pending_user_turn()
                cancel_knowledge_prefetch()
                cancel_pending_interrupt()
                with suppress(Exception):
                    await websocket.close()

        twilio_task = asyncio.create_task(receive_from_twilio(), name="twilio->openai")
        openai_task = asyncio.create_task(send_to_twilio(), name="openai->twilio")
        done, pending = await asyncio.wait({twilio_task, openai_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()

    except Exception:
        logger.exception("Media stream handler failed - Call ID: %s", call_logger.name)
        call_logger.exception("Media stream handler failed")
        with suppress(Exception):
            await websocket.close(code=1011)
    finally:
        if openai_ws is not None:
            logger.info("Closing OpenAI WebSocket connection")
            with suppress(Exception):
                await openai_ws.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT, proxy_headers=True, forwarded_allow_ips="*")
