// Before another tool's tab (or the EMB Pros logo) takes you off a page with work on it, ask:
// keep working, or discard it and go. Each page says whether it has work: window.embHasWork = () => ...
(() => {
  let box = null, target = "";
  function ask(href) {
    target = href;
    if (!box) {
      box = document.createElement("div");
      box.className = "pt-modal"; box.id = "leaveAsk"; box.hidden = true;
      box.innerHTML = `<div class="pt-modal-box" role="alertdialog" aria-modal="true" aria-labelledby="leaveTitle" aria-describedby="leaveText">
  <h2 id="leaveTitle">Leave this page?</h2>
  <p id="leaveText">The work on this page will be discarded. Download or save it first if you want to keep it.</p>
  <div class="pt-modal-actions">
    <button type="button" id="leaveKeep">Keep working</button>
    <button type="button" class="danger" id="leaveGo">Discard and leave</button>
  </div>
</div>`;
      document.body.appendChild(box);
      box.querySelector("#leaveKeep").addEventListener("click", close);
      box.querySelector("#leaveGo").addEventListener("click", () => { box.hidden = true; location.href = target; });
      box.addEventListener("click", (e) => { if (e.target === box) close(); });
      document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !box.hidden) close(); });
    }
    box.hidden = false;
    box.querySelector("#leaveKeep").focus();
  }
  function close() { box.hidden = true; }
  document.addEventListener("click", (e) => {
    const a = e.target.closest("header.top a[href]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (a.getAttribute("aria-current") === "page" && a.pathname === location.pathname) return;
    if (!(typeof window.embHasWork === "function" && window.embHasWork())) return;
    e.preventDefault();
    ask(a.href);
  });
})();
