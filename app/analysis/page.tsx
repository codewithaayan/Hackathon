"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { MapPin, ArrowRight, Thermometer, Droplets, Trees } from "lucide-react";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";
import { DataNotice } from "@/components/ui/DataNotice";
import { errorMessage, getAreas, getCities, getRisk } from "@/lib/api";
import type { Area } from "@/types/area";
import type { RiskResponse } from "@/types/risk";

export default function IntelligenceOverviewPage() {
  const [areas, setAreas] = useState<Area[]>([]);
  const [risks, setRisks] = useState<Record<string, RiskResponse>>({});
  const [cityNames, setCityNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [riskUnavailable, setRiskUnavailable] = useState(false);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const cities = await getCities();
        if (!active) return;
        setCityNames(Object.fromEntries(cities.map((city) => [city.id, city.name])));
        const areaLists = await Promise.all(cities.map((city) => getAreas(city.id)));
        const loadedAreas = areaLists.flat();
        if (!active) return;
        setAreas(loadedAreas);
        const results = await Promise.allSettled(loadedAreas.map((area) => getRisk(area.id)));
        if (!active) return;
        const available: Record<string, RiskResponse> = {};
        results.forEach((result, index) => {
          if (result.status === "fulfilled") available[loadedAreas[index].id] = result.value;
        });
        setRisks(available);
        setRiskUnavailable(results.some((result) => result.status === "rejected"));
      } catch (reason) {
        if (active) setError(errorMessage(reason));
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => { active = false; };
  }, []);

  return (
    <div className="min-h-screen bg-[#030712] text-slate-100 flex flex-col">
      <Navbar />

      <main className="mx-auto w-full max-w-7xl flex-1 space-y-8 px-4 pb-20 pt-24 sm:px-6 lg:px-8">
        <div className="border-b border-slate-800 pb-5">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono font-bold tracking-widest text-cyan-400">
              PLANETARY AI INTELLIGENCE
            </span>
          </div>
          <h1 className="mt-2 text-3xl sm:text-4xl font-extrabold tracking-tight text-white">
            Spatial AI Risk Intelligence
          </h1>
          <p className="mt-2 text-sm text-slate-400 max-w-3xl">
            Select an available area and review its supplied risk fields. AI analysis remains pending until the owner-defined schemas and adapter are connected.
          </p>
        </div>

        {loading && <DataNotice title="Loading areas" message="Requesting available city and area records." />}
        {error && <DataNotice title="Data unavailable" message={error} error />}
        {!loading && !error && areas.length === 0 && <DataNotice title="No areas available" message="The connected database has no area records to analyze." />}
        {riskUnavailable && <DataNotice title="Risk data unavailable" message="One or more areas do not yet have a connected risk component or required inputs. Missing scores remain blank." />}

        {/* Areas Selection Grid */}
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {areas.map((area) => {
            const risk = risks[area.id];
            return (
              <div
                key={area.id}
                className="group relative flex flex-col justify-between rounded-2xl border border-slate-800 bg-[#040817]/80 p-6 glass-panel transition-all hover:border-cyan-500/40 hover:shadow-[0_0_25px_rgba(6,182,212,0.12)]"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono text-slate-400 flex items-center gap-1.5">
                      <MapPin className="h-3.5 w-3.5 text-cyan-400" />
                      {cityNames[area.cityId] ?? "City unavailable"}
                    </span>
                    <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/30">
                      SCORE {risk?.scores.overall ?? "—"}
                    </span>
                  </div>

                  <h3 className="mt-3 text-xl font-bold text-white group-hover:text-cyan-300 transition-colors">
                    {area.name}
                  </h3>

                  <p className="mt-2 text-xs text-slate-400 leading-relaxed">
                    Opens the area workspace when the owner-defined AI contract is connected.
                  </p>

                  <div className="mt-5 grid grid-cols-3 gap-2 border-t border-slate-800/80 pt-4 text-center font-mono">
                    <div className="rounded-lg bg-slate-950/60 p-2 border border-slate-800/60">
                      <Thermometer className="h-3.5 w-3.5 text-red-400 mx-auto" />
                      <span className="text-[10px] text-slate-500 block mt-1">HEAT</span>
                      <span className="text-xs font-bold text-white">{risk?.scores.heat ?? "—"}</span>
                    </div>
                    <div className="rounded-lg bg-slate-950/60 p-2 border border-slate-800/60">
                      <Trees className="h-3.5 w-3.5 text-emerald-400 mx-auto" />
                      <span className="text-[10px] text-slate-500 block mt-1">CANOPY</span>
                      <span className="text-xs font-bold text-white">{risk?.scores.green ?? "—"}</span>
                    </div>
                    <div className="rounded-lg bg-slate-950/60 p-2 border border-slate-800/60">
                      <Droplets className="h-3.5 w-3.5 text-blue-400 mx-auto" />
                      <span className="text-[10px] text-slate-500 block mt-1">FLOOD</span>
                      <span className="text-xs font-bold text-white">{risk?.scores.flood ?? "—"}</span>
                    </div>
                  </div>
                </div>

                <div className="mt-6 pt-3 border-t border-slate-900">
                  <Link
                    href={`/analysis/${area.id}`}
                    className="flex w-full items-center justify-center gap-2 rounded-xl border border-cyan-500/40 bg-cyan-500/10 px-4 py-2.5 text-xs font-semibold text-cyan-300 group-hover:bg-cyan-500 group-hover:text-slate-950 transition-all"
                  >
                    <span>Launch AI Diagnostic</span>
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      </main>

      <Footer />
    </div>
  );
}
