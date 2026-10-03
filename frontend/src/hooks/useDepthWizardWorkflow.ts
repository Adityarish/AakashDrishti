"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { uploadProject } from "@/lib/api/project";
import { getJobStatus, getResultMetadata, outputUrl, runPipeline } from "@/lib/api/pipeline";
import type { UploadedFile, UploadResult } from "@/lib/types/upload";
import type { ProcessingStatus, WorkflowStatus } from "@/lib/types/processing";
import type { ProcessingResult } from "@/lib/types/results";
import { validateFile } from "@/lib/validation/file";

const POLL_INTERVAL_MS = 2000;

function readImageDimensions(file: File): Promise<{ width: number | null; height: number | null }> {
  return new Promise((resolve) => {
    // TIFF/GeoTIFF generally cannot be decoded by <img>; resolve gracefully.
    const img = new Image();
    const objectUrl = URL.createObjectURL(file);
    img.onload = () => {
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
      URL.revokeObjectURL(objectUrl);
    };
    img.onerror = () => {
      resolve({ width: null, height: null });
      URL.revokeObjectURL(objectUrl);
    };
    img.src = objectUrl;
  });
}

/**
 * Builds the results screen's data from the job's real `outputs` map. When
 * metadata.json (written by backend/app/pipeline/run.py) is present, every
 * available panel reflects genuine backend output; anything the backend
 * hasn't produced (currently: mesh) stays `available: false` rather than
 * being guessed at.
 */
export async function buildResultFromOutputs(
  jobId: string,
  outputs: Record<string, string>,
  originalImageUrl: string,
  isGeoreferenced: boolean,
): Promise<ProcessingResult> {
  const fallback: ProcessingResult = {
    jobId,
    originalImageUrl,
    isGeoreferenced,
    depth: { available: false, daV2Stats: null, depthProStats: null, depthProFocalLengthPx: null, previewUrl: null },
    dsm: { available: false, isMetric: isGeoreferenced, previewUrl: null, downloadUrl: null },
    confidence: { available: false, previewUrl: null },
    terrain: { available: false, meshUrl: null, vertexCount: null, triangleCount: null, isMetric: false, spacingUnits: null },
    validation: { available: false, rmse: null, mae: null, correlation: null, validPixelCount: null },
  };

  if (!outputs.metadata_json) {
    return fallback;
  }

  let metadata;
  try {
    metadata = await getResultMetadata(outputs.metadata_json);
  } catch {
    return fallback;
  }

  return {
    jobId,
    originalImageUrl,
    isGeoreferenced,
    depth: {
      available: true,
      daV2Stats: metadata.da_v2_stats,
      depthProStats: metadata.depth_pro_stats,
      depthProFocalLengthPx: metadata.depth_pro_focallength_px,
      previewUrl: outputs.fused_depth_preview_png ? outputUrl(outputs.fused_depth_preview_png) : null,
    },
    dsm: {
      available: Boolean(outputs.dsm_preview_png),
      isMetric: metadata.dsm_is_metric,
      previewUrl: outputs.dsm_preview_png ? outputUrl(outputs.dsm_preview_png) : null,
      downloadUrl: outputs.dsm_tif ? outputUrl(outputs.dsm_tif) : null,
    },
    confidence: {
      available: metadata.confidence_available && Boolean(outputs.confidence_preview_png),
      previewUrl: outputs.confidence_preview_png ? outputUrl(outputs.confidence_preview_png) : null,
    },
    terrain: {
      available: metadata.mesh_status === "ready" && Boolean(outputs.terrain_glb),
      meshUrl: outputs.terrain_glb ? outputUrl(outputs.terrain_glb) : null,
      vertexCount: metadata.mesh_vertex_count ?? null,
      triangleCount: metadata.mesh_triangle_count ?? null,
      isMetric: metadata.dsm_is_metric,
      spacingUnits: metadata.mesh_spacing_units ?? null,
    },
    // Reference validation (FR-11) is not implemented on the backend yet.
    validation: { available: false, rmse: null, mae: null, correlation: null, validPixelCount: null },
  };
}

