import type { ComponentProps } from "react";

import { cn } from "./cn";

/**
 * Native controls, styled with tokens and no focus-ring utility: the base layer
 * in index.css owns the focus indicator, and it knows whether a control is
 * accent-filled from `data-on-accent`.
 */

const CONTROL =
  "h-9 w-full rounded-md border border-input bg-card px-3 text-sm text-foreground " +
  "placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-60";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return (
    <input
      data-slot="input"
      className={cn(CONTROL, "aria-[invalid=true]:border-danger-foreground", className)}
      {...props}
    />
  );
}

export function Select({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      data-slot="select"
      className={cn(CONTROL, "disabled:cursor-not-allowed disabled:opacity-60", className)}
      {...props}
    />
  );
}
