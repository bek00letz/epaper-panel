// A row that slides: New page's shelves and the page strip. Its edges fade
// while there's more to slide to (the fade animates in and out with a
// spring), and on a pointer that can hover, arrows show at an edge only
// towards more. A touch screen swipes and keeps the fade. Running down
// instead of across (the strip down the side), it fades top and bottom and
// leaves the arrows out: a scroll wheel or a swipe already goes that way.

import { h, icon } from "./util.js";

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/* Wraps `row` (it keeps its own classes and children) and returns the wrapper.
   `name` labels the arrows ("More in Energy"); `vertical()` says which way it runs now. */
export function slider(row, { name, vertical = () => false } = {}) {
  row.classList.add("slides");
  // "still" until it has measured itself: a row drawn again (the strip, after every edit) mustn't fade in each time.
  const wrap = h("div", { class: "slider still" });
  const page = (dir) => {
    const v = vertical(), size = v ? row.clientHeight : row.clientWidth;
    const step = Math.max(80, Math.round(size * 0.8));                // most of a view, keeping a card in sight
    row.scrollBy({ [v ? "top" : "left"]: dir * step, behavior: reduced() ? "auto" : "smooth" });
  };
  const left = h("button", { class: "arrow l", tabindex: "-1", "aria-label": `Earlier in ${name}`, onclick: () => page(-1) }, icon("back", "sm"));
  const right = h("button", { class: "arrow r", tabindex: "-1", "aria-label": `More in ${name}`, onclick: () => page(1) }, icon("chev", "sm"));
  const sync = () => {
    const v = vertical();
    const at = v ? row.scrollTop : row.scrollLeft, max = v ? row.scrollHeight - row.clientHeight : row.scrollWidth - row.clientWidth;
    wrap.classList.toggle("vertical", v);
    wrap.classList.toggle("more-l", at > 2);
    wrap.classList.toggle("more-r", at < max - 2);
  };
  row.addEventListener("scroll", sync, { passive: true });
  new ResizeObserver(sync).observe(row);
  const settle = () => { sync(); setTimeout(() => wrap.classList.remove("still"), 60); };
  setTimeout(settle);                                                // once it's on the page
  wrap.append(left, row, right);
  wrap.sync = settle;                                                // or at once, by whoever put it there
  return wrap;
}
