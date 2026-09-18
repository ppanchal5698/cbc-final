import { describe, expect, it } from "vitest";

import { SLOT_ORDER, slotOf, slotRank } from "@/lib/slot";

describe("slotOf", () => {
  it("reads the obvious ones off the description", () => {
    expect(slotOf("3-0 x 7-0 HM flush door, 18ga")).toBe("DOOR");
    expect(slotOf("Knock-down frame, 5-5/8 in wall")).toBe("FRAME");
    expect(slotOf("Hager BB hinge, NRP")).toBe("HINGES");
    expect(slotOf("Hager 5100 closer, aluminium")).toBe("CLOSER");
    expect(slotOf("Hager 3400 storeroom lever")).toBe("LOCKSET");
  });

  it("prefers the specific component over the word door or frame in it", () => {
    // These are the ones a naive /door/ test gets wrong.
    expect(slotOf("Door sweep, aluminium/neoprene")).toBe("SWEEP");
    expect(slotOf("Rubber door silencer")).toBe("DOOR MUTES");
    expect(slotOf("Masonry T-anchor for frame, galvanised")).toBe("ANCHOR");
    expect(slotOf("National Guard 896 threshold")).toBe("THRESHOLD");
    expect(slotOf("Kick plate, 10 x 34, stainless")).toBe("KICK PLATE");
    expect(slotOf("Surface vertical rod exit device")).toBe("EXIT DEVICE");
    expect(slotOf("Overlapping astragal")).toBe("ASTRAGAL");
  });

  it("falls back to HARDWARE rather than guessing", () => {
    expect(slotOf("Bobrick matte-black grab bar, 18 in")).toBe("HARDWARE");
    expect(slotOf("")).toBe("HARDWARE");
    expect(slotOf(null)).toBe("HARDWARE");
    expect(slotOf(undefined)).toBe("HARDWARE");
  });
});

describe("slotRank", () => {
  it("puts the door and its frame ahead of the hardware", () => {
    expect(slotRank("DOOR")).toBeLessThan(slotRank("FRAME"));
    expect(slotRank("FRAME")).toBeLessThan(slotRank("HINGES"));
    expect(slotRank("HINGES")).toBeLessThan(slotRank("HARDWARE"));
  });

  it("ranks every slot it knows about", () => {
    for (const slot of SLOT_ORDER) expect(slotRank(slot)).toBeLessThan(SLOT_ORDER.length);
  });
});
