import { Link } from "react-router-dom";

import {
  Button,
  Heading,
  Text,
  type ButtonIntent,
} from "../components/ui";

const intents: Array<{ intent: ButtonIntent; label: string }> = [
  { intent: "default", label: "Default" },
  { intent: "info", label: "Info" },
  { intent: "primary", label: "Primary" },
  { intent: "danger", label: "Danger" },
  { intent: "success", label: "Success" },
  { intent: "warning", label: "Warning" },
];

const sizes = [
  { label: "Small", size: "1" },
  { label: "Medium", size: "2" },
  { label: "Large", size: "3" },
] as const;

export function ComponentButtonShowcasePage() {
  return (
    <main className="mx-auto flex min-h-[calc(100svh-56px)] w-full max-w-7xl flex-col gap-8 px-4 py-8 sm:px-6 lg:px-8">
      <header className="flex flex-col gap-3 border-b border-slate-200/15 pb-6">
        <Text className="text-sm font-semibold uppercase tracking-[0.18em] text-amber-200/80">
          Component Showcase
        </Text>
        <Heading
          as="h1"
          className="font-serif text-4xl font-black text-[#f2dfc7] sm:text-5xl"
          size="6"
        >
          Gothic Button
        </Heading>
      </header>

      <section aria-labelledby="gothic-button-intents" className="space-y-4">
        <Heading
          as="h2"
          className="font-serif text-2xl text-[#ead8bf]"
          id="gothic-button-intents"
          size="4"
        >
          Intents
        </Heading>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {intents.map(({ intent, label }) => (
            <div
              className="flex min-h-28 items-center justify-center border border-slate-200/12 bg-slate-950/30 px-5 py-6"
              key={intent}
            >
              <Button intent={intent} skin="gothic">
                {label}
              </Button>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="gothic-button-sizes" className="space-y-4">
        <Heading
          as="h2"
          className="font-serif text-2xl text-[#ead8bf]"
          id="gothic-button-sizes"
          size="4"
        >
          Sizes
        </Heading>
        <div className="flex flex-wrap items-center gap-4 border border-slate-200/12 bg-slate-950/30 px-5 py-6">
          {sizes.map(({ label, size }) => (
            <Button intent="primary" key={size} size={size} skin="gothic">
              {label}
            </Button>
          ))}
        </div>
      </section>

      <section aria-labelledby="gothic-button-states" className="space-y-4">
        <Heading
          as="h2"
          className="font-serif text-2xl text-[#ead8bf]"
          id="gothic-button-states"
          size="4"
        >
          States
        </Heading>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="flex flex-wrap items-center gap-4 border border-slate-200/12 bg-slate-950/30 px-5 py-6">
            <Button intent="danger" skin="gothic">
              Danger Active
            </Button>
            <Button disabled intent="danger" skin="gothic">
              Danger Disabled
            </Button>
            <Button intent="success" loading skin="gothic">
              Success Loading
            </Button>
          </div>
          <div className="flex flex-col gap-4 border border-slate-200/12 bg-slate-950/30 px-5 py-6">
            <Button className="w-full" intent="warning" skin="gothic">
              Full Width Warning
            </Button>
            <Button asChild intent="info" skin="gothic">
              <Link to="/games">Link To Lobby</Link>
            </Button>
          </div>
        </div>
      </section>
    </main>
  );
}
