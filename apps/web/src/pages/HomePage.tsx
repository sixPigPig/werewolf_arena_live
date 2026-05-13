import { Button } from "../components/ui";
import { Link } from "react-router-dom";

import { AppTopNav } from "../app/AppTopNav";
import { HomeHero } from "./components/HomeHero";

export function HomePage() {
  return (
    <>
      <AppTopNav
        actions={
          <Button asChild intent="primary" size="1" skin="gothic">
            <Link to="/games">进入大厅</Link>
          </Button>
        }
      />
      <main className="min-h-screen text-slate-50">
        <HomeHero />
      </main>
    </>
  );
}
