export const pad2 = (n: number) => String(Math.floor(n)).padStart(2, "0");

export function clock(d: Date = new Date()): string {
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}

/** "00:27" from seconds. */
export function mmss(secs: number): string {
  const s = Math.max(0, Math.floor(secs));
  return `${pad2(s / 60)}:${pad2(s % 60)}`;
}

export function money(x: number): string {
  return x >= 1 ? `$${x.toFixed(2)}` : `$${x.toFixed(3)}`;
}

export function ms(x: number | null): string {
  if (x === null || !Number.isFinite(x)) return "—";
  return x >= 1000 ? `${(x / 1000).toFixed(1)} s` : `${Math.round(x)} ms`;
}

/** The text-decode effect of a HUD reveal: how the string looks `u` (0..1) of the way through being typed out with scrambled glyphs ahead of the cursor. */
export function decode(text: string, u: number, rnd: () => number = Math.random, glyphs = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&/<>"): string {
  const n = text.length;
  const cut = Math.floor(Math.min(1, Math.max(0, u)) * n);
  let out = text.slice(0, cut);
  for (let i = cut; i < Math.min(n, cut + 4); i++) out += text[i] === " " ? " " : glyphs[Math.floor(rnd() * glyphs.length)];
  return out;
}

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
}
