'use client'

import { clsx, type ClassValue } from 'clsx'
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Copy,
  Info,
  Loader2,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import type {
  ButtonHTMLAttributes,
  ComponentProps,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react'
import { twMerge } from 'tailwind-merge'

import { toast } from './toast'

export { Toaster, toast } from './toast'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/* ------------------------------------------------------------------ buttons */

type Variant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger'
type Size = 'sm' | 'md' | 'lg' | 'icon'

export function buttonClasses(variant: Variant = 'primary', size: Size = 'md', className?: string) {
  return cn(
    'inline-flex shrink-0 select-none items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium',
    'transition-[background-color,border-color,color,box-shadow,opacity] duration-150',
    'disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50',
    size === 'sm' && 'h-8 px-3 text-xs',
    size === 'md' && 'h-9 px-4 text-sm',
    size === 'lg' && 'h-11 px-5 text-sm',
    size === 'icon' && 'h-8 w-8 text-sm',
    variant === 'primary' &&
      'bg-primary text-primary-foreground shadow-sm shadow-primary/20 hover:bg-primary/90',
    variant === 'secondary' && 'border border-border bg-muted text-foreground hover:bg-subtle',
    variant === 'outline' &&
      'border border-border bg-transparent text-foreground hover:border-border-strong hover:bg-muted',
    variant === 'ghost' && 'text-muted-foreground hover:bg-muted hover:text-foreground',
    variant === 'danger' && 'bg-danger text-white shadow-sm hover:bg-danger/90',
    className,
  )
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: LucideIcon
}

export function Button({
  className,
  variant = 'primary',
  size = 'md',
  loading = false,
  icon: Icon,
  disabled,
  children,
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={buttonClasses(variant, size, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      ) : (
        Icon && <Icon className="h-4 w-4" aria-hidden />
      )}
      {children}
    </button>
  )
}

/** A Next link that looks like a button, instead of a <button> nested in an <a>. */
export function LinkButton({
  variant = 'primary',
  size = 'md',
  icon: Icon,
  className,
  children,
  ...props
}: ComponentProps<typeof Link> & { variant?: Variant; size?: Size; icon?: LucideIcon }) {
  return (
    <Link className={buttonClasses(variant, size, className)} {...props}>
      {Icon && <Icon className="h-4 w-4" aria-hidden />}
      {children}
    </Link>
  )
}

/* ------------------------------------------------------------------- inputs */

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn('input', className)} {...props} />
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn('input font-mono text-xs leading-relaxed', className)} {...props} />
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn('input cursor-pointer pr-8', className)} {...props}>
      {children}
    </select>
  )
}

/** Label + control + hint, with the label actually bound to the control. */
export function Field({
  id,
  label,
  hint,
  error,
  aside,
  className,
  children,
}: {
  id?: string
  label: ReactNode
  hint?: ReactNode
  error?: ReactNode
  aside?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <div className={className}>
      <div className="flex items-baseline justify-between gap-3">
        <label className="label" htmlFor={id}>
          {label}
        </label>
        {aside}
      </div>
      {children}
      {error ? <p className="hint text-danger">{error}</p> : hint && <p className="hint">{hint}</p>}
    </div>
  )
}

/** A checkbox rendered as a toggleable pill, for picking from a small set. */
export function ToggleChip({
  checked,
  onChange,
  children,
  disabled,
  title,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  children: ReactNode
  disabled?: boolean
  title?: string
}) {
  return (
    <label
      title={title}
      className={cn(
        'inline-flex cursor-pointer select-none items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors',
        'has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring',
        checked
          ? 'border-primary/50 bg-primary/10 text-foreground'
          : 'border-border text-muted-foreground hover:border-border-strong hover:text-foreground',
        disabled && 'cursor-not-allowed opacity-50',
      )}
    >
      <input
        type="checkbox"
        className="sr-only"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span
        className={cn(
          'flex h-4 w-4 items-center justify-center rounded-full border transition-colors',
          checked ? 'border-primary bg-primary text-primary-foreground' : 'border-border-strong',
        )}
        aria-hidden
      >
        {checked && <Check className="h-3 w-3" strokeWidth={3} />}
      </span>
      {children}
    </label>
  )
}

/** Checkbox with a title and an explanation underneath. */
export function CheckboxRow({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  label: ReactNode
  description?: ReactNode
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3 text-sm">
      <input
        type="checkbox"
        className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        <span className="font-medium">{label}</span>
        {description && <span className="block text-xs text-muted-foreground">{description}</span>}
      </span>
    </label>
  )
}

