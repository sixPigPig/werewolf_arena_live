import { Button, Heading, Text } from "@radix-ui/themes";
import { Link } from "react-router-dom";

import { AppTopNav } from "../app/AppTopNav";
import { HealthCard } from "../features/health/components/HealthCard";

export function HomePage() {
  return (
    <>
      <AppTopNav
        actions={
          <Button asChild highContrast>
            <Link to="/games">进入大厅</Link>
          </Button>
        }
      />
      <main className="min-h-screen bg-slate-950 text-slate-50">
        <section className="mx-auto flex min-h-[calc(100vh-4.5rem)] w-full max-w-none flex-col items-center justify-center gap-6 px-6 text-center">
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
    </>
  );
}
