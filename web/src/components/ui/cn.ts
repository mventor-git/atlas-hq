import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * shadcn/ui's class combiner, copied into this repo and owned by it (contract
 * §39.8). It is not imported from an upstream package.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
