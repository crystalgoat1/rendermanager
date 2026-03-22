import type { JSX } from "preact";
import { useState, useRef, useCallback, useEffect } from "preact/hooks";
import { Icon } from "./Icon";
import { useInfoTooltip } from "./InfoTooltipContext";

// ─── Constants ───────────────────────────────────────────────────────────────

export const FORMATS = [
    { value: "PNG", label: "PNG" },
    { value: "JPEG", label: "JPEG" },
    { value: "OPEN_EXR", label: "OpenEXR" },
    { value: "OPEN_EXR_MULTILAYER", label: "OpenEXR Multilayer" },
    { value: "TIFF", label: "TIFF" },
    { value: "BMP", label: "BMP" },
] as const;

export const COLOR_DEPTHS = [
    { value: "8", label: "8-bit" },
    { value: "16", label: "16-bit" },
    { value: "32", label: "32-bit" },
] as const;

export const DENOISER_OPTIONS = [
    { value: "OPENIMAGEDENOISE", label: "OpenImageDenoise" },
    { value: "OPTIX", label: "OptiX" },
] as const;

export const DEVICE_OPTIONS = [
    { value: "CPU", label: "CPU" },
    { value: "GPU", label: "GPU" },
] as const;

export const EXR_CODEC_OPTIONS = [
    { value: "NONE", label: "None" },
    { value: "PXR24", label: "Pxr24 (lossy)" },
    { value: "ZIP", label: "ZIP (lossless)" },
    { value: "PIZ", label: "PIZ (lossless)" },
    { value: "RLE", label: "RLE (lossless)" },
    { value: "ZIPS", label: "ZIPS (lossless)" },
    { value: "B44", label: "B44 (lossy)" },
    { value: "B44A", label: "B44A (lossy)" },
    { value: "DWAA", label: "DWAA (lossy)" },
    { value: "DWAB", label: "DWAB (lossy)" },
] as const;

export const PIXEL_FILTER_OPTIONS = [
    { value: "BOX", label: "Box" },
    { value: "TENT", label: "Tent" },
    { value: "GAUSSIAN", label: "Gaussian" },
    { value: "MITCHELL", label: "Mitchell-Netravali" },
    { value: "CATMULLROM", label: "Catmull-Rom" },
    { value: "CUBIC", label: "Cubic" },
] as const;

export const DENOISING_PREFILTER_OPTIONS = [
    { value: "NONE", label: "None" },
    { value: "FAST", label: "Fast" },
    { value: "ACCURATE", label: "Accurate" },
] as const;

export const DENOISING_INPUT_OPTIONS = [
    { value: "RGB", label: "Color" },
    { value: "RGB_ALBEDO", label: "Color + Albedo" },
    { value: "RGB_ALBEDO_NORMAL", label: "Color + Albedo + Normal" },
] as const;

export const TEXTURE_LIMIT_OPTIONS = [
    { value: "OFF", label: "Off" },
    { value: "128", label: "128" },
    { value: "256", label: "256" },
    { value: "512", label: "512" },
    { value: "1024", label: "1024" },
    { value: "2048", label: "2048" },
    { value: "4096", label: "4096" },
    { value: "8192", label: "8192" },
] as const;

export const SHADOW_SIZE_OPTIONS = [
    { value: "64", label: "64" },
    { value: "128", label: "128" },
    { value: "256", label: "256" },
    { value: "512", label: "512" },
    { value: "1024", label: "1024" },
    { value: "2048", label: "2048" },
    { value: "4096", label: "4096" },
] as const;

export const VOLUMETRIC_TILE_OPTIONS = [
    { value: "2", label: "2px" },
    { value: "4", label: "4px" },
    { value: "8", label: "8px" },
    { value: "16", label: "16px" },
] as const;

export const MOTION_BLUR_POSITION_OPTIONS = [
    { value: "START", label: "Start on Frame" },
    { value: "CENTER", label: "Center on Frame" },
    { value: "END", label: "End on Frame" },
] as const;

// ─── Validation ─────────────────────────────────────────────────────────────

