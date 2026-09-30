import React from "react";
import { MapPin, BarChart3, ShieldAlert, Sliders, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/Badge";

const STEPS = [
  {
    step: "01",
    name: "SELECT AREA",
    action: "Target Neighbourhood",
    description: "Choose from the city and area records currently available through the backend.",
    icon: MapPin,
    accent: "border-cyan-500/30 text-cyan-400 bg-cyan-500/10",
  },
  {
    step: "02",
    name: "ANALYZE DATA",
    action: "Validated Records",
    description: "Display only processed environmental values and geometry supplied by the data owners.",
    icon: BarChart3,
    accent: "border-blue-500/30 text-blue-400 bg-blue-500/10",
  },
  {
    step: "03",
    name: "UNDERSTAND RISK",
    action: "Owner-Supplied Scores",
    description: "Show structured risk and exposure fields after the risk adapter validates its required inputs.",
    icon: ShieldAlert,
    accent: "border-amber-500/30 text-amber-400 bg-amber-500/10",
  },
  {
    step: "04",
    name: "EXPLORE INTERVENTIONS",
    action: "Pending Simulator",
    description: "Enable interventions only after the scientific owners supply schemas, coefficients, and a model adapter.",
    icon: Sliders,
    accent: "border-emerald-500/30 text-emerald-400 bg-emerald-500/10",
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="py-24 relative bg-[#030712] border-t border-slate-900">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="text-center max-w-2xl mx-auto mb-16 space-y-3">
          <Badge variant="cyan" size="sm">
            WORKFLOW PIPELINE
          </Badge>
          <h2 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            From Raw Earth Observation to Resilient Cities
          </h2>
          <p className="text-sm text-slate-400 leading-relaxed">
            Four disciplined analytical stages guiding urban planners from diagnosis to measurable civic policy.
          </p>
        </div>

        {/* 4-Stage Connected Workflow Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 relative">
          {STEPS.map((step, idx) => {
            const Icon = step.icon;
            return (
              <div
                key={step.name}
                className="group relative glass-panel-interactive rounded-2xl p-6 border-slate-800 flex flex-col justify-between"
              >
                <div>
                  {/* Step counter & Icon */}
                  <div className="flex items-center justify-between mb-6">
                    <span className="font-mono text-2xl font-bold text-slate-600 group-hover:text-cyan-400 transition-colors">
                      {step.step}
                    </span>
                    <div className={`w-11 h-11 rounded-xl flex items-center justify-center border transition-all duration-300 group-hover:scale-110 ${step.accent}`}>
                      <Icon className="w-5 h-5" />
                    </div>
                  </div>

                  {/* Stage Name */}
                  <h3 className="text-xs font-mono font-bold tracking-widest text-cyan-400 uppercase mb-1">
                    {step.name}
                  </h3>
                  <div className="text-base font-semibold text-white mb-2">
                    {step.action}
                  </div>

                  {/* Description */}
                  <p className="text-xs text-slate-400 leading-relaxed">
                    {step.description}
                  </p>
                </div>

                {/* Progress bar line */}
                <div className="mt-6 pt-4 border-t border-slate-800/80 flex items-center justify-between text-[10px] font-mono text-slate-500">
                  <span>STAGE {idx + 1} OF 4</span>
                  {idx < 3 ? (
                    <span className="text-cyan-400 flex items-center gap-0.5">
                      Next <ChevronRight className="w-3 h-3 inline" />
                    </span>
                  ) : (
                    <span className="text-slate-400">PENDING</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
