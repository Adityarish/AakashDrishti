"use client";

import { ScenarioLab } from "@/components/survey/scenarios/ScenarioLab";

export default function Hazards() {
  return (
    <>
      <div className="mx-auto flex w-full max-w-[1920px] flex-wrap items-baseline gap-x-4 gap-y-1 px-4 pb-3 pt-4 sm:px-6">
        <p className="eyebrow">Hazards</p>
        <h1 className="text-xl font-semibold tracking-tight text-polar-night sm:text-2xl">Run a disaster scenario on your image</h1>
      </div>
      <ScenarioLab />
    </>
  );
}
