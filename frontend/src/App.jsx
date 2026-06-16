import { Navigate, Route, Routes } from "react-router-dom";
import { AgentArchPage } from "./pages/AgentArchPage";
import { AuthGuard } from "./components/AuthGuard";
import { CanvasPage } from "./pages/CanvasPage";
import { CharacterListPage } from "./pages/CharacterListPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { NewWorkPage } from "./pages/NewWorkPage";
import { RegisterPage } from "./pages/RegisterPage";
import { UnifiedAgentPage } from "./pages/UnifiedAgentPage";
import { WorkDetailPage } from "./pages/WorkDetailPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/dashboard"
        element={
          <AuthGuard>
            <DashboardPage />
          </AuthGuard>
        }
      />
      <Route
        path="/works/new"
        element={
          <AuthGuard>
            <NewWorkPage />
          </AuthGuard>
        }
      />
      <Route
        path="/works/:workId/characters"
        element={
          <AuthGuard>
            <CharacterListPage />
          </AuthGuard>
        }
      />
      <Route
        path="/works/:workId"
        element={
          <AuthGuard>
            <WorkDetailPage />
          </AuthGuard>
        }
      />
      <Route
        path="/architecture"
        element={
          <AuthGuard>
            <AgentArchPage />
          </AuthGuard>
        }
      />
      <Route
        path="/agent"
        element={
          <AuthGuard>
            <UnifiedAgentPage />
          </AuthGuard>
        }
      />
      <Route
        path="/canvas"
        element={
          <AuthGuard>
            <CanvasPage />
          </AuthGuard>
        }
      />
      <Route path="*" element={<Navigate to="/canvas" replace />} />
    </Routes>
  );
}
