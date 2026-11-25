export default function ArgsSchemaEditor({ rows, onChange }) {
  function updateRow(index, patch) {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  function addRow() {
    onChange([...rows, { name: '', description: '', required: false }])
  }

  function removeRow(index) {
    onChange(rows.filter((_, i) => i !== index))
  }

  return (
    <div className="args-editor">
      <div className="field-label">Arguments</div>
      {rows.length > 0 && (
        <div className="args-header">
          <span>Name</span>
          <span>Description</span>
          <span>Required</span>
          <span />
        </div>
      )}
      {rows.map((row, i) => (
        <div className="args-row" key={i}>
          <input
            className="nodrag"
            type="text"
            placeholder="order_id"
            value={row.name}
            onChange={(e) => updateRow(i, { name: e.target.value })}
          />
          <input
            className="nodrag"
            type="text"
            placeholder="What this argument is for"
            value={row.description}
            onChange={(e) => updateRow(i, { description: e.target.value })}
          />
          <input
            className="nodrag"
            type="checkbox"
            checked={!!row.required}
            onChange={(e) => updateRow(i, { required: e.target.checked })}
          />
          <button type="button" className="icon-btn danger nodrag" onClick={() => removeRow(i)} title="Remove argument">
            ×
          </button>
        </div>
      ))}
      <button type="button" className="link-btn nodrag" onClick={addRow}>
        + Add argument
      </button>
    </div>
  )
}
