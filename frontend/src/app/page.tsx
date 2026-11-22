"use client";

import { useState } from "react";
import { jsPDF } from "jspdf";

// Set NEXT_PUBLIC_API_BASE_URL in .env.local (or the host's env settings) when deploying.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
// Demo banner is ON unless NEXT_PUBLIC_DEMO_MODE is set to "false".
const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE !== "false";

const DEMO_DISCLAIMER =
  "Demo notice: Rates, benchmarks and market comparisons shown here are sample data or internally entered " +
  "carrier/forwarder quotes. Any lane marked \"Demo data\" is illustrative and not a live market rate, quote or offer. " +
  "No third-party market index data is included. Pricing, surcharges, transit times and availability must be " +
  "confirmed with carriers before any quote is sent to a customer.";

// Reads a UN/LOCODE (e.g. "VNSGN") from text like "Ho Chi Minh City, VN (VNSGN)".
// allowBare=true also accepts a plain 5-character code (use only for fields that are meant to be codes).
function extractLocode(text?: string | null, allowBare = false): string | null {
  if (!text) return null;
  const t = String(text).trim();
  if (allowBare && /^[A-Za-z]{2}[A-Za-z0-9]{3}$/.test(t)) return t.toUpperCase();
  const m = t.match(/\(([A-Za-z]{2}[A-Za-z0-9]{3})\)/);
  return m ? m[1].toUpperCase() : null;
}
// "Ho Chi Minh City, VN (VNSGN)" -> "Ho Chi Minh City, VN"
function stripLocode(text?: string | null): string {
  return String(text ?? "").replace(/\s*\([A-Za-z]{2}[A-Za-z0-9]{3}\)\s*$/, "").trim();
}

