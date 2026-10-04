(() => {
  const boot = () => {
    if (window.PH && typeof window.PH.bindHome === "function") window.PH.bindHome();
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
