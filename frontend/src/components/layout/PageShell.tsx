import { AppHeader } from "@/components/common/AppHeader";

/** Same page chrome as the dashboard: glass header + centred main column. */
export function PageShell({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="flex min-h-full flex-col">
      <AppHeader />
      <main className={`mx-auto w-full flex-1 px-6 py-10 ${wide ? "max-w-[1600px] xl:px-10" : "max-w-5xl"}`}>{children}</main>
    </div>
  );
}