export interface DepthWizardWorkflow {
  status: WorkflowStatus;
  uploadedFile: UploadedFile | null;
  validationError: string | null;
  uploadResult: UploadResult | null;
  processingStatus: ProcessingStatus | null;
  result: ProcessingResult | null;
  errorMessage: string | null;
  selectFile: (file: File) => Promise<void>;
  clearFile: () => void;
  startProcessing: () => Promise<void>;
}

export function useDepthWizardWorkflow(): DepthWizardWorkflow {
  const [status, setStatus] = useState<WorkflowStatus>("idle");
  const [uploadedFile, setUploadedFile] = useState<UploadedFile | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [processingStatus, setProcessingStatus] = useState<ProcessingStatus | null>(null);
  const [result, setResult] = useState<ProcessingResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const previewUrlRef = useRef<string | null>(null);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const clearFile = useCallback(() => {
    stopPolling();
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    setUploadedFile(null);
    setValidationError(null);
    setUploadResult(null);
    setProcessingStatus(null);
    setResult(null);
    setErrorMessage(null);
    setStatus("idle");
  }, [stopPolling]);

  const selectFile = useCallback(async (file: File) => {
    const validation = validateFile(file);
    if (!validation.valid) {
      setValidationError(validation.error);
      setUploadedFile(null);
      setStatus("idle");
      return;
    }

    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
    }
    const previewUrl = URL.createObjectURL(file);
    previewUrlRef.current = previewUrl;

    const { width, height } = await readImageDimensions(file);

    setValidationError(null);
    setUploadResult(null);
    setProcessingStatus(null);
    setResult(null);
    setErrorMessage(null);
    setUploadedFile({
      file,
      previewUrl,
      name: file.name,
      sizeBytes: file.size,
      mimeType: file.type,
      extension: validation.extension!,
      width,
      height,
    });
    setStatus("selected");
  }, []);

  const startProcessing = useCallback(async () => {
    if (!uploadedFile) return;

    setStatus("uploading");
    setErrorMessage(null);

    let uploaded: UploadResult;
    try {
      uploaded = await uploadProject(uploadedFile.file);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.isNetworkError
            ? err.message
            : `Upload failed (${err.status}): ${err.message}`
          : "Unexpected error while uploading the image.";
      setErrorMessage(message);
      setStatus("error");
      return;
    }

    setUploadResult(uploaded);
    setStatus("processing");
    setProcessingStatus({ jobId: uploaded.jobId, stage: "UPLOADED", error: null, outputs: {}, progress: 0 });

    try {
      const started = await runPipeline(uploaded.jobId);
      setProcessingStatus(started);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.isNetworkError
            ? `Image uploaded successfully (job ${uploaded.jobId.slice(0, 8)}...), but the backend is unreachable to start processing: ${err.message}`
            : `Failed to start processing (${err.status}): ${err.message}`
          : "Unexpected error while starting processing.";
      setErrorMessage(message);
      setStatus("error");
      return;
    }

    pollTimer.current = setInterval(async () => {
      try {
        const polled = await getJobStatus(uploaded.jobId);
        setProcessingStatus(polled);
        if (polled.stage === "READY") {
          stopPolling();
          const built = await buildResultFromOutputs(
            uploaded.jobId,
            polled.outputs,
            uploadedFile.previewUrl,
            uploaded.isGeoreferenced,
          );
          setResult(built);
          setStatus("complete");
        } else if (polled.stage === "FAILED") {
          stopPolling();
          setErrorMessage(polled.error ?? "Processing failed on the backend.");
          setStatus("error");
        }
      } catch (err) {
        stopPolling();
        const message = err instanceof ApiError ? err.message : "Lost connection while polling job status.";
        setErrorMessage(message);
        setStatus("error");
      }
    }, POLL_INTERVAL_MS);
  }, [uploadedFile, stopPolling]);

  return {
    status,
    uploadedFile,
    validationError,
    uploadResult,
    processingStatus,
    result,
    errorMessage,
    selectFile,
    clearFile,
    startProcessing,
  };
}
