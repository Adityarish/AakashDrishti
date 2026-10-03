"use client";

import type { ComponentProps } from "react";
import { SylvaLivingWorldScene } from "@designcodeio/threeui";

/** Thin wrapper so page.tsx can `next/dynamic(..., { ssr: false })` this
 * specific component without triggering a dynamic `import()` on the raw
 * @designcodeio/threeui package itself. A dynamic import() on the package
 * defeats static tree-shaking of its barrel file, which pulls in an unrelated
 * broken component (temple-night's renderer references THREE.sRGBEncoding,
 * removed in the installed Three.js version) that has nothing to do with
 * Sylva -- a real build failure, not a hypothetical one. This file's own
 * import of the package IS static, so normal tree-shaking still applies; only
 * this wrapper (not the package) is loaded dynamically. */
export default function SylvaScene(props: ComponentProps<typeof SylvaLivingWorldScene>) {
  return <SylvaLivingWorldScene {...props} />;
}
