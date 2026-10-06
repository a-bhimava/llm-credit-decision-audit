import type { LucideIcon } from "lucide-react";
import { Cpu, FileText, ShieldCheck, TestTube2 } from "lucide-react";

type FlowNodeProps = {
  className: string;
  icon: LucideIcon;
  number: string;
  title: string;
  detail: string;
};

function FlowNode({ className, icon: Icon, number, title, detail }: FlowNodeProps) {
  return <div className={`auditFlowNode ${className}`}>
    <span className="auditFlowNodeTop"><Icon size={21} strokeWidth={1.8} aria-hidden="true" /><span>{number}</span></span>
    <strong>{title}</strong>
    <small>{detail}</small>
  </div>;
}

/** A static first frame keeps the audit path readable even before animation or with reduced motion. */
export function AuditFlowDiagram() {
  return <div className="auditFlow" role="img" aria-label="Structured loan data follows two paths: a structured baseline and a tool-guided platform. Both produce an evidence trace for comparison.">
    <svg className="auditFlowPaths desktop" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <path className="auditFlowPath baseline" d="M 15 50 C 31 50, 34 24, 50 24" />
      <path className="auditFlowPath platform" d="M 15 50 C 31 50, 34 76, 50 76" />
      <path className="auditFlowPath baseline" d="M 50 24 C 66 24, 69 50, 85 50" />
      <path className="auditFlowPath platform" d="M 50 76 C 66 76, 69 50, 85 50" />
    </svg>
    <svg className="auditFlowPaths mobile" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <path className="auditFlowPath baseline" d="M 50 15 C 50 31, 25 31, 25 50" />
      <path className="auditFlowPath platform" d="M 50 15 C 50 31, 75 31, 75 50" />
      <path className="auditFlowPath baseline" d="M 25 50 C 25 69, 50 69, 50 85" />
      <path className="auditFlowPath platform" d="M 75 50 C 75 69, 50 69, 50 85" />
    </svg>
    <FlowNode className="source" icon={FileText} number="01 / INPUT" title="Structured loan data" detail="One fictional case" />
    <FlowNode className="baseline" icon={Cpu} number="02 / DIRECT" title="Structured baseline" detail="Schema-constrained" />
    <FlowNode className="platform" icon={TestTube2} number="03 / TOOLS" title="Tool-guided platform" detail="Observable actions" />
    <FlowNode className="trace" icon={ShieldCheck} number="04 / OUTPUT" title="Evidence trace" detail="Paired outcomes" />
  </div>;
}
