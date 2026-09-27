import { useState } from "react";

import { Button } from "../components/ui/button";
import { useSession } from "./session";

/**
 * The light/dark switch. It is a radio group rather than a toggle button,
 * because "which theme" is a choice between two named options and a screen
 * reader should say so. The value goes to Core, not just to this browser.
 */
export function ThemeSwitch() {
  const { theme, setTheme } = useSession();
  const [pending, setPending] = useState(false);

  return (
    <fieldset
      className="flex items-center gap-2"
      onBlur={() => setPending(false)}
      aria-busy={pending || undefined}
    >
      <legend className="sr-only">Colour theme</legend>
      <span aria-hidden="true" className="text-sm text-muted-foreground">
        Theme
      </span>
      <div className="flex overflow-hidden rounded-md border border-input" role="none">
        {(["light", "dark"] as const).map((option) => {
          const active = theme === option;
          return (
            <Button
              key={option}
              type="button"
              size="sm"
              variant={active ? "default" : "outline"}
              // The tick is the non-colour signal that the option is current.
              aria-pressed={active}
              onClick={() => {
                setPending(true);
                setTheme(option);
              }}
              className="rounded-none border-0 border-r border-input last:border-r-0"
            >
              <span aria-hidden="true">{active ? "\u2713 " : ""}</span>
              {option === "light" ? "Light" : "Dark"}
            </Button>
          );
        })}
      </div>
      {pending ? <span className="sr-only">Saving the theme preference.</span> : null}
    </fieldset>
  );
}
