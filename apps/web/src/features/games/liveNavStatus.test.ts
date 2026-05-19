import { describe, expect, it } from "vitest";

import { deriveLiveNavStatus } from "./liveNavStatus";

describe("deriveLiveNavStatus", () => {
  it("maps idle and connecting streams to connecting", () => {
    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "idle",
        isPaused: false,
        runStatus: "running",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: [],
      kind: "connecting",
      label: "连接中",
    });

    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "connecting",
        isPaused: false,
        runStatus: "running",
        speed: 1,
      }).kind,
    ).toBe("connecting");
  });

  it("maps an open running stream with no backlog to live", () => {
    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "open",
        isPaused: false,
        runStatus: "running",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: ["1x"],
      kind: "live",
      label: "直播中",
    });
  });

  it("maps backlog to catching up with speed and backlog details", () => {
    expect(
      deriveLiveNavStatus({
        backlogCount: 8,
        connectionState: "open",
        isPaused: false,
        runStatus: "running",
        speed: 2,
      }),
    ).toMatchObject({
      detailItems: ["落后 8 条", "2x"],
      kind: "catchingUp",
      label: "追播中",
    });
  });

  it("prioritizes paused over catch-up", () => {
    expect(
      deriveLiveNavStatus({
        backlogCount: 2,
        connectionState: "open",
        isPaused: true,
        runStatus: "running",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: ["落后 2 条"],
      kind: "paused",
      label: "已暂停",
    });
  });

  it("prioritizes completed runs over closed connections", () => {
    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "closed",
        isPaused: false,
        runStatus: "completed",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: ["已完成"],
      kind: "ended",
      label: "已结束",
    });

    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "closed",
        hasCompletedTerminalEvent: true,
        isPaused: false,
        runStatus: "running",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: ["已完成"],
      kind: "ended",
      label: "已结束",
    });
  });

  it("treats closed completed playback as ended instead of interrupted", () => {
    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "closed",
        hasCompletedTerminalEvent: true,
        isPaused: false,
        runStatus: "completed",
        speed: 1,
      }),
    ).toMatchObject({
      kind: "ended",
      label: "已结束",
      tone: "done",
    });
  });

  it("treats failed playback as interrupted", () => {
    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "closed",
        hasFailedTerminalEvent: true,
        isPaused: false,
        runStatus: "failed",
        speed: 1,
      }),
    ).toMatchObject({
      kind: "interrupted",
      label: "异常中断",
      tone: "danger",
    });
  });

  it("prioritizes failures and active closed streams as interrupted", () => {
    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "open",
        isPaused: false,
        runStatus: "failed",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: ["失败"],
      kind: "interrupted",
      label: "异常中断",
    });

    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "closed",
        isPaused: false,
        runStatus: "running",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: ["已关闭"],
      kind: "interrupted",
      label: "异常中断",
    });

    expect(
      deriveLiveNavStatus({
        backlogCount: 0,
        connectionState: "open",
        hasFailedTerminalEvent: true,
        isPaused: false,
        runStatus: "running",
        speed: 1,
      }),
    ).toMatchObject({
      detailItems: ["失败"],
      kind: "interrupted",
      label: "异常中断",
    });
  });
});
