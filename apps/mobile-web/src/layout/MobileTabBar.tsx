import { NavLink } from "react-router-dom";

import createRoomNavAsset from "../assets/nav-bar/create-room-clean-alpha.png";
import matchRecordNavAsset from "../assets/nav-bar/match-record-clean-alpha.png";
import playerAtlasNavAsset from "../assets/nav-bar/player-atlas-clean-alpha.png";

const tabs = [
  { label: "创建对局", href: "/games", imageSrc: createRoomNavAsset },
  { label: "玩家图鉴", href: "/players", imageSrc: playerAtlasNavAsset },
  { label: "对局记录", href: "/history", imageSrc: matchRecordNavAsset },
];

export function MobileTabBar() {
  return (
    <nav className="mobile-tab-bar" aria-label="移动端主导航">
      {tabs.map((tab) => (
        <NavLink
          key={tab.href}
          to={tab.href}
          aria-label={tab.label}
          className={({ isActive }) =>
            isActive ? "mobile-tab-link mobile-tab-link-active" : "mobile-tab-link"
          }
        >
          <img
            alt=""
            aria-hidden="true"
            className="mobile-tab-image"
            draggable={false}
            src={tab.imageSrc}
          />
        </NavLink>
      ))}
    </nav>
  );
}
