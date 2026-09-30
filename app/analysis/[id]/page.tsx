"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Sparkles } from "lucide-react";
import { Footer } from "@/components/layout/Footer";
import { Navbar } from "@/components/layout/Navbar";
import { DataNotice } from "@/components/ui/DataNotice";
import { errorMessage, getArea } from "@/lib/api";
import type { Area } from "@/types/area";

export default function AnalysisPage() {
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
          <span className="flex items-center gap-2 text-xs font-mono font-bold tracking-widest text-cyan-400">
            <Sparkles className="h-4 w-4" /> AI ANALYSIS
          </span>
          <h1 className="mt-2 text-3xl font-extrabold text-white">
            {area ? `${area.name} analysis` : "Area analysis"}
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            This workspace will use the backend AI route after its owner-defined schemas and grounded adapter are connected.
          </p>
        </div>

        {error ? (
          <DataNotice title="Area unavailable" message={error} error />
        ) : !area ? (
          <DataNotice title="Loading area" message="Requesting area details." />
        ) : (
          <DataNotice
            title="AI connection pending"
            message="The backend route exists, but Arjun has not supplied the agreed request model, response model, or AI adapter. No generated answer or inferred hotspot is shown until those components are connected."
          />
        )}

        <Link href="/analysis" className="inline-flex items-center gap-2 text-sm text-cyan-300 hover:text-cyan-200">
          <ArrowLeft className="h-4 w-4" /> Back to available areas
        </Link>
      </main>
      <Footer />
    </div>
  );
}
