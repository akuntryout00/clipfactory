import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { ProjectStatus } from "@/lib/types"

const STYLE: Record<string, string> = {
  DRAFT: "bg-muted text-muted-foreground",
  READY: "bg-ready/15 text-ready border-ready/30",
  APPROVED: "bg-primary/15 text-primary border-primary/40",
  FAILED: "bg-fail/15 text-fail border-fail/30",
}
export function StatusBadge({ status, className }: { status: ProjectStatus | string; className?: string }) {
  const running = !(status in STYLE)
  return (
    <Badge variant="outline" className={cn("font-mono text-[11px] tracking-wide", STYLE[status] ?? "bg-secondary text-foreground", className)}>
      {running && <span className="mr-1.5 inline-block size-1.5 animate-pulse rounded-full bg-primary" />}
      {status.replace(/_/g, " ")}
    </Badge>
  )
}
