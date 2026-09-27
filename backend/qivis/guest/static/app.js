// Guest portal client. Plain DOM (textContent everywhere: no HTML injection).

const $ = (id) => document.getElementById(id);
const state = { convId: null, nodes: [], choose: new Set(), busy: false, model: "" };

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
  });
  if (res.status === 401) { location.reload(); throw new Error("signed out"); }
  if (!res.ok) {
    let msg = `Something went wrong (${res.status})`;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res;
}

// Read a server-sent-events response, calling onEvent(name, data) for each event.
async function readSSE(res, onEvent) {
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i); buf = buf.slice(i + 2);
      let ev = "", data = null;
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) ev = line.slice(7);
        else if (line.startsWith("data: ")) data = JSON.parse(line.slice(6));
      }
      if (ev && data) onEvent(ev, data);
    }
  }
}

// -- rendering --

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function renderBody(node) {
  const body = el("div", "body");
  if (node.tokens) {
    for (const t of node.tokens) {
      const span = el("span", "tok", t.t);
      span.style.background = `rgba(var(--heat), ${((1 - t.p) * 0.55).toFixed(3)})`;
      span.tipData = t;
      body.appendChild(span);
    }
  } else {
    body.textContent = node.content;
  }
  return body;
}

function render() {
  const box = $("messages");
  box.replaceChildren();
  if (!state.convId) {
    box.appendChild(el("p", "empty", "Start a new conversation from the list."));
    return;
  }
  if (!state.nodes.length) box.appendChild(el("p", "empty", "Say hello."));
  state.nodes.forEach((node, idx) => {
    const m = el("article", `msg ${node.role}`);
    m.appendChild(el("div", "who", node.author));
    m.appendChild(renderBody(node));
    const tools = el("div", "tools");
    const n = node.sibling_ids.length;
    if (node.role === "assistant" && n > 1) {
      const pos = node.sibling_ids.indexOf(node.id);
      const pager = el("span", "pager");
      const prev = el("button", null, "‹"); prev.disabled = pos === 0 || state.busy;
      const next = el("button", null, "›"); next.disabled = pos === n - 1 || state.busy;
      prev.onclick = () => pick(node, node.sibling_ids[pos - 1]);
      next.onclick = () => pick(node, node.sibling_ids[pos + 1]);
      pager.append(prev, `${pos + 1}/${n}`, next);
      tools.appendChild(pager);
    }
    const last = idx === state.nodes.length - 1;
    if (last && (node.role === "assistant" || node.role === "user")) {
      const again = el("button", null, node.role === "assistant" ? "Try again" : "Get a reply");
      again.disabled = state.busy;
      again.onclick = () => regenerate(node.id);
      tools.appendChild(again);
    }
    if (tools.childNodes.length) m.appendChild(tools);
    box.appendChild(m);
  });
  box.scrollTop = box.scrollHeight;
  const leaf = state.nodes[state.nodes.length - 1];
  $("send").disabled = state.busy || (leaf && leaf.role !== "assistant");
}

function pick(node, siblingId) {
  for (const id of node.sibling_ids) state.choose.delete(id);
  state.choose.add(siblingId);
  loadConversation();
}

// -- streaming a reply --

async function stream(res) {
  let live = null;
  // If the model was asleep, the first words can take a few seconds.
  const waking = el("p", "waking", `${state.model} is waking up… the first reply can take a few seconds.`);
  const wakeTimer = setTimeout(() => {
    $("messages").appendChild(waking);
    $("messages").scrollTop = $("messages").scrollHeight;
  }, 2500);
  await readSSE(res, (ev, data) => {
    if (ev !== "user") { clearTimeout(wakeTimer); waking.remove(); }
    if (ev === "user") {
      state.nodes.push(data); render();
    } else if (ev === "delta") {
      if (!live) {
        live = el("article", "msg assistant");
        live.appendChild(el("div", "who", state.model));
        live.appendChild(el("div", "body", ""));
        $("messages").appendChild(live);
      }
      live.lastChild.textContent += data.text;
      $("messages").scrollTop = $("messages").scrollHeight;
    } else if (ev === "done") {
      state.choose.add(data.id);
      for (const id of data.sibling_ids) if (id !== data.id) state.choose.delete(id);
    } else if (ev === "error") {
      $("messages").appendChild(el("p", "error", data.message));
    }
  });
  clearTimeout(wakeTimer); waking.remove();
}

