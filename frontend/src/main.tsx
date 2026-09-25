import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth";
import Central from "./central/Central";
import "@fontsource/public-sans/latin-400.css";
import "@fontsource/public-sans/latin-500.css";
import "@fontsource/public-sans/latin-600.css";
import "@fontsource/public-sans/latin-700.css";
import "@fontsource/space-grotesk/latin-500.css";
import "@fontsource/space-grotesk/latin-600.css";
import "@fontsource/space-grotesk/latin-700.css";
import "./styles.css";
import { registerServiceWorker } from "./pwa";
import { initTheme } from "./theme";

initTheme();
registerServiceWorker();

const isCentral = location.pathname === "/central" || location.pathname.startsWith("/central/");
if (isCentral) {
  // A Central é um aplicativo à parte (manifesto próprio, sem login de pessoa): abre em tela cheia no tablet
  document.querySelector('link[rel="manifest"]')?.setAttribute("href", "/central.webmanifest");
  document.title = "Ponto Central";
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {isCentral ? (
      <Central />
    ) : (
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    )}
  </StrictMode>,
);
