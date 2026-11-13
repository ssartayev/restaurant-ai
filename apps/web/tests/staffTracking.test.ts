// Run with: node --experimental-strip-types --test apps/web/tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { matchStaff, staffTracks, type PersonObject } from "../src/staffTracking.ts";

const p = (track: number): PersonObject => ({ box: [0, 0, 0.1, 0.3], kind: "person", track });
const table: PersonObject = { box: [0, 0, 0.2, 0.2], kind: "table" };
const frames: [number, PersonObject[]][] = [
  [0, [table, p(1), p(2)]],
  [1, [p(2), table, p(1)]],
  [2, [p(1)]],            // track 2 hidden for a moment
  [3, [p(1), p(2), p(7)]],
];

test("a mark labels the whole track, before and after the marked frame", () => {
  const m = matchStaff(frames, [{ sample: 1, object: 0 }]);
  assert.deepEqual([...m].sort(), ["0:2", "1:0", "3:1"]);
});

test("other people and non-person objects are never labelled", () => {
  const m = matchStaff(frames, [{ sample: 0, object: 2 }]);
  for (const key of m) {
    const [i, j] = key.split(":").map(Number);
    assert.equal(frames[i][1][j].track, 2);
  }
});

test("staffTracks lists each marked person once and ignores marks on tables", () => {
  assert.deepEqual(staffTracks(frames, [{ sample: 0, object: 1 }, { sample: 3, object: 0 }, { sample: 0, object: 0 }]), [1]);
  assert.deepEqual(staffTracks(frames, []), []);
});
