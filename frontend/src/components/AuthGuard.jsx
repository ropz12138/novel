import { Navigate } from "react-router-dom";

export function AuthGuard({ children }) {
  const token = localStorage.getItem("novel_token");
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
}
