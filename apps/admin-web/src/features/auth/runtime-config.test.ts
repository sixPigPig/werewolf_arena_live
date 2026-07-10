import {
  resolveAdminDevLoginEnabled,
  resolveAdminRuntimeMode,
} from "@/features/auth/runtime-config";

describe("admin auth runtime gates", () => {
  it("keeps production closed by default", () => {
    expect(
      resolveAdminRuntimeMode({
        DEV: false,
        MODE: "production",
      }),
    ).toBe("closed");
  });

  it("allows a deployed identity provider to opt into the authenticated boundary", () => {
    expect(
      resolveAdminRuntimeMode({
        DEV: false,
        MODE: "production",
        VITE_ADMIN_AUTH_ENABLED: "true",
      }),
    ).toBe("authenticated");
  });

  it("enables dev login by default in DEV and permits an explicit opt-out", () => {
    expect(
      resolveAdminDevLoginEnabled({
        DEV: true,
        VITE_ADMIN_DEV_LOGIN_ENABLED: "true",
      }),
    ).toBe(true);
    expect(
      resolveAdminDevLoginEnabled({
        DEV: true,
        VITE_ADMIN_DEV_LOGIN_ENABLED: "1",
      }),
    ).toBe(true);
    expect(
      resolveAdminDevLoginEnabled({
        DEV: true,
        VITE_ADMIN_DEV_LOGIN_ENABLED: "false",
      }),
    ).toBe(false);
    expect(
      resolveAdminDevLoginEnabled({
        DEV: false,
        VITE_ADMIN_DEV_LOGIN_ENABLED: "true",
      }),
    ).toBe(false);
  });

  it("makes authenticated dev mode take precedence over preview", () => {
    expect(
      resolveAdminRuntimeMode({
        DEV: true,
        MODE: "development",
        VITE_ADMIN_DEV_LOGIN_ENABLED: "true",
        VITE_ADMIN_PREVIEW_MODE: "true",
      }),
    ).toBe("authenticated");
  });
});
