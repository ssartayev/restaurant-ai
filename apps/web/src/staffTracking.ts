export type PersonObject = { box: [number, number, number, number]; kind: string; appearance?: number[] };
export type StaffMark = { sample: number; object: number };
export function matchStaff(frames: [number, PersonObject[]][], marks: StaffMark[]) {
  const matches = new Set<string>();
  for (const mark of marks) {
    const seed = frames[mark.sample]?.[1][mark.object];
    if (!seed || seed.kind !== "person" || !seed.appearance?.length) continue;
    let previous = seed;
    let seen = frames[mark.sample][0];
    matches.add(mark.sample + ":" + mark.object);
    for (let i = mark.sample + 1; i < frames.length; i++) {
      const [at, objects] = frames[i];
      if (at - seen > 3) break;
      const candidates = objects.flatMap((person, j) => {
        if (person.kind !== "person" || !person.appearance?.length) return [];
        const a = person.box, b = previous.box;
        const distance = Math.hypot((a[0]+a[2]-b[0]-b[2])/2, (a[1]+a[3]-b[1]-b[3])/2) / Math.max(.05, b[3]-b[1]);
        const similarity = seed.appearance!.reduce((sum, value, k) => sum + Math.min(value, person.appearance![k] ?? 0), 0);
        if (distance > .65 || similarity < .65) return [];
        return [{ j, person, score: similarity - .35 * distance }];
      }).sort((a,b) => b.score-a.score);
      if (!candidates.length) continue;
      // Same uniforms/crossings must not silently transfer the manual label.
      if (candidates[1] && candidates[0].score - candidates[1].score < .12) break;
      const best = candidates[0];
      matches.add(i + ":" + best.j);
      previous = best.person;
      seen = at;
    }
  }
  return matches;
}
