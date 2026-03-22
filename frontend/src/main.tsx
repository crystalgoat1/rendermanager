import { render } from "preact";
import { App } from "./App";
import "./index.css";

// Load Google Fonts asynchronously — avoids render-blocking on Safari mobile.
// Without this, Safari blocks the entire page until fonts.googleapis.com responds,
// which can add 5-10s on slow mobile connections.
const fontUrls = [
  "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap",
  "https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200",
];
for (const url of fontUrls) {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = url;
  document.head.appendChild(link);
}

render(<App />, document.getElementById("app")!);
