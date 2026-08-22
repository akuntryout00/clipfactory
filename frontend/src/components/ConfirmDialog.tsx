import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react"
import { AlertTriangle, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"

export interface ConfirmOptions {
  title: string
  description?: ReactNode
  /** label of the destructive button, e.g. "Delete project" */
  confirmLabel?: string
  cancelLabel?: string
  /** what will be removed — shown as a monospace chip */
  subject?: string
}

type Ask = (opts: ConfirmOptions) => Promise<boolean>
const Ctx = createContext<Ask | null>(null)

/** App-wide replacement for window.confirm(): `if (await confirm({...})) doIt()` */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null)
  const resolver = useRef<((ok: boolean) => void) | null>(null)
  const ask = useCallback<Ask>(o => new Promise(resolve => { resolver.current = resolve; setOpts(o) }), [])
  const settle = (ok: boolean) => { resolver.current?.(ok); resolver.current = null; setOpts(null) }
  const value = useMemo(() => ask, [ask])
  return (
    <Ctx.Provider value={value}>
      {children}
      <Dialog open={opts !== null} onOpenChange={o => { if (!o) settle(false) }}>
        <DialogContent className="sm:max-w-md" showCloseButton={false}>
          {opts && (
            <>
              <DialogHeader>
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-md bg-fail/15 text-fail"><AlertTriangle className="size-4" /></span>
                  <div className="min-w-0 space-y-1">
                    <DialogTitle className="font-heading">{opts.title}</DialogTitle>
                    {opts.subject && <div className="truncate rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground" title={opts.subject}>{opts.subject}</div>}
                    {opts.description && <DialogDescription>{opts.description}</DialogDescription>}
                  </div>
                </div>
              </DialogHeader>
              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="outline" onClick={() => settle(false)} autoFocus>{opts.cancelLabel ?? "Cancel"}</Button>
                <Button type="button" variant="destructive" onClick={() => settle(true)}><Trash2 className="size-4" /> {opts.confirmLabel ?? "Delete"}</Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </Ctx.Provider>
  )
}

export function useConfirm(): Ask {
  const c = useContext(Ctx)
  if (!c) throw new Error("useConfirm must be used inside <ConfirmProvider>")
  return c
}
