import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/fraunces/latin-500.css";
import "@fontsource/fraunces/latin-600.css";
import "@fontsource/work-sans/latin-400.css";
import "@fontsource/work-sans/latin-500.css";
import "@fontsource/work-sans/latin-600.css";
import "@fontsource/courier-prime/latin-400.css";
import "@fontsource/courier-prime/latin-700.css";
import "./styles/tokens.css";
import "./styles/app.css";
import App from "./App";
import { warmUpServer } from "./api";
import { TripProvider } from "./state/TripProvider";

// A hosted backend may be asleep: start it booting now, while the page loads
warmUpServer();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <TripProvider>
      <App />
    </TripProvider>
  </StrictMode>,
);
