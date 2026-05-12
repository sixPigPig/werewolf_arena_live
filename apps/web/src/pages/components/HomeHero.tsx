import { Heading, Text } from "../../components/ui";
import { withGlassPanel } from "../../components/ui/glass";
import { HealthCard } from "../../features/health/components/HealthCard";

export function HomeHero() {
  return (
    <section
      className={withGlassPanel(
        "home-hero-module mx-auto flex min-h-[calc(100vh-4.5rem)] w-full max-w-none flex-col items-center justify-center gap-6 rounded-lg px-6 py-10 text-center",
      )}
      data-testid="home-hero-module"
    >
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
  );
}
