const {sidebar, core, menu, file, utils, event} = iina;
const root = utils.resolvePath("~/Library/Application Support/com.colliderli.iina/plugins/local.video.ai-summary.iinaplugin");
const config = JSON.parse(file.read(root + "/config.json"));
const python = config.asrDirectory + "/.venv/bin/python";
const worker = root + "/worker.py";
const cache = utils.resolvePath("@data/");
let state = {name: "请先打开本地视频", message: "准备就绪", progress: 0, busy: false, segments: [], summary: "", complete: false};
let current = "", run = null, generation = 0, sidebarLoaded = false;

function send() { sidebar.postMessage("state", state); }
function videoPath() {
  const url = core.status.url || "";
  if (url.indexOf("file://") === 0) return decodeURIComponent(url.replace(/^file:\/\/(localhost)?/, ""));
  return url.indexOf("/") === 0 ? url : "";
}
function receive(data) {
  if (data.type === "status") { state.message = data.message; state.progress = data.progress; }
  if (data.type === "transcript") { state.segments = data.segments; state.duration = data.duration; state.complete = !!data.complete; }
  if (data.type === "transcription_done") {
    Object.assign(state, data, {busy: false, complete: true, message: "转录已完成，可手动生成总结", progress: 100});
  }
  if (data.type === "segment") { state.segments[data.index] = data.segment; state.duration = data.duration; }
  if (data.type === "result") {
    Object.assign(state, data, {busy: false, message: "总结已完成", progress: 100});
  }
  if (data.type === "error" || data.type === "cancelled") {
    state.busy = false; state.message = data.message; state.error = data.type === "error";
  }
  send();
}
function stop() {
  if (run) file.write(run.cancel, "cancel");
}
async function refresh() {
  const path = videoPath();
  if (path === current) return;
  stop(); run = null;
  current = path;
  const version = ++generation;
  state = {name: path ? path.split("/").pop() : "请先打开本地视频", message: path ? "点击开始转录" : "当前仅支持本地音视频", progress: 0, busy: false, segments: [], summary: "", complete: false};
  send();
  if (!path) return;
  try {
    const result = await utils.exec(python, [worker, "inspect", "--video", path, "--cache", cache]);
    if (version !== generation) return;
    result.stdout.split("\n").filter(Boolean).forEach(line => receive(JSON.parse(line)));
  } catch (error) {
    if (version === generation) { state.message = "环境检查失败：" + String(error); state.error = true; send(); }
  }
}
async function start() {
  if (state.busy || !current) return;
  const version = generation;
  const id = Date.now() + "-" + Math.random().toString(36).slice(2);
  run = {events: cache + "/run-" + id + ".jsonl", cancel: cache + "/cancel-" + id, offset: 0, pid: null, last: Date.now()};
  const task = run;
  file.write(task.events, "");
  state.busy = true; state.error = false; state.message = "正在启动…"; send();
  try {
    const result = await utils.exec(python, [worker, "start", "--video", current, "--cache", cache, "--cancel", task.cancel, "--events", task.events, "--mode", state.complete ? "summarize" : "transcribe"]);
    if (version !== generation) { file.write(task.cancel, "cancel"); return; }
    if (result.status !== 0) throw new Error(result.stdout || result.stderr);
    task.pid = JSON.parse(result.stdout.trim()).pid;
  } catch (error) {
    if (version === generation) receive({type: "error", message: "启动失败：" + String(error)});
  }
}
async function poll() {
  if (!run || !state.busy) return;
  try {
    const text = file.read(run.events);
    const end = text.lastIndexOf("\n") + 1;
    if (end > run.offset) {
      const lines = text.slice(run.offset, end).split("\n").filter(Boolean);
      run.offset = end; run.last = Date.now();
      lines.forEach(line => receive(JSON.parse(line)));
    }
    if (state.busy && run.pid && Date.now() - (run.checked || run.last) > 15000) {
      const task = run;
      task.checked = Date.now();
      const alive = await utils.exec("/bin/kill", ["-0", String(task.pid)]);
      if (run === task && state.busy && alive.status !== 0) {
        receive({type: "error", message: "后台进程已退出，请点击继续。诊断日志：" + task.events + ".log"});
      }
    }
  } catch (error) { iina.console.error(String(error)); }
}
function loadSidebar() {
sidebar.loadFile("sidebar.html");
sidebarLoaded = true;
sidebar.onMessage("ready", () => { send(); refresh(); });
sidebar.onMessage("start", start);
sidebar.onMessage("stop", () => { stop(); state.message = "正在停止，当前转写段结束后退出…"; send(); });
sidebar.onMessage("seek", seconds => {
  if (Number.isFinite(seconds) && seconds >= 0 && seconds <= (state.duration || 0)) core.seekTo(seconds);
});
sidebar.onMessage("reveal", () => { if (state.folder) utils.open(state.folder); });
sidebar.onMessage("copy", async content => {
  if (!current || (content !== "summary" && content !== "transcript")) return;
  if (content === "summary" ? !state.summary : !state.segments.length) return;
  const version = generation;
  try {
    const result = await utils.exec(python, [worker, "copy", "--video", current, "--cache", cache, "--content", content]);
    if (version === generation) sidebar.postMessage("copy-result", {ok: result.status === 0});
  } catch (error) {
    if (version === generation) sidebar.postMessage("copy-result", {ok: false});
  }
});
}
event.on("iina.window-loaded", loadSidebar);
menu.addItem(menu.item("打开 AI 总结", () => {
  if (!sidebarLoaded) { loadSidebar(); sidebarLoaded = true; }
  sidebar.show(); refresh();
}, {keyBinding: "Ctrl+Alt+s"}));
event.on("iina.file-loaded", refresh);
event.on("iina.window-will-close", stop);
setInterval(poll, 700);
setInterval(refresh, 2000);
refresh();
