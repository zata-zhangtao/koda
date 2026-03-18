function initializeMermaid() {
  if (typeof mermaid === "undefined") {
    return;
  }

  mermaid.initialize({
    startOnLoad: false,
  });

  mermaid.run({
    querySelector: ".mermaid",
  });
}

if (typeof document$ !== "undefined") {
  document$.subscribe(initializeMermaid);
} else {
  window.addEventListener("load", initializeMermaid);
}
