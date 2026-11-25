import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ReactFlow, ReactFlowProvider, Background, Controls, MiniMap } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from './api.js'
import AgentNode from './nodes/AgentNode.jsx'
import ToolNode from './nodes/ToolNode.jsx'
import DeletableEdge from './edges/DeletableEdge.jsx'

const nodeTypes = { agent: AgentNode, tool: ToolNode }
const edgeTypes = { deletable: DeletableEdge }

const AGENT_COL_X = 40
const TOOL_COL_X = 620
const ROW_HEIGHT = 320

const agentNodeId = (id) => `agent-${id}`
const toolNodeId = (id) => `tool-${id}`

function buildEdges(agents) {
  const edges = []
  for (const agent of agents) {
    for (const tool of agent.tools) {
      edges.push({
        id: `e-${agent.id}-${tool.id}`,
        source: agentNodeId(agent.id),
        sourceHandle: 'tools',
        target: toolNodeId(tool.id),
        targetHandle: 'agents',
        type: 'deletable',
      })
    }
    for (const child of agent.linked_agents || []) {
      edges.push({
        id: `l-${agent.id}-${child.id}`,
        source: agentNodeId(agent.id),
        sourceHandle: 'delegate',
        target: agentNodeId(child.id),
        targetHandle: 'delegator',
        label: 'delegates to',
        animated: true,
        type: 'deletable',
      })
    }
  }
  return edges
}

const NEW_AGENT = 'new'
const emptyToolDraft = () => ({ name: '', description: '', endpoint_url: 'https://', http_method: 'POST', args_schema: [], is_active: true })
const emptyDraft = () => ({ label: '', agent_type: '', description: '', prompt: '', is_active: true })

// The selected agent, its tools and its sub-agents: what its own canvas shows.
function graphItems(agent, tools, agents) {
  const items = [{ id: agentNodeId(agent.id), type: 'agent', ref: agent, fallback: { x: AGENT_COL_X, y: 40 } }]
  agent.tools.forEach((t, i) => {
    items.push({ id: toolNodeId(t.id), type: 'tool', ref: tools.find((x) => x.id === t.id), fallback: { x: TOOL_COL_X, y: 40 + i * ROW_HEIGHT } })
  })
  ;(agent.linked_agents || []).forEach((a, i) => {
    items.push({ id: agentNodeId(a.id), type: 'agent', ref: agents.find((x) => x.id === a.id), fallback: { x: AGENT_COL_X, y: 40 + (i + 1) * ROW_HEIGHT } })
  })
  return items.filter((it) => it.ref)
}

function flowNode(it, posOf) {
  const data = it.type === 'agent' ? { label: it.ref.label, agent_type: it.ref.agent_type } : { name: it.ref.name }
  return { id: it.id, type: it.type, position: posOf(it.id, it.fallback), data }
}

function flowEdges(agents) {
  return buildEdges(agents).map(({ id, source, sourceHandle, target, targetHandle }) => ({ id, source, sourceHandle, target, targetHandle }))
}

