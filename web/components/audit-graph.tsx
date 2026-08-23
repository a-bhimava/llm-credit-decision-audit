'use client';

import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Handle,
  Position,
  BaseEdge,
  getBezierPath,
  useNodesState,
  useEdgesState,
} from '@xyflow/react';
import type { EdgeProps, NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useMemo, useEffect } from 'react';

// ── Types ──────────────────────────────────────────────────────────────────────
type NodeStatus = 'idle' | 'running' | 'done' | 'error';

interface StepNodeData extends Record<string, unknown> {
  label: string;
  sub: string;
  icon: string;
  status: NodeStatus;
}

// ── Status palette ─────────────────────────────────────────────────────────────
const STATUS = {
  idle:    { border: 'rgba(255,255,255,0.15)', glow: 'none',                              dot: '#6b6884', iconColor: '#8a88a8', bgAccent: 'rgba(255,255,255,0.04)', bgCard: 'rgba(22, 24, 45, 0.85)' },
  running: { border: 'rgba(130,245,255,0.7)',  glow: '0 0 35px rgba(130,245,255,0.25)',   dot: '#82f5ff', iconColor: '#82f5ff', bgAccent: 'rgba(130,245,255,0.08)', bgCard: 'rgba(19, 29, 53, 0.95)' },
  done:    { border: 'rgba(74,222,128,0.6)',   glow: '0 0 25px rgba(74,222,128,0.15)',    dot: '#4ade80', iconColor: '#4ade80', bgAccent: 'rgba(74,222,128,0.08)',  bgCard: 'rgba(19, 36, 33, 0.9)' },
  error:   { border: 'rgba(248,113,113,0.6)',  glow: '0 0 25px rgba(248,113,113,0.15)',   dot: '#f87171', iconColor: '#f87171', bgAccent: 'rgba(248,113,113,0.08)', bgCard: 'rgba(45, 20, 24, 0.9)' },
} as const;

// ── Heroicons stroke paths (24×24 viewBox) ─────────────────────────────────────
const SVG_PATHS: Record<string, string> = {
  init:    `<path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z"/>`,
  budget:  `<path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"/>`,
  build:   `<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>`,
  episode: `<path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z"/>`,
  save:    `<path stroke-linecap="round" stroke-linejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125"/>`,
  done:    `<path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>`,
};

