"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import {
  MapPin,
  Search,
  Grid,
  Maximize2,
  Minimize2,
  Sparkles,
  Layers,
} from "lucide-react";
import Link from "next/link";
import { Footer } from "@/components/layout/Footer";
import { Navbar } from "@/components/layout/Navbar";
import { AreaPopup } from "@/components/map/AreaPopup";
import { LayerControls } from "@/components/map/LayerControls";
import { UrbanMap } from "@/components/map/UrbanMap";
import { RiskLegend } from "@/components/map/RiskLegend";
import { DataNotice } from "@/components/ui/DataNotice";
import { errorMessage, getAreas, getCities, getLayer, getRisk } from "@/lib/api";
import type { Area, City } from "@/types/area";
import type { LayerName, MapLayer, RiskResponse } from "@/types/risk";
import { cn } from "@/lib/utils";

export default function ExplorePage() {
  const [cities, setCities] = useState<City[]>([]);
  const [cityId, setCityId] = useState("");
  const [areas, setAreas] = useState<Area[]>([]);
  const [areaId, setAreaId] = useState("");
  const [risk, setRisk] = useState<RiskResponse | null>(null);
  const [layer, setLayer] = useState<MapLayer | null>(null);
  const [activeLayer, setActiveLayer] = useState<LayerName>("heat");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [layerLoading, setLayerLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [riskError, setRiskError] = useState<string | null>(null);
  const [layerError, setLayerError] = useState<string | null>(null);
  const [gridMinimized, setGridMinimized] = useState(false);

  // Load only records supplied by the backend. Empty and unavailable states stay visible.
  const loadData = useCallback(() => {
    let active = true;
    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        const items = await getCities();
        if (!active) return;
        setCities(items);
        setCityId(items[0]?.id ?? "");
        if (items.length === 0) setLoading(false);
      } catch (reason) {
        if (!active) return;
        setCities([]);
        setCityId("");
        setError(errorMessage(reason));
        setLoading(false);
      }
    }
    fetchData();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const cleanup = loadData();
    return cleanup;
  }, [loadData]);

  // Load areas when cityId changes
  useEffect(() => {
    if (!cityId) return;
    let active = true;

    async function fetchAreas() {
      try {
        const items = await getAreas(cityId);
        if (!active) return;
        setAreas(items);
        setAreaId(items[0]?.id ?? "");
      } catch (reason) {
        if (!active) return;
        setAreas([]);
        setAreaId("");
        setError(errorMessage(reason));
      } finally {
        if (active) setLoading(false);
      }
    }

    fetchAreas();
    return () => {
      active = false;
    };
  }, [cityId]);

  // Load risk and layer when areaId or activeLayer changes
  useEffect(() => {
    if (!areaId) return;
    let active = true;

    async function fetchLayerAndRisk() {
      setLayerLoading(true);
      try {
        const [riskResult, layerResult] = await Promise.allSettled([
          getRisk(areaId),
          getLayer(areaId, activeLayer),
        ]);
        if (!active) return;
        if (riskResult.status === "fulfilled") {
          setRisk(riskResult.value);
          setRiskError(null);
        } else {
          setRisk(null);
          setRiskError(errorMessage(riskResult.reason));
        }

        if (layerResult.status === "fulfilled") {
          setLayer(layerResult.value);
          setLayerError(null);
        } else {
          setLayer(null);
          setLayerError(errorMessage(layerResult.reason));
        }
      } finally {
        if (active) setLayerLoading(false);
      }
    }

    fetchLayerAndRisk();
    return () => {
      active = false;
    };
  }, [areaId, activeLayer]);

  const selectedCity = cities.find((city) => city.id === cityId);
  const selectedArea = areas.find((area) => area.id === areaId);
  const filteredAreas = useMemo(
    () => areas.filter((area) => area.name.toLowerCase().includes(search.toLowerCase())),
    [areas, search]
  );

  const selectCity = (nextCityId: string) => {
    setCityId(nextCityId);
    setAreas([]);
    setAreaId("");
    setRisk(null);
    setRiskError(null);
    setLayer(null);
    setError(null);
    setLoading(Boolean(nextCityId));
  };

  const selectArea = (nextAreaId: string) => {
    setAreaId(nextAreaId);
    setRisk(null);
    setRiskError(null);
    setLayer(null);
    setLayerError(null);
    setLayerLoading(Boolean(nextAreaId));
  };

  const selectLayer = (nextLayer: LayerName) => {
    setActiveLayer(nextLayer);
    setLayer(null);
    setLayerError(null);
    setLayerLoading(Boolean(areaId));
  };

  return (
    <div className="min-h-screen bg-[#030712] text-slate-100 flex flex-col">
      <Navbar />

      <main className="mx-auto w-full max-w-7xl flex-1 space-y-6 px-4 pb-16 pt-24 sm:px-6 lg:px-8">
        {/* Top Header & City Selection */}
        <div className="flex flex-col justify-between gap-4 border-b border-slate-800 pb-5 md:flex-row md:items-end">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono font-bold tracking-widest text-cyan-400">
                SPATIAL EXPLORER
              </span>
            </div>
            <h1 className="mt-1 text-3xl font-extrabold tracking-tight text-white">
              Explore Your City
            </h1>
            <p className="mt-1 text-xs text-slate-400">
              Browse the city, area, and GeoJSON records currently supplied by the backend.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center text-xs text-slate-400 font-mono">
              City:
              <select
                value={cityId}
                onChange={(event) => selectCity(event.target.value)}
                className="ml-2 rounded-lg border border-cyan-500/30 bg-slate-900 px-3 py-2 text-xs font-mono text-cyan-300 focus:outline-none focus:ring-1 focus:ring-cyan-400"
              >
                <option value="">Select a city</option>
                {cities.map((city) => (
                  <option key={city.id} value={city.id}>
                    {city.name}, {city.country}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {error && <DataNotice title="Data notice" message={error} error />}
        {riskError && <DataNotice title="Risk data unavailable" message={riskError} error />}
        {!loading && !error && cities.length === 0 && (
          <DataNotice title="No cities available" message="The connected database returned an empty city list." />
        )}
        {!loading && cityId && areas.length === 0 && (
          <DataNotice title="No areas available" message="This city has no area records yet." />
        )}

        {/* Main Grid: Sidebar Controls & Interactive Map */}
        <div className="grid gap-6 lg:grid-cols-12">
          {/* Left Sidebar: Area Search & Layer Controls */}
          <aside className="space-y-5 lg:col-span-4">
            {/* Area Selector */}
            <div className="space-y-3 rounded-2xl border border-slate-800 p-4 glass-panel">
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono font-semibold uppercase tracking-wider text-slate-300">
                  Target Areas
                </span>
                <span className="text-[10px] font-mono text-cyan-400">
                  {areas.length} available
                </span>
              </div>

              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search areas..."
                  className="w-full rounded-xl border border-slate-800 bg-[#050a1b] py-2 pl-9 pr-3 text-xs text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none"
                />
              </div>

              <div className="max-h-60 space-y-1.5 overflow-y-auto pr-1">
                {filteredAreas.map((area) => (
                  <button
                    key={area.id}
                    type="button"
                    onClick={() => selectArea(area.id)}
                    className={cn(
                      "flex w-full items-center justify-between rounded-xl border p-2.5 text-left text-xs transition-all",
                      area.id === areaId
                        ? "border-cyan-500/50 bg-cyan-500/15 text-white font-medium shadow-[0_0_12px_rgba(6,182,212,0.15)]"
                        : "border-slate-800/80 bg-slate-900/40 text-slate-300 hover:bg-slate-800/60"
                    )}
                  >
                    <span className="flex items-center gap-2">
                      <MapPin className="h-3.5 w-3.5 text-cyan-400 shrink-0" />
                      {area.name}
                    </span>
                    {area.population && (
                      <span className="text-[10px] font-mono text-slate-500">
                        {Math.round(area.population / 1000)}k pop
                      </span>
                    )}
                  </button>
                ))}
                {!loading && filteredAreas.length === 0 && (
                  <p className="p-3 text-center text-xs text-slate-500">
                    No matching areas found.
                  </p>
                )}
              </div>
            </div>

            {/* Layer Controls */}
            <div className="rounded-2xl border border-slate-800 p-5 glass-panel">
              <LayerControls activeLayer={activeLayer} onLayerChange={selectLayer} />
            </div>

            {/* Grid Visibility & Display Options Box */}
            <div className="rounded-2xl border border-slate-800 p-4 glass-panel space-y-3">
              <div className="flex items-center justify-between border-b border-slate-800/80 pb-2">
                <span className="text-xs font-mono font-semibold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                  <Grid className="h-3.5 w-3.5 text-cyan-400" />
                  Grid Display Mode
                </span>
                <span
                  className={cn(
                    "text-[10px] font-mono px-2 py-0.5 rounded",
                    gridMinimized
                      ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                      : "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30"
                  )}
                >
                  {gridMinimized ? "MINIMIZED" : "FULL OVERLAY"}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setGridMinimized(false)}
                  className={cn(
                    "flex flex-col items-center gap-1.5 p-2.5 rounded-xl border text-xs font-mono transition-all",
                    !gridMinimized
                      ? "border-cyan-500/50 bg-cyan-500/15 text-white shadow-sm"
                      : "border-slate-800 bg-slate-900/40 text-slate-400 hover:text-white"
                  )}
                >
                  <Maximize2 className="h-4 w-4 text-cyan-400" />
                  <span>Full Grid</span>
                </button>

                <button
                  type="button"
                  onClick={() => setGridMinimized(true)}
                  className={cn(
                    "flex flex-col items-center gap-1.5 p-2.5 rounded-xl border text-xs font-mono transition-all",
                    gridMinimized
                      ? "border-amber-500/50 bg-amber-500/15 text-white shadow-sm"
                      : "border-slate-800 bg-slate-900/40 text-slate-400 hover:text-white"
                  )}
                >
                  <Minimize2 className="h-4 w-4 text-amber-400" />
                  <span>Minimize Grid</span>
                </button>
              </div>

              <p className="text-[11px] text-slate-400">
                {gridMinimized
                  ? "Grid cells are minimized to clear the map view. Click 'Full Grid' to view individual cell metrics."
                  : "Supplied grid geometry is visible. Click a cell to inspect the values returned by the layer route."}
              </p>
            </div>

            {/* Quick Navigation to Intelligence & Simulator */}
            {selectedArea && (
              <div className="rounded-2xl border border-cyan-500/20 bg-cyan-950/20 p-4 space-y-2.5">
                <span className="text-[11px] font-mono text-cyan-300 font-semibold uppercase tracking-wider block">
                  Connected Modules for {selectedArea.name}
                </span>
                <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                  <Link
                    href={`/analysis/${selectedArea.id}`}
                    className="flex items-center justify-center gap-1.5 rounded-xl border border-cyan-500/30 bg-slate-900/80 p-2 text-cyan-300 hover:bg-cyan-500/20 transition-colors text-center"
                  >
                    <Sparkles className="h-3.5 w-3.5 text-amber-400" />
                    <span>AI Intelligence</span>
                  </Link>
                  <Link
                    href={`/simulate/${selectedArea.id}`}
                    className="flex items-center justify-center gap-1.5 rounded-xl border border-cyan-500/30 bg-slate-900/80 p-2 text-cyan-300 hover:bg-cyan-500/20 transition-colors text-center"
                  >
                    <Layers className="h-3.5 w-3.5 text-emerald-400" />
                    <span>Simulator</span>
                  </Link>
                </div>
              </div>
            )}
          </aside>

          {/* Right Main Column: UrbanMap GIS Viewport & Area Popup */}
          <section className="space-y-4 lg:col-span-8">
            <div className="relative">
              <UrbanMap
                activeLayer={activeLayer}
                selectedArea={selectedArea}
                layer={layer}
                layerLoading={layerLoading}
                layerError={layerError}
                heightClassName="h-[560px]"
                initialGridMinimized={gridMinimized}
                onGridMinimizeChange={(min) => setGridMinimized(min)}
              />

              {/* Area Popup Desktop HUD */}
              {selectedArea && (
                <div className="absolute right-4 top-16 z-20 hidden md:block">
                  <AreaPopup area={selectedArea} city={selectedCity} risk={risk} />
                </div>
              )}
            </div>

            {/* Area Popup Mobile view */}
            {selectedArea && (
              <div className="md:hidden">
                <AreaPopup area={selectedArea} city={selectedCity} risk={risk} />
              </div>
            )}
          </section>
        </div>

        <RiskLegend />
      </main>

      <Footer />
    </div>
  );
}
