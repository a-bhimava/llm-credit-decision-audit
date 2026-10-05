"use client";

// Adapted from React Bits Animated Content (MIT + Commons Clause):
// https://github.com/DavidHDev/react-bits/tree/main/src/ts-default/Animations/AnimatedContent
// Uses the app's existing Framer Motion dependency for a mount-triggered result
// reveal instead of scroll-triggered GSAP; evidence remains visible without motion.
import { motion, useReducedMotion } from "framer-motion";
import type { PropsWithChildren } from "react";

type AnimatedContentProps = PropsWithChildren<{ className?: string; ariaLive?: "off" | "polite" | "assertive" }>;

export function AnimatedContent({ children, className, ariaLive }: AnimatedContentProps) {
  const reducedMotion = useReducedMotion();
  return <motion.div className={className} aria-live={ariaLive}
    initial={reducedMotion ? false : { opacity: 0, y: 14, scale: 0.99 }}
    animate={{ opacity: 1, y: 0, scale: 1 }}
    exit={reducedMotion ? undefined : { opacity: 0, y: -8 }}
    transition={{ duration: reducedMotion ? 0 : 0.28, ease: "easeOut" }}>
    {children}
  </motion.div>;
}
