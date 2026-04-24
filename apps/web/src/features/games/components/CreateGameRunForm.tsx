import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { createGameRun } from "../api/createGameRun";

export function CreateGameRunForm() {
  const navigate = useNavigate();
  const [seed, setSeed] = useState("");
  const [maxRounds, setMaxRounds] = useState("8");

  const mutation = useMutation({
    mutationFn: createGameRun,
    onSuccess: (run) => navigate(`/games/live/${run.run_id}`),
  });

  return (
    <form
      className="rounded-md border border-slate-200 bg-white p-4"
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate({
          seed: seed ? Number(seed) : null,
          max_rounds: Number(maxRounds),
        });
      }}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-700">
          随机种子
          <input
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            inputMode="numeric"
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
            placeholder="可留空"
          />
        </label>
        <label className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-700">
          最大轮数
          <input
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            min={1}
            max={20}
            type="number"
            value={maxRounds}
            onChange={(event) => setMaxRounds(event.target.value)}
          />
        </label>
        <button
          className="rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400"
          disabled={mutation.isPending}
          type="submit"
        >
          {mutation.isPending ? "正在发起..." : "发起对局"}
        </button>
      </div>
      {mutation.isError ? (
        <p className="mt-3 text-sm text-red-700">无法发起对局</p>
      ) : null}
    </form>
  );
}
