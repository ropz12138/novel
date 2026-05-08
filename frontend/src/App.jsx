import { Navigate, Route, Routes } from "react-router-dom";
import { AgentPage } from "./pages/AgentPage";
import { AuthGuard } from "./components/AuthGuard";
import { ChaptersPage } from "./pages/ChaptersPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { NewWorkPage } from "./pages/NewWorkPage";
import { RegisterPage } from "./pages/RegisterPage";
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
        path="/works/:workId/chapters"
        element={
          <AuthGuard>
            <ChaptersPage />
          </AuthGuard>
        }
      />
      <Route
        path="/works/:workId/agent/:chapterNum"
        element={
          <AuthGuard>
            <AgentPage />
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
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
