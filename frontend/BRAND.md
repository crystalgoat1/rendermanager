# Render Manager Brand Guide

A practical reference for anyone touching the frontend. Not a corporate manual — just the rules that keep things consistent.

---

## Personality

Quiet, confident, technical. The kind of tool where you open it and things just make sense. Not trying to impress you — just works. The logo carries the energy. Everything else stays out of the way.

**We are:** Professional, calm, trustworthy, clear
**We are not:** Playful, trendy, loud, corporate-stiff

---

## Colors

### Brand

| Token        | Value     | Usage                                        |
|--------------|-----------|----------------------------------------------|
| `primary`    | `#6366f1` | Accent links, active states, focus rings      |
| `secondary`  | `#0ea5e9` | Sparingly — selected tabs, subtle highlights  |

`secondary` is not a second color to throw around. Use it only when you need a contrast to `primary`, like a toggle state or a progress indicator. Most of the UI should only know about `primary`.

### Brand Gradient

```
linear-gradient(135deg, #6366f1 0%, #0ea5e9 100%)
```

**Use for:**
- The logo
- Hero CTA buttons (one per page, max)
- Upgrade/Pro badges

**Do not use for:**
- Navigation links
- Card borders
- Backgrounds
- Every button on a page

The gradient is special. If it's everywhere, it's nowhere.

### Backgrounds

Three tones. That's it.

| Token         | Value     | Usage                              |
|---------------|-----------|------------------------------------|
| `bg-base`     | `#0B0B14` | Page background                    |
| `bg-surface`  | `#131321` | Cards, sidebar, panels             |
| `bg-elevated` | `#1A1A2E` | Modals, dropdowns, tooltips        |

Don't invent new dark hex values. If you need a layer between these, use opacity on white: `bg-white/5`.

### Text

| Class          | Usage                                    |
|----------------|------------------------------------------|
| `text-white`   | Primary headings, important labels       |
| `text-slate-200` | Body text, secondary headings          |
| `text-slate-400` | Descriptions, helper text              |
| `text-slate-500` | Timestamps, metadata, placeholders     |

Don't use `text-slate-100`, `text-slate-300`, or `text-slate-600`. Four levels is enough. More creates visual noise you can feel but can't name.

### Status

| State   | Color          | Example              |
|---------|----------------|----------------------|
| Success | `emerald-500`  | Online, completed    |
| Warning | `amber-500`    | Paused, attention    |
| Error   | `red-500`      | Failed, offline      |

Status colors follow Tailwind naming. Use them with low opacity backgrounds: `bg-emerald-500/10` with `text-emerald-400`.

### Borders

| Usage                | Value             |
|----------------------|-------------------|
| Default              | `border-white/5`  |
| Interactive/hover    | `border-white/10` |
| Active/focused       | `border-white/20` |
| Brand-highlighted    | `border-primary/30` |

Don't go above `border-white/20` for general UI. It starts looking like a wireframe.

### Opacity Scale

Use these and only these: `/5`, `/10`, `/20`, `/40`, `/60`

No `/15`, no `/25`, no `/35`. Five steps is plenty.

---

## Typography

**Font:** Inter (weights 400, 500, 600, 700)

Don't use weight 800. It's aggressive for this kind of product.

| Role           | Size       | Weight          | Extra            |
|----------------|------------|-----------------|------------------|
| Page title     | `text-3xl` | `font-bold`     | `tracking-tight` |
| Section head   | `text-xl`  | `font-semibold` | `tracking-tight` |
| Card title     | `text-lg`  | `font-semibold` | —                |
| Body           | `text-sm`  | `font-normal`   | —                |
| Label/caption  | `text-xs`  | `font-medium`   | `tracking-wide`  |

Everything uses the `font-display` class (which maps to Inter). Don't introduce other fonts.

---

## Buttons

### Primary (gradient) — hero actions only

```html
<button class="gradient-primary text-white font-semibold rounded-xl px-6 py-3
               shadow-lg shadow-black/20 hover:opacity-90 active:scale-[0.98]
               transition-all">
  Start Rendering
</button>
```

