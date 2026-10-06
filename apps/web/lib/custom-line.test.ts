import { describe, expect, it } from "vitest";

import { customDescription } from "@/lib/custom-line";

describe("customDescription", () => {
  it("says each option the estimator chose, keying with the lock", () => {
    expect(
      customDescription({
        item: "Lockset",
        manufacturer: "Hager",
        function: "storeroom",
        backset: '2-3/4" (standard)',
        finish: "US26D",
        lever: "Withnell",
        keyway: "Small format interchangeable core (SFIC)",
        strike: "extended lip ASA",
        preps: ["lead lined"],
      }),
    ).toBe(
      'HAGER LOCKSET, STOREROOM FUNCTION, 2-3/4" BACKSET, US26D, WITHNELL LEVER, ' +
        "SMALL FORMAT INTERCHANGEABLE CORE (SFIC), EXTENDED LIP ASA STRIKE, LEAD LINED",
    );
  });

  it("leaves out what was not chosen and does not double a word the option already has", () => {
    expect(customDescription({ item: "Exit device", lever: "knob", strike: "electric strike" })).toBe(
      "EXIT DEVICE, KNOB, ELECTRIC STRIKE",
    );
  });
});