/** Validation rule for a numeric field. Mirrors agent_override.py ALLOWED_OVERRIDES. */
interface NumericRule {
    label: string;
    min: number;
    max: number;
    integer?: boolean;
}

/**
 * Validates a nullable numeric value against constraints.
 * Returns an error string or null if valid (null values are always valid — they mean "use default").
 */
function checkNum(value: number | null, rule: NumericRule): string | null {
    if (value === null) return null;
    if (rule.integer && !Number.isInteger(value)) return `${rule.label} must be a whole number`;
    if (value < rule.min || value > rule.max) return `${rule.label} must be between ${rule.min} and ${rule.max}`;
    return null;
}

/** Field validation rules — mirrors agent_override.py ALLOWED_OVERRIDES ranges. */
const FIELD_RULES: Record<string, NumericRule> = {
    resX:                  { label: "Width", min: 1, max: 16384, integer: true },
    resY:                  { label: "Height", min: 1, max: 16384, integer: true },
    resPct:                { label: "Scale %", min: 1, max: 100, integer: true },
    compression:           { label: "Compression", min: 0, max: 100, integer: true },
    frameStep:             { label: "Frame Step", min: 1, max: 100, integer: true },
    threads:               { label: "CPU Threads", min: 0, max: 64, integer: true },
    ditherIntensity:       { label: "Dithering", min: 0, max: 2 },
    pixelFilterWidth:      { label: "Filter Width", min: 0.01, max: 10 },
    motionBlurShutter:     { label: "Shutter", min: 0, max: 100 },
    cmExposure:            { label: "Exposure", min: -32, max: 32 },
    cmGamma:               { label: "Gamma", min: 0.001, max: 5 },
    simplifySubdivision:   { label: "Max Subdivision", min: 0, max: 6, integer: true },
    simplifyChildParticles:{ label: "Child Particles", min: 0, max: 1 },
    simplifyVolumes:       { label: "Volume Resolution", min: 0, max: 1 },
    cameraCullMargin:      { label: "Cull Margin", min: 0, max: 5 },
    samples:               { label: "Render Samples", min: 1, max: 100000, integer: true },
    adaptiveThreshold:     { label: "Noise Threshold", min: 0, max: 1 },
    adaptiveMinSamples:    { label: "Min Samples", min: 0, max: 65536, integer: true },
    maxBounces:            { label: "Total Max Bounces", min: 0, max: 1024, integer: true },
    diffuseBounces:        { label: "Diffuse Bounces", min: 0, max: 1024, integer: true },
    glossyBounces:         { label: "Glossy Bounces", min: 0, max: 1024, integer: true },
    transmissionBounces:   { label: "Transmission Bounces", min: 0, max: 1024, integer: true },
    volumeBounces:         { label: "Volume Bounces", min: 0, max: 1024, integer: true },
    transparentBounces:    { label: "Transparent Bounces", min: 0, max: 1024, integer: true },
    clampDirect:           { label: "Clamp Direct", min: 0, max: 1e10 },
    clampIndirect:         { label: "Clamp Indirect", min: 0, max: 1e10 },
    blurGlossy:            { label: "Filter Glossy", min: 0, max: 10 },
    filmTransparentRoughness: { label: "Roughness Threshold", min: 0, max: 1 },
    tileSize:              { label: "Tile Size", min: 8, max: 16384, integer: true },
    aoBounces:             { label: "AO Bounces", min: 0, max: 1024, integer: true },
    eeveeSamples:          { label: "EEVEE Samples", min: 1, max: 65536, integer: true },
    eeveeVolStart:         { label: "Volumetric Start", min: 0, max: 10000 },
    eeveeVolEnd:           { label: "Volumetric End", min: 0, max: 10000 },
    eeveeVolSamples:       { label: "Volumetric Samples", min: 1, max: 256, integer: true },
};

/**
 * Validate all numeric fields before submission.
 * Pass a Record of field-name → current-value pairs.
 * Returns the first validation error found, or null if all valid.
 */
