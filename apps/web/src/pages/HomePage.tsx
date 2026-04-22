import { HealthCard } from "../features/health/components/HealthCard";

export function HomePage() {
  return (
    <main className="min-h-screen bg-slate-950 text-slate-50">
      <section className="mx-auto flex min-h-screen max-w-4xl flex-col items-center justify-center gap-6 px-6 text-center">
        <p className="text-sm uppercase tracking-[0.3em] text-sky-300">Project Skeleton</p>
        <h1 className="text-4xl font-semibold">Python + React monorepo is ready.</h1>
        <p className="max-w-2xl text-base text-slate-300">
          The frontend now talks to the backend through a shared API client and TanStack Query.
        </p>
        <HealthCard />
      </section>
    </main>
  );
}
