import { APP_DISPLAY_NAME } from "../brand";

const sizes = {
  sm:  { icon: "h-6",  full: "h-6"  },
  md:  { icon: "h-8",  full: "h-8"  },
  lg:  { icon: "h-10", full: "h-10" },
  xl:  { icon: "h-14", full: "h-14" },
} as const;

type LogoSize = keyof typeof sizes;

interface LogoProps {
  size?: LogoSize;
  /** Hide the wordmark and show only the icon */
  iconOnly?: boolean;
  className?: string;
}

export function Logo({ size = "md", iconOnly = false, className = "" }: LogoProps) {
  const s = sizes[size];
  const imgClass = iconOnly ? s.icon : s.full;
  return (
    <div className={`flex items-center ${className}`}>
      <img 
        src={iconOnly ? "/logo-icon.png" : "/logo_full.png"} 
        className={`${imgClass} w-auto object-contain shrink-0`} 
        alt={APP_DISPLAY_NAME} 
      />
    </div>
  );
}
