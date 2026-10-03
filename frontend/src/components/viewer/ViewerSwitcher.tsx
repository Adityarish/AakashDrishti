"use client";

import type { ComponentProps } from "react";

import type { TerrainViewer } from "./TerrainViewer";
import { UnityViewer } from "./UnityViewer";

/** Results 3D view: the interactive Unity WebGL viewer only (the classic Three.js viewer is no longer offered). */
export function ViewerSwitcher({ jobId }: ComponentProps<typeof TerrainViewer>) {
  return <UnityViewer key={jobId} jobId={jobId} />;
}
