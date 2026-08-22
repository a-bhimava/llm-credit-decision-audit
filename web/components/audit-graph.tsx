'use client';

import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Handle,
  Position,
  BaseEdge,
  getSmoothStepPath,
  useNodesState,
  useEdgesState,
} from '@xyflow/react';
import type { EdgeProps, NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useMemo, useEffect } from 'react';

type NodeStatus = 'idle' | 'running' | 'done' | 'error';

interface StepNodeData extends Record<string, unknown> {
  label: string;
  sub: string;
  icon: string;
  status: NodeStatus;
}

const STATUS_STYLE: Record<NodeStatus, { border: string; glow: string; dot: string }> = {
  idle:    { border: 'rgba(223,218,255,0.18)', glow: 'none',                             dot: '#4a4870' },
  running: { border: '#82f5ff',                glow: '0 0 28px rgba(130,245,255,0.6)',   dot: '#82f5ff' },
  done:    { border: '#4ade80',                glow: '0 0 20px rgba(74,222,128,0.5)',    dot: '#4ade80' },
  error:   { border: '#f87171',                glow: '0 0 20px rgba(248,113,113,0.5)',   dot: '#f87171' },
};

function StepNode({ data }: NodeProps) {
  const d = data as StepNodeData;
  const s = STATUS_STYLE[d.status];
  return (
    <div style={{
      background: '#121326',
      border: `1.5px solid ${s.border}`,
      borderRadius: 14,
      boxShadow: s.glow,
      padding: '14px 18px',
      minWidth: 200,
      maxWidth: 240,
      fontFamily: 'SFMono-Regular, Consolas, "Liberation Mono", monospace',
      transition: 'border-color 0.4s ease, box-shadow 0.4s ease',
      position: 'relative',
      cursor: 'default',
    }}>
      <Handle type="target" position={Position.Left} style={{ background: '#4a4870', border: 'none', width: 10, height: 10 }} />
      <span style={{
        position: 'absolute', top: 12, right: 14, width: 9, height: 9,
        borderRadius: '50%', background: s.dot,
        boxShadow: d.status === 'running' ? `0 0 8px ${s.dot}` : 'none',
        animation: d.status === 'running' ? 'auditNodePulse 1.2s ease-in-out infinite' : 'none',
        display: 'inline-block',
      }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 24, lineHeight: 1 }}>{d.icon}</span>
        <div>
          <div style={{ color: '#f3f1ff', fontWeight: 700, fontSize: '0.82rem', letterSpacing: '0.03em' }}>
            {d.label}
          </div>
          <div style={{ color: d.status === 'idle' ? '#4a4870' : '#9490b8', fontSize: '0.69rem', marginTop: 3, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
            {d.status === 'running' ? 'Processing...' : d.status === 'done' ? 'Complete' : d.sub}
          </div>
        </div>
      </div>
      <Handle type="source" position={Position.Right} style={{ background: '#82f5ff', border: 'none', width: 10, height: 10 }} />
    </div>
  );
}

function ParticleEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps) {
  const [path] = getSmoothStepPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition, borderRadius: 20 });
  const active = Boolean((data as Record<string, unknown>)?.active);
  return (
    <>
      <BaseEdge id={id} path={path} style={{ stroke: active ? 'rgba(130,245,255,0.55)' : 'rgba(130,245,255,0.12)', strokeWidth: active ? 2 : 1.5, transition: 'stroke 0.4s ease' }} />
      {active && (
        <circle r="5" fill="#82f5ff" style={{ filter: 'drop-shadow(0 0 5px #82f5ff)' }}>
          <animateMotion dur="1.6s" repeatCount="indefinite" path={path} />
        </circle>
      )}
    </>
  );
}

