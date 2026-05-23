import { Navigate } from "react-router-dom";

/**
 * Check if a JWT token is expired.
 * Returns true if the token is missing or expired.
 */
function isTokenExpired(token) {
  if (!token) return true;
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return true;
    const payload = JSON.parse(atob(parts[1]));
    if (!payload.exp) return false;
    return payload.exp * 1000 < Date.now();
  } catch {
    return true;
  }
}

export function AuthGuard({ children }) {
  const token = localStorage.getItem("novel_token");
  if (!token || isTokenExpired(token)) {
    localStorage.removeItem("novel_token");
    localStorage.removeItem("novel_user");
    return <Navigate to="/login" replace />;
  }
  return children;
}
