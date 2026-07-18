import { Navigate, Route, Routes } from "react-router-dom";
import { AuthGuard } from "./components/AuthGuard";
import { CanvasPage } from "./pages/CanvasPage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/"
        element={
          <AuthGuard>
            <CanvasPage />
          </AuthGuard>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