const STEP_DEFS = [
  { id: 'init',    label: 'Initialize',        sub: 'Workflow bootstrap',     icon: '⚡', x: 40,  y: 170 },
  { id: 'budget',  label: 'Reserve Budget',     sub: 'Daily cap check',        icon: '💰', x: 310, y: 60  },
  { id: 'build',   label: 'Build Application',  sub: 'Packet serialization',   icon: '📄', x: 310, y: 280 },
  { id: 'episode', label: 'Run Episode',         sub: 'Gemini LLM evaluation',  icon: '🤖', x: 590, y: 170 },
  { id: 'save',    label: 'Save Results',        sub: 'Trajectory write-back',  icon: '💾', x: 860, y: 60  },
  { id: 'done',    label: 'Complete',            sub: 'Audit finalized',        icon: '✅', x: 860, y: 280 },
];

const EDGE_DEFS = [
  { source: 'init',    target: 'budget'  },
  { source: 'init',    target: 'build'   },
  { source: 'budget',  target: 'episode' },
  { source: 'build',   target: 'episode' },
  { source: 'episode', target: 'save'    },
  { source: 'episode', target: 'done'    },
  { source: 'save',    target: 'done'    },
];

function progressToActiveId(msg: string): string {
  const m = msg.toLowerCase();
  if (m.includes('complet') || m.includes('finaliz') || m.includes('success')) return 'done';
  if (m.includes('baseline') || m.includes('saving') || m.includes('saved'))   return 'save';
  if (m.includes('running') || m.includes('trial') || m.includes('evaluat') || m.includes('gemini') || m.includes('episode')) return 'episode';
  if (m.includes('build') || m.includes('packet') || m.includes('serial'))     return 'build';
  if (m.includes('budget') || m.includes('reserv'))                             return 'budget';
  return 'init';
}

function buildNodes(liveProgress: string, isDone: boolean) {
  const activeId = progressToActiveId(liveProgress);
  const activeIdx = STEP_DEFS.findIndex((s) => s.id === activeId);
  return STEP_DEFS.map((d, idx) => {
    let status: NodeStatus = 'idle';
    if (isDone) { status = 'done'; }
    else if (d.id === activeId) { status = 'running'; }
    else if (activeIdx > -1 && idx < activeIdx) { status = 'done'; }
    return { id: d.id, type: 'stepNode', position: { x: d.x, y: d.y }, data: { label: d.label, sub: d.sub, icon: d.icon, status } as StepNodeData };
  });
}

function buildEdges(nodes: ReturnType<typeof buildNodes>) {
  return EDGE_DEFS.map((e, i) => {
    const srcNode = nodes.find((n) => n.id === e.source);
    const active = srcNode?.data.status === 'done' || srcNode?.data.status === 'running';
    return { id: `e-${i}`, source: e.source, target: e.target, type: 'particleEdge', data: { active } };
  });
}

export function AuditGraph({ liveProgress, isDone }: { liveProgress: string; isDone: boolean }) {
  const nodeTypes = useMemo(() => ({ stepNode: StepNode }), []);
  const edgeTypes = useMemo(() => ({ particleEdge: ParticleEdge }), []);

  const [nodes, setNodes, onNodesChange] = useNodesState(buildNodes(liveProgress, isDone));
  const [edges, setEdges, onEdgesChange] = useEdgesState(buildEdges(buildNodes(liveProgress, isDone)));

  useEffect(() => {
    const n = buildNodes(liveProgress, isDone);
    setNodes(n);
    setEdges(buildEdges(n));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveProgress, isDone]);

  return (
    <div style={{ width: '100%', height: '100%', position: 'absolute', inset: 0 }}>
      <style>{`
        @keyframes auditNodePulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.4;transform:scale(1.6)} }
        .react-flow__attribution { display:none !important; }
      `}</style>
      <ReactFlow
        nodes={nodes} edges={edges}
        nodeTypes={nodeTypes} edgeTypes={edgeTypes}
        onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
        fitView fitViewOptions={{ padding: 0.25 }}
        nodesDraggable={false} nodesConnectable={false}
        elementsSelectable={false} panOnDrag={false}
        zoomOnScroll={false} zoomOnPinch={false} zoomOnDoubleClick={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
        style={{ background: 'transparent' }}
      >
        <Background variant={BackgroundVariant.Dots} gap={28} size={1} color="rgba(130,245,255,0.07)" />
      </ReactFlow>
    </div>
  );
}
