import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";
import { IS_NATIVE_APP } from "./lib/runtime-config";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter
      basename={IS_NATIVE_APP ? "/" : "/novel"}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
