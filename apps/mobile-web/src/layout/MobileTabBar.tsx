import { NavLink } from "react-router-dom";

const tabs = [
  { label: "对局", to: "/", end: true },
  { label: "玩家", to: "/players" },
  { label: "历史", to: "/history" },
  { label: "设置", to: "/settings" },
];

export function MobileTabBar() {
  return (
    <nav aria-label="手机版主导航" className="mobile-tab-bar">
      {tabs.map((tab) => (
        <NavLink
          className={({ isActive }) =>
            ["mobile-tab-link", isActive ? "mobile-tab-link-active" : null]
              .filter(Boolean)
              .join(" ")
          }
          end={tab.end}
          key={tab.to}
          to={tab.to}
        >
          <span aria-hidden="true" className="mobile-tab-mark" />
          <span>{tab.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
