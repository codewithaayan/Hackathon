import type { Area, GeoJSONGeometry } from "./area";

export interface RiskScores {
  overall: number | null;
  heat: number | null;
  air: number | null;
  flood: number | null;
  green: number | null;
  mobility: number | null;
  populationExposure: number | null;
}

export interface SourceMetadata {
  updated: string | null;
  dataSources: string[] | null;
}

export interface RiskResponse {
  area: { id: string; name: string; city: string };
  scores: RiskScores;
  exposure: { population: number | null; highRiskPopulation: number | null };
  metadata: SourceMetadata;
}

export interface GridPopulation {
  gridCellId: string;
  timestamp: string;
  population: number | null;
}

export interface PopulationResponse {
  area: Area;
  exposure: { population: number | null; highRiskPopulation: number | null };
  gridPopulation: GridPopulation[];
  metadata: SourceMetadata;
}

export interface MapFeature {
  type: "Feature";
  id?: string | number | null;
  geometry: GeoJSONGeometry | null;
  properties: Record<string, unknown> | null;
}

export interface MapLayer {
  type: "FeatureCollection";
  features: MapFeature[];
  metadata: SourceMetadata;
  incompleteGridCellIds: string[];
}

export type LayerName = "heat" | "green" | "flood";
