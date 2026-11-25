import { Handle, Position } from '@xyflow/react'
import ArgsSchemaEditor from '../components/ArgsSchemaEditor.jsx'

export default function ToolNode({ data }) {
  const { tool, onChange, onSave, onDelete, saving } = data

  function stop(e) {
    e.stopPropagation()
  }

  return (
    <div className="flow-node tool-node">
      <Handle type="target" position={Position.Left} id="agents" className="flow-handle" />

      <div className="node-kind">TOOL</div>
      <button
        type="button"
        className="node-delete nodrag"
        onClick={(e) => {
          stop(e)
          onDelete(tool.id)
        }}
        title="Delete tool"
      >
        ×
      </button>

      <label className="field">
        <span className="field-label">Name</span>
        <input className="nodrag" type="text" value={tool.name} onChange={(e) => onChange({ name: e.target.value })} />
      </label>

      <label className="field">
        <span className="field-label">Description</span>
        <textarea className="nodrag nowheel" rows={2} value={tool.description} onChange={(e) => onChange({ description: e.target.value })} />
      </label>

      <div className="field-row">
        <label className="field grow">
          <span className="field-label">Endpoint URL</span>
          <input className="nodrag" type="url" value={tool.endpoint_url} onChange={(e) => onChange({ endpoint_url: e.target.value })} />
        </label>
        <label className="field">
          <span className="field-label">Method</span>
          <select className="nodrag" value={tool.http_method} onChange={(e) => onChange({ http_method: e.target.value })}>
            <option value="GET">GET</option>
            <option value="POST">POST</option>
          </select>
        </label>
      </div>

      <ArgsSchemaEditor rows={tool.args_schema} onChange={(rows) => onChange({ args_schema: rows })} />

      <label className="field-inline nodrag">
        <input type="checkbox" checked={tool.is_active} onChange={(e) => onChange({ is_active: e.target.checked })} />
        <span>Active</span>
      </label>

      <button type="button" className="primary-btn small nodrag" disabled={saving} onClick={() => onSave(tool.id)}>
        {saving ? 'Saving…' : 'Save'}
      </button>
    </div>
  )
}
