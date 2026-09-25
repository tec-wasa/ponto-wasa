import { useEffect, useState } from "react";
import { greeting } from "./sequence";

function localHour(tz?: string): number {
  const h = Number(new Intl.DateTimeFormat("pt-BR", { timeZone: tz, hour: "numeric", hourCycle: "h23" }).format(new Date()));
  return Number.isFinite(h) ? h : new Date().getHours();
}

/** "Bom dia, Ana": pelo horário da empresa, atualizada a cada minuto. */
export function Greeting({ name, tz }: { name: string; tz?: string }) {
  const [hour, setHour] = useState(() => localHour(tz));
  useEffect(() => {
    const t = setInterval(() => setHour(localHour(tz)), 60_000);
    return () => clearInterval(t);
  }, [tz]);
  return <p className="greeting">{greeting(hour)}, {name.trim().split(/\s+/)[0]}</p>;
}
