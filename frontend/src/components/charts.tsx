"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export const CLASS_COLORS: Record<string, string> = {
  ground: "#b0a692",
  low_vegetation: "#8cc878",
  building: "#e7604e",
  water: "#4682c8",
  road: "#6e7682",
  tree: "#1e7846",
};

const AXIS = { fontSize: 11, fill: "#6e6248", fontFamily: "var(--font-jetbrains-mono)" };
const TOOLTIP = {
  contentStyle: {
    background: "rgba(255,255,255,0.96)",
    border: "1px solid #d3c9a1",
    borderRadius: 10,
    boxShadow: "0 8px 24px rgba(31,95,139,0.14)",
    fontSize: 12,
  },
  labelStyle: { color: "#2b2416", fontWeight: 700 },
};

export function LandCoverBars({ data }: { data: { name: string; value: number; unit?: string }[] }) {
  return (
    <ResponsiveContainer width="100%" height={data.length * 34 + 16}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
        <XAxis type="number" hide />
        <YAxis type="category" dataKey="name" width={104} tick={{ ...AXIS, fontFamily: "var(--font-manrope)", fontWeight: 600 }} axisLine={false} tickLine={false} />
        <Tooltip {...TOOLTIP} formatter={(value) => [`${Number(value).toFixed(1)}%`, "Share"]} cursor={{ fill: "#ebe4cb" }} />
        <Bar dataKey="value" radius={[0, 6, 6, 0]} barSize={16}>
          {data.map((entry) => (
            <Cell key={entry.name} fill={CLASS_COLORS[entry.name.toLowerCase().replace(" ", "_")] ?? "#7d9463"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Histogram({
  bins,
  color = "#7d9463",
  xLabel,
  height = 200,
  marker,
}: {
  bins: { label: string; count: number }[];
  color?: string;
  xLabel?: string;
  height?: number;
  marker?: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={bins} margin={{ left: -12, right: 8, top: 8, bottom: xLabel ? 18 : 0 }}>
        <CartesianGrid vertical={false} stroke="#ebe4cb" />
        <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} interval="preserveStartEnd" label={xLabel ? { value: xLabel, position: "insideBottom", offset: -12, style: AXIS } : undefined} />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} allowDecimals={false} />
        <Tooltip {...TOOLTIP} cursor={{ fill: "#ebe4cb" }} />
        {marker && <ReferenceLine x={marker} stroke="#a88a2c" strokeDasharray="4 3" />}
        <Bar dataKey="count" fill={color} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ProfileChart({
  points,
  unit,
  water,
}: {
  points: { d: number; surface: number; terrain: number; upper: number; lower: number }[];
  unit: string;
  water?: number | null;
}) {
  return (
    <ResponsiveContainer width="100%" height={180}>
      <ComposedChart data={points} margin={{ left: 0, right: 12, top: 6, bottom: 0 }}>
        <CartesianGrid stroke="#ebe4cb" vertical={false} />
        <XAxis dataKey="d" tick={AXIS} tickFormatter={(v) => `${Math.round(v)}`} axisLine={false} tickLine={false} />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} domain={["auto", "auto"]} width={44} unit={unit === "m" ? "" : ""} />
        <Tooltip {...TOOLTIP} formatter={(value, name) => [`${Number(value).toFixed(1)} ${unit}`, String(name)]} labelFormatter={(v) => `${Math.round(Number(v))} m along line`} />
        <Area type="monotone" dataKey="upper" stroke="none" fill="#7d9463" fillOpacity={0.14} isAnimationActive={false} />
        <Area type="monotone" dataKey="lower" stroke="none" fill="#fbf6e7" fillOpacity={1} isAnimationActive={false} />
        <Line type="monotone" dataKey="terrain" name="Terrain" stroke="#d3c9a1" strokeWidth={1.6} dot={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="surface" name="Surface (DSM)" stroke="#3c5a33" strokeWidth={2.2} dot={false} isAnimationActive={false} />
        {water !== null && water !== undefined && <ReferenceLine y={water} stroke="#7d9463" strokeDasharray="5 4" label={{ value: "water", fill: "#7d9463", fontSize: 11, position: "insideTopRight" }} />}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function ScatterPlot({
  data,
  unit,
  range,
  xLabel = "Reference",
  yLabel = "Predicted",
}: {
  data: [number, number][];
  unit: string;
  range: [number, number];
  xLabel?: string;
  yLabel?: string;
}) {
  const points = data.map(([reference, predicted]) => ({ reference, predicted }));
  const [lo, hi] = range;
  return (
    <ResponsiveContainer width="100%" height={300}>
      <ScatterChart margin={{ left: 0, right: 12, top: 8, bottom: 22 }}>
        <CartesianGrid stroke="#ebe4cb" />
        <XAxis type="number" dataKey="reference" name="Reference" domain={[lo, hi]} tick={AXIS} axisLine={false} tickLine={false} label={{ value: `${xLabel} (${unit})`, position: "insideBottom", offset: -12, style: AXIS }} />
        <YAxis type="number" dataKey="predicted" name="Predicted" domain={[lo, hi]} tick={AXIS} axisLine={false} tickLine={false} width={44} label={{ value: `${yLabel} (${unit})`, angle: -90, position: "insideLeft", style: AXIS }} />
        <Tooltip {...TOOLTIP} cursor={{ strokeDasharray: "3 3" }} formatter={(value) => Number(value).toFixed(2)} />
        <ReferenceLine segment={[{ x: lo, y: lo }, { x: hi, y: hi }]} stroke="#a88a2c" strokeDasharray="6 4" />
        <Scatter data={points} fill="#3c5a33" fillOpacity={0.32} isAnimationActive={false} />
      </ScatterChart>
    </ResponsiveContainer>
  );
}

export function GroupedBars({
  data,
  keys,
  colors,
  unit,
}: {
  data: Record<string, string | number | null>[];
  keys: string[];
  colors: string[];
  unit: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ left: -6, right: 8, top: 8, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="#ebe4cb" />
        <XAxis dataKey="name" tick={{ ...AXIS, fontFamily: "var(--font-manrope)", fontWeight: 600 }} axisLine={false} tickLine={false} />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} unit={` ${unit}`} width={54} />
        <Tooltip {...TOOLTIP} formatter={(value) => [`${Number(value).toFixed(2)} ${unit}`]} cursor={{ fill: "#ebe4cb" }} />
        {keys.map((key, index) => (
          <Bar key={key} dataKey={key} fill={colors[index]} radius={[5, 5, 0, 0]} barSize={22} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ScoreBars({ counts, labels, color = "#7d9463" }: { counts: number[]; labels: string[]; color?: string }) {
  const data = counts.map((count, index) => ({ label: labels[index], count }));
  return <Histogram bins={data} color={color} height={150} />;
}
