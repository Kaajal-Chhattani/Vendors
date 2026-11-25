import requests
from django.conf import settings
from chat.service.langgraph_agents import DEFAULT_AGENT_TYPE, is_valid_agent_type, run_agent


def call_deepseek(messages, tools=None):
    payload = {"model": "deepseek-chat", "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]


def generate_reply(conversation, text, company, file_paths=None):
    agent_type = conversation.agent_type if is_valid_agent_type(conversation.agent_type) else DEFAULT_AGENT_TYPE
    return run_agent(agent_type, conversation, text, company, file_paths=file_paths)
