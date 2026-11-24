from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
import urllib3
from sqlalchemy.exc import IntegrityError

from backend.config import AI_PROVIDER_API_KEY, AI_PROVIDER_MODEL_NAME, GEMINI_API_KEY
from backend.db.models import AgentProviderKey, db
from backend.errors import ApiError
from backend.security.provider_secrets import decrypt_provider_data, encrypt_provider_data
from backend.security.public_http import public_http_get, public_target
from backend.services.provider_retry import DEFAULT_RETRY_POLICY, RetryPolicy, resolve_retry_policy

MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]{0,190}")
KEY_ROUTE = re.compile(r"key/([a-z0-9-]{1,48})/([a-f0-9]{24})")
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
PROTOCOLS = ("openai-completions", "openai-responses", "anthropic-messages", "google-generative-ai")
CUSTOM_ID = re.compile(r"custom-[a-z0-9][a-z0-9-]{0,34}")
PROVIDER_REVISION = re.compile(r"[a-f0-9]{64}")
MAX_PROVIDER_MODELS = 400
MAX_MODEL_CONTEXT = 16_000_000
MAX_MODEL_OUTPUT = 262_144
REASONING_WIRE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}")


@dataclass(frozen=True)
class Provider:
    title: str
    base: str
    api: str


PROVIDERS = {
    "custom": Provider("OpenAI-compatible", "", "openai-completions"),
    "openai": Provider("OpenAI", "https://api.openai.com/v1", "openai-responses"),
    "anthropic": Provider("Anthropic", "https://api.anthropic.com/v1", "anthropic-messages"),
    "google": Provider(
        "Google Gemini", "https://generativelanguage.googleapis.com/v1beta", "google-generative-ai"
    ),
    "deepseek": Provider("DeepSeek", "https://api.deepseek.com", "anthropic-messages"),
    "openrouter": Provider("OpenRouter", "https://openrouter.ai/api/v1", "openai-completions"),
    "mistral": Provider("Mistral AI", "https://api.mistral.ai/v1", "openai-completions"),
    "groq": Provider("Groq", "https://api.groq.com/openai/v1", "openai-completions"),
    "xai": Provider("xAI", "https://api.x.ai/v1", "openai-completions"),
}


def capabilities(item, *, codex=False):
    raw_efforts = (
        item.get("supportedReasoningEfforts") if codex else item.get("supported_reasoning_levels")
    )
    efforts = [
        p.get("reasoningEffort" if codex else "effort")
        for p in raw_efforts or []
        if isinstance(p, dict)
    ]
    efforts = list(dict.fromkeys(level for level in efforts if level in EFFORTS))
    default = item.get("defaultReasoningEffort" if codex else "default_reasoning_level")
    rich = item.get("serviceTiers" if codex else "service_tiers") or []
    tiers = [tier.get("id") for tier in rich if isinstance(tier, dict)]
    tiers += item.get("additionalSpeedTiers" if codex else "additional_speed_tiers") or []
    supported = {tier for tier in tiers if isinstance(tier, str)}
    speeds = ["standard"]
    if supported & {"fast", "priority"}:
        speeds.append("fast")
    if "ultrafast" in supported:
        speeds.append("ultrafast")
    return {
        "thinkingLevels": efforts,
        **(
            {"defaultThinkingLevel": default if default in efforts else efforts[0]}
            if efforts
            else {}
        ),
        "serviceTiers": speeds,
    }


def is_custom_provider(provider):
    return isinstance(provider, str) and (
        provider == "custom" or CUSTOM_ID.fullmatch(provider) is not None
    )


def uses_public_endpoint(provider, base):
    return is_custom_provider(provider) or bool(base and base != PROVIDERS[provider].base)


def provider_headers(provider, key, protocol=None):
    if provider == "google" or protocol == "google-generative-ai":
        return {"x-goog-api-key": key}
    if provider == "anthropic" or protocol == "anthropic-messages":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {key}"}


