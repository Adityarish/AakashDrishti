"use client";

import { useEffect, useState } from "react";
import { CircleCheck, Info, ShieldCheck, TriangleAlert } from "lucide-react";

import { ScatterPlot } from "@/components/charts";
import { Badge, ErrorNote, InfoNote, Spinner, Stat } from "@/components/ui";
import { getSelfCheck } from "@/lib/api/survey";
import { fmt, titleCase } from "@/lib/format";
import type { SelfCheck, SelfCheckItem } from "@/lib/sceneTypes";
import { cn } from "@/lib/utils";

const VERDICT = {
  consistent: { title: "Internally consistent", tone: "aurora" as const, text: "The scale evidence, ground level and building heights in this scene agree with each other." },
  review: { title: "Review recommended", tone: "orange" as const, text: "One or more checks below flagged something worth a look before relying on these heights." },
  limited: { title: "Limited evidence", tone: "muted" as const, text: "Not enough independent evidence to cross-check this scene. Treat heights as approximate." },
};

const STATUS_ICON = {
  pass: <CircleCheck className="h-4 w-4 text-[#4d6b3f]" strokeWidth={2} />,
  warn: <TriangleAlert className="h-4 w-4 text-station-orange" strokeWidth={2} />,
  info: <Info className="h-4 w-4 text-slate-ice" strokeWidth={2} />,
};

function CheckRow({ item }: { item: SelfCheckItem }) {
  return (
    <li className="flex gap-3 border-t border-glacier-300/40 px-4 py-3 first:border-t-0">
      <span className="mt-0.5 shrink-0">{STATUS_ICON[item.status]}</span>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-polar-night">{item.name}</p>
        <p className="mt-0.5 text-[0.82rem] leading-snug text-slate-ice">{item.detail}</p>
      </div>
    </li>
  );
}

/** Reference-free check: everything here is computed from the scene the user already uploaded. */
export function SelfCheckPanel({ jobId }: { jobId: string }) {
  const [data, setData] = useState<SelfCheck | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSelfCheck(jobId)
      .then((result) => !cancelled && setData(result))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Could not run the self-check."));
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  if (error) return <ErrorNote message={error} />;
  if (!data) {
    return (
      <div className="card flex items-center gap-3 p-6 text-sm text-slate-ice">
        <Spinner className="h-4 w-4" /> Running the self-check on this scene…
      </div>
    );
  }

  const verdict = VERDICT[data.verdict];
  const unit = data.is_metric ? "m" : "rel";
  const shadow = data.shadow;
  const scatterMax = shadow ? Math.max(1, ...shadow.scatter.flat()) * 1.05 : 1;

  return (
    <div className="space-y-5">
      <div className={cn("card flex flex-wrap items-start gap-4 p-5", data.verdict === "consistent" && "border-aurora/40", data.verdict === "review" && "border-station-orange/40")}>
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-glacier-100 text-deep-ice">
          <ShieldCheck className="h-6 w-6" strokeWidth={1.5} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-polar-night">{verdict.title}</h3>
            <Badge tone={verdict.tone}>Automatic check</Badge>
            {data.gsd_assumed && <Badge tone="orange">Pixel size assumed · {fmt(data.pixel_size_m, 2)} m/px</Badge>}
          </div>
          <p className="mt-1 text-sm leading-relaxed text-slate-ice">{verdict.text}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Median building" value={data.buildings?.median_m ?? null} unit={unit} digits={1} tone="orange" hint={data.buildings ? `${data.buildings.count} buildings` : "none detected"} />
        <Stat label="Tallest 10%" value={data.buildings?.p90_m ?? null} unit={unit} digits={1} hint={data.buildings ? `max ${fmt(data.buildings.max_m, 1)} ${unit}` : undefined} />
        <Stat label="Ground residual" value={data.ground_residual_rmse_m} unit={unit} digits={2} tone="aurora" hint="bare ground should read ~0" />
        <Stat label="Model spread" value={data.uncertainty_mean_m} unit={unit} digits={2} hint="mean test-time-augmentation spread" />
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.1fr_1fr]">
        <div className="card overflow-hidden">
          <p className="eyebrow px-4 pt-4">Consistency checks</p>
          <ul className="mt-2">
            {data.checks.map((item) => (
              <CheckRow key={item.name} item={item} />
            ))}
          </ul>
        </div>

        <div className="card p-4">
          <p className="eyebrow">Scale evidence</p>
          {data.sources.length === 0 ? (
            <p className="mt-3 text-sm text-slate-ice">No scale source: the height field is relative.</p>
          ) : (
            <table className="mt-3 w-full">
              <thead>
                <tr className="text-[0.66rem] font-semibold uppercase tracking-wider text-slate-ice">
                  <th className="pb-2 text-left">Source</th>
                  <th className="pb-2 text-right">Scale</th>
                  <th className="pb-2 text-right">Weight</th>
                </tr>
              </thead>
              <tbody>
                {data.sources.map((source) => (
                  <tr key={source.name} className="border-t border-glacier-300/40 align-top">
                    <td className="py-2.5 pr-3">
                      <p className="text-sm font-semibold text-polar-night">{titleCase(source.name)}</p>
                      <p className="text-xs leading-snug text-slate-ice">{source.detail}</p>
                    </td>
                    <td className="mono py-2.5 text-right text-sm">{fmt(source.scale, 3)}</td>
                    <td className="mono py-2.5 text-right text-sm">{fmt(source.weight, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {data.scale !== null && (
            <p className="mono mt-3 border-t border-glacier-300/40 pt-3 text-xs text-slate-ice">
              Fused scale <span className="font-semibold text-polar-night">{fmt(data.scale, 3)}</span>
              {data.gcp_rmse_m !== null && <> · control-point RMSE <span className="font-semibold text-polar-night">{fmt(data.gcp_rmse_m, 2)} m</span></>}
            </p>
          )}
        </div>
      </div>

      {shadow && (
        <div className="card p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="eyebrow">Model height vs shadow-derived height</p>
              <p className="mt-1 max-w-2xl text-sm leading-relaxed text-slate-ice">
                Each dot is one building: its height from the AI model against the height measured from its shadow and the sun angle, an independent physical measurement.
                {shadow.circular && " The scale was fitted to these shadows, so read the spread around the line, not its slope."}
              </p>
            </div>
            <div className="mono flex gap-5 text-right text-xs text-slate-ice">
              <span>n <b className="text-polar-night">{shadow.n}</b></span>
              <span>MAE <b className="text-polar-night">{fmt(shadow.mae, 1)} m</b></span>
              <span>bias <b className="text-polar-night">{fmt(shadow.bias, 1)} m</b></span>
              <span>r <b className="text-polar-night">{shadow.pearson_r !== null ? fmt(shadow.pearson_r, 2) : "n/a"}</b></span>
            </div>
          </div>
          <ScatterPlot data={shadow.scatter.map(([model, shade]) => [shade, model] as [number, number])} unit="m" range={[0, scatterMax]} xLabel="Shadow-derived" yLabel="Model" />
        </div>
      )}

      <InfoNote>{data.note}</InfoNote>
    </div>
  );
}
