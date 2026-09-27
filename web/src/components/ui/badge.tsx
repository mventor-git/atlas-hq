import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "./cn";

/**
 * A state.* badge reads its ink and its fill from one token pair and never
 * splits them (§39.2). Every variant also carries text or an icon, because
 * colour is never the sole indicator of meaning (§39.3).
 */
const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      tone: {
        neutral: "bg-card text-foreground border border-input",
        success: "bg-success text-success-foreground",
        warning: "bg-warning text-warning-foreground",
        danger: "bg-danger text-danger-foreground",
        info: "bg-info text-info-foreground",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" className={cn(badgeVariants({ tone }), className)} {...props} />;
}

/**
 * A non-text success indicator: the one place §39.2's `state.success.indicator`
 * pair may be drawn. It is a mark beside a state, never the state by itself.
 */
export function SuccessMark({ className, ...props }: ComponentProps<"span">) {
  return (
    <span
      data-slot="success-mark"
      aria-hidden="true"
      className={cn(
        "inline-block size-2.5 rounded-full border-2",
        "border-success-indicator bg-success",
        className,
      )}
      {...props}
    />
  );
}