def _custom_endpoint(value):
    if (
        not isinstance(value, str)
        or len(value) > 1024
        or not value
        or "?" in value
        or "#" in value
        or "\\" in value
    ):
        raise ApiError("provider_endpoint_invalid", status=422, code="provider_endpoint_invalid")
    try:
        public_target(value)
    except (ValueError, OSError, IndexError) as exc:
        raise ApiError(
            "provider_endpoint_invalid", status=422, code="provider_endpoint_invalid"
        ) from exc
    return value.rstrip("/")


def _public_models(provider, base, key, protocol, params):
    query = "?" + urlencode(params) if params else ""
    with public_http_get(
        base + "/models" + query, headers=provider_headers(provider, key, protocol), timeout=10
    ) as reply:
        if reply.status_code in (401, 403):
            raise ApiError("provider_key_rejected", status=422, code="provider_key_rejected")
        if reply.status_code != 200:
            raise ValueError("invalid_catalog_response")
        body = bytearray()
        for chunk in reply.iter_content(8192):
            body.extend(chunk)
            if len(body) > 2 * 1024 * 1024:
                raise ValueError()
        return json.loads(body)


def _discover(provider, key, base, protocol):
    google = protocol == "google-generative-ai"
    anthropic = protocol == "anthropic-messages" and provider != "deepseek"
    params = {"pageSize": 100} if google else {"limit": 100} if anthropic else {}
    entries = {}
    cursor = None
    public = uses_public_endpoint(provider, base)
    try:
        for _ in range(24):
            if public:
                data = _public_models(provider, base, key, protocol, params)
            else:
                with requests.get(
                    base + "/models",
                    headers=provider_headers(provider, key, protocol),
                    params=params,
                    timeout=(4, 10),
                    allow_redirects=False,
                ) as response:
                    if response.status_code in (401, 403):
                        raise ApiError(
                            "provider_key_rejected", status=422, code="provider_key_rejected"
                        )
                    if response.status_code != 200:
                        raise ValueError()
                    data = response.json()
            for item in data["models" if google else "data"]:
                if not isinstance(item, dict):
                    continue
                slug = item.get("name", "").removeprefix("models/") if google else item.get("id")
                if not isinstance(slug, str) or not MODEL_ID.fullmatch(slug):
                    continue
                if provider == "openai" and not public and (
                    not re.match(r"^(?:gpt-|chatgpt-|o[0-9]|ft:)", slug)
                    or any(
                        word in slug
                        for word in ("-audio", "-realtime", "-transcribe", "-tts", "-image")
                    )
                ):
                    continue
                if google and "generateContent" not in (
                    item.get("supportedGenerationMethods") or []
                ):
                    continue
                output_types = (item.get("architecture") or {}).get("output_modalities")
                if isinstance(output_types, list) and "text" not in output_types:
                    continue
                title = (
                    item.get("displayName")
                    or item.get("display_name")
                    or (item.get("name") if provider == "openrouter" else None)
                    or slug
                )
                entry = {"slug": slug, "title": str(title)[:160]}
                context = item.get("inputTokenLimit") if google else item.get("context_length")
                top_provider = item.get("top_provider")
                if not isinstance(top_provider, dict):
                    top_provider = {}
                output = item.get("outputTokenLimit") if google else top_provider.get("max_completion_tokens")
                if type(context) is int and 1 <= context <= MAX_MODEL_CONTEXT:
                    entry["contextWindow"] = context
                if type(output) is int and 1 <= output <= MAX_MODEL_OUTPUT and (
                    "contextWindow" not in entry or output < entry["contextWindow"]
                ):
                    entry["maxTokens"] = output
                modalities = (item.get("architecture") or {}).get("input_modalities")
                if isinstance(modalities, list) and "text" in modalities:
                    entry["inputModalities"] = ["text", "image"] if "image" in modalities else ["text"]
                entries[slug] = entry
                if len(entries) >= MAX_PROVIDER_MODELS:
                    return list(entries.values())
            next_cursor = (
                data.get("nextPageToken")
                if google
                else data.get("last_id")
                if anthropic and data.get("has_more")
                else None
            )
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
            params["pageToken" if google else "after_id"] = cursor
    except (
        requests.RequestException,
        urllib3.exceptions.HTTPError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    ) as exc:
        raise ApiError(
            "provider_catalog_failed", status=502, code="provider_catalog_failed"
        ) from exc
    if not entries:
        raise ApiError("provider_no_models", status=422, code="provider_no_models")
    return list(entries.values())


