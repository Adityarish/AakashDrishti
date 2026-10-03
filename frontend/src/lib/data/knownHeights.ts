/**
 * Curated ground-truth landmark heights for the "Estimated vs. Actual"
 * comparison card. Sourced from `test-data/known-heights.json` (copied into
 * the frontend build at `src/lib/data/known-heights.json` -- see decision
 * log: simplest option that needs no backend change, and this file is
 * small/static so bundling it via a plain TS JSON import is fine for a
 * demo build).
 *
 * Only images with a confidently-cited entry here render the comparison
 * card; everything else renders nothing (never a fabricated match).
 */
import knownHeightsData from "./known-heights.json";

export interface KnownBuilding {
  name: string;
  heightM: number;
  heightMAlt: number | null;
  source: string;
  note: string;
}

export interface KnownHeightsEntry {
  location: string;
  buildings: KnownBuilding[];
}

interface RawBuilding {
  name: string;
  height_m: number;
  height_m_alt?: number;
  source: string;
  note: string;
}

interface RawEntry {
  location: string;
  buildings: RawBuilding[];
}

interface RawKnownHeights {
  images: Record<string, RawEntry>;
}

const raw = knownHeightsData as unknown as RawKnownHeights;

/** Case-insensitive lookup by filename (e.g. "dubai-burj-khalifa-skyline.jpg"). */
export function findKnownHeights(filename: string): KnownHeightsEntry | null {
  const target = filename.trim().toLowerCase();
  const match = Object.entries(raw.images).find(([key]) => key.toLowerCase() === target);
  if (!match) return null;

  const [, entry] = match;
  return {
    location: entry.location,
    buildings: entry.buildings.map((b) => ({
      name: b.name,
      heightM: b.height_m,
      heightMAlt: b.height_m_alt ?? null,
      source: b.source,
      note: b.note,
    })),
  };
}
