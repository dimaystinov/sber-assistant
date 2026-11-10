"""FastAPI-слой:/chat, /role/switch, /consents.* (withdraw), поверх RoleContextManager."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .consent import ConsentScope, CONSENT_DOCS
from .domain import ConsentAction, Role
from .gigachat import GigaChatClient, GigaChatLangChainClient
from .chat_graph import build_chat_graph
from .calculations import CashGapInput
from .demo_tools import DemoToolBroker
from .mcp_tools import McpDemoToolBroker
from .simulated_sber_services import SimulatedSberMcpGateway
from .handoff import HandoffCoordinator, HandoffDenied
from .role_context import RoleContextManager, RoleSwitchDenied

app = FastAPI(
    title="Универсальный помощник Сбера",
    version="0.1.0",
    description="Мультиролный ассистент: клиент / предприниматель / сотрудник.",
)


# ---DI-фабрики (прод: Depends на Исты/AuthN, KMS, pg) ------------------------

@dataclass
class Runtime:
    consent: object = None
    managers: dict = field(default_factory=dict)
    handoffs: dict = field(default_factory=dict)
    gigachat: object = None
    broker: DemoToolBroker = field(default_factory=McpDemoToolBroker)
    sber_mcp: SimulatedSberMcpGateway = field(default_factory=SimulatedSberMcpGateway)


_RUNTIME = Runtime()


@app.get("/", include_in_schema=False)
def demo_page():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


def _bootstrap() -> None:
    from .consent import ConsentService
    from .domain import SubjectIdentity
    from .role_context import RoleContextManager

    if _RUNTIME.consent is None:
        _RUNTIME.consent = ConsentService()
        mode = "online" if os.getenv("GIGACHAT_CREDENTIALS") else "offline"
        if mode == "online":
            from langchain_gigachat import GigaChat

            generator = GigaChat(
                credentials=os.environ["GIGACHAT_CREDENTIALS"],
                scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
                model=os.getenv("GIGACHAT_MODEL", "GigaChat-2"),
                ca_bundle_file=os.getenv("GIGACHAT_CA_BUNDLE"),
                verify_ssl_certs=True,
                max_retries=0,
            )
            critic = GigaChat(
                credentials=os.environ["GIGACHAT_CREDENTIALS"],
                scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
                model=os.getenv("GIGACHAT_CRITIC_MODEL", "GigaChat-2-Pro"),
                ca_bundle_file=os.getenv("GIGACHAT_CA_BUNDLE"),
                verify_ssl_certs=True,
                max_retries=0,
            )
            _RUNTIME.gigachat = GigaChatLangChainClient(generator, critic)
        else:
            _RUNTIME.gigachat = GigaChatClient(mode="offline")
        _RUNTIME.managers.clear()
        _RUNTIME.handoffs.clear()


def get_current_identity(authorization: str | None = Header(default=None)):
    """Один локальный демо-субъект с серверным bearer-токеном."""
    if os.getenv("ASSISTANT_ENV", "demo").lower() != "demo":
        raise HTTPException(
            status_code=503,
            detail="Демо-авторизация отключена вне режима demo",
        )
    expected = os.getenv("ASSISTANT_DEMO_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="Демо-доступ не настроен")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Неверный токен доступа")
    _bootstrap()
    subject = "demo-subject"
    if subject not in _RUNTIME.managers:
        _RUNTIME.managers[subject] = _make_manager(subject)
    return _RUNTIME.managers[subject]


def _make_manager(sber_id: str) -> RoleContextManager:
    from .domain import SubjectIdentity

    return RoleContextManager(SubjectIdentity(sber_id), _RUNTIME.consent)


# ---Request/Response модели --------------------------------------------------

class ChatMessage(BaseModel):
    query: str = Field(min_length=1, max_length=4096)
    cross_role_opt_in: bool = False
    calculation: CashGapInput | None = None


class SwitchRoleRequest(BaseModel):
    target_role: Role
    channel: str = Field(pattern="^(sberbank_online|sbi_business|hr_portal)$")


class HandoffRequest(BaseModel):
    target_role: Role
    intent: str = Field(min_length=1, max_length=64)
    opt_in: bool = False


class HandoffClaim(BaseModel):
    token: str = Field(min_length=1, max_length=128)


class ConsentRequest(BaseModel):
    scope: ConsentScope
    role: Role
    channel: str = Field(pattern="^(sberbank_online|sbi_business|hr_portal)$")


class PrepareActionRequest(BaseModel):
    kind: str
    payload: dict


class ConfirmActionRequest(BaseModel):
    action_id: str
    confirmation_token: str


class DemoMcpCallRequest(BaseModel):
    service: str
    tool: str
    arguments: dict = Field(default_factory=dict)


class DemoPaymentDraftRequest(BaseModel):
    payload: dict


_ROLE_CHANNEL = {
    Role.RETAIL: "sberbank_online",
    Role.BUSINESS: "sbi_business",
    Role.EMPLOYEE: "hr_portal",
}


def _require_channel(role: Role, channel: str) -> None:
    if _ROLE_CHANNEL[role] != channel:
        raise HTTPException(status_code=403, detail="Канал не соответствует роли")


def _handoff(manager: RoleContextManager) -> HandoffCoordinator:
    if manager not in _RUNTIME.handoffs:
        _RUNTIME.handoffs[manager] = HandoffCoordinator(manager)
    return _RUNTIME.handoffs[manager]


# ---Эндпоинты -----------------------------------------------------------------

@app.post("/v1/handoff/request")
def request_handoff(
    req: HandoffRequest, manager: RoleContextManager = Depends(get_current_identity),
):
    try:
        token = _handoff(manager).request(
            req.target_role, intent=req.intent, opt_in=req.opt_in
        )
    except HandoffDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return {"token": token, "target_role": req.target_role.value,
            "expires_after_sec": HandoffCoordinator._TTL_SECONDS,
            "provenance": "demo_fixture"}


@app.post("/v1/handoff/claim")
def claim_handoff(
    req: HandoffClaim, manager: RoleContextManager = Depends(get_current_identity),
):
    try:
        signal = _handoff(manager).claim(req.token)
    except HandoffDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    prompt = {
        ("retail", "business", "continue_application"):
            "Помоги продолжить оформление расчётного счёта в учебном СберБизнесе: какой следующий шаг?",
        ("retail", "business", "open_business_channel"):
            "Какие учебные возможности бизнес-канала доступны после перехода?",
        ("business", "retail", "continue_application"):
            "Помоги продолжить задачу в клиентском канале: какой следующий шаг доступен?",
        ("business", "retail", "open_business_channel"):
            "Какие учебные возможности клиентского канала доступны после перехода?",
    }[(signal["source_role"], manager.active_role.value, signal["intent"])]
    return {"signal": signal, "suggested_question": prompt,
            "provenance": "demo_fixture"}

@app.post("/v1/chat")
def chat(msg: ChatMessage, manager: RoleContextManager = Depends(get_current_identity)):
    """Диалог в активной роли через граф с программной проверкой основания."""
    try:
        result = build_chat_graph(manager, _RUNTIME.gigachat, _RUNTIME.broker).invoke({
            "query": msg.query, "cross_role_opt_in": msg.cross_role_opt_in,
            "calculation": msg.calculation.model_dump(mode="json") if msg.calculation else None,
        })
    except PermissionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    ctx = result["context"]
    return {
        "role": ctx["role"],
        "session_id": ctx["session_id"],
        "namespace": ctx["namespace"],
        "answer": result["answer"],
        "tokens_used": result["tokens_used"],
        "decision": result["decision"],
        "sources": result.get("sources", []),
    }


@app.get("/v1/demo/state")
def demo_state(manager: RoleContextManager = Depends(get_current_identity)):
    try:
        return {"provenance": "demo_fixture", "state": _RUNTIME.broker.state(manager)}
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc


@app.post("/v1/demo/sber-mcp/call")
def demo_sber_mcp_call(
    req: DemoMcpCallRequest,
    manager: RoleContextManager = Depends(get_current_identity),
):
    """Только чтение: учебный двойник публично описанных Sber API MCP tools."""
    try:
        return _RUNTIME.sber_mcp.call(manager, req.service, req.tool, req.arguments)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except (ValueError, LookupError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@app.post("/v1/demo/sber-mcp/payments/prepare")
def demo_payment_prepare(
    req: DemoPaymentDraftRequest,
    manager: RoleContextManager = Depends(get_current_identity),
):
    try:
        return _RUNTIME.sber_mcp.prepare_payment_draft(manager, req.payload)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@app.post("/v1/demo/sber-mcp/payments/confirm")
def demo_payment_confirm(
    req: ConfirmActionRequest,
    manager: RoleContextManager = Depends(get_current_identity),
):
    try:
        return _RUNTIME.sber_mcp.confirm_payment_draft(
            manager, req.action_id, req.confirmation_token
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@app.get("/v1/demo/read/{name}")
def demo_read(name: str, query: str = "",
              manager: RoleContextManager = Depends(get_current_identity)):
    try:
        result = _RUNTIME.broker.read(manager, name, query)
        return {
            "name": result.name, "text": result.text,
            "source_id": result.source_id, "version": result.version,
            "provenance": result.provenance,
        }
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@app.post("/v1/demo/actions/prepare")
def prepare_action(req: PrepareActionRequest,
                   manager: RoleContextManager = Depends(get_current_identity)):
    try:
        draft = _RUNTIME.broker.prepare_action(manager, req.kind, req.payload)
        return {
            "action_id": draft.action_id,
            "confirmation_token": draft.confirmation_token,
            "kind": draft.kind, "payload": draft.payload,
            "expires_at": draft.expires_at,
            "status": "pending_user_confirmation", "provenance": "demo_fixture",
        }
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@app.post("/v1/demo/actions/confirm")
def confirm_action(req: ConfirmActionRequest,
                   manager: RoleContextManager = Depends(get_current_identity)):
    try:
        event = _RUNTIME.broker.confirm_action(
            manager, req.action_id, req.confirmation_token,
        )
        return {
            "action_id": event.action_id, "kind": event.kind,
            "status": event.status, "payload": event.payload,
            "provenance": "demo_fixture",
        }
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc


@app.post("/v1/role/switch")
def switch_role(req: SwitchRoleRequest,
                manager: RoleContextManager = Depends(get_current_identity)):
    _require_channel(req.target_role, req.channel)
    try:
        context = manager.switch_role(req.target_role, channel=req.channel)
    except RoleSwitchDenied as denied:
        doc = CONSENT_DOCS[denied.required_scope]
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "error": "consent_required",
                "reason": denied.reason,
                "required_scope": denied.required_scope.value,
                "consent_doc_url": f"/legal/consents/{doc.scope.value}/v{denied.doc_version_required}.pdf",
            },
        ) from denied
    return {
        "session": context.session.session_id,
        "role": context.session.role.value,
        "namespace": context.session.namespace,
        "switched_now": context.switched_now,
        "expires_after_sec": manager._redis.ttl_of(context.session.role,
                                                   context.session.subject_hash),
    }


@app.get("/v1/role/active")
def active_role(manager: RoleContextManager = Depends(get_current_identity)):
    return {"active_role": manager.active_role.value if manager.active_role else None}


@app.post("/v1/consents")
def grant(req: ConsentRequest,
          manager: RoleContextManager = Depends(get_current_identity)):
    _require_channel(req.role, req.channel)
    consent_id = manager.grant_consent(req.role, req.scope, req.channel)
    return {"consent_id": consent_id, "status": "granted"}


@app.delete("/v1/consents/{consent_id}")
def withdraw(consent_id: str, req: ConsentRequest,
             manager: RoleContextManager = Depends(get_current_identity)):
    _require_channel(req.role, req.channel)
    try:
        manager.withdraw_consent(req.role, req.scope, req.channel, consent_id)
    except Exception as exc:  # ConsentNotFound
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"consent_id": consent_id, "status": "withdrawn_in_demo"}
