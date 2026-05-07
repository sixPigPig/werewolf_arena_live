import { Heading, Text } from "@radix-ui/themes";

import { HealthCard } from "../features/health/components/HealthCard";

export function HomePage() {
  return (
    <main className="min-h-screen bg-slate-950 text-slate-50">
      <section className="mx-auto flex min-h-screen max-w-4xl flex-col items-center justify-center gap-6 px-6 text-center">
        <Text className="uppercase tracking-[0.3em] text-sky-300" size="2">
          Project Skeleton
        </Text>
        <Heading as="h1" className="text-slate-50" size="8">
          Python + React monorepo is ready.
        </Heading>
        <Text as="p" className="max-w-2xl text-slate-300" size="3">
          The frontend now talks to the backend through a shared API client and TanStack Query.
        </Text>
        <HealthCard />
      </section>
    </main>
  );
}