async function send(e) {
  e.preventDefault();
  const text = $("input").value.trim();
  if (!text || state.busy || !state.convId) return;
  const leaf = state.nodes[state.nodes.length - 1];
  setBusy(true);
  try {
    const res = await api(`/api/conversations/${state.convId}/messages`, {
      method: "POST", body: JSON.stringify({ content: text, parent_id: leaf ? leaf.id : null }),
    });
    $("input").value = "";
    await stream(res);
  } catch (err) {
    $("messages").appendChild(el("p", "error", err.message));
  }
  setBusy(false);
  await loadConversation();
  loadConversations();
}

async function regenerate(nodeId) {
  if (state.busy) return;
  setBusy(true);
  try {
    const res = await api(`/api/conversations/${state.convId}/regenerate`, {
      method: "POST", body: JSON.stringify({ node_id: nodeId }),
    });
    const node = state.nodes.find((n) => n.id === nodeId);
    if (node && node.role === "assistant") state.nodes.pop();  // replaced by the new attempt
    render();
    await stream(res);
  } catch (err) {
    $("messages").appendChild(el("p", "error", err.message));
  }
  setBusy(false);
  await loadConversation();
}

function setBusy(b) { state.busy = b; $("send").disabled = b; render(); }

// -- conversations --

async function loadConversation() {
  if (!state.convId) return render();
  const q = state.choose.size ? `?choose=${[...state.choose].join(",")}` : "";
  const conv = await (await api(`/api/conversations/${state.convId}${q}`)).json();
  state.nodes = conv.nodes;
  state.model = conv.model;
  $("title").textContent = conv.model;
  render();
}

async function loadConversations() {
  const convs = await (await api("/api/conversations")).json();
  const nav = $("conversations");
  nav.replaceChildren();
  for (const c of convs) {
    const a = el("a", c.id === state.convId ? "active" : null);
    a.href = `#${c.id}`;
    a.appendChild(document.createTextNode(c.preview || "New conversation"));
    a.appendChild(el("small", null, `${c.model} · ${new Date(c.updated_at).toLocaleString()}`));
    nav.appendChild(a);
  }
  return convs;
}

async function openConversation(id) {
  state.convId = id; state.choose = new Set();
  document.body.classList.remove("side-open");
  await loadConversation();
  loadConversations();
}

async function newConversation() {
  const res = await api("/api/conversations", {
    method: "POST", body: JSON.stringify({ model_id: $("model").value }),
  });
  const { id } = await res.json();
  location.hash = id;
}

// -- certainty tooltip --

function showTip(e) {
  const t = e.target.tipData;
  if (!t || document.body.classList.contains("no-heat")) return;
  const tip = $("tip");
  tip.replaceChildren();
  const rows = [{ t: t.t, p: t.p, chosen: true }, ...t.alts.filter((a) => a.t !== t.t)];
  for (const r of rows.slice(0, 6)) {
    const row = el("div", "row" + (r.chosen ? " chosen" : ""));
    row.append(el("span", null, JSON.stringify(r.t).slice(1, -1) || "∅"), el("span", null, `${(r.p * 100).toFixed(1)}%`));
    tip.appendChild(row);
  }
  tip.hidden = false;
  const box = e.target.getBoundingClientRect();
  tip.style.left = `${Math.min(box.left, innerWidth - tip.offsetWidth - 8)}px`;
  tip.style.top = `${box.bottom + 6}px`;
}

// -- start --

addEventListener("DOMContentLoaded", async () => {
  $("composer").addEventListener("submit", send);
  $("input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("composer").requestSubmit(); }
  });
  $("new-conv").onclick = newConversation;
  $("open-side").onclick = () => document.body.classList.add("side-open");
  $("close-side").onclick = () => document.body.classList.remove("side-open");
  $("heat").onchange = (e) => document.body.classList.toggle("no-heat", !e.target.checked);
  $("messages").addEventListener("mouseover", showTip);
  $("messages").addEventListener("click", showTip);
  $("messages").addEventListener("mouseout", () => { $("tip").hidden = true; });
  addEventListener("hashchange", () => openConversation(location.hash.slice(1)));

  $("who").textContent = `Hi, ${(await (await api("/api/me")).json()).name}`;
  for (const m of await (await api("/api/models")).json()) {
    const o = el("option", null, m.label); o.value = m.id; $("model").appendChild(o);
  }
  const convs = await loadConversations();
  if (location.hash.length > 1) openConversation(location.hash.slice(1));
  else if (convs.length) location.hash = convs[0].id;
  else render();
});