Use this for the single most important action on a page. One per view. The gradient makes it pop — that's the point. If two buttons on the same page are both gradient, neither one pops.

### Primary (solid) — standard actions

```html
<button class="bg-primary text-white font-medium rounded-xl px-4 py-2
               hover:bg-primary/90 active:scale-[0.98] transition-all">
  Save
</button>
```

For actions like "Save", "Submit", "Add". Important but not hero-level.

### Secondary — everything else

```html
<button class="bg-white/5 text-slate-400 border border-white/10 rounded-xl px-4 py-2
               hover:bg-white/10 hover:text-slate-200 transition-all">
  Cancel
</button>
```

### Danger

```html
<button class="bg-red-500/10 text-red-400 border border-red-500/20 rounded-xl px-4 py-2
               hover:bg-red-500/15 transition-all">
  Delete
</button>
```

### What not to do
- Don't put gradient on secondary or danger buttons
- Don't use colored shadows (`shadow-indigo-500/20`). Use `shadow-black/20`.
- Don't mix rounded values. Everything is `rounded-xl`.

---

## Shadows

Keep it simple. No colored glows.

| Level   | Class                      | Usage                         |
|---------|----------------------------|-------------------------------|
| Default | `shadow-md shadow-black/10` | Cards at rest                 |
| Raised  | `shadow-lg shadow-black/20` | Buttons, interactive cards    |
| Modal   | `shadow-2xl shadow-black/30`| Modals, overlays              |

The only exception: the Pro pricing card can have a subtle brand glow:
```
box-shadow: 0 0 20px rgba(99, 102, 241, 0.15);
```

That's it. One place.

---

## Icons

**Library:** Material Symbols Outlined (Google Fonts)
**Fill:** Always `FILL: 0` (outlined). No filled variants.
**Weight:** 400 (default)

### Sizes

| Size   | Class          | Usage                          |
|--------|----------------|--------------------------------|
| Small  | `text-[18px]`  | Inline with text, inside buttons|
| Medium | `text-[22px]`  | Navigation, card headers        |
| Large  | `text-[28px]`  | Empty states, feature cards     |

Pick one per context and stick with it. Don't eyeball icon sizes.

---

## Radius

`rounded-xl` for everything interactive (buttons, cards, inputs, modals).

Don't use `rounded-lg`, `rounded-2xl`, or `rounded-full` on containers. Status dots and avatars can be `rounded-full`. Everything else is `rounded-xl`.

---

## Spacing Principles

- Let things breathe. When in doubt, add more padding, not less.
- Cards get `p-5` or `p-6`. Not `p-3`, not `p-8`.
- Sections are separated by `space-y-6` or `gap-6`.
- Don't pack elements tight to "save space". White space is the design.

---

## Logo Usage

The logo exists in three forms:

| Form           | Usage                                  |
|----------------|----------------------------------------|
| Icon only      | Favicon, sidebar collapsed, loading    |
| Wordmark only  | Sidebar expanded, footer               |
| Full lockup    | Landing page hero, login page          |

The logo is the ONLY place the full gradient naturally lives. Treat it that way.

### Don'ts
- Don't put the logo on a gradient background
- Don't add glow/shadow to the logo
- Don't stretch or recolor it
- Don't place it smaller than 24px (icon) or 80px (full lockup)

---

## Quick Checklist

Before shipping a new page or component:

- [ ] Background uses only `bg-base`, `bg-surface`, or `bg-elevated`
- [ ] Text uses only `white`, `slate-200`, `slate-400`, or `slate-500`
- [ ] At most ONE gradient button per page
- [ ] All other buttons are solid `bg-primary` or `bg-white/5`
- [ ] Borders use only `white/5`, `white/10`, or `white/20`
- [ ] Icons are outlined, using one of the three standard sizes
- [ ] No colored shadows except on Pro card
- [ ] No new hex values — use existing tokens
- [ ] Radius is `rounded-xl` on interactive elements
- [ ] Opacity values are from the scale: `/5 /10 /20 /40 /60`

---

*Last updated: 2026-02-26*
