"""Настоящий in-process MCP для учебных знаний и расчёта.

Сервер создаётся отдельно для доверенно установленной роли. Он не публикует
изменяющих инструментов и не принимает роль от модели в аргументах tools.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

from mcp import Client
from mcp.server.mcpserver import MCPServer

from .calculations import CashGapInput, cash_gap_answer
from .demo_tools import DemoToolBroker, ToolResult
from .domain import Role
from .knowledge import DemoKnowledgeBase, KnowledgeDocument
from .role_context import RoleContextManager


def create_role_mcp_server(
    role: Role, knowledge: DemoKnowledgeBase,
    broker: DemoToolBroker | None = None,
    manager: RoleContextManager | None = None,
) -> MCPServer:
    """Внутрипроцессный сервер с закрытой ролью и только разрешёнными tools."""
    server = MCPServer(name=f"sber-assistant-demo-{role.value}")

    @server.tool(description="Поиск только по учебным документам текущей роли")
    def search_knowledge(query: str) -> dict:
        documents = knowledge.search(role, query, today=date.today())
        return {
            "documents": [
                {
                    "source_id": doc.source_id,
                    "role": doc.role.value,
                    "title": doc.title,
                    "text": doc.text,
                    "version": doc.version,
                    "effective_from": doc.effective_from.isoformat(),
                    "keywords": list(doc.keywords),
                    "provenance": doc.provenance,
                }
                for doc in documents
            ]
        }

    if role is Role.BUSINESS:
        @server.tool(description="Детерминированный расчёт учебного кассового разрыва")
        def calculate_cash_gap(
            amount_due: str, available: str, days_until_due: int
        ) -> dict:
            data = CashGapInput(
                kind="cash_gap", amount_due=amount_due, available=available,
                days_until_due=days_until_due,
            )
            return {"answer": cash_gap_answer(data), "provenance": "calculated"}

    if broker is not None and manager is not None:
        @server.tool(description="Только чтение учебных данных текущей роли")
        def read_demo_data(name: str, query: str = "") -> dict:
            if broker._READ_ROLES.get(name) is not role:
                raise PermissionError("Инструмент недоступен в текущей роли")
            item = DemoToolBroker.read(broker, manager, name, query)
            return {
                "name": item.name,
                "role": item.role.value,
                "text": item.text,
                "source_id": item.source_id,
                "version": item.version,
                "verified": item.verified,
                "provenance": item.provenance,
            }

    return server


class McpDemoToolBroker(DemoToolBroker):
    """Broker проверяет роль и согласие до MCP-вызова и результат после него."""

    async def _call(
        self, role: Role, tool: str, arguments: dict,
        manager: RoleContextManager | None = None,
    ) -> dict:
        server = create_role_mcp_server(role, self.knowledge, self, manager)
        async with Client(server) as client:
            result = await client.call_tool(tool, arguments)
        if result.is_error or not result.content:
            raise RuntimeError("MCP-инструмент не вернул проверяемый результат")
        try:
            data = json.loads(result.content[0].text)
        except (AttributeError, ValueError) as exc:
            raise RuntimeError("Некорректный MCP-ответ") from exc
        if not isinstance(data, dict):
            raise RuntimeError("MCP-ответ должен быть объектом")
        return data

    def knowledge_search(
        self, manager: RoleContextManager, query: str
    ) -> list[KnowledgeDocument]:
        role = manager.active_role
        if role is None:
            raise PermissionError("Активная роль не выбрана")
        self._session(manager, role)
        result = asyncio.run(self._call(role, "search_knowledge", {"query": query}))
        allowed = {
            doc.source_id: doc for doc in self.knowledge.search(role, query)
        }
        documents = []
        for item in result.get("documents", []):
            document = allowed.get(item.get("source_id"))
            if document is None or item.get("version") != document.version:
                raise RuntimeError("MCP-источник не прошёл проверку роли и версии")
            documents.append(document)
        return documents

    def calculate_cash_gap(self, manager: RoleContextManager, payload: dict) -> str:
        self._session(manager, Role.BUSINESS)
        data = CashGapInput.model_validate(payload)
        result = asyncio.run(self._call(Role.BUSINESS, "calculate_cash_gap", {
            "amount_due": str(data.amount_due),
            "available": str(data.available),
            "days_until_due": data.days_until_due,
        }))
        answer = result.get("answer")
        if result.get("provenance") != "calculated" or not isinstance(answer, str):
            raise RuntimeError("MCP-расчёт не прошёл проверку происхождения")
        # Доверяем только совпадению с локальным детерминированным расчётом.
        if answer != cash_gap_answer(data):
            raise RuntimeError("MCP-расчёт не совпал с локальной проверкой")
        return answer

    def read(
        self, manager: RoleContextManager, name: str, query: str = ""
    ) -> ToolResult:
        role = self._READ_ROLES.get(name)
        if role is None:
            raise PermissionError("Неизвестный инструмент")
        self._session(manager, role)
        result = asyncio.run(self._call(
            role, "read_demo_data", {"name": name, "query": query}, manager,
        ))
        reference = DemoToolBroker.read(self, manager, name, query)
        expected = {
            "name": reference.name,
            "role": reference.role.value,
            "text": reference.text,
            "source_id": reference.source_id,
            "version": reference.version,
            "verified": reference.verified,
            "provenance": reference.provenance,
        }
        if result != expected:
            raise RuntimeError("MCP-данные не прошли проверку источника и роли")
        return reference