// Turns a failed response into a readable message (uses the server's "detail" when present).
async function errorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) return body.detail.map((d: any) => d.msg).join("; ");
  } catch {}
  return `HTTP ${res.status}`;
}

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState<'workspace' | 'logs' | 'performance'>('workspace');

  const [emailText, setEmailText] = useState("");
  const [rfqData, setRfqData] = useState<any>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [approving, setApproving] = useState(false);
  const [approvalStatus, setApprovalStatus] = useState<any>(null);
  const [showDraftModal, setShowDraftModal] = useState(false);
  const [draftEmail, setDraftEmail] = useState("");

  // Email Detection State
  const [detectingEmail, setDetectingEmail] = useState(false);
  const [emailDetectionStatus, setEmailDetectionStatus] = useState<any>(null);

  // Feasibility & Rate Benchmark Engine States
  const [feasibility, setFeasibility] = useState<any>(null);
  const [checkingFeasibility, setCheckingFeasibility] = useState(false);
  const [benchmark, setBenchmark] = useState<any>(null);
  const [checkingBenchmark, setCheckingBenchmark] = useState(false);

  // Quote Generation & Modal States
  const [showQuoteModal, setShowQuoteModal] = useState(false);
  const [quoteDraft, setQuoteDraft] = useState<any>(null);
  const [generatingQuote, setGeneratingQuote] = useState(false);
  const [sentConfirmation, setSentConfirmation] = useState(false);

  // Clean Initial Performance Evaluation State (Populates strictly from live runs)
  const [perfMetrics, setPerfMetrics] = useState<{
    totalProcessed: number;
    avgConfidence: number;
    avgLatencyMs: number;
    recentEvaluations: Array<{
      id: string;
      route: string;
      confidence: number;
      latency: string;
      override: string;
      status: string;
    }>;
  }>({
    totalProcessed: 0,
    avgConfidence: 0,
    avgLatencyMs: 0,
    recentEvaluations: []
  });

  // Clean Initial Logs State (Populates strictly from live session events)
  const [executionLogs, setExecutionLogs] = useState<
    Array<{
      id: string;
      level: string;
      service: string;
      timestamp: string;
      detail: string;
    }>
  >([]);

  const addLog = (level: string, service: string, detail: string) => {
    setExecutionLogs((prev) => [
      {
        id: `LOG-${Date.now().toString().slice(-4)}-${Math.floor(10 + Math.random() * 90)}`,
        level,
        service,
        timestamp: new Date().toLocaleTimeString(),
        detail
      },
      ...prev
    ]);
  };

  // Email Detection Handler
  const handleSimulateEmailDetection = async () => {
    if (!emailText.trim()) {
      setParseError("Please enter email text before simulating inbound ingestion.");
      return;
    }
    setDetectingEmail(true);
    setEmailDetectionStatus(null);
    setParseError(null);
    addLog("INFO", "Mailbox Listener", "Sending inbound payload to /api/rfqs/ingest...");

    try {
      const response = await fetch(`${API_BASE}/api/rfqs/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          body_text: emailText
        })
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setEmailDetectionStatus(data);
      addLog("SUCCESS", "FastAPI Ingest", `Ingested RFQ ID: ${data.rfq_id || "Assigned by backend"}`);
    } catch (error: any) {
      console.warn("Failed email detection hook:", error);
      setParseError(`Backend ingestion failed: ${error.message || `Unable to reach ${API_BASE}`}`);
      addLog("ERROR", "FastAPI Ingest", `Failed to connect to /api/rfqs/ingest (${error.message})`);
    } finally {
      setDetectingEmail(false);
    }
  };

  // Process RFQ via Live DeepSeek Backend Endpoint
  const handleProcessRFQ = async () => {
    setLoading(true);
    setParseError(null);
    setRfqData(null);
    setApprovalStatus(null);
    setFeasibility(null);
    setBenchmark(null);
    const startTime = performance.now();

    addLog("INFO", "DeepSeek AI", "Sending RFQ text to /api/rfqs/analyze-rfq...");

    try {
      const response = await fetch(`${API_BASE}/api/rfqs/analyze-rfq`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rfq_text: emailText })
      });

      if (!response.ok) {
        throw new Error(`Server responded with status ${response.status}`);
      }

      const apiResult = await response.json();
      const elapsedMs = Math.round(performance.now() - startTime);

      if (apiResult.status === "success" && apiResult.data) {
        const liveAiData = apiResult.data;
        const confScore = Number(liveAiData.confidence_score ?? 0);

        const record = {
          confidence_score: confScore,
          mode: liveAiData.mode || "DEEPSEEK_LIVE_AI",
          intent_summary: liveAiData.intent_summary || null,
          data: {
            origin: {
              name: stripLocode(liveAiData.origin) || "N/A",
              port_code: extractLocode(liveAiData.origin_code, true) || extractLocode(liveAiData.origin) || "N/A"
            },
            destination: {
              name: stripLocode(liveAiData.destination) || "N/A",
              port_code: extractLocode(liveAiData.destination_code, true) || extractLocode(liveAiData.destination) || "N/A"
            },
            equipment: [
              {
                type: liveAiData.container_type || "N/A",
                quantity: liveAiData.quantity ?? 0
              }
            ],
            cargo_ready_date: liveAiData.cargo_ready_date || "N/A",
            cargo_physicals: {
              gross_weight_kg: liveAiData.weight_kg ?? null,
              volume_cbm: liveAiData.volume_cbm ?? null,
              piece_count: liveAiData.piece_count || "N/A"
            },
            hazmat_special: {
              is_hazardous: Boolean(liveAiData.is_hazardous),
              un_number: liveAiData.un_number || "None",
              temperature_control: liveAiData.temperature_control || "N/A"
            },
            commercial_terms: {
              target_rate_usd: liveAiData.target_rate_usd ?? null,
              payment_terms: liveAiData.payment_terms || "N/A",
              requested_validity: liveAiData.requested_validity || "N/A"
            },
            validation: Array.isArray(liveAiData.validation) ? liveAiData.validation : []
          }
        };

        setRfqData(record);

        // Update Live Performance Metrics strictly from real runs
        setPerfMetrics((prev) => {
          const newTotal = prev.totalProcessed + 1;
          const newAvgConf = Number(
            ((prev.avgConfidence * prev.totalProcessed + confScore) / newTotal).toFixed(1)
          );
          const newAvgLatency = Math.round(
            (prev.avgLatencyMs * prev.totalProcessed + elapsedMs) / newTotal
          );

          return {
            totalProcessed: newTotal,
            avgConfidence: newAvgConf,
            avgLatencyMs: newAvgLatency,
            recentEvaluations: [
              {
                id: `EVAL-${Date.now().toString().slice(-4)}`,
                route: `${record.data.origin.name} → ${record.data.destination.name}`,
                confidence: confScore,
                latency: `${elapsedMs}ms`,
                override: "None (Live Run)",
                status: confScore >= 90 ? "OPTIMAL" : "REVIEWED"
              },
              ...prev.recentEvaluations
            ]
          };
        });

        addLog(
          "SUCCESS",
          "DeepSeek AI",
          `Parsed route (${record.data.origin.name} → ${record.data.destination.name}) in ${elapsedMs}ms.`
        );
      } else {
        throw new Error(apiResult.message || "Invalid response format from backend");
      }
    } catch (error: any) {
      console.warn("Failed to parse RFQ via DeepSeek API:", error);
      setParseError(`Extraction failed: ${error.message || `Backend server unreachable at ${API_BASE}`}`);
      addLog("ERROR", "DeepSeek AI", `Extraction error: ${error.message || "Connection refused"}`);
    } finally {
      setLoading(false);
    }
  };

  // Trigger Feasibility Evaluation Engine using live extracted record
  const handleCheckFeasibility = async () => {
    if (!rfqData) return;
    setCheckingFeasibility(true);
    setParseError(null);

    const rec = rfqData.data;
    const payload = {
      origin: rec.origin?.port_code || rec.origin?.name,
      destination: rec.destination?.port_code || rec.destination?.name,
      equipment_type: rec.equipment?.[0]?.type,
      equipment_quantity: rec.equipment?.[0]?.quantity,
      gross_weight_kg: rec.cargo_physicals?.gross_weight_kg,
      volume_cbm: rec.cargo_physicals?.volume_cbm,
      is_hazardous: rec.hazmat_special?.is_hazardous ?? false
    };

    addLog("INFO", "Feasibility Engine", "Evaluating live shipment parameters via /api/rfqs/feasibility...");

    try {
      const response = await fetch(`${API_BASE}/api/rfqs/feasibility`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const result = data.feasibility || data;
      setFeasibility(result);
      addLog("SUCCESS", "Feasibility Engine", `Verdict returned: ${result.verdict || "COMPLETED"}`);
    } catch (error: any) {
      console.warn("Feasibility check failed:", error);
      setParseError(`Feasibility check failed: ${error.message}`);
      addLog("ERROR", "Feasibility Engine", `Check failed: ${error.message}`);
    } finally {
      setCheckingFeasibility(false);
    }
  };

  // Approve for Pricing (Triggers Rate Benchmark Engine with live values)
  const handleApprove = async () => {
    if (!rfqData) return;
    setApproving(true);
    setCheckingBenchmark(true);
    setParseError(null);

    const rec = rfqData.data;
    const payload = {
      origin_code: rec.origin?.port_code || rec.origin?.name,
      destination_code: rec.destination?.port_code || rec.destination?.name,
      target_rate: rec.commercial_terms?.target_rate_usd,
      equipment: rec.equipment?.[0]?.type
    };

    addLog("INFO", "Rate Benchmark", "Fetching rate reference via /api/rfqs/rate-benchmark...");

    try {
      const benchRes = await fetch(`${API_BASE}/api/rfqs/rate-benchmark`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!benchRes.ok) throw new Error(await errorDetail(benchRes));
      const benchData = await benchRes.json();
      setBenchmark(benchData.benchmark || benchData);

      setApprovalStatus({
        status: "REVIEWED",
        rfq_id: emailDetectionStatus?.rfq_id || `RFQ-${Date.now().toString().slice(-5)}`,
        message: "Rate reference retrieved. Nothing has been sent or saved to a pricing queue."
      });
      addLog("SUCCESS", "Rate Reference", "Rate reference retrieved for review.");
    } catch (error: any) {
      console.warn("Failed to approve RFQ:", error);
      const missingCode = String(error.message || "").startsWith("Could not read a 5-character port code");
      setParseError(
        missingCode
          ? "Rate reference needs a full 5-letter port code (UN/LOCODE) for both ports, e.g. CNNGB for Ningbo " +
            "(not NGB). Add it to the RFQ text, like \"Ningbo, CN (CNNGB)\", and parse again. " +
            `Details: ${error.message}`
          : `Rate benchmark failed: ${error.message}`
      );
      addLog("ERROR", "Rate Benchmark", `Benchmark error: ${error.message}`);
    } finally {
      setApproving(false);
      setCheckingBenchmark(false);
    }
  };

  const handleGenerateClarification = () => {
    const rec = rfqData?.data;
    const origin = rec?.origin?.name || "Origin";
    const destination = rec?.destination?.name || "Destination";

    setDraftEmail(
      `Hi Logistics Team,\n\nThank you for reaching out regarding your shipment from ${origin} to ${destination}.\n\nCould you please confirm any missing cargo specifications, hazardous declarations, or exact ready dates required for this quote?\n\nBest regards,\nNixacom Freight Team`
    );
    setShowDraftModal(true);
  };

  const handleGenerateQuoteResponse = async () => {
    if (!rfqData) return;
    setGeneratingQuote(true);
    setParseError(null);

    const rec = rfqData.data;
    const origin = rec.origin?.name || "";
    const destination = rec.destination?.name || "";
    const equipment = Array.isArray(rec.equipment) && rec.equipment.length > 0
      ? `${rec.equipment[0].quantity}x ${rec.equipment[0].type}`
      : "";

    addLog("INFO", "Quote Generator", "Requesting outbound quote draft from /api/rfqs/generate-quote-response...");

    try {
      const res = await fetch(`${API_BASE}/api/rfqs/generate-quote-response`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          origin,
          destination,
          equipment,
          target_rate: rec.commercial_terms?.target_rate_usd
        })
      });
      if (!res.ok) throw new Error(await errorDetail(res));
      const data = await res.json();
      setQuoteDraft(data);
      setShowQuoteModal(true);
      addLog("SUCCESS", "Quote Generator", "Outbound quote draft compiled successfully.");
    } catch (err: any) {
      console.warn("Quote generation failed:", err);
      setParseError(`Quote generation failed: ${err.message}`);
      addLog("ERROR", "Quote Generator", `Failed: ${err.message}`);
    } finally {
      setGeneratingQuote(false);
    }
  };

  // Client-Side Commercial TSU-Formatted PDF Generator Function (Strictly Dynamic)
  const handleDownloadPDF = async () => {
    if (!quoteDraft || !rfqData) return;

    const doc = new jsPDF({ unit: "mm", format: "letter" });
    const rec = rfqData.data;
    const origin = rec.origin?.name || "N/A";
    const originCode = rec.origin?.port_code || "";
    const destination = rec.destination?.name || "N/A";
    const destCode = rec.destination?.port_code || "";
    const equipStr = Array.isArray(rec.equipment) && rec.equipment.length > 0
      ? `${rec.equipment[0].quantity}x ${rec.equipment[0].type}`
      : "N/A";

    const baseRate = Number(rec.commercial_terms?.target_rate_usd || 0);
    const totalRate = baseRate; // same figure as the email draft; no extra surcharge added

    // PAGE 1: TSU DARK BLUE COVER PAGE
    doc.setFillColor(27, 42, 75);
    doc.rect(0, 0, 215.9, 279.4, "F");

    doc.setFillColor(50, 90, 179);
    doc.rect(0, 0, 215.9, 12, "F");
    doc.rect(0, 0, 12, 279.4, "F");

    try {
      const response = await fetch("/logo.png");
      if (response.ok) {
        const blob = await response.blob();
        const reader = new FileReader();
        const logoBase64: string = await new Promise((resolve) => {
          reader.onloadend = () => resolve(reader.result as string);
          reader.readAsDataURL(blob);
        });
        doc.addImage(logoBase64, "PNG", 20, 22, 55, 31.2);
      } else {
        throw new Error("Logo not found");
      }
    } catch {
      doc.setFont("Helvetica", "bold");
      doc.setFontSize(24);
      doc.setTextColor(72, 202, 228);
      doc.text("NIXACOM AI", 20, 35);
    }

    const startY = 85;
    const spacing = 38;

    doc.setFont("Helvetica", "bold");
    doc.setFontSize(9);
    doc.setTextColor(160, 174, 192);
    doc.text("DRAFT QUOTE FOR", 20, startY);

    doc.setFontSize(15);
    doc.setTextColor(255, 255, 255);
    doc.text(`Ocean Freight Route: ${origin} to ${destination}`, 20, startY + 7);

    doc.setFontSize(9);
    doc.setTextColor(160, 174, 192);
    doc.text("QUOTE REFERENCE", 20, startY + spacing);

    doc.setFontSize(15);
    doc.setTextColor(255, 255, 255);
    doc.text(approvalStatus?.rfq_id || `SOL-${Date.now().toString().slice(-6)}`, 20, startY + spacing + 7);

    doc.setFontSize(9);
    doc.setTextColor(160, 174, 192);
    doc.text("SUBMITTED BY", 20, startY + spacing * 2);

    doc.setFontSize(15);
    doc.setTextColor(255, 255, 255);
    doc.text("NIXACOM Freight Automation Team", 20, startY + spacing * 2 + 7);

    doc.setFontSize(9);
    doc.setTextColor(160, 174, 192);
    doc.text("SUBMISSION DATE", 20, startY + spacing * 3);

    doc.setFontSize(15);
    doc.setTextColor(255, 255, 255);
    doc.text(new Date().toISOString().split("T")[0], 20, startY + spacing * 3 + 7);

    // PAGE 2: DETAILED REPORT & RATE SCHEDULE
    doc.addPage();

    doc.setFont("Helvetica", "bold");
    doc.setFontSize(18);
    doc.setTextColor(30, 41, 59);
    doc.text("NIXACOM FREIGHT SOLUTIONS", 14, 20);

    doc.setFontSize(10);
    doc.setFont("Helvetica", "normal");
    doc.setTextColor(100, 116, 139);
    doc.text("DRAFT FREIGHT QUOTATION - FOR REVIEW, NOT AN OFFER", 14, 26);
    doc.text(`Date: ${new Date().toLocaleDateString()}`, 14, 31);

    doc.setLineWidth(0.5);
    doc.setDrawColor(203, 213, 225);
    doc.line(14, 35, 196, 35);

    doc.setFontSize(10);
    doc.setFont("Helvetica", "bold");
    doc.setTextColor(15, 23, 42);
    doc.text("Shipment Overview", 14, 43);

    doc.setFont("Helvetica", "normal");
    doc.setFontSize(9);
    doc.text(`Origin Port: ${origin} ${originCode ? `(${originCode})` : ""}`, 14, 50);
    doc.text(`Destination Port: ${destination} ${destCode ? `(${destCode})` : ""}`, 110, 50);
    doc.text(`Container Equipment: ${equipStr}`, 14, 56);
    doc.text(`Cargo Ready Date: ${rec.cargo_ready_date || "N/A"}`, 110, 56);
    doc.text(
      `Gross Weight: ${rec.cargo_physicals?.gross_weight_kg ? `${rec.cargo_physicals.gross_weight_kg.toLocaleString()} kg` : "N/A"} | Volume: ${rec.cargo_physicals?.volume_cbm ? `${rec.cargo_physicals.volume_cbm} CBM` : "N/A"}`,
      14,
      62
    );

    doc.line(14, 67, 196, 67);

    doc.setFont("Helvetica", "bold");
    doc.setFontSize(10);
    doc.text("Rate Schedule & Charges", 14, 75);

    doc.setFont("Helvetica", "normal");
    doc.setFontSize(9);
    doc.text(`1. Ocean Freight Rate per container (${equipStr}):`, 14, 83);
    doc.text(`$${baseRate.toFixed(2)} USD`, 160, 83);

    doc.setFont("Helvetica", "bold");
    doc.text("Rate per container (draft):", 14, 98);
    doc.text(`$${totalRate.toFixed(2)} USD`, 160, 98);

    doc.line(14, 104, 196, 104);

    doc.setFont("Helvetica", "bold");
    doc.setFontSize(10);
    doc.text("Customer Communication & Terms", 14, 112);

    doc.setFont("Helvetica", "normal");
    doc.setFontSize(9);
    doc.setTextColor(51, 65, 85);
    const splitText = doc.splitTextToSize(quoteDraft.quote_email || "", 180);
    doc.text(splitText, 14, 119);

    if (DEMO_MODE) {
      doc.setFont("Helvetica", "italic");
      doc.setFontSize(7);
      doc.setTextColor(100, 116, 139);
      doc.text(doc.splitTextToSize(DEMO_DISCLAIMER, 180), 14, 262);
    }

    doc.save(`Nixacom-Quote-${origin}-${destination}.pdf`);
    addLog("SUCCESS", "PDF Compiler", `Exported PDF quote for ${origin} → ${destination}`);
  };

  const record = rfqData?.data;
  const validationList = record?.validation || [];

  return (
    <main className="min-h-screen bg-slate-900 text-slate-100 p-8">
      {/* Header */}
      <header className="flex justify-between items-center pb-6 mb-6 border-b border-slate-800">
        <div>
          <h1 className="text-2xl font-bold text-white">Nixacom RFQ Workspace</h1>
          <p className="text-sm text-slate-400">Human-in-the-Loop Review Dashboard</p>
        </div>

        {/* Live Backend Connection Indicator */}
        <div className="flex gap-2 text-[10px] font-mono">
          <span className="bg-slate-800 border border-slate-700 text-slate-300 px-2.5 py-1 rounded-full flex items-center gap-1.5 shadow-sm">
            <span className={`w-1.5 h-1.5 rounded-full ${parseError ? "bg-rose-400" : "bg-emerald-400 animate-pulse"}`}></span>
            Backend: {API_BASE.replace(/^https?:\/\//, "")}
          </span>
        </div>
      </header>

      {/* Navigation Tabs Switcher */}
      <div className="flex flex-wrap gap-3 mb-8">
        <button
          onClick={() => setActiveTab("workspace")}
          className={`px-4 py-2 rounded-lg text-xs font-semibold transition cursor-pointer flex items-center gap-2 ${
            activeTab === "workspace"
              ? "bg-blue-600 text-white shadow-lg shadow-blue-600/20"
              : "bg-slate-800 text-slate-400 hover:text-white border border-slate-700"
          }`}
        >
          📊 RFQ Workspace
        </button>
        <button
          onClick={() => setActiveTab("logs")}
          className={`px-4 py-2 rounded-lg text-xs font-semibold transition cursor-pointer flex items-center gap-2 ${
            activeTab === "logs"
              ? "bg-blue-600 text-white shadow-lg shadow-blue-600/20"
              : "bg-slate-800 text-slate-400 hover:text-white border border-slate-700"
          }`}
        >
          🖥️ System Logs & Diagnostics
          <span className="px-1.5 py-0.5 rounded-full bg-slate-900 text-[10px] text-[#48CAE4] font-mono">
            {executionLogs.length}
          </span>
        </button>
        <button
          onClick={() => setActiveTab("performance")}
          className={`px-4 py-2 rounded-lg text-xs font-semibold transition cursor-pointer flex items-center gap-2 ${
            activeTab === "performance"
              ? "bg-blue-600 text-white shadow-lg shadow-blue-600/20"
              : "bg-slate-800 text-slate-400 hover:text-white border border-slate-700"
          }`}
        >
          📈 Performance & Analytics
          <span className="px-1.5 py-0.5 rounded-full bg-slate-900 text-[10px] text-emerald-400 font-mono">
            {perfMetrics.totalProcessed > 0 ? `${perfMetrics.avgConfidence}% Conf` : "0 Runs"}
          </span>
        </button>
      </div>

      {DEMO_MODE && (
        <div className="mb-6 p-3 bg-amber-950/50 border border-amber-500/40 rounded-lg text-xs text-amber-200">
          <strong>Demo mode:</strong> rates shown are sample or internally entered data, not live market rates.
          Confirm pricing, surcharges, transit times and availability with carriers before quoting a customer.
        </div>
      )}

      {/* Live Error Banner */}
      {parseError && (
        <div className="mb-6 p-4 bg-rose-950/60 border border-rose-500/40 rounded-lg text-xs text-rose-200 flex justify-between items-center">
          <span><strong>System Alert:</strong> {parseError}</span>
          <button onClick={() => setParseError(null)} className="text-rose-400 hover:text-white font-bold px-2">
            ✕
          </button>
        </div>
      )}

      {/* ==================================================== */}
      {/* TAB 1: RFQ WORKSPACE VIEW                             */}
      {/* ==================================================== */}
      {activeTab === "workspace" && (
        <>
          {/* Automated Mailbox Listener Trigger Panel */}
          <div className="mb-6 bg-slate-800/80 p-4 rounded-xl border border-blue-500/30 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-blue-400">Inbound Mailbox Endpoint</h3>
              <p className="text-xs text-slate-400">Send current input text to FastAPI ingestion webhook (/api/rfqs/ingest)</p>
            </div>
            <button
              onClick={handleSimulateEmailDetection}
              disabled={detectingEmail || !emailText.trim()}
              className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-4 py-2 rounded-lg transition cursor-pointer disabled:opacity-50"
            >
              {detectingEmail ? "Ingesting..." : "Ingest Email via API"}
            </button>
          </div>

          {/* Detection Feedback Alert */}
          {emailDetectionStatus && (
            <div className="mb-6 p-3 bg-blue-950/50 border border-blue-500/30 rounded-lg text-xs text-blue-200">
              <strong>Ingestion Response:</strong> Status: {emailDetectionStatus.status} | RFQ ID: {emailDetectionStatus.rfq_id || "N/A"}
            </div>
          )}

          {/* Input Email Section */}
          <section className="mb-8 bg-slate-800 p-6 rounded-xl border border-slate-700 shadow-md">
            <label className="block text-sm font-semibold text-slate-200 mb-2">
              Raw Email / Inquiry Input
            </label>
            <textarea
              rows={5}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
              value={emailText}
              onChange={(e) => setEmailText(e.target.value)}
              placeholder="Paste customer RFQ email text here (e.g., origin, destination, container count/type, weight, target rate)..."
            />
            <div className="flex justify-end mt-3">
              <button
                onClick={handleProcessRFQ}
                disabled={loading || !emailText.trim()}
                className="bg-blue-600 hover:bg-blue-500 text-white font-medium px-5 py-2.5 rounded-lg shadow transition cursor-pointer disabled:opacity-50 text-sm"
              >
                {loading ? "Extracting via DeepSeek..." : "Parse & Process Email RFQ"}
              </button>
            </div>
          </section>

          {/* Output RFQ Results Section */}
          {rfqData && record && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="md:col-span-2 space-y-6">
                <div className="bg-slate-800 p-6 rounded-xl border border-slate-700">
                  {rfqData.intent_summary && (
                    <div className="mb-6 bg-purple-950/30 border border-purple-500/30 p-4 rounded-lg w-full">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-semibold text-purple-400 uppercase tracking-wider flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full bg-purple-400 animate-pulse"></span>
                          Intelligence Layer Interpretation ({rfqData.mode})
                        </span>
                      </div>
                      <p className="text-xs text-slate-300 leading-relaxed italic">
                        "{rfqData.intent_summary}"
                      </p>
                    </div>
                  )}

                  <div className="flex justify-between items-center mb-4">
                    <h2 className="text-lg font-semibold text-white">Extracted RFQ Record</h2>
                    <span className="bg-emerald-500/10 text-emerald-400 text-xs font-semibold px-2.5 py-1 rounded border border-emerald-500/20">
                      Confidence: {rfqData.confidence_score}%
                    </span>
                  </div>

                  {/* Core Route Specs */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
                    <div className="bg-slate-900/50 p-3 rounded border border-slate-700/50">
                      <span className="text-xs text-slate-400 block">Origin Port</span>
                      <span className="font-semibold text-sm">
                        {record.origin?.name} ({record.origin?.port_code})
                      </span>
                    </div>
                    <div className="bg-slate-900/50 p-3 rounded border border-slate-700/50">
                      <span className="text-xs text-slate-400 block">Destination Port</span>
                      <span className="font-semibold text-sm">
                        {record.destination?.name} ({record.destination?.port_code})
                      </span>
                    </div>
                    <div className="bg-slate-900/50 p-3 rounded border border-slate-700/50">
                      <span className="text-xs text-slate-400 block">Equipment</span>
                      <span className="font-semibold text-sm">
                        {Array.isArray(record.equipment) && record.equipment.length > 0
                          ? `${record.equipment[0].quantity}x ${record.equipment[0].type}`
                          : "N/A"}
                      </span>
                    </div>
                    <div className="bg-slate-900/50 p-3 rounded border border-slate-700/50">
                      <span className="text-xs text-slate-400 block">Cargo Ready Date</span>
                      <span className="font-semibold text-sm">{record.cargo_ready_date}</span>
                    </div>
                  </div>

                  {/* Extended Freight Information Grid */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 border-t border-slate-700/50 pt-4 mb-6">
                    <div className="bg-slate-900/30 p-3 rounded border border-slate-700/30">
                      <h4 className="text-xs font-semibold text-blue-400 mb-2 uppercase tracking-wider">Cargo Physicals</h4>
                      <ul className="text-xs space-y-1.5 text-slate-300">
                        <li>
                          <span className="text-slate-400">Weight:</span>{" "}
                          {record.cargo_physicals?.gross_weight_kg !== null
                            ? `${Number(record.cargo_physicals.gross_weight_kg).toLocaleString()} kg`
                            : "N/A"}
                        </li>
                        <li>
                          <span className="text-slate-400">Volume:</span>{" "}
                          {record.cargo_physicals?.volume_cbm !== null
                            ? `${record.cargo_physicals.volume_cbm} CBM`
                            : "N/A"}
                        </li>
                        <li>
                          <span className="text-slate-400">Pieces:</span>{" "}
                          {record.cargo_physicals?.piece_count || "N/A"}
                        </li>
                      </ul>
                    </div>
                    <div className="bg-slate-900/30 p-3 rounded border border-slate-700/30">
                      <h4 className="text-xs font-semibold text-blue-400 mb-2 uppercase tracking-wider">HazMat & Special</h4>
                      <ul className="text-xs space-y-1.5 text-slate-300">
                        <li><span className="text-slate-400">Hazardous:</span> {record.hazmat_special?.is_hazardous ? "Yes" : "No"}</li>
                        <li><span className="text-slate-400">UN Number:</span> {record.hazmat_special?.un_number}</li>
                        <li><span className="text-slate-400">Temp Control:</span> {record.hazmat_special?.temperature_control}</li>
                      </ul>
                    </div>
                    <div className="bg-slate-900/30 p-3 rounded border border-slate-700/30">
                      <h4 className="text-xs font-semibold text-blue-400 mb-2 uppercase tracking-wider">Commercial Terms</h4>
                      <ul className="text-xs space-y-1.5 text-slate-300">
                        <li>
                          <span className="text-slate-400">Target Rate:</span>{" "}
                          {record.commercial_terms?.target_rate_usd !== null
                            ? `$${Number(record.commercial_terms.target_rate_usd).toLocaleString()}`
                            : "N/A"}
                        </li>
                        <li><span className="text-slate-400">Payment:</span> {record.commercial_terms?.payment_terms}</li>
                        <li><span className="text-slate-400">Validity:</span> {record.commercial_terms?.requested_validity}</li>
                      </ul>
                    </div>
                  </div>

                  {/* Feasibility Assessment Card */}
                  {feasibility && (
                    <div className="mb-6 p-4 bg-slate-900/80 border border-amber-500/30 rounded-lg">
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">Feasibility Assessment Engine</span>
                        <span className="text-xs font-bold px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-500/30">
                          {feasibility.verdict} {feasibility.score !== undefined ? `(${feasibility.score}%)` : ""}
                        </span>
                      </div>
                      <p className="text-xs text-slate-300">
                        {Array.isArray(feasibility.reasons) && feasibility.reasons.length > 0
                          ? feasibility.reasons.join(" | ")
                          : feasibility.message || "Evaluated by backend feasibility engine."}
                      </p>
                    </div>
                  )}

                  {/* Rate Benchmark Assessment Card */}
                  {benchmark && (
                    <div className="mb-6 p-4 bg-slate-900/80 border border-emerald-500/30 rounded-lg">
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-xs font-semibold text-emerald-400 uppercase tracking-wider">Rate Reference (sanity check, not a quote)</span>
                        <span className="text-xs font-bold px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-500/30">
                          {benchmark.competitiveness} {benchmark.variance_pct != null ? `(${benchmark.variance_pct}%)` : ""}
                        </span>
                      </div>

                      <div className="grid grid-cols-3 gap-2 text-xs text-slate-300 mt-3">
                        <div>
                          Reference Avg:{" "}
                          <strong className="text-white">
                            {benchmark.market_avg_rate != null ? `$${benchmark.market_avg_rate}` : "N/A"}
                          </strong>
                        </div>
                        <div>
                          Fuel Surcharge:{" "}
                          <strong className="text-white">
                            {benchmark.fuel_surcharge != null ? `$${benchmark.fuel_surcharge}` : "N/A"}
                          </strong>
                        </div>
                        <div>
                          Target Rate:{" "}
                          <strong className="text-emerald-400">
                            {benchmark.target_rate !== undefined ? `$${benchmark.target_rate}` : "N/A"}
                          </strong>
                        </div>
                      </div>

                      {(benchmark.status && benchmark.status !== "OK") && (
                        <p className="mt-3 text-xs font-semibold text-amber-400">
                          ⚠ Rate status: {benchmark.status}. Do not quote from this benchmark without review.
                        </p>
                      )}
                      {benchmark.notes?.map((n: string, i: number) => (
                        <p key={i} className="mt-1 text-xs text-slate-400">{n}</p>
                      ))}
                      {benchmark.as_of && (
                        <p className="mt-2 text-[11px] text-slate-500">
                          Rate as of {new Date(benchmark.as_of).toLocaleString()} · {benchmark.sources?.base_rate_index?.source}
                        </p>
                      )}
                    </div>
                  )}

                  {approvalStatus ? (
                    <div className="p-4 bg-emerald-950/40 border border-emerald-500/30 rounded-lg">
                      <p className="text-emerald-400 font-semibold text-sm">✓ {approvalStatus.message}</p>
                      <p className="text-xs text-slate-400 mt-1">Status: {approvalStatus.status} | ID: {approvalStatus.rfq_id}</p>
                    </div>
                  ) : (
                    <div className="flex flex-wrap gap-3 pt-4 border-t border-slate-700">
                      <button
                        onClick={handleCheckFeasibility}
                        disabled={checkingFeasibility}
                        className="bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium px-4 py-2 rounded cursor-pointer disabled:opacity-50"
                      >
                        {checkingFeasibility ? "Evaluating..." : "Check Feasibility"}
                      </button>
                      <button
                        onClick={handleApprove}
                        disabled={approving || checkingBenchmark}
                        className="bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium px-4 py-2 rounded cursor-pointer disabled:opacity-50"
                      >
                        {approving ? "Approving..." : "Approve for Pricing"}
                      </button>
                      <button
                        onClick={handleGenerateQuoteResponse}
                        disabled={generatingQuote}
                        className="bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium px-4 py-2 rounded cursor-pointer disabled:opacity-50"
                      >
                        {generatingQuote ? "Generating Quote..." : "Generate & Preview Quote"}
                      </button>
                      <button
                        onClick={handleGenerateClarification}
                        className="bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-medium px-4 py-2 rounded cursor-pointer"
                      >
                        Generate Clarification Draft
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {/* Right Column: Rule Validation Checks & Process Inspector Cell */}
              <div className="space-y-6">
                <div className="bg-slate-800 p-6 rounded-xl border border-slate-700">
                  <h2 className="text-lg font-semibold text-white mb-4">Rule Validation Checks</h2>
                  <ul className="space-y-3">
                    {validationList.length > 0 ? (
                      validationList.map((item: any, idx: number) => (
                        <li key={idx} className="flex items-center justify-between text-sm bg-slate-900/50 p-2.5 rounded border border-slate-700/50">
                          <span className="capitalize text-slate-300">{item.field_name || item.field}</span>
                          <span
                            className={`text-xs font-bold px-2 py-0.5 rounded ${
                              (item.outcome || item.status) === "PASS"
                                ? "bg-emerald-950 text-emerald-400"
                                : "bg-amber-950 text-amber-400"
                            }`}
                          >
                            {item.outcome || item.status}
                          </span>
                        </li>
                      ))
                    ) : (
                      <li className="text-xs text-slate-400 italic">No rule validation was run for this record (not enabled in this demo build).</li>
                    )}
                  </ul>
                </div>

                {/* Internal Process Inspector Cell */}
                <div className="bg-[#0B192C] text-white p-5 rounded-xl border border-slate-700 shadow-xl flex flex-col">
                  <div className="flex justify-between items-center pb-3 border-b border-slate-700 mb-4">
                    <div>
                      <h3 className="font-bold text-base text-[#48CAE4]">Internal Process Inspector</h3>
                      <p className="text-[11px] text-slate-400">Live Session Execution Trace</p>
                    </div>
                    <span className="flex items-center gap-1.5 px-2 py-1 bg-emerald-950/60 border border-emerald-500/30 rounded text-[10px] text-emerald-400 font-medium">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                      Live
                    </span>
                  </div>

                  <div className="flex-1 overflow-y-auto max-h-[280px] space-y-3 pr-1">
                    {executionLogs.length === 0 ? (
                      <p className="text-xs text-slate-400 italic text-center py-6">
                        No live actions executed yet.
                      </p>
                    ) : (
                      executionLogs.slice(0, 5).map((log, index) => (
                        <div key={index} className="relative pl-5 border-l-2 border-[#48CAE4]/40 pb-3">
                          <div className="absolute -left-[6px] top-0.5 w-2.5 h-2.5 rounded-full bg-[#48CAE4]"></div>
                          <div className="flex justify-between items-center mb-1">
                            <span className="text-xs font-bold text-slate-200">{log.service}</span>
                            <span className="text-[10px] text-slate-400 font-mono">{log.timestamp}</span>
                          </div>
                          <p className="text-[11px] text-slate-300 bg-slate-800/60 p-2 rounded border border-slate-700/50 font-mono">
                            {log.detail}
                          </p>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {/* ==================================================== */}
      {/* TAB 2: SYSTEM LOGS & DIAGNOSTICS VIEW                 */}
      {/* ==================================================== */}
      {activeTab === "logs" && (
        <div className="bg-slate-800 p-6 rounded-xl border border-slate-700 shadow-xl space-y-6">
          <div className="flex justify-between items-center pb-4 border-b border-slate-700">
            <div>
              <h2 className="text-lg font-bold text-white">System Execution Logs & Diagnostics</h2>
              <p className="text-xs text-slate-400">Live API transaction traces from your current session.</p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setExecutionLogs([])}
                className="bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs px-3 py-1.5 rounded transition cursor-pointer"
              >
                Clear Logs
              </button>
            </div>
          </div>

          <div className="bg-slate-950 rounded-lg border border-slate-800 p-4 font-mono text-xs overflow-x-auto max-h-[550px] overflow-y-auto space-y-3">
            {executionLogs.length === 0 ? (
              <p className="text-slate-500 italic text-center py-12">No live log entries recorded yet. Process an RFQ to generate traces.</p>
            ) : (
              executionLogs.map((log) => (
                <div key={log.id} className="flex flex-col sm:flex-row sm:items-center justify-between bg-slate-900/60 p-3 rounded border border-slate-800/80 gap-2">
                  <div className="flex items-center gap-3">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        log.level === "SUCCESS"
                          ? "bg-emerald-950 text-emerald-400 border border-emerald-500/30"
                          : log.level === "WARN"
                          ? "bg-amber-950 text-amber-400 border border-amber-500/30"
                          : log.level === "ERROR"
                          ? "bg-rose-950 text-rose-400 border border-rose-500/30"
                          : "bg-blue-950 text-blue-400 border border-blue-500/30"
                      }`}
                    >
                      {log.level}
                    </span>
                    <span className="text-slate-400 font-semibold">[{log.service}]</span>
                    <span className="text-slate-200">{log.detail}</span>
                  </div>
                  <div className="flex items-center gap-3 text-slate-500 text-[11px] self-end sm:self-auto">
                    <span>{log.timestamp}</span>
                    <span className="text-slate-600">{log.id}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* ==================================================== */}
      {/* TAB 3: PERFORMANCE & OUTPUT EVALUATION VIEW           */}
      {/* ==================================================== */}
      {activeTab === "performance" && (
        <div className="space-y-6">
          {/* Top KPI Summary Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
            <div className="bg-slate-800 p-5 rounded-xl border border-slate-700 shadow">
              <span className="text-xs text-slate-400 block mb-1">Total RFQs Processed (Session)</span>
              <span className="text-2xl font-bold text-white">{perfMetrics.totalProcessed}</span>
            </div>

            <div className="bg-slate-800 p-5 rounded-xl border border-slate-700 shadow">
              <span className="text-xs text-slate-400 block mb-1">Avg Extraction Confidence</span>
              <span className="text-2xl font-bold text-[#48CAE4]">
                {perfMetrics.totalProcessed > 0 ? `${perfMetrics.avgConfidence}%` : "—"}
              </span>
            </div>

            <div className="bg-slate-800 p-5 rounded-xl border border-slate-700 shadow">
              <span className="text-xs text-slate-400 block mb-1">Avg Pipeline Latency</span>
              <span className="text-2xl font-bold text-emerald-400">
                {perfMetrics.totalProcessed > 0 ? `${perfMetrics.avgLatencyMs}ms` : "—"}
              </span>
            </div>
          </div>

          {/* Model Output Evaluation Table */}
          <div className="bg-slate-800 p-6 rounded-xl border border-slate-700 shadow-xl">
            <div className="flex justify-between items-center pb-4 border-b border-slate-700 mb-4">
              <div>
                <h2 className="text-lg font-bold text-white">Live AI Output Evaluation Audit</h2>
                <p className="text-xs text-slate-400">Real-time metrics captured from live DeepSeek & FastAPI executions.</p>
              </div>
            </div>

            <div className="overflow-x-auto">
              {perfMetrics.recentEvaluations.length === 0 ? (
                <p className="text-xs text-slate-400 italic text-center py-10">
                  No live evaluations recorded yet. Process an RFQ in the workspace to capture real latency and confidence metrics.
                </p>
              ) : (
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-slate-700 text-slate-400 uppercase text-[10px]">
                      <th className="py-3 px-4">Eval ID</th>
                      <th className="py-3 px-4">Freight Route</th>
                      <th className="py-3 px-4">Confidence Score</th>
                      <th className="py-3 px-4">Response Latency</th>
                      <th className="py-3 px-4">Quality Verdict</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800">
                    {perfMetrics.recentEvaluations.map((ev) => (
                      <tr key={ev.id} className="hover:bg-slate-900/50 transition">
                        <td className="py-3 px-4 font-mono text-slate-400">{ev.id}</td>
                        <td className="py-3 px-4 font-semibold text-white">{ev.route}</td>
                        <td className="py-3 px-4">
                          <span className="text-emerald-400 font-bold">{ev.confidence}%</span>
                        </td>
                        <td className="py-3 px-4 font-mono text-slate-300">{ev.latency}</td>
                        <td className="py-3 px-4">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              ev.status === "OPTIMAL"
                                ? "bg-emerald-950 text-emerald-400 border border-emerald-500/30"
                                : "bg-amber-950 text-amber-400 border border-amber-500/30"
                            }`}
                          >
                            {ev.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Clarification Draft Modal */}
      {showDraftModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 w-full max-w-xl shadow-2xl">
            <h3 className="text-lg font-bold text-white mb-2">Draft Clarification Email</h3>
            <p className="text-xs text-amber-400 mb-4">
              ⚠️ Note: Email drafts are generated for human review and never auto-sent.
            </p>
            <textarea
              rows={6}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-sm text-slate-100 font-mono mb-4 focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={draftEmail}
              onChange={(e) => setDraftEmail(e.target.value)}
            />
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowDraftModal(false)}
                className="bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-medium px-4 py-2 rounded cursor-pointer"
              >
                Close
              </button>
              <button
                onClick={() => {
                  addLog("INFO", "Clarification Draft", "Human-reviewed clarification draft saved.");
                  setShowDraftModal(false);
                }}
                className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-2 rounded cursor-pointer"
              >
                Save Draft
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Commercial PDF Quote Generation Modal */}
      {showQuoteModal && quoteDraft && (
        <div className="fixed inset-0 bg-black/75 flex items-center justify-center p-4 z-50">
          <div className="bg-slate-800 border border-indigo-500/40 rounded-xl p-6 w-full max-w-2xl shadow-2xl">
            <div className="flex justify-between items-center mb-3">
              <h3 className="text-lg font-bold text-white">Outbound Customer Quote Response</h3>
            </div>

            <div className="text-xs text-slate-300 mb-3 space-y-1 bg-slate-900 p-3 rounded border border-slate-700">
              <div><strong>To:</strong> {quoteDraft.recipient || "Customer"}</div>
              <div><strong>Subject:</strong> {quoteDraft.subject || "Freight Quotation"}</div>
            </div>

            <textarea
              rows={10}
              readOnly
              className="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 text-xs text-slate-200 font-mono mb-4 focus:outline-none"
              value={quoteDraft.quote_email || ""}
            />

            {sentConfirmation ? (
              <div className="p-3 bg-emerald-950 text-emerald-400 border border-emerald-500/30 rounded text-center text-xs font-semibold">
                ✓ Draft marked approved. Nothing was sent. Copy the email to send it yourself.
              </div>
            ) : (
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setShowQuoteModal(false)}
                  className="bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs px-4 py-2 rounded cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDownloadPDF}
                  className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs px-4 py-2 rounded font-medium flex items-center gap-1.5 cursor-pointer"
                >
                  📥 Download PDF Quote
                </button>
                <button
                  onClick={() => {
                    navigator.clipboard?.writeText(quoteDraft.quote_email || "");
                    addLog("INFO", "Quote Draft", "Email text copied to clipboard.");
                  }}
                  className="bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs px-4 py-2 rounded cursor-pointer"
                >
                  Copy Email Text
                </button>
                <button
                  onClick={() => {
                    addLog("INFO", "Quote Draft", "Draft marked approved. Nothing was sent.");
                    setSentConfirmation(true);
                    setTimeout(() => {
                      setShowQuoteModal(false);
                      setSentConfirmation(false);
                    }, 2000);
                  }}
                  className="bg-indigo-600 hover:bg-indigo-500 text-white text-xs px-4 py-2 rounded font-medium cursor-pointer"
                >
                  Mark Draft Approved (not sent)
                </button>
              </div>
            )}
          </div>
        </div>
      )}
      {DEMO_MODE && (
        <footer className="mt-8 pt-4 border-t border-slate-800 text-[11px] text-slate-500">
          {DEMO_DISCLAIMER}
        </footer>
      )}
    </main>
  );
}