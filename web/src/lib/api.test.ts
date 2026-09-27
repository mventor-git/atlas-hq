import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, NetworkError, api } from "./api";
import { describeError } from "./errors";

/**
 * The client is the only place the console touches the network, so the rules
 * worth pinning down are: the cookie is always included, no principal is ever
 * put in a request body on a route that refuses one, an unnamed scope is not
 * sent, and a refusal arrives as a status and a public code rather than as a
 * guessed message.
 */

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const fetchMock = vi.fn();

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

function stubFetch(implementation: (url: string, init: RequestInit) => Response) {
  fetchMock.mockImplementation((url: string, init: RequestInit) => implementation(url, init));
  vi.stubGlobal("fetch", fetchMock);
}

describe("credentials", () => {
  it("sends the opaque session cookie on every request", async () => {
    stubFetch(() => jsonResponse(200, { capabilities: [] }));
    await api.capabilities();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe("include");
  });

  it("never sets an Authorization header, because there is no token to set", async () => {
    stubFetch(() => jsonResponse(200, { capabilities: [] }));
    await api.capabilities();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string> | undefined)?.Authorization).toBeUndefined();
  });
});

describe("refusals", () => {
  it.each([
    [401, "session_expired"],
    [403, "capability_denied"],
    [404, "principal_unknown"],
    [409, "confirmation_consumed"],
    [422, "scope_invalid"],
  ])("maps HTTP %i to a typed ApiError carrying the public code", async (status, code) => {
    stubFetch(() =>
      jsonResponse(status, { error: { code, message: "a fixed public sentence" } }),
    );
    const call = status === 404 ? api.permissions("user.7f3", {}) : api.capabilities();
    const error = (await call.catch((cause: unknown) => cause)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(status);
    expect((error as ApiError).code).toBe(code);
  });

  it("flags a 401 and only a 401 as needing a new session", async () => {
    stubFetch(() => jsonResponse(401, { error: { code: "session_unknown" } }));
    const unauthenticated = (await api.session().catch((cause: unknown) => cause)) as ApiError;
    expect(unauthenticated.isUnauthenticated).toBe(true);

    stubFetch(() => jsonResponse(403, { error: { code: "capability_denied" } }));
    const forbidden = (await api.session().catch((cause: unknown) => cause)) as ApiError;
    expect(forbidden.isUnauthenticated).toBe(false);
  });

  it("turns an unreachable server into a NetworkError rather than a refusal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const error = await api.capabilities().catch((cause: unknown) => cause);
    expect(error).toBeInstanceOf(NetworkError);
    expect(describeError(error).reauthenticate).toBe(false);
  });

  it("never invents a status the server did not send", () => {
    const friendly = describeError(new ApiError(418, "teapot", "short and stout"));
    expect(friendly.status).toBe(418);
    expect(friendly.code).toBe("teapot");
    expect(friendly.title).toBe("The request failed");
  });

  it("treats a 204 as an empty success, not a parse error", async () => {
    stubFetch(() => new Response(null, { status: 204 }));
    await expect(api.logout()).resolves.toBeUndefined();
  });
});

describe("request shapes", () => {
  it("sends no principal to the self monthly report (§38.6)", async () => {
    stubFetch(() => jsonResponse(200, { principal_id: "user.7f3", sections: [], audit_id: "a" }));
    await api.selfMonthlyReport();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    // A bare path: no query string, and no body at all.
    expect(url).toBe("/api/self/monthly-report");
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
  });

  it("omits a scope the caller did not name instead of sending a blank one", async () => {
    stubFetch(() => jsonResponse(200, { principal_id: "user.7f3" }));
    await api.grants("user.7f3", { organization_id: "", workplace_id: undefined });
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/principals/user.7f3/grants");
  });

  it("sends the named scope as query parameters", async () => {
    stubFetch(() => jsonResponse(200, { principal_id: "user.7f3" }));
    await api.grants("user.7f3", { organization_id: "org-1", workplace_id: "wp-1" });
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/principals/user.7f3/grants?organization_id=org-1&workplace_id=wp-1");
  });

  it("reads grant state with a bare GET: the principal is the resource, not a fact", async () => {
    stubFetch(() => jsonResponse(200, { principal_id: "user.7f3", capabilities: [], roles: [] }));
    await api.grants("user.7f3", { organization_id: "org-1" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/principals/user.7f3/grants?organization_id=org-1");
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
  });

  it("binds a confirmation to its target, so it cannot be replayed on another", async () => {
    stubFetch(() => jsonResponse(201, { confirmation_id: "conf_1" }));
    await api.confirmation({
      capability: "authorization.manage",
      action: "authorization.capability.set",
      scope: { organization_id: "org-1", workplace_id: null },
      resource_id: "user.7f3",
    });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({
      capability: "authorization.manage",
      action: "authorization.capability.set",
      scope: { organization_id: "org-1", workplace_id: null },
      resource_id: "user.7f3",
    });
  });

  it("puts a self grant's principal at the top level, never inside scope", async () => {
    stubFetch(() => jsonResponse(200, { capability_id: "c", checked: true }));
    await api.setCapability("user.7f3", "attendance.record", {
      checked: true,
      scope: { organization_id: null, workplace_id: null },
      principal_id: "user.7f3",
    });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.principal_id).toBe("user.7f3");
    expect(body.scope).not.toHaveProperty("principal_id");
  });

  it("encodes a path segment so a principal id cannot escape its route", async () => {
    stubFetch(() => jsonResponse(200, { principal_id: "x" }));
    await api.permissions("user/../admin", {});
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/principals/user%2F..%2Fadmin/permissions");
  });

  it("sends only organization_id when rendering a report", async () => {
    stubFetch(() => jsonResponse(200, { sections: [], audit_id: "a" }));
    await api.renderReport("report.attendance", "org-1");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ organization_id: "org-1" });
  });

  it("asks for the principal directory with no query and no body", async () => {
    stubFetch(() => jsonResponse(200, { principals: [] }));
    await api.principals();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/principals");
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
  });
});
