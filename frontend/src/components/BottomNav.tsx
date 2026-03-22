import { Link, useLocation } from "wouter";
import { Icon } from "./Icon";

const TABS = [
  { href: "/dashboard", icon: "dashboard", label: "Dashboard" },
  { href: "/new", icon: "add_box", label: "New Job" },
  { href: "/history", icon: "history", label: "History" },
  { href: "/settings", icon: "settings", label: "Settings" },
] as const;

export function BottomNav() {
  const [location] = useLocation();

  return (
    <nav className="fixed bottom-0 left-0 right-0 max-w-[430px] mx-auto z-50">
      <div className="bg-bg-base/95 backdrop-blur-lg border-t border-white/5 px-2 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 flex items-center justify-around">
        {TABS.map(({ href, icon, label }) => {
          const active = location === href || location.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`flex flex-col items-center gap-1 flex-1 transition-colors ${active ? "text-primary" : "text-slate-500 hover:text-slate-200"
                }`}
            >
              <Icon name={icon} fill={active} className="text-[28px]" />
              <span className="text-[10px] font-bold uppercase tracking-widest">
                {label}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
