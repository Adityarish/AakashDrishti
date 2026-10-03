import type { SupportedExtension } from "@/lib/types/upload";

export const SUPPORTED_EXTENSIONS: SupportedExtension[] = [
  "png",
  "jpg",
  "jpeg",
  "tif",
  "tiff",
];

const EXTENSION_MIME_HINTS: Record<SupportedExtension, string[]> = {
  png: ["image/png"],
  jpg: ["image/jpeg"],
  jpeg: ["image/jpeg"],
  tif: ["image/tiff"],
  tiff: ["image/tiff"],
};

/** Matches the backend's own ceiling (Settings.max_upload_bytes in core/config.py), which
 * streams the upload to disk in chunks rather than buffering it in memory, so this can be
 * generous. GeoTIFFs in particular are routinely several hundred MB. */
export const MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024; // 2 GB

export interface FileValidationResult {
  valid: boolean;
  error: string | null;
  extension: SupportedExtension | null;
}

function getExtension(filename: string): string {
  const parts = filename.split(".");
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
}

export function validateFile(file: File): FileValidationResult {
  if (!file || file.size === 0) {
    return { valid: false, error: "Selected file is empty or unreadable.", extension: null };
  }

  const ext = getExtension(file.name);
  if (!SUPPORTED_EXTENSIONS.includes(ext as SupportedExtension)) {
    return {
      valid: false,
      error: `Unsupported file type ".${ext || "unknown"}". Supported: PNG, JPG, JPEG, TIFF, GeoTIFF.`,
      extension: null,
    };
  }
  const extension = ext as SupportedExtension;

  if (file.size > MAX_FILE_SIZE_BYTES) {
    return {
      valid: false,
      error: `File is too large (${formatBytes(file.size)}). Maximum supported size is ${formatBytes(MAX_FILE_SIZE_BYTES)}.`,
      extension,
    };
  }

  // Best-effort MIME sanity check. Browsers frequently report an empty or
  // generic MIME type for TIFF, so we only reject a clear mismatch (e.g. a
  // .png that the browser insists is a video), not an empty/unknown type.
  const expectedMimes = EXTENSION_MIME_HINTS[extension];
  if (file.type && !file.type.startsWith("image/") && file.type !== "application/octet-stream") {
    return {
      valid: false,
      error: `File content type "${file.type}" does not look like an image (expected one of: ${expectedMimes.join(", ")}).`,
      extension,
    };
  }

  return { valid: true, error: null, extension };
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}
