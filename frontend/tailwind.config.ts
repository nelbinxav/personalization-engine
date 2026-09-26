import type { Config } from 'tailwindcss'

const token = (name: string) => `hsl(var(--${name}) / <alpha-value>)`

const config: Config = {
  darkMode: 'class',
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        background: token('background'),
        foreground: token('foreground'),
        card: token('card'),
        elevated: token('elevated'),
        border: token('border'),
        'border-strong': token('border-strong'),
        muted: token('muted'),
        'muted-foreground': token('muted-foreground'),
        subtle: token('subtle'),
        primary: token('primary'),
        'primary-foreground': token('primary-foreground'),
        ring: token('ring'),
        info: token('info'),
        success: token('success'),
        warning: token('warning'),
        danger: token('danger'),
      },
      borderRadius: { xl: '0.85rem', lg: '0.65rem', md: '0.5rem', sm: '0.35rem' },
      fontFamily: {
        sans: ['var(--font-sans)', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px hsl(var(--shadow) / 0.06), 0 1px 1px hsl(var(--shadow) / 0.04)',
        pop: '0 12px 32px -8px hsl(var(--shadow) / 0.35), 0 2px 6px hsl(var(--shadow) / 0.12)',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
}
export default config
