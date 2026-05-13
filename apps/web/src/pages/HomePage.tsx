import { ArenaGlobalNav, ArenaNavButton } from "../app/navigation";
import { HomeHero } from "./components/HomeHero";

export function HomePage() {
  return (
    <>
      <ArenaGlobalNav
        primaryAction={
          <ArenaNavButton intent="primary" to="/games">
            进入大厅
          </ArenaNavButton>
        }
      />
      <main className="min-h-screen text-slate-50">
        <HomeHero />
      </main>
    </>
  );
}
