import { AppHeader } from "@/components/common/AppHeader";
import { JobDetailClient } from "@/components/history/JobDetailClient";

export default async function HistoryJobPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;

  return (
    <div className="flex min-h-full flex-col">
      <AppHeader />
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-6 py-10 xl:px-10">
        <JobDetailClient jobId={jobId} />
      </main>
    </div>
  );
}
