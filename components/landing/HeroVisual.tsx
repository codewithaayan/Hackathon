"use client";

import { useEffect, useState } from "react";
import { Activity, CloudRain, Flame, Trees, Users, Wind } from "lucide-react";
import { errorMessage, getAreas, getCities, getRisk } from "@/lib/api";
import type { Area, City } from "@/types/area";
import type { RiskResponse } from "@/types/risk";

const METRICS = [
  { key: "heat", label: "Heat", icon: Flame, color: "text-red-400" },
  { key: "air", label: "Air", icon: Wind, color: "text-cyan-300" },
  { key: "flood", label: "Flood", icon: CloudRain, color: "text-blue-400" },
  { key: "green", label: "Green", icon: Trees, color: "text-emerald-400" },
  { key: "populationExposure", label: "Exposure", icon: Users, color: "text-amber-400" },
] as const;

export function HeroVisual() {
  const [cities, setCities] = useState<City[]>([]);
  const [cityId, setCityId] = useState("");
  const [area, setArea] = useState<Area | null>(null);
  const [risk, setRisk] = useState<RiskResponse | null>(null);
  const [message, setMessage] = useState("Loading cities…");

  useEffect(() => {
    let active = true;
    getCities()
      .then((items) => {
        if (!active) return;
        setCities(items);
        setCityId(items[0]?.id ?? "");
        setMessage(items.length ? "Loading area data…" : "No cities are available.");
      })
      .catch((reason) => {
        if (!active) return;
        setMessage(errorMessage(reason));
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!cityId) return;
    let active = true;

    getAreas(cityId)
      .then(async (areas) => {
        if (!active) return;
        const targetArea = areas[0];
        if (!targetArea) {
          setArea(null);
          setRisk(null);
          setMessage("This city has no areas yet.");
          return;
        }
        setArea(targetArea);
        try {
          const result = await getRisk(targetArea.id);
          if (active) {
            setRisk(result);
            setMessage("");
          }
        } catch (reason) {
          if (active) {
            setRisk(null);
            setMessage(errorMessage(reason));
          }
        }
      })
      .catch((reason) => {
        if (!active) return;
        setArea(null);
        setRisk(null);
        setMessage(errorMessage(reason));
      });

    return () => {
      active = false;
    };
  }, [cityId]);

  return (
    <div className="relative mx-auto aspect-square w-full max-w-lg overflow-hidden rounded-2xl border border-cyan-500/25 p-6 glass-panel shadow-[0_0_50px_rgba(6,182,212,0.15)]">
      <div className="absolute inset-0 bg-grid-pattern opacity-40 pointer-events-none" />

      {/* City Switcher */}
      <div className="relative z-10 flex justify-center">
        <select
          value={cityId}
          onChange={(event) => {
            setCityId(event.target.value);
            setArea(null);
            setRisk(null);
            setMessage("Loading area data…");
          }}
          className="rounded-full border border-cyan-500/30 bg-slate-950/90 px-4 py-1.5 text-[11px] font-mono text-cyan-200 focus:outline-none focus:ring-1 focus:ring-cyan-400"
        >
          <option value="">Select a city</option>
          {cities.map((city) => (
            <option key={city.id} value={city.id}>
              {city.name}, {city.country}
            </option>
          ))}
        </select>
      </div>

      {/* Central Radar Circle */}
      <div className="absolute left-0 right-0 top-[32%] z-20 flex -translate-y-1/2 justify-center px-4 pointer-events-none">
          <div className="relative mx-auto flex h-20 w-20 sm:h-24 sm:w-24 items-center justify-center rounded-full border border-cyan-400/40 bg-slate-950/90 shadow-[0_0_25px_rgba(6,182,212,0.25)]">
            <Activity className="h-7 w-7 sm:h-8 sm:w-8 text-cyan-300" />
            <span className="absolute -top-1 -right-1 flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-3 w-3 bg-cyan-500" />
            </span>
          </div>
          <p className="mt-3 text-[10px] font-mono uppercase tracking-[0.2em] text-cyan-300/80">
            Resilience Risk Index
          </p>
          <p className="text-3xl font-bold font-mono text-white">
            {risk?.scores.overall ?? "—"}
          </p>
          <p className="mt-1 max-w-48 text-[11px] font-mono text-cyan-400 font-medium truncate mx-auto">
            {area?.name ?? message}
          </p>
        </div>

      {/* Environmental Metrics Grid */}
      <div className="absolute bottom-0 left-3 right-3 z-10 grid grid-cols-3 gap-1.5 sm:bottom-1 sm:left-6 sm:right-6 sm:grid-cols-5 sm:gap-2">
        {METRICS.map(({ key, label, icon: Icon, color }) => (
          <div
            key={key}
            className="rounded-xl border border-slate-800/90 bg-slate-950/85 p-1.5 sm:p-2 text-center backdrop-blur-md"
          >
            <Icon className={`mx-auto h-3 w-3 sm:h-3.5 sm:w-3.5 ${color}`} />
            <p className="mt-0.5 text-[8px] sm:mt-1 sm:text-[9px] text-slate-400 font-mono uppercase">
              {label}
            </p>
            <p className={`text-[11px] sm:text-xs font-bold font-mono ${color}`}>
              {risk?.scores[key] ?? "—"}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
