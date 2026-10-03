/**
 * POST /api/project/upload -- backend/app/api/routes_project.py
 *
 * Sends the user's actual File object as multipart/form-data. Never a repo
 * path or sample asset.
 */

import { apiFetch } from "./client";
import type { GeoMetadata, UploadResult } from "@/lib/types/upload";

interface GeoMetadataDto {
  crs: string;
  transform: [number, number, number, number, number, number];
  width: number;
  height: number;
  bounds: [number, number, number, number];
  resolution: [number, number];
  nodata: number | null;
  band_count: number;
}

interface UploadResponseDto {
  job_id: string;
  filename: string;
  width: number;
  height: number;
  band_count: number;
  dtype: string;
  is_georeferenced: boolean;
  geo: GeoMetadataDto | null;
}

function mapGeo(dto: GeoMetadataDto | null): GeoMetadata | null {
  if (!dto) return null;
  return {
    crs: dto.crs,
    transform: dto.transform,
    width: dto.width,
    height: dto.height,
    bounds: dto.bounds,
    resolution: dto.resolution,
    nodata: dto.nodata,
    bandCount: dto.band_count,
  };
}

export async function uploadProject(file: File): Promise<UploadResult> {
  const formData = new FormData();
  formData.append("file", file);

  const dto = await apiFetch<UploadResponseDto>("/api/project/upload", {
    method: "POST",
    body: formData,
  });

  return {
    jobId: dto.job_id,
    filename: dto.filename,
    width: dto.width,
    height: dto.height,
    bandCount: dto.band_count,
    dtype: dto.dtype,
    isGeoreferenced: dto.is_georeferenced,
    geo: mapGeo(dto.geo),
  };
}
