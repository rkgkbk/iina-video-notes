const el = id => document.getElementById(id);
let shownSummary = null, shownSegments = "";
let currentState = null;
function copyContent() { return el("transcript").hidden ? "summary" : "transcript"; }
function updateCopy() {
  if (!currentState) return;
  const transcript = copyContent() === "transcript";
  el("copy").hidden = transcript ? !currentState.segments.length : !currentState.summary || currentState.busy;
  el("copy").setAttribute("aria-label", transcript ? "复制转写全文" : "复制完整总结");
  el("copy").title = transcript ? "复制转写全文" : "复制完整总结";
}
function stamp(seconds) { return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, Math.floor(seconds) % 60].map(n => String(n).padStart(2, "0")).join(":"); }
function inline(parent, text) {
  const pattern = /\[?(\d{1,2}):(\d{2}):(\d{2})\]?|\*\*([^*]+)\*\*/g;
  let match, pos = 0;
  while ((match = pattern.exec(text))) {
    parent.appendChild(document.createTextNode(text.slice(pos, match.index)));
    const node = document.createElement(match[4] ? "strong" : "button");
    if (match[4]) node.textContent = match[4];
    else {
      const seconds = Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
      node.className = "time"; node.textContent = stamp(seconds);
      node.setAttribute("aria-label", "跳转到 " + stamp(seconds));
      node.onclick = () => iina.postMessage("seek", seconds);
    }
    parent.appendChild(node); pos = pattern.lastIndex;
  }
  parent.appendChild(document.createTextNode(text.slice(pos)));
}
function renderSummary(text) {
  const target = el("summary"); target.replaceChildren();
  text.split("\n").forEach(line => {
    if (!line.trim()) return;
    const heading = line.match(/^(#{1,6})\s+(.+)/);
    const item = line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)/);
    const node = document.createElement(heading ? (heading[1].length <= 2 ? "h2" : "h3") : "p");
    inline(node, heading ? heading[2] : item ? "• " + item[1] : line);
    target.appendChild(node);
  });
}
iina.onMessage("state", state => {
  currentState = state;
  document.title = state.name + " · AI 总结";
  el("status").textContent = state.message;
  el("status").className = state.error ? "error" : "";
  updateCopy();
  el("progress").value = state.progress || 0;
  el("start").disabled = state.busy;
  el("start").hidden = state.busy || !!state.summary;
  el("start").textContent = state.complete ? "生成总结" : state.segments.length ? "继续转录" : "开始转录";
  el("status-dot").className = state.error ? "error" : state.busy ? "busy" : "";
  el("stop").hidden = !state.busy;
  el("reveal").hidden = !state.folder;
  el("count").textContent = state.segments.length || "";
  if (state.summary !== shownSummary) {
    if (state.summary) renderSummary(state.summary);
    else if (shownSummary !== null) el("summary").textContent = "先完成本地转录，再手动点击“生成总结”调用 Codex。";
    shownSummary = state.summary;
  }
  const key = JSON.stringify(state.segments);
  if (key !== shownSegments) {
    const target = el("transcript"); target.replaceChildren();
    state.segments.forEach(segment => {
      const card = document.createElement("div"); card.className = "segment";
      inline(card, "[" + stamp(segment.start) + "]");
      const text = document.createElement("p"); text.textContent = segment.text || "（未识别到语音）";
      card.appendChild(text); target.appendChild(card);
    });
    if (!state.segments.length) target.textContent = "转写完成的段落会显示在这里。";
    shownSegments = key;
  }
});
["summary", "transcript"].forEach(name => {
  el(name + "-tab").onclick = () => {
    ["summary", "transcript"].forEach(other => {
      el(other).hidden = other !== name;
      el(other + "-tab").setAttribute("aria-pressed", String(other === name));
    });
    el("copy").textContent = "复制";
    updateCopy();
  };
});
["start", "stop", "reveal"].forEach(name => { el(name).onclick = () => iina.postMessage(name); });
el("copy").onclick = () => { el("copy").disabled = true; iina.postMessage("copy", copyContent()); };
iina.onMessage("copy-result", result => {
  el("copy").disabled = false;
  el("copy").textContent = result.ok ? "已复制" : "复制失败，重试";
  setTimeout(() => { el("copy").textContent = "复制"; }, 2000);
});
iina.postMessage("ready");
