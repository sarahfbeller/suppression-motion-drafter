"use strict";
// The website: a wizard over the engine, which runs in the browser through Pyodide. Nothing the
// attorney enters leaves the page. Python (scripts/site_api.py) decides what to ask and writes the
// documents; this file only shows questions, keeps the answers, and handles files.

const BUILD = document.documentElement.dataset.build;
const DOCX_WHEEL = "python_docx-1.2.0-py3-none-any.whl";  // scripts/build_site.py copies it to pyodide/
const REVIEW = "review";
const YES_NO = [["yes", "Yes"], ["no", "No"]];

// The feedback form (a Google Form, so the maintainer's address stays private). On a question screen
// the link pre-fills the form's "Which question?" field with that question: never any answers.
const FEEDBACK_FORM = "https://docs.google.com/forms/d/e/1FAIpQLSdJGxS_RZy5EQrs42alklXfvKMKUqnlubWFXfk10HqzL7C70A/viewform";
const FEEDBACK_QUESTION_FIELD = "entry.959751634";

// ---------------------------------------------------------------- Python

let api = null;         // scripts/site_api.py
let QUESTIONS = {};     // question id -> question
let docxLoaded = null;  // promise: python-docx, loaded in the background once the engine is up

const ready = (async () => {
  const py = await loadPyodide({ indexURL: new URL("pyodide/", location.href).href });
  const bundle = await (await fetch(`bundle.json?v=${BUILD}`)).json();
  for (const [path, text] of Object.entries(bundle)) {
    const full = "/repo/" + path;
    py.FS.mkdirTree(full.slice(0, full.lastIndexOf("/")));
    py.FS.writeFile(full, text);
  }
  py.runPython('import sys; sys.path.insert(0, "/repo/scripts")');
  api = py.pyimport("site_api");
  api.load("/repo");
  QUESTIONS = JSON.parse(api.questions());
  const quiet = { messageCallback: () => {} };
  docxLoaded = py.loadPackage(["lxml", "typing-extensions"], quiet)
    .then(() => py.loadPackage(new URL("pyodide/" + DOCX_WHEEL, location.href).href, quiet));
})();

// ---------------------------------------------------------------- state

let answers = {};      // every answer given, including ones a changed answer made irrelevant
let st = null;         // site_api.state(): {path, pending, steps}
let screen = "start";  // start | question | review | done
let cur = null;        // the question on screen
let editing = false;   // came from the review screen: ask only new questions, then go back
let dirty = false;     // answers not saved to a file since the last change
let docs = null;       // [motion bytes, memo bytes]

function refresh() {
  st = JSON.parse(api.state(JSON.stringify(answers)));
}

function position(id) {
  const i = st.path.findIndex(s => s.id === id);
  return i >= 0 ? i : st.path.length;  // the pending question comes after the path
}
const nextFrom = id => (st.path[position(id) + 1] || st.pending || {}).id || null;
const prevFrom = id => (st.path[position(id) - 1] || {}).id || null;
const phaseOf = id => (st.path.find(s => s.id === id) || st.pending).phase;

function reset() {
  answers = {}; st = null; cur = null; editing = false; dirty = false; docs = null;
}

// ---------------------------------------------------------------- rendering

const app = document.getElementById("app");
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const optionsOf = q => q.type === "yes_no" ? YES_NO : (q.options || []).map(o => [o.id, o.label]);

// "What did police search? Select all that apply." -> the question, and the instruction shown under it.
function splitPrompt(prompt) {
  const m = prompt.match(/^(.*?[?.])\s+(Select all[\s\S]*)$/);
  return m ? [m[1], m[2]] : [prompt, ""];
}

function feedbackLink() {
  if (screen !== "question" || !QUESTIONS[cur]) return FEEDBACK_FORM;
  const which = `${splitPrompt(QUESTIONS[cur].prompt)[0]} (${cur})`;
  return `${FEEDBACK_FORM}?usp=pp_url&${FEEDBACK_QUESTION_FIELD}=${encodeURIComponent(which)}`;
}

function show(next, { scroll = true } = {}) {
  screen = next;
  document.getElementById("save").classList.toggle("hidden", screen === "start");
  document.getElementById("feedback").href = feedbackLink();
  try {
    ({ start: renderStart, question: renderQuestion, review: renderReview, done: renderDone })[screen]();
  } catch (e) {
    showError(e);
  }
  if (scroll) window.scrollTo(0, 0);
}

function showError(e) {
  console.error(e);
  app.innerHTML = `
    <div class="start">
      <h1>Something went wrong</h1>
      <p class="lede small-lede">The page hit an error it couldn't recover from. If you've answered questions,
        save them to a file before reloading, then open the file after.</p>
      <div class="actions"><button class="btn btn-primary" id="reload" type="button">Reload the page</button></div>
    </div>`;
  document.getElementById("reload").onclick = () => location.reload();
}

