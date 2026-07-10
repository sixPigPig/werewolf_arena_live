type ModuleId =
  | "runs"
  | "games"
  | "players"
  | "voice"
  | "users"
  | "roles"
  | "audit"
  | "settings";

type ModuleDefinition = {
  api: string[];
  capabilities: string[];
  description: string;
  eyebrow: string;
  migrationSource: string;
  title: string;
};

const modules: Record<ModuleId, ModuleDefinition> = {
  runs: {
    eyebrow: "OPERATIONS",
    title: "实时运行",
    description: "监控运行状态、事件、错误与恢复链路。",
    capabilities: ["状态与时间筛选", "运行事件流", "错误诊断", "受控恢复操作"],
    api: ["GET /api/v1/admin/runs", "GET /api/v1/admin/runs/:runId"],
    migrationSource: "LiveGamePage 的诊断逻辑，不迁直播剧场 UI",
  },
  games: {
    eyebrow: "OPERATIONS",
    title: "对局记录",
    description: "服务端分页检索对局，并按权限查看完整模型诊断。",
    capabilities: ["分页与组合筛选", "关联运行", "回放时间线", "敏感 Debug Trace"],
    api: ["GET /api/v1/admin/games", "GET /api/v1/admin/games/:sessionId"],
    migrationSource: "GameDetailWorkbench、DebugPanel 与 replay adapters",
  },
  players: {
    eyebrow: "CONTENT",
    title: "虚拟玩家",
    description: "以草稿、发布、归档生命周期管理 C 端玩家内容。",
    capabilities: ["服务端搜索筛选", "玩家编辑与预览", "AI 草稿", "发布与归档"],
    api: ["GET /api/v1/admin/player-profiles", "POST /api/v1/admin/player-profiles"],
    migrationSource: "VirtualPlayerLibrary 的业务规则与校验，不复制旧样式",
  },
  voice: {
    eyebrow: "CONTENT",
    title: "法官语音",
    description: "查看资产状态、试听并执行受权限控制的生成任务。",
    capabilities: ["分类与缺失筛选", "安全试听", "生成缺失项", "任务状态与审计"],
    api: ["GET /api/v1/admin/voice-assets", "POST /api/v1/admin/voice-assets/jobs"],
    migrationSource: "JudgeVoiceAssetsPage 的分组与试听逻辑",
  },
  users: {
    eyebrow: "ACCESS",
    title: "后台用户",
    description: "管理后台账号状态，并分配固定角色。",
    capabilities: ["用户搜索", "启用与停用", "角色分配", "最后登录信息"],
    api: ["GET /api/v1/admin/users", "PATCH /api/v1/admin/users/:userId"],
    migrationSource: "全新模块；当前 User 模型不足以支持",
  },
  roles: {
    eyebrow: "ACCESS",
    title: "角色权限",
    description: "以固定角色展示后台能力矩阵，MVP 不提供自定义权限设计器。",
    capabilities: ["角色说明", "权限矩阵", "敏感能力标识", "数据范围说明"],
    api: ["GET /api/v1/admin/roles"],
    migrationSource: "全新模块；权限必须由后端强制执行",
  },
  audit: {
    eyebrow: "SYSTEM",
    title: "审计日志",
    description: "追踪操作者、资源、动作、结果与请求 ID。",
    capabilities: ["操作者筛选", "资源与动作筛选", "前后差异", "请求链路定位"],
    api: ["GET /api/v1/admin/audit-logs"],
    migrationSource: "全新模块；所有后台写操作的上线前置",
  },
  settings: {
    eyebrow: "SYSTEM",
    title: "系统配置",
    description: "MVP 仅展示非敏感运行配置与服务健康信息。",
    capabilities: ["环境信息", "模型可用性", "TTS 状态", "存储与任务健康"],
    api: ["GET /api/v1/admin/system/health"],
    migrationSource: "全新模块；API Key 永不返回浏览器",
  },
};

export default function ModulePage({ moduleId }: { moduleId: ModuleId }) {
  const definition = modules[moduleId];

  return (
    <div className="admin-page">
      <header className="page-heading">
        <div>
          <span className="page-kicker">{definition.eyebrow}</span>
          <h1>{definition.title}</h1>
          <p>{definition.description}</p>
        </div>
        <span className="module-status">等待 Admin API</span>
      </header>

      <section className="module-blueprint" aria-label={`${definition.title}开发蓝图`}>
        <div className="module-empty-state">
          <span className="blueprint-mark" aria-hidden="true">{definition.title.slice(0, 1)}</span>
          <h2>页面骨架已就位</h2>
          <p>
            该模块不会连接现有匿名接口。完成后台 DTO、鉴权和权限测试后，再迁入真实业务能力。
          </p>
        </div>
        <div className="blueprint-columns">
          <article>
            <span>计划能力</span>
            <ul>
              {definition.capabilities.map((capability) => (
                <li key={capability}>{capability}</li>
              ))}
            </ul>
          </article>
          <article>
            <span>目标接口</span>
            <ul className="code-list">
              {definition.api.map((endpoint) => (
                <li key={endpoint}>{endpoint}</li>
              ))}
            </ul>
          </article>
        </div>
        <footer>
          <span>迁移来源</span>
          <strong>{definition.migrationSource}</strong>
        </footer>
      </section>
    </div>
  );
}
