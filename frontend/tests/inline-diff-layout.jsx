import React from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import InlineTextDiff from "../src/components/InlineTextDiff";
import "../src/styles.css";

const root = createRoot(document.getElementById("root"));
window.renderDiff = ({ oldText, newText, editable, fontSize = 18 }) => flushSync(() => root.render(
  <div style={{ padding: 20, fontSize, lineHeight: 1.5 }}>
    <InlineTextDiff oldText={oldText} newText={newText} onResolveChange={editable ? () => {} : undefined} />
  </div>,
));
