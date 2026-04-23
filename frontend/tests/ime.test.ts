import assert from "node:assert/strict";

import { shouldSubmitOnEnter } from "../src/utils/ime.ts";

assert.equal(
  shouldSubmitOnEnter({ key: "Enter", shiftKey: false }, false),
  true
);
assert.equal(
  shouldSubmitOnEnter(
    { key: "Enter", shiftKey: false, nativeEvent: { isComposing: true } },
    false
  ),
  false
);
assert.equal(
  shouldSubmitOnEnter({ key: "Enter", shiftKey: false }, true),
  false
);
assert.equal(
  shouldSubmitOnEnter({ key: "Enter", shiftKey: true }, false),
  false
);
assert.equal(shouldSubmitOnEnter({ key: "a", shiftKey: false }, false), false);

console.log("ime.test.ts: PASS");