export function validateNumericFields(fields: Record<string, number | null>): string | null {
    for (const [key, value] of Object.entries(fields)) {
        const rule = FIELD_RULES[key];
        if (!rule) continue;
        const err = checkNum(value, rule);
        if (err) return err;
    }
    return null;
}

/** Add " · default" suffix to the option matching blendDefault */
export function withDefaultMark<T extends { value: string; label: string }>(
    options: ReadonlyArray<T>,
    blendDefault: string | undefined,
): Array<{ value: string; label: string }> {
    return options.map(o => ({
        ...o,
        label: blendDefault && o.value === blendDefault ? `${o.label}  · default` : o.label,
    }));
}

const VT_FALLBACK = [
    { value: "Standard", label: "Standard" },
    { value: "Filmic", label: "Filmic" },
    { value: "AgX", label: "AgX" },
    { value: "Raw", label: "Raw" },
    { value: "False Color", label: "False Color" },
];
const LOOK_FALLBACK = [
    { value: "None", label: "None" },
    { value: "High Contrast", label: "High Contrast" },
    { value: "Medium High Contrast", label: "Medium High Contrast" },
    { value: "Medium Contrast", label: "Medium Contrast" },
    { value: "Medium Low Contrast", label: "Medium Low Contrast" },
    { value: "Low Contrast", label: "Low Contrast" },
    { value: "Very Low Contrast", label: "Very Low Contrast" },
];

/**
 * Build the options list for View Transform / Look selects.
 * Falls back to hardcoded list when the agent-reported options are missing
 * or only contain the "NONE" placeholder (happens when Blender's OCIO isn't
 * fully initialized in --background mode).
 */
export function getViewTransformOptions(
    available: string[] | undefined,
    blendDefault: string | undefined,
): Array<{ value: string; label: string }> {
    const usable = available?.filter(v => v !== "NONE");
    if (usable && usable.length > 0) {
        return withDefaultMark(usable.map(v => ({ value: v, label: v })), blendDefault);
    }
    return VT_FALLBACK;
}

export function getLookOptions(
    available: string[] | undefined,
    blendDefault: string | undefined,
): Array<{ value: string; label: string }> {
    const usable = available?.filter(v => v !== "NONE");
    if (usable && usable.length > 0) {
        return withDefaultMark(usable.map(v => ({ value: v, label: v })), blendDefault);
    }
    return LOOK_FALLBACK;
}

// ─── Field components ────────────────────────────────────────────────────────

// Global counter so each tooltip-enabled label gets a stable unique ID.
let _tooltipIdCounter = 0;

/**
 * Wraps label text to show a tooltip on hover (desktop, 500ms delay) or tap (mobile).
 * No icon — the label itself is the trigger, keeping the UI minimal like Blender.
 */
function LabelWithTooltip({ label, info }: { label: string; info: string }) {
    const idRef = useRef(`tt-${++_tooltipIdCounter}`);
    const id = idRef.current;
    const spanRef = useRef<HTMLSpanElement>(null);

    const { activeId, open, close } = useInfoTooltip();
    const show = activeId === id;

    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

    const clearTimer = useCallback(() => {
        if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    }, []);

    const [above, setAbove] = useState(true);

    const updatePos = useCallback(() => {
        if (!spanRef.current) return;
        const rect = spanRef.current.getBoundingClientRect();
        let left = rect.left;
        const tooltipWidth = 208; // w-52 = 13rem = 208px
        const tooltipHeight = 80; // approximate max height
        // Clamp so tooltip doesn't go offscreen right
        if (left + tooltipWidth > window.innerWidth - 8) {
            left = window.innerWidth - tooltipWidth - 8;
        }
        // Clamp so tooltip doesn't go offscreen left
        if (left < 8) left = 8;
        // If tooltip would go above viewport, show below instead
        const showAbove = rect.top - tooltipHeight - 8 > 0;
        setAbove(showAbove);
        setPos({
            top: showAbove ? rect.top - 8 : rect.bottom + 8,
            left,
        });
    }, []);

    // Desktop: hover with delay
    const handleEnter = useCallback(() => {
        clearTimer();
        timerRef.current = setTimeout(() => { updatePos(); open(id); }, 500);
    }, [id, open, clearTimer, updatePos]);

    const handleLeave = useCallback(() => {
        clearTimer();
        close(id);
    }, [id, close, clearTimer]);

    // Mobile: tap label text to toggle
    const handleClick = useCallback((e: Event) => {
        e.preventDefault();
        e.stopPropagation();
        clearTimer();
        if (show) { close(id); } else { updatePos(); open(id); }
    }, [id, show, open, close, clearTimer, updatePos]);

    useEffect(() => () => clearTimer(), [clearTimer]);

    return (
        <span
            ref={spanRef}
            className="relative cursor-default"
            onMouseEnter={handleEnter}
            onMouseLeave={handleLeave}
            onClick={handleClick}
        >
            {label}
            {show && pos && (
                <div
                    className="fixed z-50 px-3 py-2 bg-slate-800 border border-white/10 rounded-lg text-[11px] leading-relaxed text-slate-300 w-52 shadow-xl pointer-events-none whitespace-normal normal-case tracking-normal font-normal"
                    style={{ top: pos.top, left: pos.left, transform: above ? "translateY(-100%)" : "none" }}
                >
                    {info}
                </div>
            )}
        </span>
    );
}

