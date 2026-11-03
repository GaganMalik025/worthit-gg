/**
 * THE FALLBACK PROMISES NOTHING THE PRODUCT DOES NOT DO.
 *
 * The button records one analytics event and nothing else: no list, no job, no
 * notification. So the page may not state a date or claim anything was queued.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { QueueFallback } from "../../components/GenerationProgress";

const html = renderToStaticMarkup(<QueueFallback appid={1} gameName="Some Game" />);

describe("the queue fallback copy", () => {
  it("says what is true", () => {
    expect(html).toContain("right now. Try again tomorrow.");
    expect(html).toContain("I want this one");
    expect(html).toContain("Some Game");
  });

  it("promises no date and claims no queue", () => {
    for (const lie of [/\d+\s*hours/i, /queued/i, /request verdict/i, /be here/i]) {
      expect(html).not.toMatch(lie);
    }
  });
});
