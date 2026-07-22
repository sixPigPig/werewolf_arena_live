import type { ThemeConfig } from "antd/es/config-provider/context";

export const adminTheme: ThemeConfig = {
  cssVar: {},
  hashed: false,
  token: {
    borderRadius: 8,
    colorBgContainer: "#ffffff",
    colorBgLayout: "#f5f7fa",
    colorBorder: "#d9e0e8",
    colorInfo: "#0958d9",
    colorPrimary: "#0958d9",
    colorSuccess: "#237804",
    colorText: "#172033",
    colorTextDescription: "#475467",
    colorTextSecondary: "#475467",
    colorWarning: "#d97706",
    fontFamily:
      'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    fontSize: 14,
    motion: false,
    wireframe: false,
  },
  components: {
    Card: {
      borderRadiusLG: 10,
      headerBg: "transparent",
    },
    Layout: {
      bodyBg: "#f5f7fa",
      headerBg: "rgba(255, 255, 255, 0.94)",
      siderBg: "#111827",
    },
    Menu: {
      darkItemBg: "#111827",
      darkItemColor: "#aab4c4",
      darkItemHoverBg: "rgba(255, 255, 255, 0.08)",
      darkItemHoverColor: "#ffffff",
      darkItemSelectedBg: "#0958d9",
      darkItemSelectedColor: "#ffffff",
      itemBorderRadius: 7,
    },
    Table: {
      borderColor: "#e6eaf0",
      headerBg: "#f8fafc",
      headerColor: "#344054",
      rowHoverBg: "#f7faff",
    },
  },
};
