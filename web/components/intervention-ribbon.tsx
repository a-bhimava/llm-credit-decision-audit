export function InterventionRibbon() {
  return (
    <div className="ribbon" aria-label="A diagram showing the same fictional application passing through two audit configurations">
      <svg viewBox="0 0 720 230" role="img" aria-labelledby="ribbon-title ribbon-desc">
        <title id="ribbon-title">The audit compares two configurations on an identical fictional application</title>
        <desc id="ribbon-desc">A source record branches into a structured baseline and a tool-guided platform, then returns as two evidence traces.</desc>
        <defs>
          <linearGradient id="ribbon-flow" x1="0" x2="1">
            <stop offset="0%" stopColor="#82f5ff" />
            <stop offset="53%" stopColor="#8770ff" />
            <stop offset="100%" stopColor="#ff72bd" />
          </linearGradient>
          <filter id="ribbon-blur"><feGaussianBlur stdDeviation="4" /></filter>
        </defs>
        <path className="ribbonGlow" d="M24 113 H160 C220 113 236 48 302 48 H430 C482 48 485 84 540 84 H696" filter="url(#ribbon-blur)" />
        <path className="ribbonTrack" d="M24 113 H160 C220 113 236 48 302 48 H430 C482 48 485 84 540 84 H696" />
        <path className="ribbonTrack ribbonTrackTwo" d="M24 117 H165 C226 117 235 177 302 177 H430 C481 177 494 142 540 142 H696" />
        <circle className="ribbonNode source" cx="90" cy="115" r="13" />
        <circle className="ribbonNode" cx="304" cy="48" r="9" />
        <circle className="ribbonNode" cx="304" cy="177" r="9" />
        <circle className="ribbonNode finish" cx="625" cy="113" r="13" />
        <text x="42" y="157">same fictional facts</text>
        <text x="282" y="25">structured baseline</text>
        <text x="278" y="212">tool-guided platform</text>
        <text x="568" y="157">evidence traces</text>
      </svg>
    </div>
  );
}