/** Segmented control: a small, mutually exclusive set of options. */
export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  size = 'md',
  className,
  label,
}: {
  options: { value: T; label: ReactNode; count?: number; disabled?: boolean }[]
  value: T
  onChange: (value: T) => void
  size?: 'sm' | 'md'
  className?: string
  label?: string
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className={cn('inline-flex flex-wrap gap-1 rounded-lg border border-border bg-muted/60 p-1', className)}
    >
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={String(option.value)}
            type="button"
            role="tab"
            aria-selected={active}
            disabled={option.disabled}
            onClick={() => onChange(option.value)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md font-medium transition-colors disabled:opacity-40',
              size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-sm',
              active
                ? 'bg-card text-foreground shadow-card ring-1 ring-border'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {option.label}
            {option.count !== undefined && (
              <span
                className={cn(
                  'rounded-full px-1.5 text-[11px] tabular-nums',
                  active ? 'bg-muted text-foreground' : 'bg-transparent text-muted-foreground',
                )}
              >
                {option.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------------- layout */

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('card', className)}>{children}</div>
}

export function CardHeader({
  title,
  description,
  action,
  icon: Icon,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  icon?: LucideIcon
  className?: string
}) {
  return (
    <div className={cn('mb-4 flex flex-wrap items-start justify-between gap-3', className)}>
      <div className="flex min-w-0 items-start gap-3">
        {Icon && (
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
            <Icon className="h-4 w-4" aria-hidden />
          </span>
        )}
        <div className="min-w-0">
          <h2 className="font-semibold leading-tight">{title}</h2>
          {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
        </div>
      </div>
      {action}
    </div>
  )
}

export function PageHeader({
  title,
  description,
  action,
  eyebrow,
}: {
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  eyebrow?: ReactNode
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-2 text-sm text-muted-foreground">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && (
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted-foreground">{description}</p>
        )}
      </div>
      {action && <div className="flex flex-wrap items-center gap-2">{action}</div>}
    </div>
  )
}

/* ------------------------------------------------------------------- status */

const TONES = {
  neutral: 'bg-muted text-muted-foreground ring-border',
  success: 'bg-success/10 text-success ring-success/25',
  warning: 'bg-warning/10 text-warning ring-warning/25',
  danger: 'bg-danger/10 text-danger ring-danger/25',
  info: 'bg-info/10 text-info ring-info/25',
  primary: 'bg-primary/10 text-primary ring-primary/25',
} as const

const DOTS: Record<Tone, string> = {
  neutral: 'bg-muted-foreground',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  info: 'bg-info',
  primary: 'bg-primary',
}

export type Tone = keyof typeof TONES

export function Badge({
  children,
  tone = 'neutral',
  title,
  dot = false,
  pulse = false,
  className,
}: {
  children: ReactNode
  tone?: Tone
  title?: string
  dot?: boolean
  pulse?: boolean
  className?: string
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
        TONES[tone],
        className,
      )}
    >
      {dot && (
        <span className="relative flex h-1.5 w-1.5">
          {pulse && (
            <span className={cn('absolute inline-flex h-full w-full animate-ping rounded-full opacity-60', DOTS[tone])} />
          )}
          <span className={cn('relative inline-flex h-1.5 w-1.5 rounded-full', DOTS[tone])} />
        </span>
      )}
      {children}
    </span>
  )
}

export function statusTone(status: string): Tone {
  switch (status) {
    case 'done':
      return 'success'
    case 'running':
    case 'queued':
    // Waiting for a limit is still in progress: it restarts by itself.
    case 'rate_limited':
      return 'info'
    case 'failed':
      return 'danger'
    case 'blocked_auth':
    case 'needs_review':
      return 'warning'
    default:
      return 'neutral'
  }
}

const STATUS_LABELS: Record<string, string> = {
  pending: 'Not run',
  queued: 'Queued',
  running: 'Running',
  done: 'Done',
  failed: 'Failed',
  skipped: 'Skipped',
  cancelled: 'Cancelled',
  blocked_auth: 'Paused',
  rate_limited: 'Waiting for limit',
  thin_context: 'Generic message',
  needs_review: 'Hold',
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status.replace(/_/g, ' ')
}

export function StatusBadge({ status, title }: { status: string; title?: string }) {
  const tone = statusTone(status)
  return (
    <Badge tone={tone} dot pulse={status === 'running'} title={title}>
      {statusLabel(status)}
    </Badge>
  )
}

const ALERT_ICONS: Record<Tone, LucideIcon> = {
  neutral: Info,
  info: Info,
  primary: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: XCircle,
}

export function Alert({
  tone = 'danger',
  title,
  action,
  children,
  className,
}: {
  tone?: Tone
  title?: ReactNode
  action?: ReactNode
  children?: ReactNode
  className?: string
}) {
  const Icon = ALERT_ICONS[tone]
  return (
    <div
      role={tone === 'danger' ? 'alert' : 'status'}
      className={cn(
        'flex gap-3 rounded-lg border px-4 py-3 text-sm',
        tone === 'danger' && 'border-danger/30 bg-danger/[0.07]',
        tone === 'warning' && 'border-warning/30 bg-warning/[0.07]',
        tone === 'success' && 'border-success/30 bg-success/[0.07]',
        (tone === 'info' || tone === 'primary') && 'border-info/30 bg-info/[0.07]',
        tone === 'neutral' && 'border-border bg-muted/60',
        className,
      )}
    >
      <Icon
        className={cn(
          'mt-0.5 h-4 w-4 shrink-0',
          tone === 'danger' && 'text-danger',
          tone === 'warning' && 'text-warning',
          tone === 'success' && 'text-success',
          (tone === 'info' || tone === 'primary') && 'text-info',
          tone === 'neutral' && 'text-muted-foreground',
        )}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium text-foreground">{title}</p>}
        {children && (
          <div className={cn('leading-relaxed text-muted-foreground', title && 'mt-0.5')}>{children}</div>
        )}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  )
}

