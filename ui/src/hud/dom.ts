import { escapeHtml } from "../util/format";

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string> = {}, html = ""): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (html) e.innerHTML = html;
  return e;
}

/** Re-render an element's HTML only when its data changed: frames arrive ten times a second, the words almost never do. */
export class Memo {
  private sig = "";
  constructor(private readonly el: HTMLElement) {}
  set(data: unknown, render: () => string): boolean {
    const s = JSON.stringify(data);
    if (s === this.sig) return false;
    this.sig = s;
    this.el.innerHTML = render();
    return true;
  }
}

export const esc = escapeHtml;

export function panel(title: string, id: string, index: number, aside = ""): { root: HTMLElement; body: HTMLElement; aside: HTMLElement } {
  const root = h("section", { class: "panel", id, style: `--i:${index}` });
  root.innerHTML = `<i class="tick tr"></i><i class="tick bl"></i><h2 class="cap"><span class="led"></span>${esc(title)}<span class="rule"></span><span class="aside mono">${esc(aside)}</span></h2><div class="body"></div>`;
  const body = root.querySelector(".body") as HTMLElement;
  body.style.cssText = "display:flex;flex-direction:column;min-height:0;flex:1";
  return { root, body, aside: root.querySelector(".aside") as HTMLElement };
}
