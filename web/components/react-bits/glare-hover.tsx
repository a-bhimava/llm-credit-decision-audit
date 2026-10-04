"use client";

// Adapted from React Bits Glare Hover (MIT + Commons Clause):
// https://github.com/DavidHDev/react-bits/tree/main/src/ts-default/Animations/GlareHover
import type { CSSProperties, PropsWithChildren } from "react";
import "./glare-hover.css";

type GlareHoverProps = PropsWithChildren<{
  className?: string;
  glareColor?: string;
}>;

export function GlareHover({ children, className = "", glareColor = "rgba(170, 235, 217, 0.28)" }: GlareHoverProps) {
  const style = { "--rt-glare-color": glareColor } as CSSProperties;
  return <div className={`rt-glare-hover ${className}`} style={style}>{children}</div>;
}
