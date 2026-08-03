'use strict';

// Regression tests for the Android PWA black-screen reload guard.
// Run with: node flutter_client/web/reload_guard.test.js
const test = require('node:test');
const assert = require('node:assert/strict');
const { createReloadGuard } = require('./reload_guard.js');

function makeCanvas() {
  const listeners = {};
  return {
    shadowRoot: null,
    addEventListener(type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    dispatch(type) {
      (listeners[type] || []).forEach((fn) => fn());
    },
  };
}

function makeDoc(canvases) {
  const listeners = {};
  return {
    hidden: false,
    querySelectorAll(sel) {
      return sel === 'canvas' ? canvases : [];
    },
    addEventListener(type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    removeEventListener(type, fn) {
      listeners[type] = (listeners[type] || []).filter((f) => f !== fn);
    },
    fire(type) {
      (listeners[type] || []).forEach((fn) => fn());
    },
  };
}

// A fake window with a controllable clock: advance() fires any timers whose
// deadline has passed and re-arms intervals, so tests can simulate elapsed
// time deterministically instead of relying on real delays.
function makeWindow() {
  let clock = 0;
  const timers = [];
  let nextId = 1;
  return {
    reloadCalls: 0,
    location: {
      reload() {
        this.reloadCalls = (this.reloadCalls || 0) + 1;
      },
    },
    now: () => clock,
    setTimeout(fn, ms) {
      const id = nextId++;
      timers.push({ id, at: clock + ms, fn, interval: null });
      return id;
    },
    clearTimeout(id) {
      const i = timers.findIndex((t) => t.id === id);
      if (i >= 0) timers.splice(i, 1);
    },
    setInterval(fn, ms) {
      const id = nextId++;
      timers.push({ id, at: clock + ms, fn, interval: ms });
      return id;
    },
    clearInterval(id) {
      const i = timers.findIndex((t) => t.id === id);
      if (i >= 0) timers.splice(i, 1);
    },
    advance(ms) {
      clock += ms;
      for (const t of [...timers]) {
        if (t.at <= clock) {
          t.fn();
          if (t.interval != null) {
            t.at = clock + t.interval;
          } else {
            const i = timers.indexOf(t);
            if (i >= 0) timers.splice(i, 1);
          }
        }
      }
    },
  };
}

const SCAN_MS = 2000;
const GRACE_MS = 3000;
const HIDDEN_FALLBACK_MS = 30 * 60 * 1000;

function setup(canvas) {
  const win = makeWindow();
  const doc = makeDoc([canvas]);
  win.location.reload = win.location.reload.bind(win);
  createReloadGuard({
    window: win,
    document: doc,
    reload: () => win.location.reload(),
    now: () => win.now(),
    restoreGraceMs: GRACE_MS,
    hiddenFallbackMs: HIDDEN_FALLBACK_MS,
    scanIntervalMs: SCAN_MS,
  });
  win.advance(SCAN_MS); // let the scan discover the canvas
  return { win, doc };
}

test('context lost then restored within the grace period does not reload', () => {
  const canvas = makeCanvas();
  const { win } = setup(canvas);

  canvas.dispatch('webglcontextlost');
  canvas.dispatch('webglcontextrestored');
  win.advance(GRACE_MS + 100);

  assert.equal(win.reloadCalls, 0);
});

test('context lost with no restore reloads after the grace period', () => {
  const canvas = makeCanvas();
  const { win } = setup(canvas);

  canvas.dispatch('webglcontextlost');
  win.advance(GRACE_MS + 100);

  assert.equal(win.reloadCalls, 1);
});

test('backgrounding shorter than the fallback threshold does not reload', () => {
  const canvas = makeCanvas();
  const { win, doc } = setup(canvas);

  doc.hidden = true;
  doc.fire('visibilitychange');
  win.advance(HIDDEN_FALLBACK_MS - 1000);
  doc.hidden = false;
  doc.fire('visibilitychange');
  win.advance(GRACE_MS + 100);

  assert.equal(win.reloadCalls, 0);
});

test('backgrounding longer than the fallback threshold reloads as a last resort', () => {
  const canvas = makeCanvas();
  const { win, doc } = setup(canvas);

  doc.hidden = true;
  doc.fire('visibilitychange');
  win.advance(HIDDEN_FALLBACK_MS + 1000);
  doc.hidden = false;
  doc.fire('visibilitychange');
  win.advance(GRACE_MS + 100);

  assert.equal(win.reloadCalls, 1);
});
