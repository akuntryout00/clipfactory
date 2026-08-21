import { Check, X } from "lucide-react"
import { STAGES, type ProjectStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

/** The PRD §22 generation states, drawn as a production line. Order is real: each stage feeds the next. */
export function StageTimeline({ status, error, message }: { status: ProjectStatus; error?: string | null; message?: string | null }) {
  const idx = STAGES.findIndex(s => s.key === status)
  const done = status === "READY" || status === "APPROVED"
  const failedStage = status === "FAILED" ? (error?.split(":")[0] ?? "") : ""
  const failIdx = { script: 0, voice: 1, plan: 2, render: 5 }[failedStage as "script"] ?? -1
  return (
    <div>
      <ol className="flex items-center gap-1">
        {STAGES.map((s, i) => {
          const state = done ? "done" : status === "FAILED" ? (i < failIdx ? "done" : i === failIdx ? "fail" : "todo")
            : status === "DRAFT" ? "todo" : i < idx ? "done" : i === idx ? "active" : "todo"
          return (
            <li key={s.key} className="flex flex-1 items-center gap-1 last:flex-none">
              <div className="flex flex-col items-center gap-1">
                <span className={cn("grid size-6 place-items-center rounded-full border text-[10px] font-mono",
                  state === "done" && "border-ready/40 bg-ready/15 text-ready",
                  state === "active" && "border-primary bg-primary text-primary-foreground animate-pulse",
                  state === "fail" && "border-fail bg-fail/15 text-fail",
                  state === "todo" && "border-border text-muted-foreground")}>
                  {state === "done" ? <Check className="size-3" /> : state === "fail" ? <X className="size-3" /> : i + 1}
                </span>
                <span className={cn("text-[10px] uppercase tracking-wider", state === "todo" ? "text-muted-foreground" : "text-foreground")}>{s.label}</span>
              </div>
              {i < STAGES.length - 1 && <span className={cn("mb-4 h-px flex-1", state === "done" ? "bg-ready/40" : "bg-border")} />}
            </li>
          )
        })}
      </ol>
      {(message || error) && (
        <p className={cn("mt-2 text-xs", status === "FAILED" ? "text-fail" : "text-muted-foreground")}>{status === "FAILED" ? error : message}</p>
      )}
    </div>
  )
}
