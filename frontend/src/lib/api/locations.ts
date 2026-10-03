import { API_BASE_URL, apiFetch } from "./client";

/** One georeferenced job for the world map (`GET /api/pipeline/locations`). */
export interface JobLocation {
  jobId: string;
  name: string;
  /** [west, south, east, north] in WGS84 degrees. */
  bounds: [number, number, number, number];
  /** [lon, lat]. */
  centre: [number, number];
  thumbnailUrl: string | null;
  widthPx: number | null;
  heightPx: number | null;
  pixelSizeM: number | null;
  buildings: number | null;
  isSite: boolean;
}

interface LocationDto {
  job_id: string;
  name: string;
  bounds_wgs84: [number, number, number, number];
  centre_lon_lat: [number, number];
  thumbnail_url: string | null;
  width_px: number | null;
  height_px: number | null;
  pixel_size_m: number | null;
  buildings: number | null;
  is_site: boolean;
}

export async function listLocations(): Promise<JobLocation[]> {
  const dto = await apiFetch<{ locations: LocationDto[] }>("/api/pipeline/locations");
  return dto.locations.map((l) => ({
    jobId: l.job_id,
    name: l.name,
    bounds: l.bounds_wgs84,
    centre: l.centre_lon_lat,
    thumbnailUrl: l.thumbnail_url ? `${API_BASE_URL}${l.thumbnail_url}` : null,
    widthPx: l.width_px,
    heightPx: l.height_px,
    pixelSizeM: l.pixel_size_m,
    buildings: l.buildings,
    isSite: l.is_site,
  }));
}
