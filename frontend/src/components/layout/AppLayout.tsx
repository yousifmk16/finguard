import { useState } from "react";
import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";

export default function AppLayout() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className="app" data-sidebar={sidebarCollapsed ? "collapsed" : "expanded"}>
      <TopBar onToggleSidebar={() => setSidebarCollapsed((c) => !c)} />
      <Sidebar />
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