def key_model_id(provider, slug):
    digest = hashlib.sha256(slug.encode()).hexdigest()[:24]
    return f"key/{provider}/{digest}"


def _read_profile(row):
    return decrypt_provider_data(row.secret) if row else {}


def _profile_config(provider, body, previous):
    built_in = PROVIDERS.get(provider)
    custom = is_custom_provider(provider)
    if not built_in and not custom:
        raise ApiError("provider_unknown", status=404, code="provider_unknown")
    default_base = built_in.base if built_in else ""
    previous_api = previous.get("api") or (built_in.api if built_in else PROTOCOLS[0])
    previous_base = previous.get("base") or default_base
    api = body.get("protocol", previous_api) if custom else previous_api
    base = body.get("baseUrl", previous_base)
    if not isinstance(base, str):
        raise ApiError("provider_endpoint_invalid", status=422, code="provider_endpoint_invalid")
    base = base.strip().rstrip("/") or default_base
    name = previous.get("name") or (built_in.title if built_in else provider)
    if custom:
        name = body.get("name", name)
    if not isinstance(api, str) or api not in PROTOCOLS:
        raise ApiError("provider_invalid_protocol", status=400, code="provider_invalid_protocol")
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 80
        or any(ord(c) < 32 for c in name)
    ):
        raise ApiError(
            "provider_invalid_configuration", status=400, code="provider_invalid_configuration"
        )
    if previous and (base, api) != (previous_base, previous_api) and not body.get("key"):
        raise ApiError(
            "provider_key_for_endpoint_required",
            status=400,
            code="provider_key_for_endpoint_required",
        )
    key = body.get("key") or previous.get("key")
    if (
        not isinstance(key, str)
        or not 4 <= len(key) <= 4096
        or not key.isascii()
        or not key.isprintable()
        or any(c.isspace() for c in key)
    ):
        raise ApiError("provider_key_invalid", status=400, code="provider_key_invalid")
    if (custom or base != default_base) and (not previous or base != previous_base):
        base = _custom_endpoint(base)
    try:
        retry_policy = resolve_retry_policy(body.get("retryPolicy", previous.get("retryPolicy")))
    except ValueError as error:
        raise ApiError(
            "provider_retry_invalid", status=400, code="provider_retry_invalid"
        ) from error
    return {
        "key": key,
        "base": base,
        "api": api,
        "name": name.strip(),
        "retryPolicy": retry_policy.to_dict(),
    }


def _revision(row):
    if row is None:
        return None
    return hashlib.sha256(f"{row.updated_at.isoformat()}\n{row.secret}".encode()).hexdigest()


def _check_revision(row, options):
    if "expectedRevision" not in options:
        return
    expected = options["expectedRevision"]
    if expected is not None and (
        not isinstance(expected, str) or PROVIDER_REVISION.fullmatch(expected) is None
    ):
        raise ApiError(
            "provider_invalid_configuration", status=400, code="provider_invalid_configuration"
        )
    if expected != _revision(row):
        raise ApiError(
            "provider_connection_changed", status=409, code="provider_connection_changed"
        )


def _as_options(body):
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(
            "provider_invalid_configuration", status=400, code="provider_invalid_configuration"
        )
    return body


