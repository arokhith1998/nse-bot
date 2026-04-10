"use client";

import { useState, useEffect } from "react";
import { fetchSettings, updateSettings } from "@/lib/api";
import type { Settings } from "@/lib/types";
import {
  Settings as SettingsIcon,
  Save,
  AlertCircle,
  CheckCircle,
} from "lucide-react";

const SETUP_OPTIONS = [
  "BREAKOUT",
  "MOMENTUM",
  "GAP-AND-GO",
  "SWING-INTRADAY",
  "MEAN-REVERSION",
  "PULLBACK-ENTRY",
];

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  const [draft, setDraft] = useState<Partial<Settings>>({});

  useEffect(() => {
    fetchSettings()
      .then((data) => {
        setSettings(data);
        setDraft(data);
      })
      .catch(() => {
        const defaults: Settings = {
          capital: 1000,
          risk_per_trade: 50,
          max_positions: 6,
          preferred_setups: SETUP_OPTIONS,
          min_score: 60,
          auto_refresh_interval: 60,
          notifications_enabled: true,
          paper_trading: true,
        };
        setSettings(defaults);
        setDraft(defaults);
      })
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    try {
      setSaving(true);
      setMessage(null);
      const updated = await updateSettings(draft);
      setSettings(updated);
      setDraft(updated);
      setMessage({ type: "success", text: "Settings saved successfully" });
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to save settings",
      });
    } finally {
      setSaving(false);
      setTimeout(() => setMessage(null), 4000);
    }
  };

  const toggleSetup = (setup: string) => {
    const current = draft.preferred_setups ?? [];
    const next = current.includes(setup)
      ? current.filter((s) => s !== setup)
      : [...current, setup];
    setDraft({ ...draft, preferred_setups: next });
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-32 bg-line rounded animate-pulse" />
        <div className="bg-card border border-line rounded-xl p-5 space-y-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="h-12 bg-card-alt rounded-lg animate-pulse"
            />
          ))}
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <SettingsIcon className="w-5 h-5 text-mute" />
          <h1 className="text-lg font-semibold text-ink">Settings</h1>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-1.5 px-4 py-2 text-sm bg-accent text-bg font-semibold rounded-lg hover:brightness-110 transition-all disabled:opacity-50"
        >
          <Save className="w-4 h-4" />
          {saving ? "Saving..." : "Save Changes"}
        </button>
      </div>

      {/* Status message */}
      {message && (
        <div
          className={`flex items-center gap-2 px-4 py-3 rounded-xl text-sm ${
            message.type === "success"
              ? "bg-green/10 border border-green/20 text-green"
              : "bg-red/10 border border-red/20 text-red"
          }`}
        >
          {message.type === "success" ? (
            <CheckCircle className="w-4 h-4" />
          ) : (
            <AlertCircle className="w-4 h-4" />
          )}
          {message.text}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Capital & Risk */}
        <div className="bg-card border border-line rounded-xl p-5">
          <h2 className="text-xs font-semibold text-mute uppercase tracking-wider mb-4">
            Capital & Risk Management
          </h2>
          <div className="space-y-4">
            <div>
              <label className="block text-xs text-mute mb-1.5">
                Total Capital (INR)
              </label>
              <input
                type="number"
                value={draft.capital ?? 1000}
                onChange={(e) =>
                  setDraft({ ...draft, capital: Number(e.target.value) })
                }
                className="w-full px-3 py-2 text-sm bg-card-alt border border-line rounded-lg text-ink focus:outline-none focus:border-accent/40 font-mono"
              />
            </div>
            <div>
              <label className="block text-xs text-mute mb-1.5">
                Risk Per Trade (INR)
              </label>
              <input
                type="number"
                value={draft.risk_per_trade ?? 50}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    risk_per_trade: Number(e.target.value),
                  })
                }
                className="w-full px-3 py-2 text-sm bg-card-alt border border-line rounded-lg text-ink focus:outline-none focus:border-accent/40 font-mono"
              />
            </div>
            <div>
              <label className="block text-xs text-mute mb-1.5">
                Max Concurrent Positions
              </label>
              <input
                type="number"
                value={draft.max_positions ?? 6}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    max_positions: Number(e.target.value),
                  })
                }
                min={1}
                max={20}
                className="w-full px-3 py-2 text-sm bg-card-alt border border-line rounded-lg text-ink focus:outline-none focus:border-accent/40 font-mono"
              />
            </div>
            <div>
              <label className="block text-xs text-mute mb-1.5">
                Minimum Score Threshold
              </label>
              <input
                type="number"
                value={draft.min_score ?? 60}
                onChange={(e) =>
                  setDraft({ ...draft, min_score: Number(e.target.value) })
                }
                min={0}
                max={100}
                className="w-full px-3 py-2 text-sm bg-card-alt border border-line rounded-lg text-ink focus:outline-none focus:border-accent/40 font-mono"
              />
              <span className="text-[10px] text-mute/60 mt-1 block">
                Picks below this score will be filtered out
              </span>
            </div>
          </div>
        </div>

        {/* Preferences */}
        <div className="bg-card border border-line rounded-xl p-5">
          <h2 className="text-xs font-semibold text-mute uppercase tracking-wider mb-4">
            Preferences
          </h2>
          <div className="space-y-4">
            <div>
              <label className="block text-xs text-mute mb-2">
                Preferred Setups
              </label>
              <div className="flex flex-wrap gap-2">
                {SETUP_OPTIONS.map((setup) => {
                  const active = (draft.preferred_setups ?? []).includes(setup);
                  return (
                    <button
                      key={setup}
                      onClick={() => toggleSetup(setup)}
                      className={`px-3 py-1.5 text-xs rounded-lg border transition-colors ${
                        active
                          ? "bg-accent/10 border-accent/30 text-accent"
                          : "bg-card-alt border-line text-mute hover:text-ink"
                      }`}
                    >
                      {setup}
                    </button>
                  );
                })}
              </div>
            </div>

            <div>
              <label className="block text-xs text-mute mb-1.5">
                Auto-Refresh Interval (seconds)
              </label>
              <input
                type="number"
                value={draft.auto_refresh_interval ?? 60}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    auto_refresh_interval: Number(e.target.value),
                  })
                }
                min={10}
                max={600}
                className="w-full px-3 py-2 text-sm bg-card-alt border border-line rounded-lg text-ink focus:outline-none focus:border-accent/40 font-mono"
              />
            </div>

            <div className="space-y-3 pt-2">
              <label className="flex items-center justify-between cursor-pointer">
                <span className="text-sm text-ink">Enable Notifications</span>
                <button
                  onClick={() =>
                    setDraft({
                      ...draft,
                      notifications_enabled: !draft.notifications_enabled,
                    })
                  }
                  className={`w-10 h-5 rounded-full transition-colors ${
                    draft.notifications_enabled ? "bg-accent" : "bg-line"
                  }`}
                >
                  <div
                    className={`w-4 h-4 rounded-full bg-white shadow transition-transform ${
                      draft.notifications_enabled
                        ? "translate-x-5"
                        : "translate-x-0.5"
                    }`}
                  />
                </button>
              </label>

              <label className="flex items-center justify-between cursor-pointer">
                <div>
                  <span className="text-sm text-ink">Paper Trading Mode</span>
                  <span className="block text-[10px] text-mute/60">
                    Always enabled for safety
                  </span>
                </div>
                <button
                  disabled
                  className="w-10 h-5 rounded-full bg-accent cursor-not-allowed"
                >
                  <div className="w-4 h-4 rounded-full bg-white shadow translate-x-5" />
                </button>
              </label>
            </div>
          </div>
        </div>
      </div>

      {/* Danger Zone */}
      <div className="bg-card border border-red/20 rounded-xl p-5">
        <h2 className="text-xs font-semibold text-red uppercase tracking-wider mb-2">
          Important Notice
        </h2>
        <p className="text-xs text-mute leading-relaxed">
          This platform operates in paper trading mode only. No real orders are
          placed. All picks are generated by an AI-driven scoring system and
          should not be construed as investment advice. Past performance of the
          scoring engine does not guarantee future results. SEBI&apos;s 2023
          study found approximately 70% of individual intraday traders incur net
          losses.
        </p>
      </div>
    </>
  );
}
