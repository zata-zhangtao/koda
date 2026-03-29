/** React 应用入口
 *
 * 渲染根组件到 DOM
 */

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { ProjectTimelinePage } from "./pages/ProjectTimelinePage";
import "./index.css";

function resolveRootPage(): React.ReactNode {
  const normalizedPathname = window.location.pathname.replace(/\/+$/, "") || "/";
  if (normalizedPathname === "/project-timeline") {
    return <ProjectTimelinePage />;
  }
  return <App />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {resolveRootPage()}
  </React.StrictMode>
);
