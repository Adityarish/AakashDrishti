"use client";

import { useParams } from "next/navigation";

import { AppHeader } from "@/components/common/AppHeader";
import { SurveyProvider } from "@/components/survey/SurveyContext";

export default function SurveyLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  return (
    <>
      <AppHeader />
      <SurveyProvider id={id}>{children}</SurveyProvider>
    </>
  );
}
