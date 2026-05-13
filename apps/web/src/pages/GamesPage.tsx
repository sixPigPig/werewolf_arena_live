import { Button } from "../components/ui";
import { useRef } from "react";
import { Link } from "react-router-dom";

import { AppTopNav } from "../app/AppTopNav";
import { GamesWorkspace } from "./components/GamesWorkspace";

export function GamesPage() {
  const createFormRef = useRef<HTMLDivElement>(null);
  const focusCreateForm = () => {
    createFormRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    createFormRef.current
      ?.querySelector<HTMLElement>(
        "button, input, [tabindex]:not([tabindex='-1'])",
      )
      ?.focus();
  };

  return (
    <>
      <AppTopNav
        actions={
          <Button
            intent="primary"
            onClick={focusCreateForm}
            size="1"
            skin="gothic"
            type="button"
          >
            新建对局
          </Button>
        }
        utilityActions={
          <Button asChild color="gray" size="1" skin="gothic" variant="surface">
            <Link to="/games/history">对局历史</Link>
          </Button>
        }
      />
      <GamesWorkspace createFormRef={createFormRef} />
    </>
  );
}