/** Progress bar. Failed rows show as a red segment so a "finished" bar that is
 *  half failures does not look like success. */
export function Progress({
  done,
  failed = 0,
  total,
  showLabel = true,
  className,
}: {
  done: number
  failed?: number
  total: number
  showLabel?: boolean
  className?: string
}) {
  const pct = (n: number) => (total > 0 ? Math.min(100, (n / total) * 100) : 0)
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <div
        className="flex h-1.5 w-28 overflow-hidden rounded-full bg-muted ring-1 ring-inset ring-border/60"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done + failed}
      >
        <div className="h-full bg-success transition-all duration-500" style={{ width: `${pct(done)}%` }} />
        <div className="h-full bg-danger transition-all duration-500" style={{ width: `${pct(failed)}%` }} />
      </div>
      {showLabel && (
        <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
          {done + failed}/{total}
        </span>
      )}
    </div>
  )
}

export function Stat({
  label,
  value,
  tone,
  hint,
}: {
  label: ReactNode
  value: ReactNode
  tone?: Tone
  hint?: ReactNode
}) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div
        className={cn(
          'mt-1 text-xl font-semibold tabular-nums',
          tone === 'success' && 'text-success',
          tone === 'danger' && 'text-danger',
          tone === 'warning' && 'text-warning',
          tone === 'info' && 'text-info',
        )}
      >
        {value}
      </div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  )
}

/* ----------------------------------------------------------------- stepper */

export type StepState = 'done' | 'partial' | 'current' | 'upcoming'

export function Stepper({
  steps,
  className,
}: {
  steps: { label: ReactNode; description?: ReactNode; state: StepState }[]
  className?: string
}) {
  return (
    <ol className={cn('flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-0', className)}>
      {steps.map((step, index) => (
        <li key={index} className="flex flex-1 items-start gap-3 sm:flex-col sm:gap-2.5">
          <div className="flex items-center sm:w-full">
            <span
              className={cn(
                'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ring-1 ring-inset',
                step.state === 'done' && 'bg-success/15 text-success ring-success/30',
                step.state === 'partial' && 'bg-success/10 text-success ring-success/30',
                step.state === 'current' && 'bg-primary text-primary-foreground ring-primary shadow-sm shadow-primary/30',
                step.state === 'upcoming' && 'bg-muted text-muted-foreground ring-border',
              )}
              aria-current={step.state === 'current' ? 'step' : undefined}
            >
              {step.state === 'done' ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : index + 1}
            </span>
            {index < steps.length - 1 && (
              <span
                className={cn(
                  'mx-3 hidden h-px flex-1 sm:block',
                  step.state === 'done' ? 'bg-success/40' : step.state === 'partial' ? 'bg-gradient-to-r from-success/40 to-border' : 'bg-border',
                )}
                aria-hidden
              />
            )}
          </div>
          <div className="min-w-0 sm:pr-4">
            <div
              className={cn(
                'text-sm font-medium',
                step.state === 'upcoming' ? 'text-muted-foreground' : 'text-foreground',
              )}
            >
              {step.label}
            </div>
            {step.description && <div className="mt-0.5 text-xs text-muted-foreground">{step.description}</div>}
          </div>
        </li>
      ))}
    </ol>
  )
}

/* ---------------------------------------------------------------- feedback */

export function Spinner({ label = 'Loading', className }: { label?: string; className?: string }) {
  return (
    <div
      className={cn('flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground', className)}
      role="status"
    >
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {label}…
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-md bg-muted', className)} />
}

export function Empty({
  icon: Icon,
  title,
  children,
  action,
  className,
}: {
  icon?: LucideIcon
  title?: ReactNode
  children?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center rounded-xl border border-dashed border-border-strong/60 px-6 py-14 text-center',
        className,
      )}
    >
      {Icon && (
        <span className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-muted text-muted-foreground ring-1 ring-border">
          <Icon className="h-5 w-5" aria-hidden />
        </span>
      )}
      {title && <p className="font-medium">{title}</p>}
      {children && <div className="mt-1 max-w-md text-sm text-muted-foreground">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Button
      size="sm"
      variant="ghost"
      icon={copied ? Check : Copy}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        } catch {
          toast.error('Could not copy to the clipboard.')
        }
      }}
    >
      {copied ? 'Copied' : label}
    </Button>
  )
}

