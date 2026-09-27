import type { ComponentProps, ReactNode } from "react";

import { cn } from "./cn";

const TONES = {
  danger: { box: "bg-danger text-danger-foreground", mark: "!" },
  warning: { box: "bg-warning text-warning-foreground", mark: "!" },
  info: { box: "bg-info text-info-foreground", mark: "i" },
  success: { box: "bg-success text-success-foreground", mark: "\u2713" },
} as const;

export type AlertTone = keyof typeof TONES;

/**
 * An error, a warning, or a confirmation. It pairs the state colour with a
 * glyph and with words, because colour is never the sole indicator of meaning
 * (§39.3), and it takes a live region so the message is announced rather than
 * only drawn.
 *
 * `assertive` is for a refusal the user just caused; `polite` for a result that
 * merely arrived.
 */
export function Alert({
  tone = "info",
  title,
  children,
  action,
  assertive = tone === "danger",
  className,
  ...props
}: Omit<ComponentProps<"div">, "title"> & {
  tone?: AlertTone;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  assertive?: boolean;
}) {
  const { box, mark } = TONES[tone];
  return (
    <div
      data-slot="alert"
      role={assertive ? "alert" : "status"}
      aria-live={assertive ? "assertive" : "polite"}
      className={cn("flex items-start gap-3 rounded-md border border-input p-3", box, className)}
      {...props}
    >
      <span
        aria-hidden="true"
        className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border border-current text-xs font-bold"
      >
        {mark}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">{title}</p>
        {children ? <div className="mt-1 text-sm">{children}</div> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

/** The one empty state a list can show. Never a blank region. */
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div
      data-slot="empty-state"
      className="rounded-md border border-dashed border-input p-6 text-center"
    >
      <p className="text-sm font-medium">{title}</p>
      {children ? <p className="mt-1 text-sm text-muted-foreground">{children}</p> : null}
    </div>
  );
}

/** A busy region that a screen reader is told about, not just a spinner. */
export function Loading({ label }: { label: string }) {
  return (
    <p role="status" aria-live="polite" className="text-sm text-muted-foreground">
      {label}
    </p>
  );
}