function renderStart() {
  app.replaceChildren(document.getElementById("start-screen").content.cloneNode(true));
  const begin = document.getElementById("begin");
  const status = document.getElementById("load-status");
  let waiting = false;
  const whenReady = action => async () => {
    if (!api) {
      waiting = true;
      begin.disabled = true;
      status.textContent = "Getting ready…";
    }
    try {
      await ready;
    } catch (e) {
      console.error(e);
      status.classList.add("error");
      status.textContent = "This browser couldn't load the drafting engine. Try a current version of Chrome, Edge, Firefox, or Safari.";
      return;
    }
    if (waiting) { begin.disabled = false; status.textContent = ""; }
    action();
  };
  begin.onclick = whenReady(() => {
    refresh();
    cur = st.pending ? st.pending.id : null;
    cur ? show("question") : show(REVIEW);
  });
  document.getElementById("open").onclick = whenReady(() => document.getElementById("open-file").click());
}

function renderQuestion() {
  const q = QUESTIONS[cur];
  const [title, hint] = splitPrompt(q.prompt);
  const val = answers[cur];
  const multi = q.type === "multi_select";
  const answered = val !== undefined;
  // Until it's answered, what comes after isn't known, so the button doesn't promise the review yet.
  const toReview = answered && !(editing ? st.pending : nextFrom(cur));
  const label = toReview ? (editing ? "Back to review" : "Review answers") : "Next";
  const canNext = multi || (q.type === "short_text" ? true : answered);
  const hasBack = Boolean(prevFrom(cur)) || editing;

  let field;
  if (q.type === "short_text") {
    field = `<input class="text-answer" id="text-answer" type="text" value="${esc(val || "")}" aria-label="${esc(title)}">`;
  } else {
    const on = id => multi ? (val || []).includes(id) : val === id;
    field = `<fieldset class="opts ${multi ? "check" : "radio"}"><legend class="sr-only">${esc(title)}</legend>
      ${optionsOf(q).map(([id, lab]) => `
        <label class="opt ${on(id) ? "on" : ""}" data-id="${esc(id)}">
          <input type="${multi ? "checkbox" : "radio"}" name="answer" ${on(id) ? "checked" : ""}>
          <span class="mark" aria-hidden="true"></span><span>${esc(lab)}</span>
        </label>`).join("")}
    </fieldset>`;
  }

  app.innerHTML = `
    <div class="qgrid">
      <div class="qmain">
        <h1 class="q-title">${esc(title)}</h1>
        ${hint ? `<p class="q-hint">${esc(hint)}</p>` : ""}
        ${field}
        <div class="qnav">
          ${hasBack ? `<button class="btn btn-secondary" id="back" type="button">Back</button>` : ""}
          <button class="btn btn-primary" id="next" type="button" ${canNext ? "" : "disabled"}>${label}</button>
        </div>
      </div>
      ${stepList(phaseOf(cur))}
    </div>`;

  app.querySelectorAll(".opt").forEach(el => el.onclick = e => {
    e.preventDefault();
    const id = el.dataset.id;
    if (multi) {
      const picked = new Set(answers[cur] || []);
      picked.has(id) ? picked.delete(id) : picked.add(id);
      answers[cur] = optionsOf(q).map(o => o[0]).filter(o => picked.has(o));
    } else {
      answers[cur] = id;
    }
    changed();
    show("question", { scroll: false });
    const again = app.querySelector(`.opt[data-id="${CSS.escape(id)}"] input`);
    if (again) again.focus({ preventScroll: true });
  });
  const text = document.getElementById("text-answer");
  if (text) text.oninput = () => { answers[cur] = text.value; changed(); };

  const back = document.getElementById("back");
  if (back) back.onclick = () => {
    const p = prevFrom(cur);
    if (editing && !p) { editing = false; show(REVIEW); return; }
    cur = p;
    show("question");
  };
  document.getElementById("next").onclick = () => {
    if (answers[cur] === undefined) {  // a checklist with nothing checked, or an empty text answer
      answers[cur] = multi ? [] : "";
      changed();
    }
    const n = editing ? (st.pending || {}).id : nextFrom(cur);
    if (n) { cur = n; show("question"); } else { editing = false; show(REVIEW); }
  };
  wireSteps();
}

function stepList(current) {
  const steps = [...st.steps, { phase: REVIEW, name: "Review your answers" }];
  const at = steps.findIndex(s => s.phase === current);
  const visited = new Set(st.path.map(s => s.phase));
  return `
    <aside class="steps" aria-label="Where you are in the interview">
      <div class="steps-title">Your interview</div>
      <ol>${steps.map((s, i) => {
        const state = i < at ? "done" : i === at ? "current" : "todo";
        const link = i !== at && visited.has(s.phase);
        const name = link
          ? `<button class="name" type="button" data-phase="${esc(s.phase)}">${esc(s.name)}</button>`
          : `<span class="name">${esc(s.name)}</span>`;
        return `<li class="${link ? "done" : state}" ${i === at ? 'aria-current="step"' : ""}>
          <span class="dot" aria-hidden="true">${state === "done" ? "✓" : i + 1}</span>${name}</li>`;
      }).join("")}</ol>
    </aside>`;
}

