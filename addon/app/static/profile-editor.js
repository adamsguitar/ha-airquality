(() => {
  function sync(pair) {
    const num = pair.querySelector('input.profile-num');
    const rng = pair.querySelector('input.profile-range');
    if (!num || !rng) return;
    rng.addEventListener('input', () => {
      num.value = rng.value;
    });
    num.addEventListener('input', () => {
      const v = Number(num.value);
      if (!Number.isNaN(v)) rng.value = v;
    });
  }
  document.querySelectorAll('[data-sync-pair]').forEach(sync);
})();