def _stored_catalog_mode(row, profile):
    return profile.get("catalogMode", "custom" if row else "provider")


def reasoning_levels_for(provider, protocol):
    native = native_efforts(provider, protocol)
    if native:
        return native
    if protocol == "anthropic-messages":
        return ["low", "medium", "high", "xhigh", "max"]
    return list(EFFORTS)


def _validate_model_fields(entry, provider, protocol):
    config = {}
    for key, limit in (("contextWindow", MAX_MODEL_CONTEXT), ("maxTokens", MAX_MODEL_OUTPUT)):
        if key in entry:
            value = entry[key]
            if type(value) is not int or not 1 <= value <= limit:
                raise ValueError(key)
            config[key] = value
    if "maxTokens" in config and config["maxTokens"] >= config.get("contextWindow", MAX_MODEL_CONTEXT):
        raise ValueError("maxTokens")
    if "inputModalities" in entry:
        modalities = entry["inputModalities"]
        if not isinstance(modalities, list) or modalities not in (["text"], ["text", "image"], ["image", "text"]):
            raise ValueError("inputModalities")
        config["inputModalities"] = ["text", "image"] if "image" in modalities else ["text"]
    if "reasoningEfforts" not in entry:
        return config
    value = entry["reasoningEfforts"]
    if value is False:
        return {**config, "reasoningEfforts": False}
    if not isinstance(value, dict) or not 1 <= len(value) <= len(EFFORTS):
        raise ValueError("reasoningEfforts")
    allowed = reasoning_levels_for(provider, protocol)
    fixed_wire = provider == "deepseek" or protocol in {"google-generative-ai", "anthropic-messages"}
    efforts = {}
    for level, wire in value.items():
        if level == "off":
            level = "none"
        if level not in allowed or level in efforts:
            raise ValueError("reasoningEfforts")
        if wire is None:
            if level != "none":
                raise ValueError("reasoningEfforts")
        elif not isinstance(wire, str) or not REASONING_WIRE.fullmatch(wire) or (
            fixed_wire and wire != level and (level, wire) != ("none", "off")
        ):
            raise ValueError("reasoningEfforts")
        efforts[level] = wire
    return {**config, "reasoningEfforts": efforts}


def _model_catalog(raw, provider, protocol):
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_PROVIDER_MODELS:
        raise ApiError("provider_no_models", status=422, code="provider_no_models")
    models = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError(
                "provider_invalid_configuration", status=400, code="provider_invalid_configuration"
            )
        slug, title = entry.get("slug"), entry.get("title")
        if (
            not isinstance(slug, str)
            or not MODEL_ID.fullmatch(slug)
            or slug in seen
            or not isinstance(title, str)
            or not title.strip()
            or len(title) > 160
            or any(ord(c) < 32 for c in title)
        ):
            raise ApiError(
                "provider_invalid_configuration", status=400, code="provider_invalid_configuration"
            )
        seen.add(slug)
        try:
            spec = _validate_model_fields(entry, provider, protocol)
        except ValueError as error:
            raise ApiError("provider_model_config_invalid", status=400, code="provider_model_config_invalid") from error
        models.append({"slug": slug, "title": title.strip(), **spec})
    return models


