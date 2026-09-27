import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "./cn";

/**
 * Control boundaries use `--input` (border.control), never `--border`
 * (border.divider) -- §39.3.
 *
 * No focus-ring utility appears here, and that is deliberate. The focus
 * indicator is owned entirely by the base layer in index.css: it draws
 * `focus.ring` everywhere and swaps to `focus.ring.onAccent` for any control
 * carrying `data-on-accent`. A variant that set its own outline colour would
 * either lose the swap to specificity or win it everywhere, which is exactly
 * the bug this shape exists to prevent.
 *
 * So the only thing a variant decides is the fill, and the one accent-filled
 * variant marks itself.
 */
const ACCENT_FILLED: Record<string, true> = { default: true };

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium " +
    "transition-colors disabled:pointer-events-none disabled:opacity-60",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground border border-input",
        outline: "bg-card text-foreground border border-input hover:bg-background",
        ghost: "bg-transparent text-foreground border border-transparent hover:bg-card",
        link: "bg-transparent text-foreground underline underline-offset-4 border-0 p-0 h-auto",
      },
      size: {
        sm: "h-8 px-3",
        default: "h-9 px-4",
        lg: "h-10 px-6",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Component = asChild ? Slot : "button";
  return (
    <Component
      data-slot="button"
      data-on-accent={ACCENT_FILLED[variant ?? "default"] ? "" : undefined}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

export { buttonVariants };
