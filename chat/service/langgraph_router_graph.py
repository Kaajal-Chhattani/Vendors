"""Explicit StateGraph version of the agent flow drawn in LangGraph-GUI
(vendors_agents_graph.json): route -> agent (support | complaints | dynamic) -> END.

Reuses route_agent / get_agent_graph from langgraph_agents, so prompts, tools and
guardrails are the same as the existing agents. Nothing in that module is changed.
"""

from typing import Optional

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph

from chat.service.langgraph_agents import DEFAULT_AGENT_TYPE, get_agent_graph, route_agent


class RouterState(MessagesState):
    agent_type: Optional[str]


def route_node(state: RouterState, config: RunnableConfig):
    """Pick the agent for the latest user message (skipped if the caller already chose one)."""
    if state.get("agent_type"):
        return {}
    configurable = config["configurable"]
    last = state["messages"][-1]
    text = last.content if hasattr(last, "content") else last["content"]
    agent_type = route_agent(
        text,
        configurable["company"],
        has_file=bool(configurable.get("file_paths")),
        current_agent=configurable.get("current_agent"),
    )
    return {"agent_type": agent_type}


def agent_node(state: RouterState, config: RunnableConfig):
    """Run the chosen agent (built-in or database-defined) on the conversation."""
    agent_type = state.get("agent_type") or DEFAULT_AGENT_TYPE
    result = get_agent_graph(agent_type).invoke({"messages": state["messages"]}, config=config)
    return {"messages": result["messages"][len(state["messages"]):]}


_router_graph = None


def get_router_graph():
    global _router_graph
    if _router_graph is None:
        _router_graph = build_router_graph()
    return _router_graph


def build_router_graph():
    graph = StateGraph(RouterState)
    graph.add_node("route", route_node)
    graph.add_node("agent", agent_node)
    graph.add_edge(START, "route")
    graph.add_edge("route", "agent")
    graph.add_edge("agent", END)
    return graph.compile()
