import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/app";
import { SessionProvider } from "./app/session";
import "./index.css";

const container = document.getElementById("root");
if (container === null) throw new Error("the #root mount point is missing from index.html");

createRoot(container).render(
  <StrictMode>
    <SessionProvider>
      <App />
    </SessionProvider>
  </StrictMode>,
);
