import type { StepState } from "../protocol";

const wrap = (inner: string) => `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;

/** One glyph per real step state. Drawn as SVG so they stay crisp and take the row's colour. */
export const STEP_ICON: Record<StepState, string> = {
  pending: wrap('<path d="M8 2.5 13.5 8 8 13.5 2.5 8Z"/>'),
  running: wrap('<path d="M5.5 3.5 12.5 8l-7 4.5Z" fill="currentColor"/><circle cx="8" cy="8" r="7" stroke-dasharray="3 3"><animateTransform attributeName="transform" type="rotate" from="0 8 8" to="360 8 8" dur="3s" repeatCount="indefinite"/></circle>'),
  waiting: wrap('<path d="M8 1.8 13.6 5v6L8 14.2 2.4 11V5Z"/><path d="M8 5v3.4M8 10.6v.2"/>'),
  ran: wrap('<path d="M8 2.5 13.5 8 8 13.5 2.5 8Z" fill="currentColor" fill-opacity=".35"/>'),
  verified: wrap('<path d="M3 8.4 6.6 12 13.2 4.6"/>'),
  denied: wrap('<path d="M4 4l8 8M12 4l-8 8"/>'),
  failed: wrap('<path d="M4 4l8 8M12 4l-8 8"/>'),
  "rolled back": wrap('<path d="M3.5 7.5A5 5 0 1 1 5 11.5M3.5 3.5v4h4"/>'),
};

export const CHECK_ICON = { ok: STEP_ICON.verified, bad: STEP_ICON.failed };

/** A brain's hexagon with a budget arc around it (how much of its allowance is spent) and a centre dot coloured by cost class. */
export function brainIcon(pressure: number, color: string, gaugeColor: string, dashed: boolean): string {
  const R = 16.5;
  const C = 2 * Math.PI * R;
  const p = Math.max(0, Math.min(1, pressure));
  return `<svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="${R}" fill="none" stroke="rgb(var(--accent-rgb) / .16)" stroke-width="2"/>
    <circle cx="20" cy="20" r="${R}" fill="none" stroke="${gaugeColor}" stroke-width="2.4" stroke-linecap="round" stroke-dasharray="${(C * p).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 20 20)"/>
    <path d="M20 8.5 30 14.2v11.6L20 31.5 10 25.8V14.2Z" fill="rgba(2,8,14,.85)" stroke="${color}" stroke-width="1.6" ${dashed ? 'stroke-dasharray="3 3"' : ""}/>
    <circle cx="20" cy="20" r="3" fill="${color}"/></svg>`;
}
