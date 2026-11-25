# Multi-agent links — brief

## Problem Statement
Agents (LangGraph `create_react_agent`, `chat/service/langgraph_agents.py`) are standalone. We want one agent to delegate to other agents, and to wire that up visually in the React flow UI (`frontend/src/App.jsx`, `AgentNode.jsx`).

## Users
Admins who build agents in the React canvas; end users chatting see the delegation trace.

## Inputs
- Edge drawn agent -> agent in the React canvas (parent -> child).
- Existing Agent fields (prompt, tools, is_active, company).

## Outputs
- Parent agent gets one tool per linked child (name/description from child's agent_type/description). Calling it runs the child's graph and returns its final reply to the parent.
- Chat UI shows which sub-agents were called (delegation trace).

## Decisions
| Topic | Decision |
|---|---|
| Invocation | Sub-agent as a tool (parent stays in control) |
| Storage | New M2M `Agent.linked_agents` (self, asymmetric) + migration; saved via existing agent API |
| UI | Edges on the React canvas create/remove links; DB-defined agents only (built-in `support`/`complaints` not linkable in v1) |
| Cycles | Rejected on save (API + UI) and guarded at runtime |
| Depth | Runtime max delegation depth 3 |
| Config | Child receives parent's `configurable` (company, file_paths, conversation) |
| Routing | `route_agent` only offers top-level agents; any agent that is a child of another is hidden from the router |
| Trace | Child calls recorded and shown in chat UI |

## Operational
Graph cache `_agent_graph_cache` must be invalidated when links, prompts or tools change (children are baked into the parent graph). Each delegation = extra LLM calls; depth cap bounds cost.

## Acceptance Criteria
1. Draw edge A -> B in canvas, save, reload: edge persists.
2. Chat with A: A can call B and uses its answer; trace shows B.
3. Drawing B -> A (cycle) is rejected with a clear message.
4. A chain deeper than 3 stops with a tool error, not a crash.
5. B can read the same CSV/documents as A when called by A.
6. Auto routing never selects a child-only agent directly.

## Out of Scope
Handoff mode, linking built-in agents, per-link settings, parallel delegation.

## Constraints
Stay in existing stack (Django, LangGraph, React Flow). No data entered by me; schema/code only.

## Open Questions
- Hiding children from the router means a child can't be used standalone via Auto (still selectable manually?). Assumed yes.
- Inactive child: skip its tool silently. Assumed.
