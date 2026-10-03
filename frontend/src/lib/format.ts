export function fmt(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function fmtDuration(seconds: number): string {
  if (!Number.isFinite(seconds)) return "-";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

export function fmtDate(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtLonLat(lon: number | null | undefined, lat: number | null | undefined): string {
  if (lon === null || lon === undefined || lat === null || lat === undefined) return "no georeference";
  return `${Math.abs(lat).toFixed(5)}° ${lat >= 0 ? "N" : "S"}, ${Math.abs(lon).toFixed(5)}° ${lon >= 0 ? "E" : "W"}`;
}

export function heightUnit(unit: string | undefined): string {
  return unit === "m" ? "m" : "rel";
}

export function titleCase(text: string): string {
  return text.replace(/[_-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function compassLabel(degrees: number): string {
  const names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  return names[Math.round((((degrees % 360) + 360) % 360) / 45) % 8];
}

export interface UnitValue {
  value: number;
  unit: string;
  digits: number;
}

/** Area in the unit that reads best: m² below 1 ha, hectares below 1 km², otherwise km². */
export function areaParts(km2: number): UnitValue {
  const m2 = km2 * 1e6;
  if (m2 < 10_000) return { value: m2, unit: "m²", digits: 0 };
  if (km2 < 1) return { value: m2 / 10_000, unit: "ha", digits: 2 };
  return { value: km2, unit: "km²", digits: 2 };
}

/** Distance in metres below 1 km, otherwise kilometres. */
export function distanceParts(metres: number): UnitValue {
  if (metres < 1000) return { value: metres, unit: "m", digits: metres < 100 ? 1 : 0 };
  return { value: metres / 1000, unit: "km", digits: 2 };
}

/** Volume in m³ below one million, otherwise millions of m³. */
export function volumeParts(m3: number): UnitValue {
  if (m3 < 1e6) return { value: m3, unit: "m³", digits: 0 };
  return { value: m3 / 1e6, unit: "Mm³", digits: 2 };
}
