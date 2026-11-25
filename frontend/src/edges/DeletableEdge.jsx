import { BaseEdge, EdgeLabelRenderer, getBezierPath, useReactFlow } from '@xyflow/react'

export default function DeletableEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, label, animated }) {
  const { deleteElements } = useReactFlow()
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} className={animated ? 'animated' : undefined} />
      <EdgeLabelRenderer>
        <div
          className="edge-actions nodrag nopan"
          style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
        >
          {label && <span className="edge-label">{label}</span>}
          <button
            type="button"
            className="edge-delete"
            title="Remove connection"
            onClick={() => deleteElements({ edges: [{ id }] })}
          >
            ×
          </button>
        </div>
      </EdgeLabelRenderer>
    </>
  )
}
