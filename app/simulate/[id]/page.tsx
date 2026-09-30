"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Sliders } from "lucide-react";
import { Footer } from "@/components/layout/Footer";
import { Navbar } from "@/components/layout/Navbar";
import { DataNotice } from "@/components/ui/DataNotice";
import { errorMessage, getArea } from "@/lib/api";
import type { Area } from "@/types/area";

export default function SimulationPage() {
  const id = String(useParams<{ id: string }>().id);
  const [area, setArea] = useState<Area | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getArea(id)
      .then((value) => {
        if (active) setArea(value);
      })
      .catch((reason) => {
        if (active) setError(errorMessage(reason));
      });
    return () => { active = false; };
  }, [id]);

  return (
    <div className="min-h-screen bg-[#030712] text-slate-100 flex flex-col">
      <Navbar />
      <main className="mx-auto w-full max-w-4xl flex-1 space-y-6 px-4 pb-20 pt-28 sm:px-6">
        <div className="border-b border-slate-800 pb-5">
          <span className="flex items-center gap-2 text-xs font-mono font-bold tracking-widest text-emerald-400">
            <Sliders className="h-4 w-4" /> INTERVENTION SIMULATOR
          </span>
          <h1 className="mt-2 text-3xl font-extrabold text-white">
            {area ? `${area.name} simulation` : "Simulation"}
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            Scenario controls will be enabled after the scientific owners provide the validated request and response contracts.
          </p>
        </div>

        {error ? (
          <DataNotice title="Area unavailable" message={error} error />
        ) : !area ? (
          <DataNotice title="Loading area" message="Requesting area details." />
        ) : (
          <DataNotice
            title="Simulation connection pending"
            message="The backend route exists, but Arjun and Chip have not supplied the agreed schemas or simulator adapter. No coefficients, projections, or saved-success state are fabricated locally."
          />
        )}

        <Link href="/simulate" className="inline-flex items-center gap-2 text-sm text-emerald-300 hover:text-emerald-200">
          <ArrowLeft className="h-4 w-4" /> Back to available areas
        </Link>
      </main>
      <Footer />
    </div>
  );
}
