"use client";

import React, { useState, useMemo, useRef, useCallback } from "react";
import {
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Maximize2,
  Minimize2,
  Grid,
  Flame,
  Trees,
  CloudRain,
  EyeOff,
  Crosshair,
} from "lucide-react";
import type { Area, GeoJSONGeometry } from "@/types/area";
import type { LayerName, MapFeature, MapLayer } from "@/types/risk";
import { cn, formatNumber } from "@/lib/utils";

export interface UrbanMapProps {
  activeLayer?: LayerName;
  selectedArea?: Area | null;
  layer?: MapLayer | null;
  layerLoading?: boolean;
  layerError?: string | null;
  heightClassName?: string;
  initialGridMinimized?: boolean;
  onGridMinimizeChange?: (minimized: boolean) => void;
  onSelectCell?: (feature: MapFeature | null) => void;
}

interface BBox {
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
}

function mercatorY(lat: number): number {
  const clamped = Math.max(-85.051129, Math.min(85.051129, lat));
  const rad = (clamped * Math.PI) / 180;
  return Math.log(Math.tan(Math.PI / 4 + rad / 2));
}

export function UrbanMap({
  activeLayer = "heat",
  selectedArea,
  layer,
  layerLoading = false,
  layerError,
  heightClassName = "h-[540px]",
  initialGridMinimized = false,
  onGridMinimizeChange,
  onSelectCell,
}: UrbanMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [gridMinimized, setGridMinimized] = useState(initialGridMinimized);
  const [hoveredCell, setHoveredCell] = useState<MapFeature | null>(null);
  const [selectedCell, setSelectedCell] = useState<MapFeature | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);

  // Synchronize area changes without effect-induced render cascades (React 19 pattern)
  const [prevAreaId, setPrevAreaId] = useState(selectedArea?.id);
  if (selectedArea?.id !== prevAreaId) {
    setPrevAreaId(selectedArea?.id);
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setSelectedCell(null);
    setHoveredCell(null);
  }

  const toggleGridMinimize = useCallback(() => {
    setGridMinimized((prev) => {
      const next = !prev;
      onGridMinimizeChange?.(next);
      return next;
    });
  }, [onGridMinimizeChange]);

  // Compute bounding box from selectedArea geometry or layer features
  const bbox: BBox = useMemo(() => {
    const coords: Array<[number, number]> = [];

    const extractCoords = (geom: GeoJSONGeometry | null | undefined) => {
      if (!geom) return;
      if (geom.geometries) {
        geom.geometries.forEach(extractCoords);
      }
      if (!geom.coordinates) return;
      const traverse = (item: unknown) => {
        if (Array.isArray(item)) {
          if (
            item.length >= 2 &&
            typeof item[0] === "number" &&
            typeof item[1] === "number"
          ) {
            coords.push([item[0], item[1]]);
          } else {
            item.forEach(traverse);
          }
        }
      };
      traverse(geom.coordinates);
    };

    if (selectedArea?.geometry) {
      extractCoords(selectedArea.geometry);
    }

    if (layer?.features) {
      layer.features.forEach((f) => extractCoords(f.geometry));
    }

    if (coords.length === 0) {
      return { minLon: -180, minLat: -85, maxLon: 180, maxLat: 85 };
    }

    let minLon = Infinity;
    let minLat = Infinity;
    let maxLon = -Infinity;
    let maxLat = -Infinity;

    for (const [lon, lat] of coords) {
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }

    const lonPad = Math.max(0.005, (maxLon - minLon) * 0.12);
    const latPad = Math.max(0.005, (maxLat - minLat) * 0.12);

    return {
      minLon: minLon - lonPad,
      minLat: minLat - latPad,
      maxLon: maxLon + lonPad,
      maxLat: maxLat + latPad,
    };
  }, [selectedArea, layer]);

  const viewWidth = 1000;
  const viewHeight = 650;
  const padding = 50;

  const minMerc = useMemo(() => mercatorY(bbox.minLat), [bbox.minLat]);
  const maxMerc = useMemo(() => mercatorY(bbox.maxLat), [bbox.maxLat]);

  const project = useCallback(
    (lon: number, lat: number): [number, number] => {
      const lonSpan = bbox.maxLon - bbox.minLon || 0.01;
      const mercSpan = maxMerc - minMerc || 0.01;

      const normX = (lon - bbox.minLon) / lonSpan;
      const currentMerc = mercatorY(lat);
      const normY = (maxMerc - currentMerc) / mercSpan;

      const x = padding + normX * (viewWidth - 2 * padding);
      const y = padding + normY * (viewHeight - 2 * padding);
      return [x, y];
    },
    [bbox, minMerc, maxMerc]
  );

  const geometryToSvgPath = useCallback(
    (geometry: GeoJSONGeometry | null | undefined): string => {
      if (!geometry?.coordinates || !Array.isArray(geometry.coordinates)) return "";
      let polygonRings: Array<Array<[number, number]>>;
      if (geometry.type === "Polygon") {
        polygonRings = geometry.coordinates as Array<Array<[number, number]>>;
      } else if (geometry.type === "MultiPolygon") {
        polygonRings = (geometry.coordinates as Array<Array<Array<[number, number]>>>).flat();
      } else {
        return "";
      }

      return polygonRings
        .map((ring) => {
          if (!Array.isArray(ring) || ring.length === 0) return "";
          return (
            ring
              .map(([lon, lat], i) => {
                const [x, y] = project(lon, lat);
                return `${i === 0 ? "M" : "L"} ${x.toFixed(1)},${y.toFixed(1)}`;
              })
              .join(" ") + " Z"
          );
        })
        .join(" ");
    },
    [project]
  );

  // Mouse pan & tooltip positioning handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    setIsDragging(true);
    setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isDragging) {
      setPan({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      });
    }

    if (containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      const clampedX = Math.min(e.clientX - rect.left + 15, rect.width - 275);
      const clampedY = Math.max(10, e.clientY - rect.top - 120);
      setTooltipPos({ x: clampedX, y: clampedY });
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 0.87;
    setZoom((z) => Math.min(5, Math.max(0.8, z * factor)));
  };

  // The scientific owners have not supplied risk bands or styling thresholds.
  // Use one neutral color per layer so missing values are never rendered as zero.
  const getCellFill = useCallback(
    () => {
      if (activeLayer === "green") return "rgba(16, 185, 129, 0.55)";
      if (activeLayer === "flood") return "rgba(14, 165, 233, 0.55)";
      return "rgba(249, 115, 22, 0.55)";
    },
    [activeLayer]
  );

  const getCellStroke = useCallback(
    (feature: MapFeature, isHovered: boolean, isSelected: boolean) => {
      if (isSelected) return "#06b6d4";
      if (isHovered) return "#ffffff";
      if (gridMinimized) return "rgba(6, 182, 212, 0.15)";
      return "rgba(15, 23, 42, 0.85)";
    },
    [gridMinimized]
  );

  const drawableFeatures = useMemo(() => {
    return (layer?.features ?? []).filter(
      (feature) => feature.geometry?.type === "Polygon" || feature.geometry?.type === "MultiPolygon"
    );
  }, [layer]);

  const areaBoundaryPath = useMemo(() => {
    return geometryToSvgPath(selectedArea?.geometry);
  }, [selectedArea, geometryToSvgPath]);

  return (
    <div
      ref={containerRef}
      className={cn(
        "relative flex w-full flex-col justify-between overflow-hidden rounded-2xl border border-cyan-500/25 bg-[#030713] select-none",
        heightClassName
      )}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={() => {
        handleMouseUp();
        setHoveredCell(null);
      }}
      onWheel={handleWheel}
    >
      <div className="absolute inset-0 pointer-events-none bg-grid-pattern opacity-30" />
      <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-cyan-950/20 via-[#030713]/80 to-[#02050e]" />

      {/* Top Map HUD Bar */}
      <div className="relative z-20 flex flex-wrap items-center justify-between gap-2 p-3 sm:p-4 text-xs font-mono">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-lg border border-cyan-500/30 bg-slate-900/90 px-3 py-1.5 text-cyan-300 backdrop-blur-md shadow-lg shadow-black/40">
            {activeLayer === "heat" ? (
              <Flame className="h-3.5 w-3.5 text-red-400" />
            ) : activeLayer === "green" ? (
              <Trees className="h-3.5 w-3.5 text-emerald-400" />
            ) : activeLayer === "flood" ? (
              <CloudRain className="h-3.5 w-3.5 text-blue-400" />
            ) : null}
            <span className="font-bold tracking-wider uppercase">
              {`${activeLayer.toUpperCase()} LAYER`}
            </span>
          </div>

          {/* Grid Minimize / Expand Toggle Button */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              toggleGridMinimize();
            }}
            className={cn(
              "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-all backdrop-blur-md",
              gridMinimized
                ? "border-amber-500/50 bg-amber-500/15 text-amber-300 hover:bg-amber-500/25"
                : "border-cyan-500/40 bg-slate-900/90 text-cyan-300 hover:bg-cyan-500/20"
            )}
            title={gridMinimized ? "Expand Grid Cells" : "Minimize Grid Overlay"}
          >
            {gridMinimized ? (
              <>
                <Maximize2 className="h-3.5 w-3.5" />
                <span>Expand Grid</span>
              </>
            ) : (
              <>
                <Minimize2 className="h-3.5 w-3.5" />
                <span>Minimize Grid</span>
              </>
            )}
          </button>
        </div>

        {/* Status Pills */}
        <div className="flex items-center gap-2">
          {layerLoading ? (
            <span className="flex items-center gap-1.5 rounded-lg border border-cyan-500/30 bg-slate-900/90 px-2.5 py-1 text-[11px] text-cyan-400 animate-pulse">
              <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-ping" />
              Loading GeoJSON layer…
            </span>
          ) : layerError ? (
            <span className="rounded-lg border border-red-500/30 bg-red-950/60 px-2.5 py-1 text-[11px] text-red-300">
              {layerError}
            </span>
          ) : drawableFeatures.length > 0 ? (
            <span className="hidden sm:flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-950/80 px-2.5 py-1 text-[11px] text-slate-400">
              <Grid className="h-3 w-3 text-cyan-400" />
              {gridMinimized ? "Grid minimized" : `${drawableFeatures.length} active grid cells`}
            </span>
          ) : null}

          {selectedArea && (
            <span className="flex items-center gap-1 rounded-lg border border-slate-800 bg-slate-950/80 px-2.5 py-1 text-[11px] text-slate-300">
              <Crosshair className="h-3 w-3 text-emerald-400" />
              {selectedArea.name}
            </span>
          )}
        </div>
      </div>

      {/* Main Interactive SVG Map Viewport */}
      <div
        className={cn(
          "absolute inset-0 cursor-grab active:cursor-grabbing",
          isDragging && "cursor-grabbing"
        )}
      >
        <svg
          viewBox={`0 0 ${viewWidth} ${viewHeight}`}
          className="h-full w-full"
          preserveAspectRatio="xMidYMid meet"
        >
          <defs>
            <linearGradient id="areaGlow" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.08" />
              <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.03" />
            </linearGradient>

            <filter id="cyanGlow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>

            <pattern id="diagHatch" width="8" height="8" patternTransform="rotate(45 0 0)" patternUnits="userSpaceOnUse">
              <line x1="0" y1="0" x2="0" y2="8" stroke="#06b6d4" strokeWidth="0.75" strokeOpacity="0.12" />
            </pattern>
          </defs>

          <g
            transform={`translate(${pan.x + (viewWidth * (1 - zoom)) / 2}, ${pan.y + (viewHeight * (1 - zoom)) / 2
              }) scale(${zoom})`}
            style={{ transition: isDragging ? "none" : "transform 0.15s ease-out" }}
          >
            <g className="opacity-20 pointer-events-none">
              {[0.2, 0.4, 0.6, 0.8].map((ratio) => {
                const y = padding + ratio * (viewHeight - 2 * padding);
                const x = padding + ratio * (viewWidth - 2 * padding);
                return (
                  <React.Fragment key={ratio}>
                    <line x1={padding} y1={y} x2={viewWidth - padding} y2={y} stroke="#06b6d4" strokeDasharray="3 4" strokeWidth="0.75" />
                    <line x1={x} y1={padding} x2={x} y2={viewHeight - padding} stroke="#06b6d4" strokeDasharray="3 4" strokeWidth="0.75" />
                  </React.Fragment>
                );
              })}
            </g>

            {areaBoundaryPath && (
              <g>
                <path
                  d={areaBoundaryPath}
                  fill="url(#areaGlow)"
                  stroke="#06b6d4"
                  strokeWidth="2.5"
                  strokeOpacity="0.9"
                  strokeDasharray="8 4"
                  filter="url(#cyanGlow)"
                />
                <path d={areaBoundaryPath} fill="url(#diagHatch)" pointerEvents="none" />
              </g>
            )}

            {drawableFeatures.map((feature, i) => {
              const geom = feature.geometry;
              if (!geom?.coordinates) return null;
              const path = geometryToSvgPath(geom);
              if (!path) return null;

              const isHovered = hoveredCell === feature;
              const isSelected = selectedCell === feature;
              const props = (feature.properties ?? {}) as Record<string, unknown>;

              return (
                <path
                  key={String(props.grid_cell_id ?? i)}
                  d={path}
                  fill={gridMinimized ? "transparent" : getCellFill()}
                  fillOpacity={gridMinimized ? 0 : 0.85}
                  stroke={getCellStroke(feature, isHovered, isSelected)}
                  strokeWidth={isSelected ? 2.5 : isHovered ? 2 : gridMinimized ? 0.8 : 1.2}
                  strokeDasharray={gridMinimized ? "3 3" : undefined}
                  className="transition-colors duration-150 cursor-pointer"
                  onMouseEnter={() => setHoveredCell(feature)}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedCell(feature);
                    onSelectCell?.(feature);
                  }}
                />
              );
            })}

          </g>
        </svg>
      </div>

      {gridMinimized && drawableFeatures.length > 0 && (
        <div className="absolute top-16 left-4 z-20 flex items-center gap-2 rounded-xl border border-amber-500/40 bg-slate-950/90 px-3 py-2 text-xs font-mono text-amber-300 shadow-xl backdrop-blur-md animate-in fade-in duration-200">
          <EyeOff className="h-4 w-4 text-amber-400 shrink-0" />
          <span>Grid overlay is minimized ({drawableFeatures.length} cells hidden)</span>
          <button
            type="button"
            onClick={toggleGridMinimize}
            className="ml-1 rounded-md bg-amber-500/20 px-2 py-0.5 text-[11px] font-bold text-amber-200 hover:bg-amber-500/30 transition-colors"
          >
            Restore Grid
          </button>
        </div>
      )}

      {hoveredCell && tooltipPos && (
        <div
          className="pointer-events-none absolute z-30 w-64 rounded-xl border border-cyan-500/40 bg-slate-950/95 p-3 font-mono text-xs shadow-2xl backdrop-blur-xl"
          style={{
            left: tooltipPos.x,
            top: tooltipPos.y,
          }}
        >
          {(() => {
            const p = (hoveredCell.properties ?? {}) as Record<string, unknown>;
            const cellId = String(p.grid_cell_id ?? "Cell");
            const temp = p.temperature == null ? "—" : String(p.temperature);
            const heatScore = p.heat_score == null ? "—" : String(p.heat_score);
            const ndvi = p.ndvi == null ? "—" : String(p.ndvi);
            const floodScore = p.flood_score == null ? "—" : String(p.flood_score);
            const pop = p.population == null ? "—" : formatNumber(Number(p.population));

            return (
              <div className="space-y-2">
                <div className="flex items-center justify-between border-b border-slate-800 pb-1.5">
                  <span className="font-bold text-cyan-300 flex items-center gap-1.5">
                    <Crosshair className="h-3 w-3 text-cyan-400" />
                    {cellId}
                  </span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded font-bold uppercase bg-cyan-500/10 text-cyan-300 border border-cyan-500/30">
                    SUPPLIED VALUES
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-1.5 text-[11px]">
                  <div>
                    <span className="text-[10px] text-slate-400 block">TEMPERATURE</span>
                    <span className="font-bold text-red-300">{temp}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-400 block">HEAT RISK</span>
                    <span className="font-bold text-white">{heatScore}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-400 block">VEGETATION (NDVI)</span>
                    <span className="font-bold text-emerald-300">{ndvi}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-400 block">FLOOD RISK</span>
                    <span className="font-bold text-blue-300">{floodScore}</span>
                  </div>
                  <div className="col-span-2 pt-1 border-t border-slate-900 flex justify-between text-[10px]">
                    <span className="text-slate-400">EST. POPULATION:</span>
                    <span className="font-bold text-cyan-200">{pop}</span>
                  </div>
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {selectedCell && (
        <div className="absolute bottom-16 right-4 z-20 w-72 rounded-xl border border-cyan-500/50 bg-[#040817]/95 p-3.5 font-mono text-xs shadow-2xl backdrop-blur-xl animate-in slide-in-from-bottom-2">
          {(() => {
            const p = (selectedCell.properties ?? {}) as Record<string, unknown>;
            return (
              <div className="space-y-2">
                <div className="flex items-center justify-between border-b border-cyan-500/30 pb-2">
                  <div className="flex items-center gap-1.5">
                    <Grid className="h-3.5 w-3.5 text-cyan-400" />
                    <span className="font-bold text-white">{String(p.grid_cell_id)}</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setSelectedCell(null)}
                    className="text-slate-400 hover:text-white text-xs px-1.5 py-0.5 rounded bg-slate-800"
                  >
                    ✕
                  </button>
                </div>
                <p className="text-[11px] text-slate-300">
                  Target spatial grid cell within {selectedArea?.name}.
                </p>
                <div className="grid grid-cols-2 gap-2 text-[11px] rounded-lg bg-slate-950/80 p-2 border border-slate-800">
                  <div>
                    <span className="text-[9px] text-slate-400">SURFACE HEAT</span>
                    <p className="text-red-400 font-bold">
                      {p.temperature == null ? "—" : String(p.temperature)}
                    </p>
                  </div>
                  <div>
                    <span className="text-[9px] text-slate-400">CANOPY COVER</span>
                    <p className="text-emerald-400 font-bold">
                      {p.green_percentage == null ? "—" : String(p.green_percentage)}
                    </p>
                  </div>
                  <div>
                    <span className="text-[9px] text-slate-400">PRECIPITATION</span>
                    <p className="text-blue-400 font-bold">
                      {p.rainfall == null ? "—" : String(p.rainfall)}
                    </p>
                  </div>
                  <div>
                    <span className="text-[9px] text-slate-400">POPULATION</span>
                    <p className="text-cyan-300 font-bold">{p.population == null ? "—" : formatNumber(Number(p.population))}</p>
                  </div>
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {/* Floating Map Controls & Navigation Tools */}
      <div className="relative z-20 flex items-center justify-between p-3 sm:p-4 text-[11px] font-mono border-t border-slate-900 bg-[#030713]/90 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="text-slate-400">SUPPLIED LAYER</span>
            <div
              className={cn(
                "h-2 w-20 sm:w-28 rounded-full",
                activeLayer === "heat"
                  ? "bg-orange-500"
                  : activeLayer === "green"
                    ? "bg-emerald-500"
                    : "bg-sky-500"
              )}
            />
          </div>

          <span className="hidden sm:inline-block text-slate-500">|</span>
          <span className="hidden sm:inline-block text-slate-400">
            WGS84 EPSG:4326 • supplied grid geometry
          </span>
        </div>

        <div className="flex items-center gap-1.5 bg-slate-900/90 border border-slate-800 p-1 rounded-xl backdrop-blur-md">
          <button
            type="button"
            onClick={() => setZoom((z) => Math.min(5, z * 1.25))}
            className="p-1.5 hover:bg-slate-800 text-slate-400 hover:text-cyan-300 rounded-lg transition-colors"
            title="Zoom In"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => setZoom((z) => Math.max(0.8, z * 0.8))}
            className="p-1.5 hover:bg-slate-800 text-slate-400 hover:text-cyan-300 rounded-lg transition-colors"
            title="Zoom Out"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => {
              setZoom(1);
              setPan({ x: 0, y: 0 });
            }}
            className="p-1.5 hover:bg-slate-800 text-slate-400 hover:text-cyan-300 rounded-lg transition-colors"
            title="Reset Viewport"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={toggleGridMinimize}
            className={cn(
              "p-1.5 rounded-lg transition-colors",
              gridMinimized ? "text-amber-400 bg-amber-500/10" : "text-slate-400 hover:text-cyan-300 hover:bg-slate-800"
            )}
            title={gridMinimized ? "Restore Grid" : "Minimize Grid"}
          >
            <Grid className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
