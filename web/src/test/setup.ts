import "@testing-library/jest-dom/vitest";

// jsdom has no matchMedia, and `prefers-reduced-motion` is queried by nothing
// in the app today. Left undefined on purpose rather than stubbed speculatively.
