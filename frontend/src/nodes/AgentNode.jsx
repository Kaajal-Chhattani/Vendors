import { Handle, Position } from '@xyflow/react'

export default function AgentNode({ data }) {
  const { agent, onChange, onSave, onDelete, saving } = data

  function stop(e) {
    e.stopPropagation()
  }

  return (
    <div className="flow-node agent-node">
      <Handle type="target" position={Position.Top} id="delegator" className="flow-handle" />
      <div className="node-kind">AGENT</div>
      <button
        type="button"
        className="node-delete nodrag"
        onClick={(e) => {
          stop(e)
          onDelete(agent.id)
        }}
        title="Delete agent"
      >
        ×
      </button>

      <label className="field">
        <span className="field-label">Label</span>
        <input className="nodrag" type="text" value={agent.label} onChange={(e) => onChange({ label: e.target.value })} />
      </label>

      <label className="field">
        <span className="field-label">Agent type</span>
        <input className="nodrag" type="text" value={agent.agent_type} onChange={(e) => onChange({ agent_type: e.target.value })} />
      </label>

      <label className="field">
        <span className="field-label">Description</span>
        <input className="nodrag" type="text" value={agent.description} onChange={(e) => onChange({ description: e.target.value })} />
      </label>

      <label className="field">
        <span className="field-label">Prompt</span>
        <textarea className="nodrag nowheel" rows={2} value={agent.prompt} onChange={(e) => onChange({ prompt: e.target.value })} />
      </label>

      <label className="field-inline nodrag">
        <input type="checkbox" checked={agent.is_active} onChange={(e) => onChange({ is_active: e.target.checked })} />
        <span>Active</span>
      </label>

      <button type="button" className="primary-btn small nodrag" disabled={saving} onClick={() => onSave(agent.id)}>
        {saving ? 'Saving…' : 'Save'}
      </button>

      <Handle type="source" position={Position.Right} id="tools" className="flow-handle" />
      <Handle type="source" position={Position.Bottom} id="delegate" className="flow-handle" />
    </div>
  )
}
