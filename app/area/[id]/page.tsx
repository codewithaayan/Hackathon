"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  Activity,
  Sparkles,
  Layers,
  Globe,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  Grid3x3,
} from "lucide-react";
import { DashboardHeader } from "@/components/dashboard/DashboardHeader";
import { PopulationCard } from "@/components/dashboard/PopulationCard";
import { RiskCard } from "@/components/dashboard/RiskCard";
import { ScoreCard } from "@/components/dashboard/ScoreCard";
import { Footer } from "@/components/layout/Footer";
import { Navbar } from "@/components/layout/Navbar";
import { UrbanMap } from "@/components/map/UrbanMap";
import { DataNotice } from "@/components/ui/DataNotice";
import { errorMessage, getArea, getCities, getLayer, getPopulation, getRisk } from "@/lib/api";
import type { Area, City } from "@/types/area";
import type { MapLayer, PopulationResponse, RiskResponse } from "@/types/risk";

export default function AreaPage() {
  const id = String(useParams<{ id: string }>().id);
  const [area, setArea] = useState<Area | null>(null);
  const [city, setCity] = useState<City>();
  const [risk, setRisk] = useState<RiskResponse | null>(null);
  const [population, setPopulation] = useState<PopulationResponse | null>(null);
  const [layer, setLayer] = useState<MapLayer | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [secondaryErrors, setSecondaryErrors] = useState<string[]>([]);
  const [gridMinimized, setGridMinimized] = useState(false);
  const [activeLayer, setActiveLayer] = useState<"heat" | "green" | "flood">("heat");

  useEffect(() => {
    let active = true;

    Promise.allSettled([
      getArea(id),
      getCities(),
      getRisk(id),
      getPopulation(id),
      getLayer(id, activeLayer),
    ]).then((results) => {
      if (!active) return;
      const [areaResult, citiesResult, riskResult, populationResult, layerResult] = results;
      setLoading(false);

      if (areaResult.status === "rejected") {
        setArea(null);
        setError(errorMessage(areaResult.reason));
        return;
      }
      setArea(areaResult.value);
      setError(null);

      if (citiesResult.status === "fulfilled") {
        setCity(
          citiesResult.value.find(
            (item) => item.id === areaResult.value.cityId
          )
        );
      }

      if (riskResult.status === "fulfilled") {
        setRisk(riskResult.value);
      } else {
        setRisk(null);
      }

      if (populationResult.status === "fulfilled") {
        setPopulation(populationResult.value);
      } else {
        setPopulation(null);
      }

      if (layerResult.status === "fulfilled") {
        setLayer(layerResult.value);
      } else {
        setLayer(null);
      }

      const unavailable = [citiesResult, riskResult, populationResult, layerResult]
        .filter((result) => result.status === "rejected")
        .map((result) => errorMessage((result as PromiseRejectedResult).reason));
      setSecondaryErrors([...new Set(unavailable)]);
    });

    return () => {
      active = false;
    };
  }, [id, activeLayer]);

  if (loading && !area) {
    return (
      <div className="min-h-screen bg-[#030712] text-slate-100 flex flex-col">
        <Navbar />
        <main className="mx-auto max-w-4xl px-4 pt-28">
          <DataNotice title="Loading area" message="Requesting area data and geospatial datasets…" />
        </main>
      </div>
    );
  }

  if (!area) {
    return (
      <div className="min-h-screen bg-[#030712] text-slate-100 flex flex-col">
        <Navbar />
        <main className="mx-auto max-w-4xl px-4 pt-28">
          <DataNotice
            title="Area unavailable"
            message={error ?? "Could not load this area. Please try again."}
            error
          />
        </main>
      </div>
    );
  }

  const scores = risk?.scores;

  const layerMeta: Record<string, { label: string; color: string; border: string }> = {
    heat:  { label: "Thermal",    color: "text-red-300",    border: "border-red-500/40 bg-red-500/10" },
    green: { label: "Vegetation", color: "text-emerald-300", border: "border-emerald-500/40 bg-emerald-500/10" },
    flood: { label: "Flood Risk", color: "text-blue-300",    border: "border-blue-500/40 bg-blue-500/10" },
  };

  return (
    <div className="min-h-screen bg-[#030712] text-slate-100 flex flex-col">
      <Navbar />

      <main className="mx-auto w-full max-w-7xl flex-1 space-y-8 px-4 pb-20 pt-24 sm:px-6 lg:px-8">
        <DashboardHeader area={area} city={city} />

        {secondaryErrors.map((message) => (
          <DataNotice key={message} title="Some data is unavailable" message={message} error />
        ))}

        {/* Quick Action Navigation Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-cyan-500/25 bg-cyan-950/20 p-4 font-mono text-xs">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-cyan-400 animate-ping" />
            <span className="text-cyan-300 font-semibold">
              Active Municipal Profile: {area.name}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/simulate/${area.id}`}
              className="flex items-center gap-1.5 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3.5 py-2 text-emerald-300 hover:bg-emerald-500/20 transition-all font-semibold"
            >
              <Layers className="h-3.5 w-3.5" />
              <span>Intervention Simulator</span>
              <ArrowRight className="h-3 w-3" />
            </Link>

            <Link
              href={`/analysis/${area.id}`}
              className="flex items-center gap-1.5 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3.5 py-2 text-amber-300 hover:bg-amber-500/20 transition-all font-semibold"
            >
              <Sparkles className="h-3.5 w-3.5" />
              <span>Spatial AI Diagnostic</span>
              <ArrowRight className="h-3 w-3" />
            </Link>

            <Link
              href="/explore"
              className="flex items-center gap-1.5 rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2 text-slate-300 hover:bg-slate-800 transition-all"
            >
              <Globe className="h-3.5 w-3.5 text-cyan-400" />
              <span>Full GIS Map</span>
            </Link>
          </div>
        </div>

        <ScoreCard risk={risk} />

        {/* Risk Indicators */}
        <section className="space-y-4">
          <h3 className="flex items-center gap-2 text-base font-bold text-white">
            <Activity className="h-4 w-4 text-cyan-400" />
            Environmental risk indicators
          </h3>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            <RiskCard title="Heat"               score={scores?.heat              ?? null} iconType="heat" />
            <RiskCard title="Air"                score={scores?.air               ?? null} iconType="air" />
            <RiskCard title="Flood"              score={scores?.flood             ?? null} iconType="flood" />
            <RiskCard title="Green"              score={scores?.green             ?? null} iconType="green" />
            <RiskCard title="Mobility"           score={scores?.mobility          ?? null} iconType="mobility" />
            <RiskCard title="Population exposure" score={scores?.populationExposure ?? null} iconType="population" />
          </div>
        </section>

        {/* Interactive Spatial Map with Minimizable Grid */}
        <section className="space-y-0 rounded-2xl border border-slate-700/60 bg-slate-900/50 overflow-hidden">
          {/* Map Header / Controls Bar */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-700/60 px-4 py-3">
            <div className="flex items-center gap-2">
              <Globe className="h-4 w-4 text-cyan-400" />
              <h3 className="text-sm font-bold text-white font-mono">
                Spatial Microclimate Grid
              </h3>
              <span className="rounded-full border border-cyan-500/30 bg-cyan-950/40 px-2 py-0.5 text-[10px] font-mono text-cyan-400">
                supplied geometry
              </span>
            </div>

            <div className="flex items-center gap-2">
              {/* Layer switcher */}
              {(["heat", "green", "flood"] as const).map((l) => (
                <button
                  key={l}
                  onClick={() => setActiveLayer(l)}
                  className={`rounded-lg border px-2.5 py-1 text-[11px] font-mono font-semibold capitalize transition-all ${
                    activeLayer === l
                      ? layerMeta[l].border + " " + layerMeta[l].color
                      : "border-slate-700 bg-slate-800/60 text-slate-400 hover:border-slate-600 hover:text-slate-200"
                  }`}
                >
                  {layerMeta[l].label}
                </button>
              ))}

              {/* Minimize / Expand toggle */}
              <button
                onClick={() => setGridMinimized((v) => !v)}
                title={gridMinimized ? "Expand map" : "Minimize map"}
                className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/60 px-2.5 py-1.5 text-[11px] font-mono text-slate-300 hover:border-slate-500 hover:text-white transition-all"
              >
                <Grid3x3 className="h-3 w-3" />
                {gridMinimized ? (
                  <>
                    <span>Expand</span>
                    <ChevronDown className="h-3 w-3" />
                  </>
                ) : (
                  <>
                    <span>Minimize</span>
                    <ChevronUp className="h-3 w-3" />
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Map canvas — collapses smoothly */}
          <div
            className="transition-all duration-500 overflow-hidden"
            style={{ maxHeight: gridMinimized ? 0 : 520 }}
          >
            <UrbanMap
              activeLayer={activeLayer}
              selectedArea={area}
              layer={layer}
              heightClassName="h-[520px]"
            />
          </div>

          {/* Minimized summary strip */}
          {gridMinimized && (
            <div className="flex items-center gap-4 px-4 py-3 font-mono text-xs text-slate-400">
              <span className="h-2 w-2 rounded-full bg-slate-600" />
              <span>Grid collapsed — click <strong className="text-slate-200">Expand</strong> to view the spatial layer</span>
              <span className="ml-auto text-slate-500">{area.name} · {layerMeta[activeLayer].label} layer</span>
            </div>
          )}
        </section>

        <PopulationCard area={area} population={population} risk={risk} />
      </main>

      <Footer />
    </div>
  );
}
