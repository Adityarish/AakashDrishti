/** Frontend-only representation of a user-selected file, before/after upload. */

export type SupportedExtension = "png" | "jpg" | "jpeg" | "tif" | "tiff";

export interface UploadedFile {
  /** The actual browser File object selected/dropped by the user. Never a repo asset. */
  file: File;
  /** Object URL created from `file` for local preview. Must be revoked on cleanup. */
  previewUrl: string;
  name: string;
  sizeBytes: number;
  mimeType: string;
  extension: SupportedExtension;
  /** Natural pixel dimensions, read client-side via an Image element (best-effort; TIFF may not decode in-browser). */
  width: number | null;
  height: number | null;
}

/** Geospatial metadata as detected by the backend (rasterio), never fabricated client-side. */
export interface GeoMetadata {
  crs: string;
  transform: [number, number, number, number, number, number];
  width: number;
  height: number;
  bounds: [number, number, number, number];
  resolution: [number, number];
  nodata: number | null;
  bandCount: number;
}

/** Result of POST /api/project/upload. */
export interface UploadResult {
  jobId: string;
  filename: string;
  width: number;
  height: number;
  bandCount: number;
  dtype: string;
  isGeoreferenced: boolean;
  geo: GeoMetadata | null;
}
