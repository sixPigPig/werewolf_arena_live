import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <section className="not-found-page">
      <span>404</span>
      <h1>后台页面不存在</h1>
      <p>当前地址不在已规划的管理后台信息架构中。</p>
      <Link to="/overview">返回运营总览</Link>
    </section>
  );
}
