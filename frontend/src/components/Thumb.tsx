import { media } from "@/lib/api"
import { cn } from "@/lib/utils"

export function Thumb({ assetId, className }: { assetId: string; className?: string }) {
  return (
    <div className={cn("aspect-[9/16] overflow-hidden rounded-md bg-surface-2", className)}>
      <img src={media.assetThumb(assetId)} alt="" loading="lazy" className="h-full w-full object-cover" />
    </div>
  )
}
