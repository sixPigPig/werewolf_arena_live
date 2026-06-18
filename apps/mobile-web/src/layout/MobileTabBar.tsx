import { NavLink } from "react-router-dom";

const tabs = [
  { label: "大厅", href: "/games" },
  { label: "玩家", href: "/players" },
  { label: "历史", href: "/history" },
];

export function MobileTabBar() {
  return (
    <nav className="mobile-tab-bar" aria-label="移动端主导航">
      {tabs.map((tab) => (
        <NavLink
          key={tab.href}
          to={tab.href}
          className={({ isActive }) =>
            isActive ? "mobile-tab-link mobile-tab-link-active" : "mobile-tab-link"
          }
        >
          <span className="mobile-tab-mark" aria-hidden="true" />
          <span>{tab.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
