const GRID = [
  "................", "...RRRRRRRRRR...", "..RRHHRRRRRRRR..", "..RRHRRRRRRRRR..",
  "..RRWWRRRRWWRR..", "..RRWKRRRRWKRR..", "..RRWKRRRRWKRR..", "..RRRRRRRRRRRR..",
  ".DRRRRRKKRRRRRD.", ".DRRRRRRRRRRRRD.", "..RRRRRRRRRRRR..", "..DRRRRRRRRRRD..",
  "..RRRRR..RRRRR..", "..RRRR....RRRR..", "..RRR......RRR..", "..DD........DD..",
] as const;

function pixels(key: string, include: (x: number, y: number) => boolean = () => true): string {
  return GRID.flatMap((row, y) => Array.from(row).flatMap((pixel, x) => pixel === key && include(x, y) ? [`M${x} ${y}h1v1h-1z`] : [])).join("");
}
const paths = {
  body: pixels("R"), shade: pixels("D"), highlight: pixels("H"),
  whites: pixels("W"), pupils: pixels("K", (_x, y) => y !== 8), mouth: pixels("K", (_x, y) => y === 8),
  closed: "M4 5h2v1h-2zM10 5h2v1h-2z",
  alert: "M5 4h1v2h-1zM11 4h1v2h-1z",
};

export function Mascot({ mood = "idle", size = 28 }: { mood?: "idle" | "busy" | "sleepy" | "alert"; size?: 20 | 28 | 72 }) {
  return (
    <span className="ws-mascot-wrap" data-mood={mood} aria-hidden="true">
    <svg className="ws-mascot" data-mood={mood} width={size} height={size} viewBox="0 0 16 16" shapeRendering="crispEdges" aria-hidden="true">
      <path className="ws-mascot-body" d={paths.body} />
      <path className="ws-mascot-shade" d={paths.shade} />
      <path className="ws-mascot-highlight" d={paths.highlight} />
      <g className="ws-mascot-eyes">
        <path className="ws-mascot-whites" d={paths.whites} />
        <path className="ws-mascot-pupils" d={paths.pupils} />
        <path className="ws-mascot-alert-pupils" d={paths.alert} />
      </g>
      <path className="ws-mascot-mouth" d={paths.mouth} />
      <path className="ws-mascot-closed" d={paths.closed} />
    </svg>
    </span>
  );
}