function wireSteps() {
  app.querySelectorAll(".steps button[data-phase]").forEach(b => b.onclick = () => {
    cur = st.path.find(s => s.phase === b.dataset.phase).id;
    editing = false;
    show("question");
  });
}

function answerHTML(q, val) {
  if (q.type === "short_text") return val ? esc(val) : `<span class="none">No answer</span>`;
  const labels = Object.fromEntries(optionsOf(q));
  if (Array.isArray(val)) {
    return val.length ? `<ul>${val.map(v => `<li>${esc(labels[v] || v)}</li>`).join("")}</ul>` : `<span class="none">None</span>`;
  }
  return esc(labels[val] || val);
}

function renderReview() {
  refresh();
  const groups = st.steps
    .map(s => [s.name, st.path.filter(p => p.phase === s.phase)])
    .filter(([, qs]) => qs.length);
  app.innerHTML = `
    <div class="review">
      <h1>Check your answers</h1>
      <p class="lede small-lede">Change anything that isn't right, then draft the motion.</p>
      ${groups.map(([name, qs]) => `
        <h2 class="rv-phase">${esc(name)}</h2>
        <div class="rv">${qs.map(({ id }) => `
          <div class="rv-row">
            <div class="rv-q">${esc(splitPrompt(QUESTIONS[id].prompt)[0])}</div>
            <div class="rv-a">${answerHTML(QUESTIONS[id], answers[id])}</div>
            <div><button class="linkish" type="button" data-q="${esc(id)}">Change</button></div>
          </div>`).join("")}</div>`).join("")}
      <div class="actions"><button class="btn btn-primary" id="draft" type="button">Draft my motion</button></div>
    </div>`;
  app.querySelectorAll("[data-q]").forEach(b => b.onclick = () => {
    cur = b.dataset.q;
    editing = true;
    show("question");
  });
  document.getElementById("draft").onclick = () => { docs = null; show("done"); };
}

function renderDone() {
  app.innerHTML = `
    <div class="done-wrap">
      <h1>Your motion and memo are ready</h1>
      <p class="lede small-lede">Two Word files. The memo is for you only — don't file it.</p>
      <div class="downloads">
        <button class="btn btn-primary" data-doc="0" type="button" disabled>Download motion (.docx)</button>
        <button class="btn btn-secondary" data-doc="1" type="button" disabled>Download memo (.docx)</button>
      </div>
      <p class="status" id="doc-status" aria-live="polite">Preparing your documents…</p>
      <p class="small">Want to come back to this case? <button class="linkish" id="save-done" type="button">Save it to a file</button>
        and open it here later.</p>
      <div class="done-links">
        <button class="linkish" id="back-review" type="button">Back to your answers</button>
        <button class="linkish" id="new-case" type="button">Start a new case</button>
      </div>
    </div>`;
  const names = ["suppression-motion.docx", "suppression-memo.docx"];
  const buttons = app.querySelectorAll("[data-doc]");
  const status = document.getElementById("doc-status");
  buttons.forEach(b => b.onclick = () => download(docs[b.dataset.doc], names[b.dataset.doc],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"));
  document.getElementById("save-done").onclick = saveCase;
  document.getElementById("back-review").onclick = () => show(REVIEW);
  document.getElementById("new-case").onclick = () => startOver();

  (async () => {
    try {
      if (!docs) {
        await docxLoaded;
        const result = api.documents(JSON.stringify(answers));
        docs = result.toJs();
        result.destroy();
      }
      buttons.forEach(b => { b.disabled = false; });
      status.textContent = "";
    } catch (e) {
      console.error(e);
      status.classList.add("error");
      status.textContent = "The documents couldn't be made. Save your case to a file, reload the page, and try again.";
    }
  })();
}

// ---------------------------------------------------------------- files

function download(bytes, name, type) {
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function saveCase() {
  download(JSON.stringify({ answers }, null, 2), "suppression-case.json", "application/json");
  dirty = false;
}

async function openCase(file) {
  try {
    const data = JSON.parse(await file.text());
    if (!data || typeof data.answers !== "object" || Array.isArray(data.answers)) throw new Error("no answers");
    reset();
    answers = data.answers;
    refresh();
  } catch (e) {
    console.error(e);
    reset();
    show("start");
    const status = document.getElementById("load-status");
    status.classList.add("error");
    status.textContent = "That file isn't a saved case from this site.";
    return;
  }
  cur = st.pending ? st.pending.id : null;
  cur ? show("question") : show(REVIEW);
}

function changed() {
  dirty = true;
  docs = null;
  refresh();
}

function startOver() {
  if (dirty && !confirm("Start over? Your answers will be cleared. Save them to a file first if you need them.")) return;
  reset();
  show("start");
}

document.getElementById("save").onclick = saveCase;
document.getElementById("home").onclick = e => { e.preventDefault(); if (screen !== "start") startOver(); };
document.getElementById("open-file").onchange = e => {
  const f = e.target.files[0];
  e.target.value = "";
  if (f) openCase(f);
};
window.addEventListener("beforeunload", e => {
  if (dirty) { e.preventDefault(); e.returnValue = ""; }
});

show("start");
