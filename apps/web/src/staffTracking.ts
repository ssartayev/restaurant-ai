// Waiter marks follow the server's person tracks (apps/api/app/tracking.py).
// A mark names one detection; every detection on the same track, before and after,
// carries the label. If the track is lost (long occlusion, identical uniforms crossing)
// the label stops instead of jumping to someone else, and the person can be marked again.
export type PersonObject = { box: [number, number, number, number]; kind: string; appearance?: number[]; track?: number };
export type StaffMark = { sample: number; object: number };

/** Track numbers of everyone marked as staff. */
export function staffTracks(frames: [number, PersonObject[]][], marks: StaffMark[]): number[] {
  const tracks = new Set<number>();
  for (const mark of marks) {
    const seed = frames[mark.sample]?.[1][mark.object];
    if (seed?.kind === "person" && seed.track !== undefined) tracks.add(seed.track);
  }
  return [...tracks].sort((a, b) => a - b);
}

/** Keys "sample:object" of every detection that belongs to a marked person. */
export function matchStaff(frames: [number, PersonObject[]][], marks: StaffMark[]) {
  const matches = new Set<string>();
  const tracks = new Set(staffTracks(frames, marks));
  frames.forEach(([, objects], i) => objects.forEach((object, j) => {
    if (object.kind === "person" && object.track !== undefined && tracks.has(object.track)) matches.add(i + ":" + j);
  }));
  for (const mark of marks) matches.add(mark.sample + ":" + mark.object);
  return matches;
}
