type PanelHeadingProps = {
  id: string;
  step: "01" | "02" | "03";
  phase: string;
  title: string;
  description: string;
};

export function ReasonTracePanelHeading({ id, step, phase, title, description }: PanelHeadingProps) {
  return <div className="rt-panel-heading">
    <div className="rt-panel-heading-step"><span>{step}</span><strong>{phase}</strong></div>
    <h2 id={id} tabIndex={-1}>{title}</h2>
    <p>{description}</p>
  </div>;
}
