/* Threshold profile editor.
 * Each [data-band-editor] manages 4 number inputs and a band strip with
 * draggable handles. Values are kept non-decreasing in the order:
 *   simple : good <= fair <= poor <= unhealthy
 *   range  : fair_min <= good_min <= good_max <= fair_max
 * It is impossible to set a more-severe band to a value below a less-severe
 * one; typed entries are clamped, drag/keyboard input pushes neighbours.
 */
(() => {
  const ORDER = {
    simple: ['good', 'fair', 'poor', 'unhealthy'],
    range: ['fair_min', 'good_min', 'good_max', 'fair_max'],
  };

  function setupEditor(root) {
    const kind = root.dataset.kind || 'simple';
    const stripMin = parseFloat(root.dataset.min);
    const stripMax = parseFloat(root.dataset.max);
    const order = ORDER[kind] || [];

    const strip = root.querySelector('[data-strip]');
    if (!strip) return;

    const inputs = {};
    root.querySelectorAll('input.profile-num').forEach((el) => {
      inputs[el.dataset.band] = el;
    });

    const handles = {};
    root.querySelectorAll('[data-handle]').forEach((el) => {
      handles[el.dataset.band] = el;
      el.tabIndex = 0;
    });

    const regions = root.querySelectorAll('[data-region]');

    const span = stripMax - stripMin;
    const decimals = span >= 100 ? 0 : span >= 10 ? 1 : 2;

    function clampToStrip(v) {
      if (!Number.isFinite(v)) return stripMin;
      return Math.min(stripMax, Math.max(stripMin, v));
    }

    function getValue(band) {
      const el = inputs[band];
      if (!el) return 0;
      const v = parseFloat(el.value);
      return Number.isFinite(v) ? v : 0;
    }

    function setValue(band, value) {
      const el = inputs[band];
      if (!el) return;
      const factor = Math.pow(10, decimals);
      const rounded = Math.round(value * factor) / factor;
      el.value = String(rounded);
    }

    function pct(value) {
      if (stripMax <= stripMin) return 50;
      const r = (value - stripMin) / (stripMax - stripMin);
      return Math.max(0, Math.min(100, r * 100));
    }

    function resolveAnchor(name) {
      if (name === 'lo') return stripMin;
      if (name === 'hi') return stripMax;
      return getValue(name);
    }

    function render() {
      order.forEach((band) => {
        const h = handles[band];
        if (h) h.style.left = pct(getValue(band)) + '%';
      });
      regions.forEach((r) => {
        const a = resolveAnchor(r.dataset.from);
        const b = resolveAnchor(r.dataset.to);
        const lo = Math.min(a, b);
        const hi = Math.max(a, b);
        r.style.left = pct(lo) + '%';
        r.style.width = Math.max(0, pct(hi) - pct(lo)) + '%';
      });
      // Update each input's min/max to reflect the dynamic neighbour bounds.
      order.forEach((band, idx) => {
        const inp = inputs[band];
        if (!inp) return;
        inp.min = String(idx === 0 ? stripMin : getValue(order[idx - 1]));
        inp.max = String(idx === order.length - 1 ? stripMax : getValue(order[idx + 1]));
      });
    }

    function clampChangedInput(band) {
      const idx = order.indexOf(band);
      const lo = idx <= 0 ? -Infinity : getValue(order[idx - 1]);
      const hi = idx >= order.length - 1 ? Infinity : getValue(order[idx + 1]);
      const v = getValue(band);
      if (v < lo) setValue(band, lo);
      else if (v > hi) setValue(band, hi);
    }

    function pushNeighbours(band) {
      const idx = order.indexOf(band);
      for (let i = idx + 1; i < order.length; i++) {
        if (getValue(order[i]) < getValue(order[i - 1])) {
          setValue(order[i], getValue(order[i - 1]));
        } else break;
      }
      for (let i = idx - 1; i >= 0; i--) {
        if (getValue(order[i]) > getValue(order[i + 1])) {
          setValue(order[i], getValue(order[i + 1]));
        } else break;
      }
    }

    function normalizeAll() {
      for (let i = 1; i < order.length; i++) {
        if (getValue(order[i]) < getValue(order[i - 1])) {
          setValue(order[i], getValue(order[i - 1]));
        }
      }
    }

    Object.entries(inputs).forEach(([band, input]) => {
      input.addEventListener('input', () => {
        clampChangedInput(band);
        render();
      });
      input.addEventListener('change', () => {
        clampChangedInput(band);
        render();
      });
    });

    Object.entries(handles).forEach(([band, handle]) => {
      let dragging = false;

      function valueAtClientX(clientX) {
        const rect = strip.getBoundingClientRect();
        if (rect.width <= 0) return getValue(band);
        const ratio = (clientX - rect.left) / rect.width;
        return stripMin + Math.max(0, Math.min(1, ratio)) * span;
      }

      function onPointerMove(e) {
        if (!dragging) return;
        e.preventDefault();
        const v = clampToStrip(valueAtClientX(e.clientX));
        setValue(band, v);
        pushNeighbours(band);
        render();
      }

      function onPointerUp(e) {
        if (!dragging) return;
        dragging = false;
        handle.classList.remove('dragging');
        try { handle.releasePointerCapture?.(e.pointerId); } catch (_) {}
        window.removeEventListener('pointermove', onPointerMove);
        window.removeEventListener('pointerup', onPointerUp);
        window.removeEventListener('pointercancel', onPointerUp);
      }

      handle.addEventListener('pointerdown', (e) => {
        dragging = true;
        handle.classList.add('dragging');
        try { handle.setPointerCapture?.(e.pointerId); } catch (_) {}
        window.addEventListener('pointermove', onPointerMove);
        window.addEventListener('pointerup', onPointerUp);
        window.addEventListener('pointercancel', onPointerUp);
        handle.focus();
        e.preventDefault();
      });

      handle.addEventListener('keydown', (e) => {
        const stepMag = e.shiftKey ? 0.05 : 0.01;
        const step = stepMag * (span || 1);
        let delta = 0;
        if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') delta = -step;
        else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') delta = step;
        else if (e.key === 'Home') {
          const idx = order.indexOf(band);
          const floor = idx === 0 ? stripMin : getValue(order[idx - 1]);
          setValue(band, floor);
          render();
          e.preventDefault();
          return;
        } else if (e.key === 'End') {
          const idx = order.indexOf(band);
          const ceil = idx === order.length - 1 ? stripMax : getValue(order[idx + 1]);
          setValue(band, ceil);
          render();
          e.preventDefault();
          return;
        } else {
          return;
        }
        e.preventDefault();
        setValue(band, clampToStrip(getValue(band) + delta));
        pushNeighbours(band);
        render();
      });
    });

    normalizeAll();
    render();
  }

  function guardForm(form) {
    form.addEventListener('submit', (e) => {
      let bad = false;
      form.querySelectorAll('[data-band-editor]').forEach((root) => {
        const kind = root.dataset.kind || 'simple';
        const order = ORDER[kind] || [];
        let prev = -Infinity;
        for (const band of order) {
          const inp = root.querySelector(`input[data-band="${band}"]`);
          if (!inp) { bad = true; break; }
          const v = parseFloat(inp.value);
          if (!Number.isFinite(v) || v < prev) { bad = true; break; }
          prev = v;
        }
      });
      if (bad) {
        e.preventDefault();
        alert(
          'Threshold values must be in non-decreasing order from less severe '
          + 'to more severe. Please fix the highlighted values.'
        );
      }
    });
  }

  document.querySelectorAll('[data-band-editor]').forEach(setupEditor);
  document.querySelectorAll('form').forEach((form) => {
    if (form.querySelector('[data-band-editor]')) guardForm(form);
  });
})();
