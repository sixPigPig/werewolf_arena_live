import { afterEach, describe, expect, it, vi } from "vitest";

import { listModelOptions } from "./listModelOptions";

describe("model options api", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists configured model options", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          models: [
            { id: "deepseek-chat", label: "DeepSeek · deepseek-chat" },
            { id: "MiniMax-M2.7", label: "MiniMax · MiniMax-M2.7" },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const response = await listModelOptions();

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/model-options",
      undefined,
    );
    expect(response.models.map((model) => model.id)).toEqual([
      "deepseek-chat",
      "MiniMax-M2.7",
    ]);
  });
});