def provider_status(user_id):
    rows = {row.provider: row for row in AgentProviderKey.query.filter_by(user_id=user_id)}
    known = list(PROVIDERS) + sorted(
        provider for provider in rows if provider not in PROVIDERS and is_custom_provider(provider)
    )
    result = []
    for provider in known:
        row = rows.get(provider)
        built_in = PROVIDERS.get(provider)
        profile = _read_profile(row)
        result.append(
            {
                "id": provider,
                "name": profile.get("name") or (built_in.title if built_in else provider),
                "protocol": profile.get("api") or (built_in.api if built_in else PROTOCOLS[0]),
                "baseUrl": profile.get("base") or (built_in.base if built_in else ""),
                "defaultBaseUrl": built_in.base if built_in else "",
                "connected": row is not None,
                "models": row.catalog if row else [],
                "modelCount": len(row.catalog) if row else 0,
                "custom": is_custom_provider(provider),
                "catalogMode": _stored_catalog_mode(row, profile),
                "revision": _revision(row),
                "reasoningLevels": reasoning_levels_for(
                    provider, profile.get("api") or (built_in.api if built_in else PROTOCOLS[0])
                ),
                "retryPolicy": resolve_retry_policy(profile.get("retryPolicy")).to_dict(),
            }
        )
    return result


def preview_catalog(user_id, provider, body):
    row = db.session.get(AgentProviderKey, (user_id, provider))
    options = _as_options(body)
    _check_revision(row, options)
    config = _profile_config(provider, options, _read_profile(row))
    return _discover(provider, config["key"], config["base"], config["api"])


def save_key(user_id, provider, *, refresh=False, options=None):
    options = _as_options(options)
    row = db.session.get(AgentProviderKey, (user_id, provider))
    _check_revision(row, options)
    if refresh and not row:
        raise ApiError("provider_unknown", status=404, code="provider_unknown")
    previous = _read_profile(row)
    current_mode = _stored_catalog_mode(row, previous)
    if refresh and current_mode == "custom":
        return
    changes = {} if refresh else options
    config = _profile_config(provider, changes, previous)
    requested = changes.get("models")
    mode = changes.get("catalogMode", "custom" if "models" in changes else current_mode)
    if mode not in ("provider", "custom") or (mode == "provider" and "models" in changes):
        raise ApiError(
            "provider_invalid_configuration", status=400, code="provider_invalid_configuration"
        )
    if mode == "custom":
        models = _model_catalog(
            requested if "models" in changes else row.catalog if row else [],
            provider,
            config["api"],
        )
    elif (
        row is not None
        and current_mode == "provider"
        and not refresh
        and all(config[field] == previous.get(field) for field in ("key", "base", "api"))
    ):
        models = row.catalog
    else:
        models = _model_catalog(
            _discover(provider, config["key"], config["base"], config["api"]),
            provider,
            config["api"],
        )
    encrypted = encrypt_provider_data({**config, "catalogMode": mode})
    if row:
        changed = AgentProviderKey.query.filter_by(
            user_id=user_id, provider=provider, secret=row.secret, updated_at=row.updated_at
        ).update({"secret": encrypted, "catalog": models, "updated_at": datetime.now(timezone.utc)})
        if not changed:
            db.session.rollback()
            raise ApiError(
                "provider_connection_changed", status=409, code="provider_connection_changed"
            )
    else:
        db.session.add(
            AgentProviderKey(user_id=user_id, provider=provider, secret=encrypted, catalog=models)
        )
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ApiError(
            "provider_connection_changed", status=409, code="provider_connection_changed"
        ) from exc


def remove_key(user_id, provider, options=None):
    if provider not in PROVIDERS and not is_custom_provider(provider):
        return
    row = db.session.get(AgentProviderKey, (user_id, provider))
    _check_revision(row, _as_options(options))
    if row is None:
        return
    removed = AgentProviderKey.query.filter_by(
        user_id=user_id, provider=provider, secret=row.secret, updated_at=row.updated_at
    ).delete()
    if not removed:
        db.session.rollback()
        raise ApiError(
            "provider_connection_changed", status=409, code="provider_connection_changed"
        )
    db.session.commit()


