// @vitest-environment node
import { describe, expect, it } from "vitest";

/**
 * The dev server is the only place the browser half and the Python half meet, so
 * two things about it are worth pinning: `/api` is proxied to the standard-library
 * server on loopback, and the console's own port is fixed rather than merely
 * preferred. Same-origin in development is what lets the `SameSite=Strict`
 * cookie work with no CORS exception, so the target is load-bearing rather than
 * cosmetic, and `ATLAS_WEB_API_URL` is the documented override.
 *
 * This file runs in the node environment because importing `vite.config.ts`
 * loads esbuild, whose invariant does not hold under jsdom.
 */
const { default: config } = await import("../vite.config");

describe("the dev server proxy", () => {
  const server = (
    config as { server?: { port?: number; strictPort?: boolean; proxy?: Record<string, { target: string }> } }
  ).server;

  it("proxies /api to the standard-library server on loopback", () => {
    expect(server?.proxy?.["/api"]?.target).toBe("http://127.0.0.1:8000");
  });

  it("serves the console on its own port, so the two never collide", () => {
    expect(server?.port).toBe(5175);
  });

  it("refuses to move rather than silently taking the next free port", () => {
    // A silent hop to 5176 would break every bookmark and every script that
    // points at this console while still looking like it started fine.
    expect(server?.strictPort).toBe(true);
  });
});
