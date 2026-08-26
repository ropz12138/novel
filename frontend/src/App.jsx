import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AuthGuard } from "./components/AuthGuard";

const CanvasPage = lazy(() => import("./pages/CanvasPage").then((module) => ({
  default: module.CanvasPage,
})));
const LoginPage = lazy(() => import("./pages/LoginPage").then((module) => ({
  default: module.LoginPage,
})));
const RegisterPage = lazy(() => import("./pages/RegisterPage").then((module) => ({
  default: module.RegisterPage,
})));
const ResearchPage = lazy(() => import("./pages/ResearchPage").then((module) => ({
  default: module.ResearchPage,
})));

function PageFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 text-sm text-slate-500">
      加载中...
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<PageFallback />}>
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
      <Route
        path="/research"
        element={
          <AuthGuard>
            <ResearchPage />
          </AuthGuard>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
