# AMIPI NACHA ACH Payment System — Design System

## Overview
This design system uses **CSS custom properties (variables)** for complete customization. All visual styling can be changed by editing values in `/css/base.css` under the `:root` selector.

---

## Color Palette

### Primary Colors (Indigo-Blue)
Used for main actions, links, and brand identity.

```css
--color-primary:        hsl(235, 65%, 58%)  /* Main brand color */
--color-primary-hover:  hsl(235, 70%, 50%)  /* Hover state */
--color-primary-light:  hsl(235, 70%, 97%)  /* Backgrounds */
--color-primary-dark:   hsl(235, 50%, 35%)  /* Dark variant */
--color-primary-muted:  hsl(235, 30%, 70%)  /* Subtle text */
```

**How to customize:** Change the first value (hue) for a different color:
- `200` = Cyan/Teal
- `260` = Purple
- `350` = Red/Pink
- `140` = Green

### Accent Colors (Vibrant Teal)
Used for highlights, secondary actions, and visual interest.

```css
--color-accent:         hsl(175, 70%, 45%)  /* Accent color */
--color-accent-hover:   hsl(175, 75%, 38%)  /* Hover state */
--color-accent-light:   hsl(175, 70%, 95%)  /* Backgrounds */
```

### Semantic Colors

**Danger (Coral Red)**
```css
--color-danger:         hsl(355, 75%, 58%)  /* Error states */
--color-danger-hover:   hsl(355, 75%, 50%)  /* Hover */
--color-danger-light:   hsl(355, 75%, 96%)  /* Error backgrounds */
```

**Warning (Amber)**
```css
--color-warning:        hsl(38, 92%, 58%)   /* Warning states */
--color-warning-hover:  hsl(38, 92%, 50%)   /* Hover */
--color-warning-light:  hsl(38, 92%, 95%)   /* Warning backgrounds */
```

**Success (Emerald)**
```css
--color-success:        hsl(155, 65%, 45%)  /* Success states */
--color-success-hover:  hsl(155, 65%, 38%)  /* Hover */
--color-success-light:  hsl(155, 65%, 95%)  /* Success backgrounds */
```

### Neutral Colors

```css
--color-bg:             hsl(220, 15%, 96%)  /* Page background */
--color-surface:        hsl(0, 0%, 100%)    /* Card/panel background */
--color-surface-alt:    hsl(220, 12%, 98%)  /* Alternative surface */
--color-surface-raised: hsl(0, 0%, 100%)    /* Elevated surfaces */

--color-border:         hsl(220, 12%, 88%)  /* Standard borders */
--color-border-light:   hsl(220, 12%, 92%)  /* Subtle borders */
--color-border-strong:  hsl(220, 12%, 75%)  /* Emphasized borders */

--color-text:           hsl(220, 18%, 18%)  /* Body text */
--color-text-secondary: hsl(220, 12%, 42%)  /* Secondary text */
--color-text-muted:     hsl(220, 10%, 58%)  /* Muted text */
--color-text-inverse:   hsl(0, 0%, 100%)    /* White text on dark */
```

---

## Typography

### Font Families

```css
--font-body: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif
--font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Courier New', monospace
```

**To change fonts:** Update these values with your preferred Google Fonts or system fonts.

### Font Sizes

```css
--text-xs:    0.6875rem  /* 11px - Tiny labels */
--text-sm:    0.75rem    /* 12px - Small text */
--text-base:  0.875rem   /* 14px - Body text */
--text-md:    0.9375rem  /* 15px - Slightly larger */
--text-lg:    1.125rem   /* 18px - Headings */
--text-xl:    1.375rem   /* 22px - Large headings */
--text-2xl:   1.75rem    /* 28px - Page titles */
```

### Font Weights

```css
--font-weight-normal:   400  /* Regular text */
--font-weight-medium:   500  /* Slightly emphasized */
--font-weight-semibold: 600  /* Headings, labels */
--font-weight-bold:     700  /* Strong emphasis */
```

---

## Spacing Scale

Consistent spacing creates visual rhythm. Use these values for padding, margins, and gaps.

```css
--space-xs:   0.25rem  /* 4px  - Tight spacing */
--space-sm:   0.5rem   /* 8px  - Small spacing */
--space-md:   0.75rem  /* 12px - Medium spacing */
--space-base: 1rem     /* 16px - Base spacing */
--space-lg:   1.5rem   /* 24px - Large spacing */
--space-xl:   2rem     /* 32px - Extra large */
--space-2xl:  2.5rem   /* 40px - XXL spacing */
--space-3xl:  3rem     /* 48px - Huge spacing */
--space-4xl:  4rem     /* 64px - Massive spacing */
```

---

## Border Radius

