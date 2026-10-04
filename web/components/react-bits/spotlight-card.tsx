"use client";

// Adapted from React Bits Spotlight Card (MIT + Commons Clause):
// https://github.com/DavidHDev/react-bits/tree/main/src/ts-default/Components/SpotlightCard
import { useRef, type MouseEventHandler, type PropsWithChildren } from "react";
import "./spotlight-card.css";

type SpotlightCardProps = PropsWithChildren<{
  className?: string;
  spotlightColor?: string;
}>;

export function SpotlightCard({
  children,
  className = "",
  spotlightColor = "rgba(23, 127, 120, 0.16)",
}: SpotlightCardProps) {
  const ref = useRef<HTMLDivElement>(null);
  const handleMouseMove: MouseEventHandler<HTMLDivElement> = event => {
    const element = ref.current;
    if (!element) return;
    const bounds = element.getBoundingClientRect();
    element.style.setProperty("--mouse-x", `${event.clientX - bounds.left}px`);
    element.style.setProperty("--mouse-y", `${event.clientY - bounds.top}px`);
    element.style.setProperty("--spotlight-color", spotlightColor);
  };

  return <div ref={ref} onMouseMove={handleMouseMove} className={`rt-spotlight-card ${className}`}>
    {children}
  </div>;
}
