import React from "react";
import ReactDOM from "react-dom/client";
import { Toaster } from "sonner";
import App from "./App";
import ColumnConfigProvider from "./components/ColumnConfigProvider";
import "./styles/index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ColumnConfigProvider>
      <App />
      <Toaster richColors position="top-right" theme="dark" />
    </ColumnConfigProvider>
  </React.StrictMode>
);
