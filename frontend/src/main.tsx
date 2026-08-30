import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { bootstrapAuth } from "./api/client";

if (window.location.pathname.endsWith("/benchmark")) {
  void import("./benchmark/benchmark").then(({ startBenchmark }) => startBenchmark());
} else {
  void bootstrapAuth().then((authenticated) => {
    if (!authenticated) {
      const next = `${window.location.pathname}${window.location.search}`;
      window.location.replace(`/accounts/login?next=${encodeURIComponent(next)}`);
      return;
    }
    createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
  });
}
