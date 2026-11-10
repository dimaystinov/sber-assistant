import json

import httpx

from assistant.domain import Role
from assistant.gigachat import GigaChatClient


def test_langchain_adapter_sends_only_role_context():
    from langchain_core.messages import AIMessage
    from assistant.gigachat import GigaChatLangChainClient

    class FakeLLM:
        def __init__(self):
            self.messages = None

        def invoke(self, messages):
            self.messages = messages
            return AIMessage(content="Проверенный ответ", usage_metadata={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8})

    llm = FakeLLM()
    result = GigaChatLangChainClient(llm).chat(Role.BUSINESS, "Что делать?", "Оборот: 100")
    assert result.content == "Проверенный ответ"
    assert result.tokens_used == 8
    assert "biz_ns" in llm.messages[0].content
    assert "Оборот: 100" in llm.messages[0].content
    assert llm.messages[1].content == "Что делать?"


def test_online_chat_exchanges_key_and_calls_model():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/v2/oauth":
            assert request.headers["authorization"] == "Basic test-key"
            assert b"scope=GIGACHAT_API_PERS" in request.content
            assert request.headers["rquid"]
            return httpx.Response(200, json={"access_token": "short-token", "expires_at": 9999999999})
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer short-token"
        body = json.loads(request.content)
        assert body["model"] == "GigaChat-2"
        assert body["messages"][0]["role"] == "system"
        assert "biz_ns" in body["messages"][0]["content"]
        assert "предположения" in body["messages"][0]["content"]
        assert body["messages"][1] == {"role": "user", "content": "Помоги с кредитом"}
        return httpx.Response(200, json={"choices": [{"message": {"content": "Ответ"}}], "usage": {"total_tokens": 12}})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = GigaChatClient(mode="online", credentials="test-key", http_client=http,
                            model="GigaChat-2")
    first = client.chat(Role.BUSINESS, "Помоги с кредитом")
    second = client.chat(Role.BUSINESS, "Помоги с кредитом")
    assert first.content == second.content == "Ответ"
    assert first.tokens_used == 12
    assert [request.url.path for request in requests].count("/api/v2/oauth") == 1
