/** 从已按 updated_at 降序排列的 session 列表中取最新一条。 */
export function getLatestSupervisorSession(sessions) {
  if (!Array.isArray(sessions) || sessions.length === 0) return null;
  return sessions[0];
}
