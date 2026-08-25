"use client";

import React from "react";
import { motion } from "framer-motion";
import { FileText, Cpu, Database, Link2, ShieldCheck, TestTube2 } from "lucide-react";

const Node = ({ icon: Icon, title, x, y, delay, color = "var(--foreground)" }: any) => {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay, duration: 0.5 }}
      style={{ left: `${x}%`, top: `${y}%`, borderColor: color }}
      className="absolute -translate-x-1/2 -translate-y-1/2 w-16 h-16 rounded-xl border bg-[#060010]/80 backdrop-blur-md flex items-center justify-center shadow-xl z-10 overflow-visible"
    >
      <Icon size={24} color={color} />
      <span className="absolute -bottom-6 whitespace-nowrap text-[0.65rem] font-bold tracking-widest text-[var(--dim)] uppercase">
        {title}
      </span>
    </motion.div>
  );
};

const Beam = ({ d, delay = 0, color = "var(--cyan)" }: any) => {
  return (
    <>
      {/* Background track */}
      <path d={d} fill="none" stroke="var(--line-dark)" strokeWidth="2" strokeLinecap="round" />
      {/* Animated glowing beam */}
      <motion.path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth="3"
        strokeLinecap="round"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: [0, 1, 1, 0] }}
        transition={{
          duration: 2.5,
          delay,
          repeat: Infinity,
          ease: "easeInOut",
          repeatDelay: 1,
        }}
        style={{ filter: `drop-shadow(0 0 8px ${color})` }}
      />
    </>
  );
};

export function AnimatedBeamHero() {
  return (
    <div className="relative w-full h-full min-h-[400px] flex items-center justify-center p-4">
      
      {/* SVG Canvas for beams */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none"
        preserveAspectRatio="none"
        viewBox="0 0 100 100"
      >
        {/* Facts to Baseline */}
        <Beam d="M 15 50 C 35 50, 35 25, 50 25" delay={0} color="#b3c5ff" />
        {/* Facts to Intervention */}
        <Beam d="M 15 50 C 35 50, 35 75, 50 75" delay={0.2} color="var(--pink)" />
        
        {/* Baseline to Ledger */}
        <Beam d="M 50 25 C 70 25, 70 50, 85 50" delay={2.5} color="#b3c5ff" />
        {/* Intervention to Ledger */}
        <Beam d="M 50 75 C 70 75, 70 50, 85 50" delay={2.7} color="var(--pink)" />
      </svg>

      {/* Nodes */}
      <Node icon={FileText} title="Fictional Facts" x={15} y={50} delay={0} />
      
      <Node icon={Cpu} title="Structured Baseline" x={50} y={25} delay={0.4} color="#b3c5ff" />
      <Node icon={TestTube2} title="Tool-guided Platform" x={50} y={75} delay={0.6} color="var(--pink)" />

      <Node icon={ShieldCheck} title="Evidence Trace" x={85} y={50} delay={1.0} color="var(--cyan)" />

    </div>
  );
}
