(() => {
  const boot = () => {
    if (window.PH && typeof window.PH.loadArticle === "function") window.PH.loadArticle();
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
