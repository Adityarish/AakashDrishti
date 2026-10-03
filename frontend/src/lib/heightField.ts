import { jobFileUrl } from "./api/survey";

export interface Field {
  width: number;
  height: number;
  data: Float32Array;
}

const cache = new Map<string, Promise<Field>>();

/** Loads a raw little-endian float32 raster written by the pipeline (height.f32, ndsm.f32, uncertainty.f32). */
export function loadField(jobId: string, name: string, width: number, height: number): Promise<Field> {
  const key = `${jobId}/${name}`;
  let pending = cache.get(key);
  if (!pending) {
    pending = fetch(jobFileUrl(jobId, name))
      .then(async (response) => {
        if (!response.ok) throw new Error(`${name} is not available (${response.status}).`);
        const buffer = await response.arrayBuffer();
        if (buffer.byteLength !== width * height * 4) throw new Error(`${name} has an unexpected size.`);
        return { width, height, data: new Float32Array(buffer) };
      })
      .catch((error) => {
        cache.delete(key);
        throw error;
      });
    cache.set(key, pending);
  }
  return pending;
}

export function sample(field: Field, col: number, row: number): number {
  const x = Math.min(field.width - 1.001, Math.max(0, col));
  const y = Math.min(field.height - 1.001, Math.max(0, row));
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const fx = x - x0;
  const fy = y - y0;
  const i = y0 * field.width + x0;
  const d = field.data;
  return (d[i] * (1 - fx) + d[i + 1] * fx) * (1 - fy) + (d[i + field.width] * (1 - fx) + d[i + field.width + 1] * fx) * fy;
}