export function FieldLabel({ label, note, info }: { label: string; note?: string; info?: string }) {
    return (
        <div className="mb-1.5">
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
                {info ? <LabelWithTooltip label={label} info={info} /> : label}
            </label>
            {note && <p className="text-[10px] text-slate-500 mt-0.5">{note}</p>}
        </div>
    );
}

export function SelectField({
    value,
    onChange,
    options,
    disabled = false,
}: {
    value: string;
    onChange: (v: string) => void;
    options: ReadonlyArray<{ value: string; label: string }>;
    disabled?: boolean;
}) {
    return (
        <div className="relative">
            <select
                className={`w-full appearance-none bg-bg-base border border-white/10 rounded-lg px-3 py-2.5 text-sm text-slate-200 focus:ring-2 focus:ring-primary/50 outline-none ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
                value={value}
                onChange={(e) => onChange((e.target as HTMLSelectElement).value)}
                disabled={disabled}
            >
                {options.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                ))}
            </select>
            <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-slate-500">
                <Icon name="unfold_more" className="text-base" />
            </div>
        </div>
    );
}

export function NumberField({
    value,
    onChange,
    min,
    max,
    step = 1,
    placeholder = "Blend default",
    disabled = false,
}: {
    value: number | null;
    onChange: (v: number | null) => void;
    min?: number;
    max?: number;
    step?: number | string;
    placeholder?: string;
    disabled?: boolean;
}) {
    const isInteger = step === 1 || step === "1";

    /** Parse and optionally clamp a raw string value */
    const parse = (raw: string, clamp: boolean): number | null => {
        if (raw === "" || raw === "-") return null;
        const n = isInteger ? parseInt(raw, 10) : parseFloat(raw);
        if (isNaN(n)) return null;
        if (!clamp) return n;
        let v = n;
        if (min !== undefined && v < min) v = min;
        if (max !== undefined && v > max) v = max;
        return isInteger ? Math.round(v) : v;
    };

    return (
        <input
            type="number"
            min={min}
            max={max}
            step={step}
            value={value ?? ""}
            placeholder={placeholder}
            disabled={disabled}
            className={`w-full bg-bg-base border border-white/10 rounded-lg px-3 py-2.5 text-sm text-slate-200 focus:ring-2 focus:ring-primary/50 outline-none placeholder:text-slate-500 ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
            onInput={(e) => {
                const raw = (e.target as HTMLInputElement).value;
                if (raw === "") { onChange(null); return; }
                const n = parse(raw, false);
                if (n !== null) onChange(n);
            }}
            onBlur={(e) => {
                // On blur: clamp to min/max and enforce integer
                const raw = (e.target as HTMLInputElement).value;
                if (raw === "") return;
                const clamped = parse(raw, true);
                if (clamped !== null && clamped !== value) {
                    onChange(clamped);
                }
                // Force the input to show the sanitized value
                if (clamped !== null) {
                    (e.target as HTMLInputElement).value = String(clamped);
                }
            }}
            onKeyDown={(e) => {
                // Block decimal point for integer fields
                if (isInteger && ((e as KeyboardEvent).key === "." || (e as KeyboardEvent).key === ",")) {
                    e.preventDefault();
                }
            }}
        />
    );
}

export function ToggleField({
    label,
    value,
    onChange,
    blendDefault,
    disabled = false,
    info,
}: {
    label: string;
    value: boolean;
    onChange: (v: boolean) => void;
    blendDefault?: boolean;
    disabled?: boolean;
    info?: string;
}) {
    const states = [
        { val: true, label: "On" },
        { val: false, label: "Off" },
    ] as const;

    return (
        <div>
            <FieldLabel label={label} info={info} />
            <div className="flex gap-1 bg-bg-base border border-white/10 rounded-lg p-1">
                {states.map((s) => (
                    <button
                        key={String(s.val)}
                        type="button"
                        disabled={disabled}
                        onClick={() => { if (!disabled) onChange(s.val); }}
                        className={`flex-1 py-1.5 text-xs font-semibold rounded-md transition-all ${value === s.val
                            ? "bg-white/10 text-white"
                            : "text-slate-500 hover:text-slate-200"
                            } ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
                    >
                        {s.label}{blendDefault !== undefined && s.val === blendDefault ? "  · default" : ""}
                    </button>
                ))}
            </div>
        </div>
    );
}

export function EngineToggle({
    value,
    onChange,
    disabled = false,
}: {
    value: string;
    onChange: (v: string) => void;
    disabled?: boolean;
}) {
    const engines = [
        { value: "CYCLES", label: "Cycles" },
        { value: "BLENDER_EEVEE", label: "Eevee" },
    ];

    return (
        <div>
            <FieldLabel label="Render Engine" info="Cycles is a ray-trace engine for photorealism. Eevee is a rasterize engine for speed" />
            <div className="flex bg-bg-base border border-white/10 rounded-lg p-1 gap-1">
                {engines.map((eng) => (
                    <button
                        key={eng.value}
                        type="button"
                        disabled={disabled}
                        onClick={() => { if (!disabled) onChange(eng.value); }}
                        className={`flex-1 py-2.5 text-sm font-semibold rounded-md transition-all ${value === eng.value
                            ? "bg-white/10 text-white shadow-sm"
                            : "text-slate-500 hover:text-slate-200"
                            } ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
                    >
                        {eng.label}
                    </button>
                ))}
            </div>
        </div>
    );
}

export function CollapsibleGroup({
    title,
    defaultOpen = false,
    children,
    variant = "default",
}: {
    title: string;
    defaultOpen?: boolean;
    children: any;
    variant?: "default" | "warning";
}) {
    const [isOpen, setIsOpen] = useState(defaultOpen);
    const borderColor = variant === "warning" ? "border-amber-500/30" : "border-white/10";
    const headerAccent = variant === "warning" ? "text-amber-400" : "text-slate-300";

    return (
        <div className={`rounded-xl border ${borderColor} overflow-hidden bg-black/20`}>
            <button
                type="button"
                onClick={() => setIsOpen(!isOpen)}
                className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-white/[0.03] transition-colors outline-none focus:bg-white/[0.03]"
            >
                <span className={`text-xs font-bold uppercase tracking-widest ${headerAccent}`}>{title}</span>
                <Icon name={isOpen ? "expand_less" : "expand_more"} className="text-lg text-slate-500" />
            </button>
            {isOpen && (
                <div className="border-t border-white/5 px-4 pt-5 pb-4 space-y-4">
                    {children}
                </div>
            )}
        </div>
    );
}

export function PassSelectionList({
    allPasses,
    defaultActivePasses,
    selectedPasses,
    onChange,
    disabled = false,
}: {
    allPasses: string[];
    defaultActivePasses: string[];
    selectedPasses: string[] | null;
    onChange: (v: string[] | null) => void;
    disabled?: boolean;
}) {
    const [isOpen, setIsOpen] = useState(false);

    if (allPasses.length === 0) {
        return null; // Will not render if no passes are available
    }

    const formatName = (p: string) => {
        let name = p.replace("use_pass_", "");
        if (name === "z") return "Z / Depth";
        if (name === "ambient_occlusion") return "Ambient Occlusion";
        if (name === "cryptomatte_object") return "Crypto Object";
        if (name === "cryptomatte_material") return "Crypto Material";
        if (name === "cryptomatte_asset") return "Crypto Asset";
        return name.split("_").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
    };

    const hasOverride = selectedPasses !== null;
    const currentPasses = selectedPasses !== null ? selectedPasses : defaultActivePasses;

    return (
        <div className="bg-black/20 rounded-xl border border-white/5 overflow-hidden">
            <button
                type="button"
                onClick={() => setIsOpen(!isOpen)}
                className={`w-full flex flex-col px-4 py-3 text-left hover:bg-white/[0.02] transition-colors outline-none focus:bg-white/[0.02] ${disabled ? "opacity-75" : ""}`}
            >
                <div className="w-full flex items-center justify-between">
                    <span className="flex items-center gap-2">
                        <span className="text-xs font-bold uppercase tracking-widest text-slate-300">Render Passes</span>
                        {hasOverride && <span className="w-1.5 h-1.5 rounded-full bg-primary" title="Overridden" />}
                    </span>
                    <div className="flex items-center gap-3">
                        <span className="text-[10px] text-slate-500 font-mono bg-white/5 px-2 py-0.5 rounded border border-white/5">{currentPasses.length} Active</span>
                        <Icon name={isOpen ? "expand_less" : "expand_more"} className="text-lg text-slate-500 shrink-0" />
                    </div>
                </div>
            </button>
            {isOpen && (
                <div className="border-t border-white/5 bg-black/10">
                    <div className="p-2 flex justify-end bg-black/20 border-b border-white/5">
                        <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); onChange(null); }}
                            disabled={!hasOverride || disabled}
                            className={`text-[10px] px-3 py-1.5 rounded-lg border transition-all ${hasOverride ? "text-primary border-primary/30 hover:bg-primary/10 focus:ring-2 focus:ring-primary/50" : "text-slate-600 border-white/5 cursor-not-allowed"}`}
                        >
                            Reset to File Defaults
                        </button>
                    </div>
                    <div className="flex flex-col max-h-64 overflow-y-auto custom-scrollbar p-2 gap-0.5">
                        {allPasses.map(p => {
                            const isSelected = currentPasses.includes(p);
                            const isDefault = defaultActivePasses.includes(p);
                            return (
                                <button
                                    key={p}
                                    type="button"
                                    disabled={disabled}
                                    onClick={() => {
                                        if (disabled) return;
                                        let next = [...currentPasses];
                                        if (isSelected) {
                                            next = next.filter(x => x !== p);
                                        } else {
                                            next.push(p);
                                        }
                                        onChange(next);
                                    }}
                                    className={`flex items-center justify-between px-3 py-2.5 rounded-lg text-sm text-left transition-colors outline-none focus:ring-2 focus:ring-primary/50 hover:bg-white/5 ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
                                >
                                    <div className="flex items-center gap-3">
                                        <div className={`w-4 h-4 rounded flex-shrink-0 border flex items-center justify-center transition-colors ${
                                            isSelected ? "bg-primary border-primary text-bg-base" : "border-slate-600 bg-black/40"
                                        }`}>
                                            {isSelected && <Icon name="check" className="text-[10px] font-bold" />}
                                        </div>
                                        <span className={isSelected ? "text-slate-200" : "text-slate-400"}>{formatName(p)}</span>
                                    </div>
                                    {isDefault && <span className="text-[9px] uppercase tracking-wider text-slate-500 bg-white/5 px-1.5 py-0.5 rounded border border-white/5">Default</span>}
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}