// ── Custom Node ────────────────────────────────────────────────────────────────
function StepNode({ data, id }: NodeProps) {
  const d = data as StepNodeData;
  const s = STATUS[d.status];
  const iconPath = SVG_PATHS[id as string] ?? SVG_PATHS.done;

  return (
    <div style={{
      background: s.bgCard,
      border: `1px solid ${s.border}`,
      borderRadius: 14,
      boxShadow: s.glow !== 'none' ? s.glow : '0 4px 20px rgba(0,0,0,0.15)',
      padding: '18px 22px 18px',
      width: 290,
      fontFamily: 'var(--font-inter, Inter, system-ui, sans-serif)',
      transition: 'all 0.4s cubic-bezier(0.16, 1, 0.3, 1)',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Shimmer sweep on running */}
      {d.status === 'running' && (
        <div style={{
          position: 'absolute', inset: 0, borderRadius: 14, pointerEvents: 'none',
          background: 'linear-gradient(105deg, transparent 30%, rgba(130,245,255,0.07) 50%, transparent 70%)',
          animation: 'shimmerSweep 2.2s ease-in-out infinite',
        }}/>
      )}

      <Handle type="target" position={Position.Left}
        style={{ background: s.dot, border: '2px solid #13142a', width: 12, height: 12, left: -6 }}/>

      {/* Icon badge + status indicator */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div style={{
          width: 44, height: 44, borderRadius: 10, flexShrink: 0,
          background: s.bgAccent,
          border: `1px solid ${d.status === 'idle' ? 'rgba(255,255,255,0.08)' : s.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: 'inset 0 2px 10px rgba(255,255,255,0.02)',
        }}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
            stroke={s.iconColor} strokeWidth="1.75"
            dangerouslySetInnerHTML={{ __html: iconPath }}/>
        </div>

        {/* Status badge */}
        {d.status === 'done' && (
          <span style={{ color: '#4ade80', fontSize: 16, fontWeight: 700, lineHeight: 1 }}>✓</span>
        )}
        {d.status === 'error' && (
          <span style={{ color: '#f87171', fontSize: 16, fontWeight: 700, lineHeight: 1 }}>✗</span>
        )}
        {(d.status === 'idle' || d.status === 'running') && (
          <span style={{
            width: 8, height: 8, borderRadius: '50%', background: s.dot, display: 'block', flexShrink: 0,
            boxShadow: d.status === 'running' ? `0 0 8px ${s.dot}` : 'none',
            animation: d.status === 'running' ? 'statusPing 1.6s ease-in-out infinite' : 'none',
          }}/>
        )}
      </div>

      {/* Label */}
      <div style={{
        color: d.status === 'idle' ? '#b6b4d4' : '#ffffff',
        fontWeight: 600, fontSize: '1rem', letterSpacing: '-0.02em', lineHeight: 1.25, marginBottom: 4,
      }}>
        {d.label}
      </div>

      {/* Subtitle */}
      <div style={{
        color: d.status === 'idle' ? '#6b6884' : '#9ca3af',
        fontSize: '0.78rem', fontWeight: 400, letterSpacing: 0, lineHeight: 1.4, marginBottom: 16,
      }}>
        {d.status === 'running' ? 'Running task in background…' : d.status === 'done' ? 'Completed successfully' : d.sub}
      </div>

      {/* Progress track */}
      <div style={{ height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 4, overflow: 'hidden' }}>
        {d.status === 'running' && (
          <div style={{
            height: '100%', width: '40%', borderRadius: 4,
            background: `linear-gradient(90deg, transparent, ${s.dot} 70%, transparent)`,
            animation: 'trackSlide 1.5s ease-in-out infinite',
          }}/>
        )}
        {d.status === 'done' && (
          <div style={{ height: '100%', width: '100%', background: '#4ade80', borderRadius: 4 }}/>
        )}
      </div>

      <Handle type="source" position={Position.Right}
        style={{ background: s.dot, border: '2px solid #13142a', width: 12, height: 12, right: -6 }}/>
    </div>
  );
}

// ── Custom Particle Edge ───────────────────────────────────────────────────────
function ParticleEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps) {
  const [path] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  const active = Boolean((data as Record<string, unknown>)?.active);
  return (
    <>
      {/* Glow halo */}
      {active && <path d={path} fill="none" stroke="rgba(130,245,255,0.1)" strokeWidth={10}/>}
      {/* Base edge */}
      <BaseEdge id={id} path={path} style={{
        stroke: active ? 'rgba(130,245,255,0.6)' : 'rgba(255,255,255,0.15)',
        strokeWidth: active ? 2.5 : 2,
        transition: 'stroke 0.6s ease, stroke-width 0.5s ease',
      }}/>
      {/* Particle 1 — lead */}
      {active && (
        <circle r="4.5" fill="#82f5ff" style={{ filter: 'drop-shadow(0 0 6px #82f5ff)' }}>
          <animateMotion dur="2s" repeatCount="indefinite" path={path}/>
        </circle>
      )}
      {/* Particle 2 — trail */}
      {active && (
        <circle r="2.5" fill="#82f5ff" opacity="0.5">
          <animateMotion dur="2s" begin="-1s" repeatCount="indefinite" path={path}/>
        </circle>
      )}
    </>
  );
}

// ── Graph topology (Tighter, cleaner layout) ──────────────────────────────────
const STEP_DEFS = [
  { id: 'init',    label: 'Initialize',        sub: 'Workflow bootstrap',     x: 50,   y: 200 },
  { id: 'budget',  label: 'Reserve Budget',     sub: 'Daily cap check',        x: 420,  y: 80  },
  { id: 'build',   label: 'Build Application',  sub: 'Packet serialization',   x: 420,  y: 320 },
  { id: 'episode', label: 'Run Episode',         sub: 'Gemini LLM evaluation',  x: 790,  y: 200 },
  { id: 'save',    label: 'Save Results',        sub: 'Trajectory write-back',  x: 1160, y: 200 },
  { id: 'done',    label: 'Complete',            sub: 'Audit finalized',        x: 1530, y: 200 },
];

const EDGE_DEFS = [
  { source: 'init',    target: 'budget'  },
  { source: 'init',    target: 'build'   },
  { source: 'budget',  target: 'episode' },
  { source: 'build',   target: 'episode' },
  { source: 'episode', target: 'save'    },
  { source: 'save',    target: 'done'    },
];

// ── Progress string → active node ─────────────────────────────────────────────
function progressToActiveId(msg: string): string {
  const m = msg.toLowerCase();
  if (m.includes('audit completed') || m.includes('completed successfully') || m.includes('success'))  return 'done';
  if (m.includes('completed baseline') || m.includes('baseline trial') || m.includes('saving'))        return 'save';
  if (m.includes('episode') || m.includes('trial') || m.includes('evaluat') || m.includes('gemini'))  return 'episode';
  if (m.includes('packet') || m.includes('build') || m.includes('application'))                        return 'build';
  if (m.includes('budget') || m.includes('reserv') || m.includes('daily') || m.includes('cap'))       return 'budget';
  return 'init';
}

function buildNodes(liveProgress: string, isDone: boolean) {
  const activeId = progressToActiveId(liveProgress);
  const activeIdx = STEP_DEFS.findIndex((s) => s.id === activeId);
  return STEP_DEFS.map((d, idx) => {
    let status: NodeStatus = 'idle';
    if (isDone)                                 { status = 'done'; }
    else if (d.id === activeId)                 { status = 'running'; }
    else if (activeIdx > -1 && idx < activeIdx) { status = 'done'; }
    return {
      id: d.id, type: 'stepNode',
      position: { x: d.x, y: d.y },
      data: { label: d.label, sub: d.sub, icon: d.id, status } as StepNodeData,
    };
  });
}

function buildEdges(nodes: ReturnType<typeof buildNodes>) {
  return EDGE_DEFS.map((e, i) => {
    const src = nodes.find((n) => n.id === e.source);
    const active = src?.data.status === 'done' || src?.data.status === 'running';
    return { id: `e-\${i}`, source: e.source, target: e.target, type: 'particleEdge', data: { active } };
  });
}

// ── Main export ────────────────────────────────────────────────────────────────
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
        @keyframes statusPing   { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.25;transform:scale(2.5)} }
        @keyframes shimmerSweep { 0%{transform:translateX(-120%)} 100%{transform:translateX(120%)} }
        @keyframes trackSlide   { 0%{transform:translateX(-200%)} 100%{transform:translateX(350%)} }
        .react-flow__attribution { display:none !important; }
        /* Override default handles to show custom ones clearly */
        .react-flow__handle { opacity: 1 !important; }
      `}</style>
      <ReactFlow
        nodes={nodes} edges={edges}
        nodeTypes={nodeTypes} edgeTypes={edgeTypes}
        onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
        fitView fitViewOptions={{ padding: 0.15, minZoom: 0.3, maxZoom: 1.2 }}
        nodesDraggable={true} nodesConnectable={false}
        elementsSelectable={true} panOnDrag={true}
        zoomOnScroll={true} zoomOnPinch={true} zoomOnDoubleClick={true}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
        style={{ background: 'transparent' }}
      >
        <Background variant={BackgroundVariant.Dots} gap={40} size={1.5} color="rgba(130,245,255,0.08)"/>
      </ReactFlow>
    </div>
  );
}
