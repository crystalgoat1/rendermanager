interface IconProps {
  name: string;
  fill?: boolean;
  className?: string;
}

/** Thin wrapper around Material Symbols Outlined.
 *  Set fill={true} for the solid (filled) variant. */
export function Icon({ name, fill = false, className = "" }: IconProps) {
  return (
    <span
      className={`material-symbols-outlined ${className}`}
      style={fill ? { fontVariationSettings: "'FILL' 1" } : undefined}
    >
      {name}
    </span>
  );
}
