import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

// Every state-changing request carries a header a foreign website cannot add (CSRF defence, see SECURITY.md),
// and a 401 anywhere sends the user back to the sign-in page.
const nativeFetch = window.fetch.bind(window);
window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const req = input instanceof Request ? input : null;
  const method = (init?.method ?? req?.method ?? "GET").toUpperCase();
  if (method !== "GET" && method !== "HEAD") {
    const headers = new Headers(init?.headers ?? req?.headers);
    headers.set("X-Requested-With", "gcc");
    init = { ...init, headers };
  }
  const url = typeof input === "string" ? input : input instanceof URL ? input.pathname : (input as Request).url;
  return nativeFetch(input, init).then((r) => {
    if (r.status === 401 && !url.includes("/api/auth/")) window.dispatchEvent(new Event("gcc-unauthorized"));
    return r;
  });
};

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
