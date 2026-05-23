import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { API_BASE } from "../lib/runtime-config";

export function LoginPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const parseError = (data, fallback) => {
    if (typeof data?.detail === "string" && data.detail) return data.detail;
    if (Array.isArray(data?.detail) && data.detail.length > 0) {
      const first = data.detail[0];
      if (first?.msg) return first.msg;
    }
    return fallback;
  };

  if (localStorage.getItem("novel_token")) {
    return <Navigate to="/dashboard" replace />;
  }

  const onSubmit = async (event) => {
    event.preventDefault();
    if ((form.password || "").length < 6) {
      setError("密码至少需要 6 位");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(parseError(data, "登录失败"));
      }
      localStorage.setItem("novel_token", data.token);
      localStorage.setItem("novel_user", data?.user?.username || form.email.split("@")[0] || "创作者");
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err.message || "登录失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-b from-slate-50 to-blue-100 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>登录账号</CardTitle>
          <CardDescription>登录后进入你的小说创作空间。</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={onSubmit}>
            <div className="space-y-2">
              <Label htmlFor="email">邮箱</Label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                value={form.email}
                onChange={(event) => setForm((prev) => ({ ...prev, email: event.target.value }))}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                placeholder="请输入密码"
                value={form.password}
                onChange={(event) => setForm((prev) => ({ ...prev, password: event.target.value }))}
                required
              />
            </div>
            <Button type="submit" className="w-full">
              {submitting ? "登录中..." : "登录"}
            </Button>
            {error && <p className="text-sm text-red-600">{error}</p>}
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            还没有账号？
            <Link className="ml-1 text-primary hover:underline" to="/register">
              立即注册
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
