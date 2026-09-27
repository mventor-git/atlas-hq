import { ApiError, NetworkError } from "./api";

/**
 * One accessible sentence per status, plus the public code the server sent.
 * The server already refuses to echo a Core decision reason (docs/WEB_API.md),
 * so nothing internal can reach the screen through this path.
 */
export interface FriendlyError {
  title: string;
  detail: string;
  code: string;
  status: number | null;
  /** True when the console should offer the dev login again. */
  reauthenticate: boolean;
}

const TITLES: Record<number, string> = {
  401: "Your session has ended",
  403: "Not permitted",
  404: "Not found",
  405: "Not allowed",
  409: "Already used",
  422: "That request is not valid",
  503: "The service is not configured",
};

const DETAILS: Record<number, string> = {
  401: "Sign in again to continue.",
  403: "The roles engine refused this action for your principal. Nothing was changed.",
  404: "The server has nothing at that address.",
  405: "That method is not accepted on this address.",
  409: "That confirmation was already used. Ask for a new one.",
  422: "Correct the highlighted values and try again.",
  503: "The server is missing configuration it needs. Check ATLAS_WEB_DEV_LOGIN and ATLAS_WEB_OPERATOR_PRINCIPAL.",
};

export function describeError(error: unknown): FriendlyError {
  if (error instanceof ApiError) {
    return {
      title: TITLES[error.status] ?? "The request failed",
      detail: DETAILS[error.status] ?? "The request could not be completed.",
      code: error.code,
      status: error.status,
      reauthenticate: error.isUnauthenticated,
    };
  }
  if (error instanceof NetworkError) {
    return {
      title: "The API is not reachable",
      detail: "Start the Atlas web API and reload. Nothing was sent.",
      code: "network_unavailable",
      status: null,
      reauthenticate: false,
    };
  }
  return {
    title: "Something went wrong",
    detail: error instanceof Error ? error.message : "The request could not be completed.",
    code: "unknown",
    status: null,
    reauthenticate: false,
  };
}
