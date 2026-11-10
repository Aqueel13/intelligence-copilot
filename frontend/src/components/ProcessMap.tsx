import dagre from '@dagrejs/dagre'
import {
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  getBezierPath,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import { useMemo, useState } from 'react'
import type { ActivityStats, ProcessMap as ProcessMapData } from '../api/client'
import { formatCount, formatHours, formatPercent } from '../lib/format'
import { StatusBadge, TableView } from './ui'

export type MapMode = 'frequency' | 'time'

const NODE_W = 166
const NODE_H = 86
const TERMINAL_W = 76
const TERMINAL_H = 34
const LABEL_MIN_SHARE = 0.05 // label only edges carrying ≥ 5% of cases

interface ActivityNodeData extends Record<string, unknown> {
  name: string
  kind: string
  instances: number
  cases: number
  meanWait: number
  mode: MapMode
  bottleneck: boolean
  totalCases: number
}

const hidden = '!h-1.5 !w-1.5 !border-0 !bg-transparent'

function TerminalNode({ data }: NodeProps<Node<ActivityNodeData>>) {
  return (
    <div
      className="flex items-center justify-center rounded-full border border-axis bg-surface text-[11px] font-semibold text-ink-2"
      style={{ width: TERMINAL_W, height: TERMINAL_H }}
      title={`${data.name}: ${formatCount(data.instances)} claims`}
    >
      <Handle id="in" type="target" position={Position.Left} className={hidden} />
      {data.name}
      <Handle id="out" type="source" position={Position.Right} className={hidden} />
    </div>
  )
}

function ActivityNode({ data, selected }: NodeProps<Node<ActivityNodeData>>) {
  const customer = data.kind === 'customer_wait'
  return (
    <div
      className={`rounded-lg border bg-surface px-3 py-2 text-left shadow-sm ${
        data.bottleneck ? 'border-critical border-2' : selected ? 'border-series-1' : 'border-hairline'
      } ${customer ? 'bg-ghost' : ''}`}
      style={{ width: NODE_W, height: NODE_H }}
    >
      <Handle id="in" type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-axis" />
      <Handle id="back-in" type="target" position={Position.Top} className={hidden} />
      <Handle id="back-out" type="source" position={Position.Top} className={hidden} />
      <div className="line-clamp-2 text-xs font-semibold leading-tight text-ink" title={data.name}>
        {data.name}
      </div>
      <div className="tabular mt-0.5 text-[11px] text-ink-2">
        {data.mode === 'frequency'
          ? `${formatCount(data.instances)}× · ${formatPercent(data.cases / data.totalCases, 0)} of claims`
          : customer
            ? 'Customer time'
            : `waits ${formatHours(data.meanWait)} on average`}
      </div>
      <div className="mt-1 min-h-4">
        {data.bottleneck && <StatusBadge status="critical" label="Bottleneck" />}
        {customer && <span className="text-[11px] text-ink-muted">Waiting on customer</span>}
      </div>
      <Handle id="out" type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-axis" />
    </div>
  )
}

const nodeTypes = { activity: ActivityNode, terminal: TerminalNode }

type Point = { x: number; y: number }
type RoutedEdgeData = { waypoints: Point[]; text?: string }

/** Forward edge drawn along dagre's route (which goes around nodes, not through them). */
function RoutedEdge(props: EdgeProps<Edge<RoutedEdgeData>>) {
  const { sourceX, sourceY, targetX, targetY, data, markerEnd, style, interactionWidth } = props
  const waypoints = data?.waypoints ?? []
  let path: string
  let label: Point
  if (waypoints.length === 0) {
    const [d, lx, ly] = getBezierPath(props)
    path = d
    label = { x: lx, y: ly }
  } else {
    // Smooth polyline: straight into each waypoint's midpoint, quadratic curve around it.
    const pts = [{ x: sourceX, y: sourceY }, ...waypoints, { x: targetX, y: targetY }]
    const mid = (a: Point, b: Point) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })
    const m0 = mid(pts[0], pts[1])
    path = `M ${pts[0].x} ${pts[0].y} L ${m0.x} ${m0.y}`
    for (let i = 1; i < pts.length - 1; i++) {
      const m = mid(pts[i], pts[i + 1])
      path += ` Q ${pts[i].x} ${pts[i].y} ${m.x} ${m.y}`
    }
    path += ` L ${targetX} ${targetY}`
    label = waypoints[Math.floor(waypoints.length / 2)]
  }
  return (
    <>
      <BaseEdge path={path} markerEnd={markerEnd} style={style} interactionWidth={interactionWidth} />
      {data?.text && (
        <EdgeLabelRenderer>
          <div
            className="tabular pointer-events-none absolute rounded bg-surface px-1 text-[11px] text-ink-2"
            style={{ transform: `translate(-50%, -50%) translate(${label.x}px, ${label.y}px)` }}
          >
            {data.text}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

const edgeTypes = { routed: RoutedEdge }

const size = (n: Node) =>
  n.type === 'terminal' ? { width: TERMINAL_W, height: TERMINAL_H } : { width: NODE_W, height: NODE_H }

/** Left-to-right layout. Forward edges follow dagre's routes (around nodes); edges that
 *  point backwards (loops) arc over the top between the nodes' top handles. */
function layout(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 64, ranksep: 36, marginx: 8, marginy: 40 })
  g.setDefaultEdgeLabel(() => ({}))
  nodes.forEach((n) => g.setNode(n.id, size(n)))
  edges.forEach((e) => g.setEdge(e.source, e.target))
  dagre.layout(g)
  const placed = nodes.map((n) => {
    const p = g.node(n.id)
    const { width, height } = size(n)
    return { ...n, position: { x: p.x - width / 2, y: p.y - height / 2 } }
  })
  const x = Object.fromEntries(placed.map((n) => [n.id, n.position.x]))
  const routed = edges.map((e): Edge => {
    if (x[e.target] < x[e.source]) {
      return { ...e, sourceHandle: 'back-out', targetHandle: 'back-in', zIndex: 1 }
    }
    // dagre's first/last points sit on node borders; we use the handles as endpoints instead.
    const points: Point[] = g.edge(e.source, e.target)?.points ?? []
    return {
      ...e,
      type: 'routed',
      sourceHandle: 'out',
      targetHandle: 'in',
      label: undefined,
      data: { waypoints: points.slice(1, -1), text: typeof e.label === 'string' ? e.label : undefined },
    }
  })
  return { nodes: placed, edges: routed }
}

type Hovered =
  | { type: 'node'; id: string }
  | { type: 'edge'; source: string; target: string }
  | null

export function ProcessMap({
  data,
  activities,
  mode,
}: {
  data: ProcessMapData
  activities: ActivityStats[]
  mode: MapMode
}) {
  const [hovered, setHovered] = useState<Hovered>(null)
  const bottlenecks = useMemo(
    () => new Set(activities.filter((a) => a.is_bottleneck).map((a) => a.activity)),
    [activities],
  )

  const { nodes, edges } = useMemo(() => {
    const maxT = Math.max(...data.edges.map((e) => e.transitions), 1)
    const flowEdges: Edge[] = data.edges.map((e) => {
      const share = e.cases / data.cases
      const width = 1 + 3 * Math.sqrt(e.transitions / maxT)
      const label =
        share >= LABEL_MIN_SHARE
          ? mode === 'frequency'
            ? formatCount(e.transitions)
            : formatHours(e.median_hours)
          : undefined
      return {
        id: `${e.source}→${e.target}`,
        source: e.source,
        target: e.target,
        label,
        labelStyle: { fill: 'var(--ink-2)', fontSize: 11 },
        labelBgStyle: { fill: 'var(--surface)' },
        labelBgPadding: [4, 2] as [number, number],
        style: { stroke: 'var(--ink-muted)', strokeWidth: width },
        markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--ink-muted)', width: 14, height: 14 },
        interactionWidth: 24, // hit target bigger than the mark
      }
    })
    const terminals = new Set([
      ...Object.keys(data.start_activities),
      ...Object.keys(data.end_activities),
    ])
    const flowNodes: Node<ActivityNodeData>[] = data.nodes.map((n) => ({
      id: n.activity,
      type: terminals.has(n.activity) ? 'terminal' : 'activity',
      position: { x: 0, y: 0 },
      data: {
        name: n.activity,
        kind: n.kind,
        instances: n.instances,
        cases: n.cases,
        meanWait: n.mean_wait_hours,
        mode,
        bottleneck: bottlenecks.has(n.activity),
        totalCases: data.cases,
      },
      ariaLabel: `${n.activity}: ${n.instances} occurrences, mean wait ${formatHours(n.mean_wait_hours)}`,
    }))
    return layout(flowNodes, flowEdges)
  }, [data, mode, bottlenecks])

  return (
    <div>
      <div className="h-[380px] overflow-hidden rounded-lg border border-hairline">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          fitViewOptions={{ padding: 0.04, maxZoom: 1 }}
          nodesDraggable={false}
          nodesConnectable={false}
          minZoom={0.3}
          proOptions={{ hideAttribution: true }}
          onNodeMouseEnter={(_, n) => setHovered({ type: 'node', id: n.id })}
          onEdgeMouseEnter={(_, e) => setHovered({ type: 'edge', source: e.source, target: e.target })}
          onPaneMouseEnter={() => setHovered(null)}
        >
          <Background color="var(--grid)" gap={24} size={1} />
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>
      </div>
      <HoverDetail hovered={hovered} data={data} activities={activities} />
      <TableView
        caption="Process transitions"
        columns={['From', 'To', 'Transitions', 'Claims', 'Median time', 'Mean time']}
        rows={data.edges.map((e) => [
          e.source,
          e.target,
          formatCount(e.transitions),
          formatCount(e.cases),
          formatHours(e.median_hours),
          formatHours(e.mean_hours),
        ])}
      />
    </div>
  )
}

