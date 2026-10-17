import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, RequireAuth } from "./AuthGate";
import { AppShell } from "./components/AppShell";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ProjectPage } from "./pages/ProjectPage";
import { SettingsPage } from "./pages/SettingsPage";
import { VulnsPage } from "./pages/VulnsPage";
import { AgentsPage } from "./pages/AgentsPage";
import { LoginPage } from "./pages/LoginPage";
import { AboutPage } from "./pages/AboutPage";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route
          path="/*"
          element={
            <RequireAuth>
              <AppShell>
                <Routes>
                  <Route path="/" element={<ProjectsPage />} />
                  <Route path="/vulns" element={<VulnsPage />} />
                  <Route path="/agents" element={<AgentsPage />} />
                  <Route path="/project/:id" element={<ProjectPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                  <Route path="/intro" element={<Navigate to="/" replace />} />
                  <Route path="/replay" element={<Navigate to="/" replace />} />
                </Routes>
              </AppShell>
            </RequireAuth>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