```css
--radius-sm:   0.375rem  /* 6px  - Subtle rounding */
--radius-md:   0.5rem    /* 8px  - Standard buttons */
--radius-lg:   0.75rem   /* 12px - Cards */
--radius-xl:   1rem      /* 16px - Large cards */
--radius-2xl:  1.25rem   /* 20px - Login box */
--radius-full: 9999px    /* Full pill shape */
```

---

## Shadows

Layered shadows create depth and hierarchy.

```css
--shadow-xs:  /* Minimal elevation */
--shadow-sm:  /* Subtle card shadow */
--shadow-md:  /* Standard elevation */
--shadow-lg:  /* Prominent elevation */
--shadow-xl:  /* High elevation (modals) */
--shadow-2xl: /* Maximum elevation */
```

---

## Transitions

```css
--transition-fast: 150ms ease  /* Quick interactions */
--transition-base: 250ms ease  /* Standard animations */
--transition-slow: 350ms ease  /* Smooth transitions */
```

---

## Component Classes

### Buttons
- `.btn` — Base button style
- `.btn-primary` — Primary action (gradient, shadowed)
- `.btn-secondary` — Secondary action (outline)
- `.btn-accent` — Accent color button
- `.btn-danger` — Destructive action
- `.btn-sm` — Small button
- `.btn-lg` — Large button
- `.btn-block` — Full-width button

### Forms
- `.form-group` — Form field wrapper
- `.form-label` — Field label
- `.form-input` — Text input
- `.form-select` — Dropdown select
- `.form-hint` — Help text
- `.form-error` — Error message

### Alerts
- `.alert` — Base alert
- `.alert-error` — Error alert (red)
- `.alert-success` — Success alert (green)
- `.alert-warning` — Warning alert (amber)
- `.alert-info` — Info alert (blue)

### Badges
- `.badge` — Base badge
- `.badge-success`, `.badge-danger`, `.badge-warning`, `.badge-info`

### Cards
- `.card` — Content card with shadow
- `.card-title` — Card header/title

### Tables
- `.data-table` — Data table with hover states

### Layout
- `.app-header` — Top navigation bar
- `.main-container` — Main content wrapper
- `.tabs` / `.tab` — Tab navigation
- `.view` — Tab panel content

---

## Login Screen Customization

The login screen features:
- **Multi-color gradient background** with animated floating orbs
- **Glass-morphism login card** with backdrop blur
- **Gradient title text** (primary → accent)
- **Floating logo animation**
- **Smooth slide-up entrance animation**

### Quick Customization Tips

**Change login background gradient:**
Edit `.login-screen` background in `/css/login.css`:
```css
background: linear-gradient(135deg, 
            hsl(235, 65%, 58%) 0%,    /* Start color */
            hsl(260, 60%, 55%) 50%,   /* Middle color */
            hsl(175, 70%, 45%) 100%); /* End color */
```

**Adjust glass effect opacity:**
Edit `.login-box` background:
```css
background: hsla(0, 0%, 100%, 0.95); /* 0.95 = 95% opaque */
backdrop-filter: blur(16px);          /* Blur strength */
```

**Change title gradient:**
Edit `.login-title` background:
```css
background: linear-gradient(135deg, var(--color-primary), var(--color-accent));
```

---

## Accessibility Notes

- All colors meet WCAG AA contrast requirements for text
- Focus states have 3-4px outlines for keyboard navigation
- Buttons have clear hover and active states
- Forms include proper labels and ARIA attributes
- Animations respect `prefers-reduced-motion` (can be added if needed)

---

## Browser Support

- Modern browsers (Chrome, Firefox, Safari, Edge) — last 2 versions
- CSS Custom Properties (IE not supported)
- CSS Grid and Flexbox
- Backdrop-filter (may need fallback for older browsers)

---

## Quick Theme Examples

### Dark Mode (Future Enhancement)
Add a `.dark-mode` class and override variables:
```css
.dark-mode {
  --color-bg: hsl(220, 20%, 12%);
  --color-surface: hsl(220, 18%, 16%);
  --color-text: hsl(220, 15%, 90%);
  /* ... etc */
}
```

### Corporate Blue Theme
```css
--color-primary: hsl(210, 100%, 45%);  /* Corporate blue */
--color-accent: hsl(195, 95%, 48%);    /* Light blue accent */
```

### Warm/Earthy Theme
```css
--color-primary: hsl(25, 75%, 50%);   /* Burnt orange */
--color-accent: hsl(45, 85%, 55%);    /* Golden yellow */
```

---

## File Structure

```
frontend/
├── css/
│   ├── base.css      — Design tokens, component styles, layout
│   └── login.css     — Login screen specific styles
├── js/
│   ├── api.js        — API client (no styling)
│   └── login.js      — Login controller (no styling)
├── index.html        — Main HTML (semantic structure)
└── DESIGN_SYSTEM.md  — This file
```

All visual customization happens in **CSS files only**. HTML and JS remain unchanged.
