import Button from "antd/es/button";
import Result from "antd/es/result";
import { useNavigate } from "react-router-dom";

export default function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <Result
      extra={<Button onClick={() => navigate("/overview")} type="primary">返回运营总览</Button>}
      status="404"
      subTitle="当前地址不在已规划的管理后台信息架构中。"
      title={<h1>后台页面不存在</h1>}
    />
  );
}