def list_key_models(user_id):
    if not user_id:
        return []
    models = []
    rows = AgentProviderKey.query.filter_by(user_id=user_id).order_by(AgentProviderKey.provider)
    for row in rows:
        built_in = PROVIDERS.get(row.provider)
        if not built_in and not is_custom_provider(row.provider):
            continue
        profile = _read_profile(row)
        api = profile.get("api") or (built_in.api if built_in else PROTOCOLS[0])
        for item in row.catalog:
            levels = exposed_efforts(item, row.provider, api)
            models.append(
                {
                    "id": key_model_id(row.provider, item["slug"]),
                    "title": item["title"],
                    "subtitle": profile.get("name")
                    or (built_in.title if built_in else row.provider),
                    "source": "key",
                    "thinkingLevels": levels,
                    **(
                        {"defaultThinkingLevel": default_effort(levels, row.provider, api)}
                        if levels else {}
                    ),
                    **{
                        key: item[key]
                        for key in ("contextWindow", "maxTokens", "inputModalities")
                        if key in item
                    },
                    "provider": row.provider,
                    "stage": "release",
                }
            )
    return models


@dataclass(frozen=True, repr=False)
class ModelRoute:
    provider: str
    model: str
    key: str
    base: str | None = None
    api: str | None = None
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY
    spec: dict = field(default_factory=dict)

    @property
    def protocol(self):
        return self.api or PROVIDERS[self.provider].api

    @property
    def public_endpoint(self):
        return uses_public_endpoint(self.provider, self.base)

    @property
    def context_window(self):
        return self.spec.get("contextWindow")

    @property
    def max_tokens(self):
        return self.spec.get("maxTokens")

    @property
    def text_only(self):
        return self.spec.get("inputModalities") == ["text"]

    def wire_effort(self, requested):
        efforts = self.spec.get("reasoningEfforts")
        if efforts is False:
            return "off" if self.provider == "deepseek" else None
        levels = exposed_efforts(self.spec, self.provider, self.protocol)
        if not levels:
            return None
        level = requested if requested in levels else default_effort(levels, self.provider, self.protocol)
        wire = efforts[level] if isinstance(efforts, dict) else level
        return "off" if self.provider == "deepseek" and level == "none" else wire


def key_route(user_id, model_id):
    match = KEY_ROUTE.fullmatch(model_id or "")
    if not match or not user_id or (match[1] not in PROVIDERS and not is_custom_provider(match[1])):
        return None
    row = db.session.get(AgentProviderKey, (user_id, match[1]), populate_existing=True)
    if row:
        for item in row.catalog:
            if key_model_id(row.provider, item["slug"]) == model_id:
                record = _read_profile(row)
                return ModelRoute(
                    row.provider,
                    item["slug"],
                    record["key"],
                    record.get("base"),
                    record.get("api")
                    or (PROVIDERS[row.provider].api if row.provider in PROVIDERS else PROTOCOLS[0]),
                    resolve_retry_policy(record.get("retryPolicy")),
                    item,
                )
    return None


def native_efforts(provider, protocol=None):
    if provider == "deepseek":
        return ["none", "low", "high", "max"]
    if provider == "google" or protocol == "google-generative-ai":
        return ["minimal", "low", "medium", "high"]
    return []


def exposed_efforts(spec, provider, protocol):
    configured = spec.get("reasoningEfforts")
    if configured is False:
        return []
    if isinstance(configured, dict):
        return [level for level in reasoning_levels_for(provider, protocol) if level in configured]
    return native_efforts(provider, protocol)


def default_effort(levels, provider, protocol):
    if provider == "deepseek" and "high" in levels:
        return "high"
    if protocol == "google-generative-ai" and "medium" in levels:
        return "medium"
    return levels[0] if levels else None


def platform_route(model_id):
    if model_id == "harness" and os.getenv("DEEPSEEK_API_KEY"):
        return ModelRoute(
            "deepseek",
            os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-pro",
            os.environ["DEEPSEEK_API_KEY"],
        )
    return ModelRoute(
        "google",
        AI_PROVIDER_MODEL_NAME or "gemini-3.1-flash-lite",
        GEMINI_API_KEY or AI_PROVIDER_API_KEY or "",
    )
