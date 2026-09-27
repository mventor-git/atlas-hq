import type { ComponentProps } from "react";

import { cn } from "./cn";

/**
 * A native checkbox input, tinted with tokens.
 *
 * `appearance-none` is deliberately NOT used. The platform draws the tick, so
 * the state is a shape as well as a colour (§39.3 never lets colour be the
 * only signal), keyboard and screen-reader behaviour come from the input
 * itself, and no `::after` hack is needed to fake a tick. `accent-color` tints
 * the native control, tick included, from the §39 accent token.
 */export function Checkbox({ className, ...props }: Omit<ComponentProps<"input">, "type">) {
  return (
    <input
      type="checkbox"
      data-slot="checkbox"
      className={cn(
        "size-4 shrink-0 cursor-pointer rounded-[3px]",
        "accent-[var(--primary)]",
        "border border-input",
        "disabled:cursor-not-allowed disabled:opacity-60",
        className,
      )}
      {...props}
    />
  );
}