function FlowCanvas() {
  const [selectedId, setSelectedId] = useState(NEW_AGENT)
  const [draft, setDraft] = useState(emptyDraft)
  const [toolDraft, setToolDraft] = useState(null)
  const [agents, setAgents] = useState([])
  const [tools, setTools] = useState([])
  const [positions, setPositions] = useState({})
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [savingIds, setSavingIds] = useState({})
  const firstLoad = useRef(false)

  const load = useCallback(async () => {
    setLoadError('')
    try {
      const [agentsRes, toolsRes] = await Promise.all([api.listAgents(), api.listTools()])
      setAgents(agentsRes.agents)
      setTools(toolsRes.tools)
      setSelectedId((cur) => {
        if (cur === NEW_AGENT && !firstLoad.current) return agentsRes.agents[0]?.id ?? NEW_AGENT
        return cur === NEW_AGENT || agentsRes.agents.some((a) => a.id === cur) ? cur : NEW_AGENT
      })
      firstLoad.current = true
    } catch (e) {
      setLoadError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const selectedAgent = agents.find((a) => a.id === selectedId) || null

  const savedPositions = useMemo(
    () => Object.fromEntries(((selectedAgent && selectedAgent.workflow_json && selectedAgent.workflow_json.nodes) || []).map((n) => [n.id, n.position])),
    [selectedAgent],
  )
  const posOf = (id, fallback) => positions[id] || savedPositions[id] || fallback

  // React Flow shaped JSON of one agent's canvas, saved into Agent.workflow_json.
  function agentWorkflow(agent, extraTools = []) {
    const items = graphItems(agent, [...tools, ...extraTools], agents)
    return { nodes: items.map((it) => flowNode(it, posOf)), edges: flowEdges([agent]) }
  }

  // Same idea for a tool: the tool node plus the agents using it.
  function toolWorkflow(tool) {
    const toolId = toolNodeId(tool.id)
    const nodes = [{ id: toolId, type: 'tool', position: positions[toolId] || { x: TOOL_COL_X, y: 40 }, data: { name: tool.name } }]
    const edges = []
    ;(tool.agents || []).forEach((a, i) => {
      const id = agentNodeId(a.id)
      nodes.push({ id, type: 'agent', position: positions[id] || { x: AGENT_COL_X, y: 40 + i * ROW_HEIGHT }, data: { label: a.label } })
      edges.push({ id: `e-${a.id}-${tool.id}`, source: id, sourceHandle: 'tools', target: toolId, targetHandle: 'agents' })
    })
    return { nodes, edges }
  }

  function patchAgentLocal(id, patch) {
    setAgents((prev) => prev.map((a) => (a.id === id ? { ...a, ...patch } : a)))
  }
  function patchToolLocal(id, patch) {
    setTools((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)))
  }

  async function saveAgent(id) {
    const agent = agents.find((a) => a.id === id)
    setSavingIds((s) => ({ ...s, [agentNodeId(id)]: true }))
    try {
      await api.updateAgent(id, {
        label: agent.label,
        agent_type: agent.agent_type,
        description: agent.description,
        prompt: agent.prompt,
        is_active: agent.is_active,
        workflow_json: agentWorkflow(agent),
      })
      await load()
    } catch (e) {
      alert(e.message)
    } finally {
      setSavingIds((s) => ({ ...s, [agentNodeId(id)]: false }))
    }
  }

  async function saveTool(id) {
    const tool = tools.find((t) => t.id === id)
    setSavingIds((s) => ({ ...s, [toolNodeId(id)]: true }))
    try {
      await api.updateTool(id, {
        name: tool.name,
        description: tool.description,
        endpoint_url: tool.endpoint_url,
        http_method: tool.http_method,
        args_schema: tool.args_schema,
        workflow_json: toolWorkflow(tool),
        is_active: tool.is_active,
      })
      await load()
    } catch (e) {
      alert(e.message)
    } finally {
      setSavingIds((s) => ({ ...s, [toolNodeId(id)]: false }))
    }
  }

  async function deleteAgent(id) {
    if (!confirm('Delete this agent?')) return
    await api.deleteAgent(id)
    await load()
  }
  async function deleteTool(id) {
    if (!confirm('Delete this tool?')) return
    await api.deleteTool(id)
    await load()
  }

  // "New agent" canvas: the row is only created when Save is clicked.
  async function saveDraft() {
    setSavingIds((s) => ({ ...s, [agentNodeId(NEW_AGENT)]: true }))
    try {
      const created = await api.createAgent({ ...draft })
      const position = positions[agentNodeId(NEW_AGENT)] || { x: AGENT_COL_X, y: 40 }
      await api.updateAgent(created.id, {
        workflow_json: { nodes: [{ id: agentNodeId(created.id), type: 'agent', position, data: { label: created.label, agent_type: created.agent_type } }], edges: [] },
      })
      setDraft(emptyDraft())
      setSelectedId(created.id)
      await load()
    } catch (e) {
      alert(e.message)
    } finally {
      setSavingIds((s) => ({ ...s, [agentNodeId(NEW_AGENT)]: false }))
    }
  }

  // "+ Tool" only opens an unsaved draft node; the row is created when its Save is clicked.
  function addTool() {
    if (selectedAgent && !toolDraft) setToolDraft(emptyToolDraft())
  }

  async function saveToolDraft() {
    const name = (toolDraft.name || '').trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '')
    if (!name) {
      alert('Enter a tool name first')
      return
    }
    const key = toolNodeId(NEW_AGENT)
    setSavingIds((s) => ({ ...s, [key]: true }))
    try {
      const created = await api.createTool({ ...toolDraft, name, agent_ids: [selectedAgent.id] })
      const agent = { ...selectedAgent, tools: [...selectedAgent.tools, { id: created.id, name: created.name }] }
      const toolPos = positions[key]
      if (toolPos) setPositions((p) => ({ ...p, [toolNodeId(created.id)]: toolPos }))
      await api.updateAgent(agent.id, { workflow_json: agentWorkflow(agent, [created]) })
      setToolDraft(null)
      await load()
    } catch (e) {
      alert(e.message)
    } finally {
      setSavingIds((s) => ({ ...s, [key]: false }))
    }
  }

  async function connectTool(agentId, toolId) {
    const agent = agents.find((a) => a.id === agentId)
    const tool = tools.find((t) => t.id === toolId)
    if (!agent || !tool || agent.tools.some((t) => t.id === toolId)) return
    const next = { ...agent, tools: [...agent.tools, { id: tool.id, name: tool.name }] }
    await api.updateAgent(agentId, { tool_ids: next.tools.map((t) => t.id), workflow_json: agentWorkflow(next) })
    await load()
  }

  async function connectAgent(parentId, childId) {
    const parent = agents.find((a) => a.id === parentId)
    const child = agents.find((a) => a.id === childId)
    if (!parent || !child || parentId === childId || (parent.linked_agents || []).some((a) => a.id === childId)) return
    const next = { ...parent, linked_agents: [...(parent.linked_agents || []), { id: child.id, label: child.label }] }
    try {
      await api.updateAgent(parentId, { linked_agent_ids: next.linked_agents.map((a) => a.id), workflow_json: agentWorkflow(next) })
    } catch (e) {
      alert(e.message)
    }
    await load()
  }

  const nodes = useMemo(() => {
    if (!selectedAgent) {
      const id = agentNodeId(NEW_AGENT)
      return [{
        id,
        type: 'agent',
        position: positions[id] || { x: AGENT_COL_X, y: 40 },
        data: {
          agent: { id: NEW_AGENT, ...draft },
          onChange: (patch) => setDraft((d) => ({ ...d, ...patch })),
          onSave: saveDraft,
          onDelete: () => setDraft(emptyDraft()),
          saving: !!savingIds[id],
        },
      }]
    }
    const draftToolNode = toolDraft ? [{
      id: toolNodeId(NEW_AGENT),
      type: 'tool',
      position: positions[toolNodeId(NEW_AGENT)] || { x: TOOL_COL_X, y: 40 + selectedAgent.tools.length * ROW_HEIGHT },
      data: {
        tool: { id: NEW_AGENT, ...toolDraft },
        onChange: (patch) => setToolDraft((d) => ({ ...d, ...patch })),
        onSave: saveToolDraft,
        onDelete: () => setToolDraft(null),
        saving: !!savingIds[toolNodeId(NEW_AGENT)],
      },
    }] : []
    const real = graphItems(selectedAgent, tools, agents).map((it) => {
      const base = { id: it.id, type: it.type, position: posOf(it.id, it.fallback) }
      if (it.type === 'agent') {
        const agent = it.ref
        return {
          ...base,
          data: {
            agent,
            onChange: (patch) => patchAgentLocal(agent.id, patch),
            onSave: saveAgent,
            onDelete: deleteAgent,
            saving: !!savingIds[it.id],
          },
        }
      }
      const tool = it.ref
      return {
        ...base,
        data: {
          tool,
          onChange: (patch) => patchToolLocal(tool.id, patch),
          onSave: saveTool,
          onDelete: deleteTool,
          saving: !!savingIds[it.id],
        },
      }
    })
    return [...real, ...draftToolNode]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents, tools, positions, savingIds, selectedAgent, draft, toolDraft, savedPositions])

  const edges = useMemo(() => (selectedAgent ? buildEdges([selectedAgent]) : []), [selectedAgent])

  const onNodesChange = useCallback((changes) => {
    setPositions((prev) => {
      let next = prev
      for (const change of changes) {
        if (change.type === 'position' && change.position) {
          if (next === prev) next = { ...prev }
          next[change.id] = change.position
        }
      }
      return next
    })
  }, [])

  async function onConnect(connection) {
    const { source, target } = connection
    if (source?.startsWith('agent-') && target?.startsWith('agent-')) {
      await connectAgent(Number(source.replace('agent-', '')), Number(target.replace('agent-', '')))
      return
    }
    if (!source?.startsWith('agent-') || !target?.startsWith('tool-')) return
    await connectTool(Number(source.replace('agent-', '')), Number(target.replace('tool-', '')))
  }

  async function onEdgesDelete(deleted) {
    for (const edge of deleted) {
      const agentId = Number(edge.source.replace('agent-', ''))
      const agent = agents.find((a) => a.id === agentId)
      if (!agent) continue
      if (edge.target.startsWith('agent-')) {
        const childId = Number(edge.target.replace('agent-', ''))
        const next = { ...agent, linked_agents: (agent.linked_agents || []).filter((a) => a.id !== childId) }
        await api.updateAgent(agentId, { linked_agent_ids: next.linked_agents.map((a) => a.id), workflow_json: agentWorkflow(next) })
        continue
      }
      const toolId = Number(edge.target.replace('tool-', ''))
      const next = { ...agent, tools: agent.tools.filter((t) => t.id !== toolId) }
      await api.updateAgent(agentId, { tool_ids: next.tools.map((t) => t.id), workflow_json: agentWorkflow(next) })
    }
    await load()
  }

  async function onNodesDelete(deleted) {
    for (const node of deleted) {
      if (node.id.startsWith('agent-')) {
        await api.deleteAgent(Number(node.id.replace('agent-', '')))
      } else if (node.id.startsWith('tool-')) {
        await api.deleteTool(Number(node.id.replace('tool-', '')))
      }
    }
    await load()
  }

  if (loading) return <div className="page-status">Loading…</div>
  if (loadError) return <div className="page-status error">{loadError}</div>

  return (
    <div className="flow-page">
      <header className="flow-toolbar">
        <div>
          <h1>Workflows</h1>
          <p>Drag from an agent's right dot to a tool's dot to connect them, or from its bottom dot to another agent's top dot to let it delegate to that agent. Select a connection and press Delete to remove it.</p>
        </div>
        <div className="flow-toolbar-actions">
          <select value={selectedId} onChange={(e) => {
            setToolDraft(null)
            setSelectedId(e.target.value === NEW_AGENT ? NEW_AGENT : Number(e.target.value))
          }}>
            <option value={NEW_AGENT}>+ New agent</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>{a.label || a.agent_type}</option>
            ))}
          </select>
          {selectedAgent && (
            <>
              <select value="" onChange={(e) => e.target.value && connectTool(selectedAgent.id, Number(e.target.value))}>
                <option value="">Attach existing tool…</option>
                {tools.filter((t) => !selectedAgent.tools.some((x) => x.id === t.id)).map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
              <select value="" onChange={(e) => e.target.value && connectAgent(selectedAgent.id, Number(e.target.value))}>
                <option value="">Delegate to agent…</option>
                {agents.filter((a) => a.id !== selectedAgent.id && !(selectedAgent.linked_agents || []).some((x) => x.id === a.id)).map((a) => (
                  <option key={a.id} value={a.id}>{a.label || a.agent_type}</option>
                ))}
              </select>
              <button type="button" className="primary-btn" onClick={addTool}>+ Tool</button>
            </>
          )}
        </div>
      </header>
      <div className="flow-canvas">
        <ReactFlow
          key={selectedId}
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onConnect={onConnect}
          onEdgesDelete={onEdgesDelete}
          onNodesDelete={onNodesDelete}
          deleteKeyCode={['Backspace', 'Delete']}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap pannable zoomable />
        </ReactFlow>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <ReactFlowProvider>
      <FlowCanvas />
    </ReactFlowProvider>
  )
}
