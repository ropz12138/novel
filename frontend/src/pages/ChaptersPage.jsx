import { Navigate, useParams } from "react-router-dom";

/** 章节编辑已并入作品工作台 `/works/:id`；本路由仅兼容旧链接。 */
export function ChaptersPage() {
  const { workId } = useParams();
  return <Navigate to={`/works/${workId}?tab=chapter`} replace />;
}