function HoverDetail({
  hovered,
  data,
  activities,
}: {
  hovered: Hovered
  data: ProcessMapData
  activities: ActivityStats[]
}) {
  let content = <span className="text-ink-muted">Hover an activity or a transition for details.</span>
  if (hovered?.type === 'node') {
    const n = data.nodes.find((x) => x.activity === hovered.id)
    const a = activities.find((x) => x.activity === hovered.id)
    if (n)
      content = (
        <>
          <b className="text-ink">{n.activity}</b> · {formatCount(n.instances)} occurrences in{' '}
          {formatCount(n.cases)} claims · mean wait {formatHours(n.mean_wait_hours)} · mean work{' '}
          {formatHours(n.mean_work_hours)}
          {a && (
            <>
              {' '}
              · claims with it breach {formatPercent(a.breach_rate_with)}
              {a.breach_rate_without !== null && <> vs {formatPercent(a.breach_rate_without)} without</>}
            </>
          )}
        </>
      )
  } else if (hovered?.type === 'edge') {
    const e = data.edges.find((x) => x.source === hovered.source && x.target === hovered.target)
    if (e)
      content = (
        <>
          <b className="text-ink">
            {e.source} → {e.target}
          </b>{' '}
          · {formatCount(e.transitions)} transitions in {formatCount(e.cases)} claims · median{' '}
          {formatHours(e.median_hours)} · mean {formatHours(e.mean_hours)}
        </>
      )
  }
  return (
    <p className="mt-2 min-h-5 text-xs text-ink-2" aria-live="polite">
      {content}
    </p>
  )
}
