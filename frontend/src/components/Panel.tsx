import type { ReactNode } from "react";

export function Panel({
  title,
  right,
  children,
}: {
  title: string;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-term-border bg-term-panel p-4">
      <header className="mb-3 flex items-center justify-between gap-3">
        <h2 className="font-head text-xs font-semibold uppercase tracking-[0.12em] text-term-muted">
          {title}
        </h2>
        {right}
      </header>
      {children}
    </section>
  );
}

export function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs uppercase tracking-wide text-term-muted">{label}</span>
      <span className={`font-mono text-xl tabnum ${tone ?? "text-term-fg"}`}>{value}</span>
    </div>
  );
}
