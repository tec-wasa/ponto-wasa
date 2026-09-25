import type { ReactNode } from "react";

/** Ícones em traço (24×24, stroke 2, currentColor), como no design system. */
function Svg({ children }: { children: ReactNode }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

export const IconHome = () => <Svg><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></Svg>;
export const IconList = () => <Svg><path d="M8 6h13M8 12h13M8 18h13" /><path d="M3 6h.01M3 12h.01M3 18h.01" /></Svg>;
export const IconPeople = () => <Svg><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" /><path d="M16 4.6a3.5 3.5 0 010 6.8M18 14.3c2 .8 3.5 2.6 3.5 5.7" /></Svg>;
export const IconBars = () => <Svg><path d="M5 21V11M12 21V4M19 21v-7" /></Svg>;
export const IconMore = () => <Svg><path d="M4 6h16M4 12h16M4 18h16" /></Svg>;
export const IconSun = () => <Svg><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></Svg>;
export const IconMoon = () => <Svg><path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" /></Svg>;
export const IconClock = () => <Svg><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Svg>;
