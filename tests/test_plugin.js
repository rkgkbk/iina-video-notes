const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const messages = {}, timers = [], writes = new Map();
let state, url = 'file:///tmp/test%20video.mp4';
const context = vm.createContext({
  iina: {
    sidebar: {onMessage: (n, fn) => messages[n] = fn, postMessage: (_, v) => state = {...v}, loadFile: () => {}, show: () => {}},
    core: {status: {get url() {return url;}}, seekTo: v => context.position = v},
    menu: {item: () => ({}), addItem: () => {}}, event: {on: (name, fn) => {if(name === 'iina.window-loaded') context.loadSidebar = fn;}}, console: {error: console.error},
    file: {read: p => p.endsWith('config.json') ? '{"asrDirectory":"/tmp/asr"}' : writes.get(p) || '', write: (p,v) => writes.set(p,v)},
    utils: {resolvePath: p => p, exec: async (_,args) => ({status:0, stdout: args.includes('start') ? '{"pid":123}' : '', stderr:''})}
  },
  setInterval: fn => timers.push(fn), Date, Math, Number
});
vm.runInContext(fs.readFileSync('AI-Video.iinaplugin/main.js','utf8'), context);
(async () => {
  context.loadSidebar();
  await messages.ready();
  assert.equal(state.name,'test video.mp4');
  await messages.start();
  assert.equal(state.busy,true);
  const events = [...writes.keys()].find(p => p.endsWith('.jsonl'));
  writes.set(events, JSON.stringify({type:'result', segments:[{start:0,text:'hello'}], duration:120, summary:'summary',folder:'/tmp/result'})+'\n');
  await timers[0]();
  assert.equal(state.summary,'summary');
  assert.equal(state.busy,false);
  messages.seek(61); assert.equal(context.position,61);
  messages.seek(-1); assert.equal(context.position,61);
  url = 'file:///tmp/second.mp4';
  await timers[1]();
  assert.equal(state.summary,'');
  assert.equal(state.name,'second.mp4');
  assert.ok([...writes.keys()].some(p => p.includes('/cancel-')));
  console.log('PASS: state, background job, result, seek bounds, video switch/cancellation');
})().catch(e => {console.error(e);process.exitCode=1;});
